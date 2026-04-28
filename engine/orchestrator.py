from __future__ import annotations

import json
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .agent_runner import AgentRunner
from .code_applier import CodeApplier
from .config import (
    ConfigError,
    agent_map,
    load_config,
    read_prompt,
    validate_production_config,
)
from .context_scanner import scan_codebase
from .cost_tracker import CostTracker
from .events import EventBus
from .models import AgentDefinition, AgentRun, RequirementUnit, RequirementUnitProgress, RunReport, StageRun, model_to_dict, utc_now
from .requirement_splitter import estimate_prompt_size, should_split, split_requirement
from .runtimes import runtime_config
from .quality_gates import (
    has_blocking_failure,
    max_retry_count_for_failures,
    render_gate_feedback,
    run_quality_gates,
)
from .logging_config import (
    get_logger,
    log_agent_complete,
    log_agent_start,
    log_engine_start,
    log_loopback,
    log_stage_complete,
    log_stage_start,
)
from .metrics import record_gate_result, record_run, record_stage_duration
from .worktree import WorktreeManager


class OrchestratorError(RuntimeError):
    pass


def new_run_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _duration(start: float) -> float:
    return round(time.monotonic() - start, 3)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _triggered(content: str, trigger: Any) -> bool:
    """检测内容是否触发 loopback。

    支持三种匹配模式：
    1. 精确字符串匹配（默认）
    2. 正则表达式（regex: 前缀）
    3. 语义关键词匹配（自动扩展同义词）
    """
    # 语义关键词映射：当触发词命中时，自动扩展同义词
    SEMANTIC_KEYWORDS = {
        "FAILED": ["失败", "不通过", "未通过", "FAIL", "ERROR", "出错", "报错"],
        "ERROR": ["错误", "异常", "失败", "FAIL", "FAILED", "出错", "报错"],
        "失败": ["FAILED", "FAIL", "ERROR", "不通过", "未通过", "出错"],
        "Request Changes": ["需要修改", "需要更改", "请修改", "请更改", "需要修复"],
    }

    content_lower = content.lower()
    for item in _as_list(trigger):
        if not item:
            continue
        trigger_str = str(item)

        # 正则表达式匹配
        if trigger_str.startswith("regex:"):
            if re.search(trigger_str[len("regex:"):], content, re.MULTILINE):
                return True
            continue

        # 精确字符串匹配
        if trigger_str in content:
            return True

        # 语义关键词匹配：检查同义词
        synonyms = SEMANTIC_KEYWORDS.get(trigger_str, [])
        for synonym in synonyms:
            if synonym in content:
                return True

        # 大小写不敏感匹配（英文触发词）
        if trigger_str.isascii() and trigger_str.lower() in content_lower:
            return True

    return False


class Orchestrator:
    def __init__(
        self,
        project_root: Path,
        config_path: Optional[str] = None,
        event_bus: Optional[EventBus] = None,
        output_base: Optional[Path] = None,
    ) -> None:
        self.project_root = project_root.expanduser().resolve()
        self.loaded_config = load_config(self.project_root, config_path)
        self.config = self.loaded_config.config
        self.config_warnings = list(self.loaded_config.warnings)
        validate_production_config(self.config)
        self.bus = event_bus or EventBus()
        self.output_base = output_base or (self.project_root / ".ai" / "team-output")
        self.agents = agent_map(self.config)

    def run(
        self,
        requirement: str,
        run_id: Optional[str] = None,
        only_stage: Optional[str] = None,
        skip_stages: Optional[Sequence[str]] = None,
        yes: bool = False,
        production: bool = False,
        merge: bool = False,
        resume: bool = False,
        execution_mode: Optional[str] = None,
    ) -> RunReport:
        if execution_mode and execution_mode not in {"serial", "parallel", "auto"}:
            raise ConfigError("execution_mode must be one of: serial, parallel, auto")
        run_id = run_id or new_run_id()
        logger = get_logger("orchestrator", run_id=run_id)
        log_engine_start(str(self.project_root), self.loaded_config.source)
        logger.info("pipeline run started (resume=%s)", resume)
        output_dir = self.output_base / run_id

        # Resume 模式：检查 checkpoint
        checkpoint = None
        if resume:
            checkpoint = self._load_checkpoint(output_dir)
            if not checkpoint:
                logger.warning("resume 模式但无 checkpoint，从头开始")
                resume = False

        if not resume:
            output_dir.mkdir(parents=True, exist_ok=False)
            (output_dir / "requirement.md").write_text(requirement, encoding="utf-8")
        else:
            output_dir.mkdir(parents=True, exist_ok=True)

        start = time.monotonic()
        report = RunReport(
            run_id=run_id,
            status="running",
            mode=(checkpoint or {}).get("mode", "single"),
            requirement=requirement,
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source=self.loaded_config.source,
            config_path=self.loaded_config.path,
            started_at=utc_now(),
            warnings=self.config_warnings,
        )

        # Resume 模式：恢复已完成的 stages
        completed_stages: List[str] = []
        if checkpoint:
            completed_stages = checkpoint.get("completed_stages", [])
            logger.info("从 checkpoint 恢复，已完成 stages: %s", completed_stages)

        self._write_report(report, output_dir)
        self.bus.emit("run:started", run_id, pipeline_id=self.config.get("metadata", {}).get("name"), requirement=requirement)

        worktree_manager: Optional[WorktreeManager] = None
        worktree_path: Optional[Path] = None
        if self.config.get("worktree", {}).get("enabled"):
            worktree_manager = WorktreeManager(self.project_root, self.config.get("worktree"))
            if resume and checkpoint and checkpoint.get("worktree_path"):
                worktree_path = Path(checkpoint["worktree_path"])
                if not worktree_path.exists():
                    logger.warning("checkpoint 中的 worktree 路径不存在，重新创建")
                    worktree_path = worktree_manager.create(run_id)
            else:
                worktree_path = worktree_manager.create(run_id)
            report.worktree_path = str(worktree_path)
            self._write_report(report, output_dir)

        skip_set = set(skip_stages or [])
        stages = [stage for stage in self.config.get("pipeline", []) if not only_stage or stage.get("id") == only_stage]
        split_units: List[RequirementUnit] = []
        if resume and checkpoint and checkpoint.get("mode") == "multi-unit":
            split_units = self._load_requirement_units(output_dir)
            report.mode = "multi-unit"
            report.units = self._unit_progress_from_checkpoint(checkpoint, split_units)
            self._write_report(report, output_dir)
        elif not resume and not only_stage:
            prompt_size = estimate_prompt_size(requirement, [])
            if should_split(self.config, prompt_size):
                split_units = split_requirement(self.project_root, requirement, self.config, output_dir=output_dir, event_bus=self.bus)
                self._write_requirement_units(output_dir, split_units)
                report.mode = "multi-unit"
                report.units = [RequirementUnitProgress(unit_id=unit.id, status="pending") for unit in split_units]
                report.warnings.append(f"需求过大，已拆分为 {len(split_units)} 个单元")
                self._write_report(report, output_dir)

        try:
            if split_units:
                sequence_status = self._run_requirement_units(
                    split_units,
                    stages,
                    report,
                    output_dir,
                    worktree_path,
                    skip_set,
                    yes,
                    completed_stages,
                    start,
                    execution_mode,
                    resume=resume,
                )
            else:
                sequence_status = self._run_stage_sequence(
                    stages,
                    report,
                    artifact_dir=output_dir,
                    report_dir=output_dir,
                    worktree_path=worktree_path,
                    skip_set=skip_set,
                    yes=yes,
                    completed_stages=completed_stages,
                    start=start,
                    execution_mode=execution_mode,
                    resume=resume,
                )
            if sequence_status == "waiting":
                report.status = "waiting"

            if report.status == "running":
                report.status = "completed"
                if worktree_path and worktree_manager:
                    if merge or self.config.get("worktree", {}).get("merge_on_success"):
                        report.merge_result = worktree_manager.merge(worktree_path)
                    else:
                        report.merge_result = {"status": "skipped", "reason": "merge_on_success disabled"}
                    if self.config.get("worktree", {}).get("auto_cleanup") and report.merge_result.get("status") in {"merged", "no_changes"}:
                        worktree_manager.cleanup(worktree_path)
                if report.status == "completed" and worktree_path:
                    self._run_ci_cd_hook(worktree_path, report, output_dir)
            report.completed_at = utc_now()
            report.duration_seconds = _duration(start)
            record_run(report.status)
            logger.info("pipeline run completed status=%s duration=%.1fs", report.status, report.duration_seconds)
            self.bus.emit("run:completed", report.run_id, status=report.status, summary={"duration": report.duration_seconds})
            self._write_report(report, output_dir)
            # 清理 checkpoint
            if report.status == "completed":
                self._cleanup_checkpoint(output_dir)
            return report
        except Exception as exc:
            report.status = "failed"
            report.error_message = str(exc)
            report.completed_at = utc_now()
            report.duration_seconds = _duration(start)
            record_run("failed")
            logger.error("pipeline run failed: %s", exc)
            self.bus.emit("run:completed", report.run_id, status="failed", summary={"error": str(exc)})
            self._write_report(report, output_dir)
            if worktree_path and worktree_manager and self.config.get("worktree", {}).get("auto_cleanup_on_failure", False):
                worktree_manager.cleanup(worktree_path)
            return report

    def _run_stage_sequence(
        self,
        stages: List[Dict[str, Any]],
        report: RunReport,
        artifact_dir: Path,
        report_dir: Path,
        worktree_path: Optional[Path],
        skip_set: set,
        yes: bool,
        completed_stages: List[str],
        start: float,
        execution_mode: Optional[str],
        resume: bool = False,
        checkpoint_mode: str = "single",
        checkpoint_units: Optional[List[RequirementUnitProgress]] = None,
        unit_progress: Optional[RequirementUnitProgress] = None,
    ) -> str:
        stage_index_by_id = {stage.get("id"): index for index, stage in enumerate(stages)}
        loop_counts: Dict[str, int] = {}
        loopback_errors: Dict[str, List[str]] = {}
        index = 0
        extra_feedback = ""
        skip_completed = resume
        max_duration_seconds = int(self.config.get("runner", {}).get("max_run_duration_seconds") or 7200)
        logger = get_logger("orchestrator", run_id=report.run_id)

        while index < len(stages):
            elapsed = time.monotonic() - start
            if elapsed > max_duration_seconds:
                raise OrchestratorError(f"Run 超过最大耗时限制 ({max_duration_seconds}s)，已自动停止")

            stage = stages[index]
            stage_id = stage.get("id") or f"stage-{index}"

            if skip_completed and stage_id in completed_stages:
                logger.info("跳过已完成的 stage: %s", stage_id)
                report.stages.append(
                    StageRun(stage_id=stage_id, stage_name=stage.get("name", stage_id), status="completed", type=stage.get("type", "agent"))
                )
                index += 1
                continue

            if stage_id in skip_set:
                report.stages.append(
                    StageRun(stage_id=stage_id, stage_name=stage.get("name", stage_id), status="skipped", type=stage.get("type", "agent"))
                )
                if stage_id not in completed_stages:
                    completed_stages.append(stage_id)
                if unit_progress:
                    unit_progress.completed_stages = list(completed_stages)
                self._save_checkpoint(report_dir, report.run_id, completed_stages, worktree_path, mode=checkpoint_mode, units=checkpoint_units)
                index += 1
                self._write_report(report, report_dir)
                continue

            if unit_progress:
                unit_progress.status = "in_progress"
                unit_progress.current_stage = stage_id
                unit_progress.completed_stages = list(completed_stages)
                self._save_checkpoint(report_dir, report.run_id, completed_stages, worktree_path, mode=checkpoint_mode, units=checkpoint_units)

            stage_runs_to_append: List[StageRun]
            if stage.get("type") == "context_scan":
                stage_run = self._run_context_stage(stage, report, artifact_dir, worktree_path)
                stage_runs_to_append = [stage_run]
            elif stage.get("type") == "human_review":
                stage_run = self._run_human_review_stage(stage, report, artifact_dir, yes=yes)
                stage_runs_to_append = [stage_run]
            elif stage.get("type") == "code_apply":
                stage_run = self._run_code_apply_stage(stage, report, artifact_dir, worktree_path)
                stage_runs_to_append = [stage_run]
            else:
                cwd = self._stage_cwd(stage_id, worktree_path)
                stage_run = self._run_agent_stage(stage, report, artifact_dir, cwd, extra_feedback, execution_mode=execution_mode)
                extra_feedback = ""
                if stage_run.status == "completed" and stage_id == "develop" and self.config.get("quality_gates"):
                    stage_runs_to_append = self._run_develop_quality_loop(stage, stage_run, report, artifact_dir, cwd, execution_mode)
                    stage_run = stage_runs_to_append[-1]
                else:
                    stage_runs_to_append = [stage_run]

            skip_completed = False
            report.stages.extend(stage_runs_to_append)
            self._refresh_artifacts(report, report_dir)
            self._write_report(report, report_dir)

            if stage_run.status in {"completed", "skipped"}:
                if stage_id not in completed_stages:
                    completed_stages.append(stage_id)
                if unit_progress:
                    unit_progress.completed_stages = list(completed_stages)
                    unit_progress.current_stage = None
                self._save_checkpoint(report_dir, report.run_id, completed_stages, worktree_path, mode=checkpoint_mode, units=checkpoint_units)
            elif stage_run.status == "waiting":
                if unit_progress:
                    unit_progress.current_stage = stage_id
                self._save_checkpoint(report_dir, report.run_id, completed_stages, worktree_path, mode=checkpoint_mode, units=checkpoint_units)
                return "waiting"

            if stage_run.status not in {"completed", "skipped"}:
                raise OrchestratorError(stage_run.error_message or f"Stage failed: {stage_id}")

            output_content = self._stage_output_text(stage_run)
            if stage.get("loopback_to") and stage.get("loopback_trigger") and _triggered(output_content, stage.get("loopback_trigger")):
                count = loop_counts.get(stage_id, 0) + 1
                loop_counts[stage_id] = count
                max_retries = int(stage.get("max_retries") or 0)
                if count > max_retries:
                    raise OrchestratorError(f"Stage {stage_id} requested loopback more than {max_retries} times")
                target = stage.get("loopback_to")
                if target not in stage_index_by_id:
                    raise OrchestratorError(f"Loopback target not found: {target}")

                error_signature = self._extract_error_signature(output_content)
                loopback_errors.setdefault(stage_id, []).append(error_signature)
                if len(loopback_errors[stage_id]) >= 2:
                    last_errors = loopback_errors[stage_id][-2:]
                    if last_errors[0] == last_errors[1] and last_errors[0]:
                        raise OrchestratorError(
                            f"Stage {stage_id} 连续 {len(last_errors)} 次出现相同错误，已自动停止。"
                            f"错误签名: {error_signature[:100]}..."
                        )

                self.bus.emit(
                    "loopback:triggered",
                    report.run_id,
                    from_stage=stage_id,
                    to_stage=target,
                    iteration=count + 1,
                )
                log_loopback(report.run_id, stage_id, target, count)
                target_index = stage_index_by_id[target]
                target_stage_ids = {s.get("id") for s in stages[target_index:]}
                completed_stages[:] = [item for item in completed_stages if item not in target_stage_ids]
                if unit_progress:
                    unit_progress.completed_stages = list(completed_stages)
                extra_feedback = self._render_loopback_feedback(stage_id, stage_run, count, target)
                feedback_file = artifact_dir / f"loopback-feedback-{stage_id}-{count}.md"
                feedback_file.write_text(extra_feedback, encoding="utf-8")
                self._save_checkpoint(report_dir, report.run_id, completed_stages, worktree_path, mode=checkpoint_mode, units=checkpoint_units)
                self._write_report(report, report_dir)
                index = target_index
                continue

            index += 1

        return "completed"

    def _run_requirement_units(
        self,
        units: List[RequirementUnit],
        stages: List[Dict[str, Any]],
        report: RunReport,
        output_dir: Path,
        worktree_path: Optional[Path],
        skip_set: set,
        yes: bool,
        completed_stages: List[str],
        start: float,
        execution_mode: Optional[str],
        resume: bool,
    ) -> str:
        unit_stages = self._unit_stages(stages)
        if not unit_stages:
            raise OrchestratorError("No stages available for requirement units")
        progress_by_id = {unit.unit_id: unit for unit in report.units}
        completed_unit_ids = {unit.unit_id for unit in report.units if unit.status == "completed"}

        ordered_units = self._order_requirement_units(units)
        progress_by_id = {unit.unit_id: unit for unit in report.units}
        report.units = [progress_by_id.get(unit.id, RequirementUnitProgress(unit_id=unit.id, status="pending")) for unit in ordered_units]
        progress_by_id = {unit.unit_id: unit for unit in report.units}

        for unit in ordered_units:
            progress = progress_by_id.setdefault(unit.id, RequirementUnitProgress(unit_id=unit.id, status="pending"))
            if progress not in report.units:
                report.units.append(progress)
            if progress.status == "completed":
                completed_unit_ids.add(unit.id)
                continue
            missing_deps = [dep for dep in unit.depends_on if dep not in completed_unit_ids]
            if missing_deps:
                raise OrchestratorError(f"Requirement unit {unit.id} has incomplete dependencies: {', '.join(missing_deps)}")

            unit_dir = output_dir / "requirement-units" / unit.id
            unit_dir.mkdir(parents=True, exist_ok=True)
            (unit_dir / "requirement.md").write_text(unit.requirement_text, encoding="utf-8")
            (unit_dir / "unit.json").write_text(json.dumps(model_to_dict(unit), ensure_ascii=False, indent=2), encoding="utf-8")
            progress.status = "in_progress"
            self._save_checkpoint(output_dir, report.run_id, completed_stages, worktree_path, mode="multi-unit", units=report.units)
            self._write_report(report, output_dir)

            try:
                status = self._run_stage_sequence(
                    unit_stages,
                    report,
                    artifact_dir=unit_dir,
                    report_dir=output_dir,
                    worktree_path=worktree_path,
                    skip_set=skip_set,
                    yes=yes,
                    completed_stages=progress.completed_stages,
                    start=start,
                    execution_mode=execution_mode,
                    resume=resume and bool(progress.completed_stages),
                    checkpoint_mode="multi-unit",
                    checkpoint_units=report.units,
                    unit_progress=progress,
                )
            except Exception:
                progress.status = "failed"
                self._save_checkpoint(output_dir, report.run_id, completed_stages, worktree_path, mode="multi-unit", units=report.units)
                raise
            if status == "waiting":
                return "waiting"
            progress.status = "completed"
            progress.current_stage = None
            completed_unit_ids.add(unit.id)
            self._save_checkpoint(output_dir, report.run_id, completed_stages, worktree_path, mode="multi-unit", units=report.units)
            self._write_report(report, output_dir)

        return "completed"

    def _order_requirement_units(self, units: List[RequirementUnit]) -> List[RequirementUnit]:
        pending = {unit.id: unit for unit in units}
        ordered: List[RequirementUnit] = []
        completed: set = set()
        while pending:
            ready = [
                unit
                for unit in pending.values()
                if all(dep in completed for dep in unit.depends_on)
            ]
            if not ready:
                remaining = ", ".join(sorted(pending))
                raise OrchestratorError(f"Requirement unit dependencies contain a cycle or missing dependency: {remaining}")
            ready.sort(key=lambda item: (item.priority, item.id))
            for unit in ready:
                ordered.append(unit)
                completed.add(unit.id)
                pending.pop(unit.id)
        return ordered

    def _unit_stages(self, stages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        configured = self.config.get("runner", {}).get("unit_stage_ids")
        if configured:
            wanted = set(_as_list(configured))
            return [stage for stage in stages if stage.get("id") in wanted]
        excluded = {"plan", "plan_confirm", "accept"}
        return [stage for stage in stages if stage.get("id") not in excluded and stage.get("type") != "human_review"]

    def _write_requirement_units(self, output_dir: Path, units: List[RequirementUnit]) -> None:
        payload = {"units": [model_to_dict(unit) for unit in units]}
        output_dir.joinpath("requirement-units.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_requirement_units(self, output_dir: Path) -> List[RequirementUnit]:
        units_file = output_dir / "requirement-units.json"
        if not units_file.exists():
            raise OrchestratorError("checkpoint is multi-unit but requirement-units.json is missing")
        payload = json.loads(units_file.read_text(encoding="utf-8"))
        return [RequirementUnit(**item) for item in payload.get("units", [])]

    def _unit_progress_from_checkpoint(self, checkpoint: Dict[str, Any], units: List[RequirementUnit]) -> List[RequirementUnitProgress]:
        by_id = {item.get("unit_id"): RequirementUnitProgress(**item) for item in checkpoint.get("units", []) if isinstance(item, dict)}
        return [by_id.get(unit.id, RequirementUnitProgress(unit_id=unit.id, status="pending")) for unit in units]

    def _save_checkpoint(
        self,
        output_dir: Path,
        run_id: str,
        completed_stages: List[str],
        worktree_path: Optional[Path],
        mode: str = "single",
        units: Optional[List[RequirementUnitProgress]] = None,
    ) -> None:
        """保存 checkpoint 到文件"""
        checkpoint_data = {
            "run_id": run_id,
            "mode": mode,
            "completed_stages": completed_stages,
            "units": [model_to_dict(unit) for unit in units] if units is not None else [],
            "worktree_path": str(worktree_path) if worktree_path else None,
            "timestamp": utc_now(),
        }
        checkpoint_file = output_dir / "checkpoint.json"
        checkpoint_file.write_text(json.dumps(checkpoint_data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger = get_logger("orchestrator", run_id=run_id)
        logger.debug("checkpoint 已保存: %s", completed_stages)

    def _load_checkpoint(self, output_dir: Path) -> Optional[Dict]:
        """从文件加载 checkpoint"""
        checkpoint_file = output_dir / "checkpoint.json"
        if not checkpoint_file.exists():
            return None
        try:
            return json.loads(checkpoint_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _cleanup_checkpoint(self, output_dir: Path) -> None:
        """清理 checkpoint 文件"""
        checkpoint_file = output_dir / "checkpoint.json"
        if checkpoint_file.exists():
            checkpoint_file.unlink(missing_ok=True)

    def _stage_cwd(self, stage_id: str, worktree_path: Optional[Path]) -> Path:
        if not worktree_path:
            return self.project_root
        if stage_id in {"plan", "architect", "context", "code_apply"}:
            return self.project_root
        return worktree_path

    def _run_code_apply_stage(self, stage: Dict[str, Any], report: RunReport, output_dir: Path, worktree_path: Optional[Path]) -> StageRun:
        stage_id = stage.get("id", "code_apply")
        stage_run = StageRun(stage_id=stage_id, stage_name=stage.get("name", stage_id), status="running", type="code_apply", started_at=utc_now())
        start = time.monotonic()
        logger = get_logger("orchestrator", run_id=report.run_id)
        self.bus.emit("stage:started", report.run_id, stage_id=stage_id, stage_name=stage_run.stage_name, iteration=stage_run.iteration)
        apply_root = worktree_path or self.project_root
        source_files = stage.get("input") or ["tech-lead-output.md"]
        source_files = _as_list(source_files)
        applier = CodeApplier(apply_root)
        total_changes = 0
        try:
            for source_name in source_files:
                source_path = output_dir / source_name
                if not source_path.exists():
                    continue
                content = source_path.read_text(encoding="utf-8")
                changes = applier.apply(content)
                total_changes += len(changes)
                for change in changes:
                    self.bus.emit("agent:output", report.run_id, stage_id=stage_id, agent_name="code-applier", text=f"[{change.action}] {change.filepath} ({change.lines} lines)")

            # 自动 commit 变更到 worktree 分支
            if total_changes > 0 and worktree_path:
                worktree_mgr = WorktreeManager(self.project_root, self.config.get("worktree"))
                commit_msg = f"[ai-team] code_apply - {report.run_id}"
                committed = worktree_mgr.commit_all(worktree_path, commit_msg)
                if committed:
                    logger.info("code_apply 自动提交: %s", commit_msg)
                    self.bus.emit("worktree:committed", report.run_id, message=commit_msg)
                else:
                    logger.warning("code_apply 自动提交失败（可能无变更）")

            stage_run.status = "completed"
            stage_run.output_dir = str(output_dir)
        except Exception as exc:
            stage_run.status = "failed"
            stage_run.error_message = str(exc)
        stage_run.completed_at = utc_now()
        stage_run.duration_seconds = _duration(start)
        self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
        return stage_run

    def _run_context_stage(self, stage: Dict[str, Any], report: RunReport, output_dir: Path, worktree_path: Optional[Path]) -> StageRun:
        stage_id = stage.get("id", "context")
        stage_run = StageRun(stage_id=stage_id, stage_name=stage.get("name", stage_id), status="running", type="context_scan", started_at=utc_now())
        start = time.monotonic()
        self.bus.emit("stage:started", report.run_id, stage_id=stage_id, stage_name=stage_run.stage_name, iteration=stage_run.iteration)
        output_file = output_dir / (stage.get("output_file") or "codebase-context.md")
        solution_path = output_dir / "solution-draft.md"
        scan_root = worktree_path or self.project_root
        try:
            scan_codebase(scan_root, solution_path if solution_path.exists() else None, output_file, self.config.get("context_scanner"))
            stage_run.status = "completed"
            stage_run.output_dir = str(output_dir)
        except Exception as exc:
            stage_run.status = "failed"
            stage_run.error_message = str(exc)
        stage_run.completed_at = utc_now()
        stage_run.duration_seconds = _duration(start)
        self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
        return stage_run

    def _run_human_review_stage(self, stage: Dict[str, Any], report: RunReport, output_dir: Path, yes: bool) -> StageRun:
        stage_id = stage.get("id", "accept")
        stage_run = StageRun(stage_id=stage_id, stage_name=stage.get("name", stage_id), status="running", type="human_review", started_at=utc_now())
        start = time.monotonic()
        self.bus.emit("stage:started", report.run_id, stage_id=stage_id, stage_name=stage_run.stage_name, iteration=stage_run.iteration)
        blocker_content = ""
        if stage.get("skip_if_no_blocker"):
            blocker_source = stage.get("blocker_source")
            if blocker_source:
                source_path = output_dir / str(blocker_source)
                if source_path.exists():
                    blocker_content = source_path.read_text(encoding="utf-8", errors="replace")
                else:
                    stage_run.status = "failed"
                    stage_run.error_message = f"blocker_source not found: {blocker_source}"
                    stage_run.completed_at = utc_now()
                    stage_run.duration_seconds = _duration(start)
                    self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
                    return stage_run
            if not self._has_blockers(blocker_content):
                decision = "skipped"
                self._write_human_review_outputs(stage, output_dir, decision, blocker_content)
                stage_run.status = "skipped"
                stage_run.completed_at = utc_now()
                stage_run.duration_seconds = _duration(start)
                self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
                return stage_run

        if yes:
            decision = "accepted"
        elif sys.stdin.isatty():
            response = input(f"Human review for run {report.run_id}. Accept? [y/N] ").strip().lower()
            decision = "accepted" if response in {"y", "yes"} else "rejected"
        else:
            decision = "waiting"
        self._write_human_review_outputs(stage, output_dir, decision, blocker_content)
        stage_run.status = "completed" if decision == "accepted" else ("failed" if decision == "rejected" else "waiting")
        stage_run.error_message = None if decision != "rejected" else "Human review rejected"
        stage_run.completed_at = utc_now()
        stage_run.duration_seconds = _duration(start)
        self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
        return stage_run

    def _write_human_review_outputs(self, stage: Dict[str, Any], output_dir: Path, decision: str, blocker_content: str) -> None:
        stage_id = stage.get("id", "accept")
        json_name = "human-review.json" if stage_id == "accept" else f"{stage_id}-human-review.json"
        payload = {"stage_id": stage_id, "decision": decision}
        (output_dir / json_name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        output_file = stage.get("output_file")
        if output_file:
            lines = [
                "## Human Review Decision",
                "",
                f"- Stage: `{stage_id}`",
                f"- Decision: `{decision}`",
            ]
            if decision == "skipped":
                lines.append("- Reason: 无 blocker，自动跳过人工确认")
            if blocker_content:
                lines.extend(["", "## Blocker Source", "", blocker_content.rstrip()])
            (output_dir / str(output_file)).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _has_blockers(self, content: str) -> bool:
        if not content:
            return False
        lowered = content.lower()
        negative_patterns = [
            r"\bno\s+blockers?\b",
            r"\bwithout\s+blockers?\b",
            r"\bnone\s+blockers?\b",
            "无 blocker",
            "没有 blocker",
            "无阻塞",
            "没有阻塞",
        ]
        if any(re.search(pattern, lowered) if pattern.startswith(r"\b") else pattern in lowered for pattern in negative_patterns):
            return False
        return bool(re.search(r"\bblockers?\b", content, re.IGNORECASE) or "阻塞" in content or "阻断" in content)

    def _run_agent_stage(
        self,
        stage: Dict[str, Any],
        report: RunReport,
        output_dir: Path,
        cwd: Path,
        extra_feedback: str = "",
        execution_mode: Optional[str] = None,
    ) -> StageRun:
        stage_id = stage.get("id")
        is_parallel = self._stage_parallel_enabled(stage, report.requirement, execution_mode)
        stage_run = StageRun(
            stage_id=stage_id,
            stage_name=stage.get("name", stage_id),
            status="running",
            is_parallel=is_parallel,
            started_at=utc_now(),
            output_dir=str(output_dir),
        )
        start = time.monotonic()
        log_stage_start(report.run_id, stage_id)
        self.bus.emit("stage:started", report.run_id, stage_id=stage_id, stage_name=stage_run.stage_name, iteration=stage_run.iteration)
        cost_tracker = CostTracker(self.project_root, bus=self.bus)
        runner = AgentRunner(self.config, bus=self.bus, cost_tracker=cost_tracker)
        agent_names = _as_list(stage.get("agents"))
        if not agent_names:
            stage_run.status = "skipped"
            stage_run.completed_at = utc_now()
            stage_run.duration_seconds = _duration(start)
            return stage_run

        def run_one(agent_name: str) -> AgentRun:
            if agent_name not in self.agents:
                raise ConfigError(f"Agent not configured: {agent_name}")
            agent = self.agents[agent_name]
            runtime = runtime_config(self.config, agent.runtime_id)
            output_name = (stage.get("output") or {}).get(agent.name) or f"{agent.name}-output.md"
            output_file = output_dir / output_name
            raw_log_file = output_dir / f"{stage_id}-{agent.name}.raw.log"
            prompt = self._render_prompt(stage, agent, output_dir, cwd, extra_feedback)
            return runner.run(report.run_id, stage_id, agent, runtime, prompt, cwd, output_file, raw_log_file)

        try:
            if is_parallel and len(agent_names) > 1:
                with ThreadPoolExecutor(max_workers=len(agent_names)) as pool:
                    futures = {pool.submit(run_one, name): name for name in agent_names}
                    for future in as_completed(futures):
                        stage_run.agents.append(future.result())
            else:
                for name in agent_names:
                    stage_run.agents.append(run_one(name))
            failed = [agent for agent in stage_run.agents if agent.status != "completed"]
            if failed:
                stage_run.status = "failed"
                stage_run.error_message = "; ".join(agent.error_message or agent.agent_name for agent in failed)
            else:
                stage_run.status = "completed"
        except Exception as exc:
            stage_run.status = "failed"
            stage_run.error_message = str(exc)

        stage_run.completed_at = utc_now()
        stage_run.duration_seconds = _duration(start)
        log_stage_complete(report.run_id, stage_id, stage_run.status, stage_run.duration_seconds)
        record_stage_duration(stage_id, stage_run.duration_seconds)
        self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
        return stage_run

    def _stage_parallel_enabled(self, stage: Dict[str, Any], requirement: str, execution_mode: Optional[str]) -> bool:
        mode = execution_mode or self.config.get("pipeline_settings", {}).get("execution_mode", "parallel")
        if mode == "auto":
            size = estimate_prompt_size(requirement, [])
            threshold = int(self.config.get("runner", {}).get("context_threshold_chars") or 100000)
            mode = "serial" if size >= threshold else "parallel"
        if mode == "serial":
            return False
        return bool(stage.get("parallel"))

    def _render_loopback_feedback(self, stage_id: str, stage_run: StageRun, retry_count: int, target: str) -> str:
        max_chars = int(self.config.get("runner", {}).get("max_loopback_feedback_chars") or 20000)
        lines = [f"## Loopback 反馈（第 {retry_count} 次重试）", ""]
        lines.append(f"Stage `{stage_id}` 触发了回退到 `{target}`。以下是该 stage 各 agent 的详细输出：")
        used_chars = 0
        for agent in stage_run.agents:
            lines.extend([
                "",
                f"### Agent: {agent.agent_name}",
                f"- Runtime: {agent.runtime_id}",
                f"- CLI: {agent.runtime_cli or 'unknown'}",
                f"- 状态: {agent.status}",
            ])
            if agent.error_message:
                lines.append(f"- 错误: {agent.error_message}")
            if agent.output_file:
                path = Path(agent.output_file)
                if path.exists():
                    remaining = max_chars - used_chars
                    if remaining <= 0:
                        lines.append("\n[...达到反馈上限，后续 agent 输出已省略]")
                        break
                    content = path.read_text(encoding="utf-8", errors="replace")
                    if len(content) > remaining:
                        content = content[:remaining] + "\n\n[...truncated]"
                    used_chars += len(content)
                    lines.extend(["", "```text", content, "```"])
        if not stage_run.agents:
            fallback = self._stage_output_text(stage_run)
            if fallback:
                if len(fallback) > max_chars:
                    fallback = fallback[:max_chars] + "\n\n[...truncated]"
                lines.extend(["", "```text", fallback, "```"])
        lines.extend(["", "请根据以上反馈修复问题，只修改必要的部分，不要改动已通过的文件。"])
        return "\n".join(lines)

    def _run_develop_quality_loop(
        self,
        stage: Dict[str, Any],
        stage_run: StageRun,
        report: RunReport,
        output_dir: Path,
        cwd: Path,
        execution_mode: Optional[str] = None,
    ) -> List[StageRun]:
        gates = self.config.get("quality_gates", [])
        retry_count = 0
        stage_runs = [stage_run]
        while True:
            gate_results = run_quality_gates(gates, cwd, report.run_id, self.bus, retry_count=retry_count)
            stage_run.quality_gates.extend(gate_results)
            self._write_report(report, output_dir)
            if not has_blocking_failure(gate_results):
                return stage_runs
            max_retries = max_retry_count_for_failures(gates, gate_results)
            if retry_count >= max_retries:
                stage_run.status = "failed"
                stage_run.error_message = "Required quality gate failed"
                return stage_runs
            retry_count += 1
            feedback = render_gate_feedback(gate_results, retry_count)
            feedback_file = output_dir / f"quality-feedback-{retry_count}.md"
            feedback_file.write_text(feedback, encoding="utf-8")
            self.bus.emit("loopback:triggered", report.run_id, from_stage="quality_gates", to_stage="develop", iteration=retry_count + 1)
            retry_stage = self._run_agent_stage(stage, report, output_dir, cwd, feedback, execution_mode=execution_mode)
            retry_stage.iteration = retry_count + 1
            stage_runs.append(retry_stage)
            if retry_stage.status != "completed":
                return stage_runs
            stage_run = retry_stage

    def _render_prompt(self, stage: Dict[str, Any], agent: AgentDefinition, output_dir: Path, cwd: Path, extra_feedback: str = "") -> str:
        warnings = self.config_warnings
        base_prompt = read_prompt(self.project_root, self.loaded_config.path, agent, warnings)
        inputs = self._collect_inputs(stage.get("input"), output_dir, cwd)
        parts = [
            base_prompt.rstrip(),
            "",
            "## 运行上下文",
            f"- Project root: `{self.project_root}`",
            f"- Working directory: `{cwd}`",
            f"- Stage: `{stage.get('id')}` / `{stage.get('name', stage.get('id'))}`",
            "",
        ]
        if extra_feedback:
            parts.extend([extra_feedback.rstrip(), ""])
        parts.extend(inputs)
        return "\n".join(parts).rstrip() + "\n"

    def _collect_inputs(self, input_config: Any, output_dir: Path, cwd: Path) -> List[str]:
        items = _as_list(input_config or "requirement")
        max_chars = self.config.get("runner", {}).get("max_input_chars_per_file")
        max_chars = int(max_chars) if max_chars else None
        parts: List[str] = []
        for item in items:
            if item == "requirement":
                parts.extend(["## Requirement", (output_dir / "requirement.md").read_text(encoding="utf-8"), ""])
            elif item == "git-diff":
                diff = self._git_diff(cwd)
                parts.extend(["## git-diff", "```diff", diff or "(no diff)", "```", ""])
            elif isinstance(item, str) and "*" in item:
                for path in sorted(output_dir.glob(item)):
                    parts.extend(self._artifact_section(path, max_chars))
            elif isinstance(item, str):
                path = output_dir / item
                if path.exists():
                    parts.extend(self._artifact_section(path, max_chars))
        return parts

    def _artifact_section(self, path: Path, max_chars: Optional[int]) -> List[str]:
        content = path.read_text(encoding="utf-8", errors="replace")
        if max_chars and len(content) > max_chars:
            content = content[:max_chars] + "\n\n[truncated]"
        return [f"## Artifact: `{path.name}`", "```markdown", content, "```", ""]

    def _git_diff(self, cwd: Path) -> str:
        import subprocess

        # 获取已提交的变更（相对于 base branch）
        base_branch = self.config.get("worktree", {}).get("base_branch", "main")
        committed = subprocess.run(["git", "diff", f"{base_branch}...HEAD"], cwd=cwd, capture_output=True, text=True, check=False)
        # 获取 staged changes
        staged = subprocess.run(["git", "diff", "--cached"], cwd=cwd, capture_output=True, text=True, check=False)
        # 获取 unstaged changes
        unstaged = subprocess.run(["git", "diff"], cwd=cwd, capture_output=True, text=True, check=False)
        # 获取 stat
        stat = subprocess.run(["git", "diff", "--stat"], cwd=cwd, capture_output=True, text=True, check=False)

        parts = [stat.stdout, committed.stdout, staged.stdout, unstaged.stdout]
        return "\n".join(part for part in parts if part.strip())

    def _stage_output_text(self, stage_run: StageRun) -> str:
        chunks = []
        for agent in stage_run.agents:
            if agent.output_file and Path(agent.output_file).exists():
                chunks.append(Path(agent.output_file).read_text(encoding="utf-8", errors="replace"))
        return "\n".join(chunks)

    def _extract_error_signature(self, content: str) -> str:
        """提取错误签名用于检测重复错误。

        策略：提取错误相关的关键行，忽略行号、时间戳等易变信息。
        """
        import re

        # 错误关键词
        ERROR_KEYWORDS = [
            "error", "Error", "ERROR",
            "failed", "Failed", "FAILED",
            "failure", "Failure", "FAILURE",
            "exception", "Exception", "EXCEPTION",
            "Traceback", "traceback",
            "失败", "错误", "异常",
        ]

        lines = content.split("\n")
        error_lines = []

        for line in lines:
            # 检查是否包含错误关键词
            if any(keyword in line for keyword in ERROR_KEYWORDS):
                # 标准化行：移除行号、时间戳等易变信息
                normalized = line.strip()
                # 移除行号（如 "line 42", "L42"）
                normalized = re.sub(r'(?:line|L)\s*\d+', 'line N', normalized)
                # 移除时间戳
                normalized = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', 'TIMESTAMP', normalized)
                # 移除具体路径中的数字
                normalized = re.sub(r'/\d+/', '/N/', normalized)
                error_lines.append(normalized)

        # 返回前 5 行错误作为签名
        return "\n".join(error_lines[:5]) if error_lines else ""

    def _refresh_artifacts(self, report: RunReport, output_dir: Path) -> None:
        artifacts = []
        for path in output_dir.rglob("*"):
            if path.is_file():
                artifacts.append(str(path.relative_to(output_dir)))
        report.artifacts = sorted(artifacts)

    def _run_ci_cd_hook(self, worktree_path: Path, report: RunReport, output_dir: Path) -> None:
        ci_cd_config = self.config.get("ci_cd", {})
        if not ci_cd_config.get("create_pr"):
            return
        logger = get_logger("orchestrator", run_id=report.run_id)
        try:
            from .ci_cd import run_ci_cd_hook
            summary = {
                "run_id": report.run_id,
                "requirement": report.requirement,
                "duration_seconds": report.duration_seconds,
                "stages": [s.model_dump(mode="json") for s in report.stages],
            }
            result = run_ci_cd_hook(self.config, str(worktree_path), summary)
            report.merge_result = report.merge_result or {}
            report.merge_result["ci_cd"] = result
            self._write_report(report, output_dir)
            if result.get("status") == "created":
                logger.info("CI/CD PR created: %s", result.get("url", ""))
                self.bus.emit("ci_cd:pr_created", report.run_id, url=result.get("url"), number=result.get("number"))
        except Exception as exc:
            logger.warning("CI/CD hook failed (non-blocking): %s", exc)

    def _write_report(self, report: RunReport, output_dir: Path) -> None:
        self._refresh_artifacts(report, output_dir)
        report.write(output_dir / "report.json")
        try:
            from persistence import save_report_sync

            save_report_sync(report, self.config)
        except Exception:
            pass


def load_report(path: Path) -> RunReport:
    data = json.loads(path.read_text(encoding="utf-8"))
    for stage in data.get("stages", []) or []:
        if not isinstance(stage, dict):
            continue
        for agent in stage.get("agents", []) or []:
            if isinstance(agent, dict) and not agent.get("runtime_id"):
                agent["runtime_id"] = "legacy"
    return RunReport(**data)


def find_run_reports(project_root: Path) -> List[Path]:
    output_root = project_root / ".ai" / "team-output"
    if not output_root.exists():
        return []
    return sorted(output_root.glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
