from __future__ import annotations

import json
import re
import shutil
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .agent_runner import AgentRunner
from .artifact_contracts import (
    SchemaValidationError,
    has_artifact_validation_failure,
    load_schema_for_artifact,
    stage_schema_hint,
    validate_artifact,
    validate_requirement_for_planning,
    validate_required_artifacts,
    validate_review_for_loopback,
)
from .config import (
    ConfigError,
    agent_map,
    load_config,
    read_prompt,
    validate_production_config,
)
from .context_scanner import scan_codebase, scan_to_json
from .cost_tracker import CostTracker
from .events import EventBus
from .human_gate import (
    is_hard_human_gate,
    normalize_decision,
    render_reject_feedback,
    waiting_decision,
    write_decision_artifacts,
)
from .harness_checks import render_harness_feedback, run_harness_verification
from .models import AgentDefinition, AgentRun, HumanDecision, RequirementUnit, RequirementUnitProgress, RunReport, StageRun, model_to_dict, utc_now
from .requirement_splitter import estimate_prompt_size, should_split, split_requirement
from .runtimes import _cli_config_model, backfill_runtime_models, resolve_auto_cli, runtime_config
from .stage_context import build_stage_context
from .truncate_utils import truncate_with_fallback
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
from .release_readiness import generate_release_readiness
from .worktree import WorktreeError, WorktreeManager


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
        self._production_run = False
        self._backfill_runtime_models()

    def _backfill_runtime_models(self) -> None:
        """对未显式声明 model 的 runtime，尝试从 CLI 配置回填，仅用于可观测性。"""
        runtimes = self.config.get("runtimes", {})
        backfill_runtime_models(runtimes)

    def run(
        self,
        requirement: str,
        run_id: Optional[str] = None,
        only_stage: Optional[str] = None,
        skip_stages: Optional[Sequence[str]] = None,
        yes: bool = False,
        reject: bool = False,
        production: bool = False,
        merge: bool = False,
        resume: bool = False,
        execution_mode: Optional[str] = None,
        human_decision: Optional[HumanDecision] = None,
    ) -> RunReport:
        if execution_mode and execution_mode not in {"serial", "parallel", "auto"}:
            raise ConfigError("execution_mode must be one of: serial, parallel, auto")
        self._production_run = bool(production or self.config.get("runner", {}).get("production_mode"))
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
        if checkpoint:
            report.human_decisions = self._load_human_decisions_from_checkpoint(checkpoint, report)

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

        all_stages = list(self.config.get("pipeline", []))
        skip_set = set(skip_stages or [])
        selection_error = self._validate_stage_selection(all_stages, only_stage, skip_set)
        if selection_error:
            report.status = "failed"
            report.error_message = selection_error
            report.completed_at = utc_now()
            report.duration_seconds = _duration(start)
            record_run("failed")
            self._write_report(report, output_dir)
            return report
        stages = [stage for stage in all_stages if not only_stage or stage.get("id") == only_stage]
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
                sequence_status = self._run_multi_unit_pipeline(
                    split_units,
                    stages,
                    report,
                    output_dir,
                    worktree_path,
                    skip_set,
                    yes,
                    reject,
                    completed_stages,
                    start,
                    execution_mode,
                    human_decision=human_decision,
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
                    reject=reject,
                    completed_stages=completed_stages,
                    start=start,
                    execution_mode=execution_mode,
                    human_decision=human_decision,
                    resume=resume,
                )
            if sequence_status == "waiting":
                report.status = "paused"

            if report.status == "running":
                if worktree_path and worktree_manager:
                    report.changed_files = worktree_manager.get_changed_files(worktree_path)
                    report.diff_stat = worktree_manager.get_diff_stat(worktree_path)
                    self.bus.emit("files:changed", run_id, changed_files=report.changed_files, diff_stat=report.diff_stat)

                    if self.config.get("ci_cd", {}).get("create_pr"):
                        delivery_result = self._deliver_pr(worktree_manager, worktree_path, report, output_dir)
                        report.pr_info = delivery_result
                        if delivery_result.get("status") == "blocked":
                            report.status = "blocked"
                        elif delivery_result.get("status") in {"created", "existing"}:
                            report.status = "completed"
                        else:
                            report.status = "failed"
                            report.error_message = delivery_result.get("error") or "PR delivery failed"
                    elif merge or self.config.get("worktree", {}).get("merge_on_success"):
                        report.merge_result = worktree_manager.merge(worktree_path)
                        report.status = "completed"
                        if self.config.get("worktree", {}).get("auto_cleanup") and report.merge_result.get("status") in {"merged", "no_changes"}:
                            worktree_manager.cleanup(worktree_path)
                    else:
                        report.merge_result = {"status": "skipped", "reason": "merge_on_success disabled"}
                        report.status = "completed"
                else:
                    report.status = "completed"

                if report.status == "completed" and worktree_path and not report.pr_info:
                    self._run_ci_cd_hook(worktree_path, report, output_dir)
            report.completed_at = utc_now()
            report.duration_seconds = _duration(start)
            record_run(report.status)
            logger.info("pipeline run completed status=%s duration=%.1fs", report.status, report.duration_seconds)
            self.bus.emit("run:completed", report.run_id, status=report.status, summary={"duration": report.duration_seconds})
            self._write_report(report, output_dir)
            generate_release_readiness(report, output_dir)
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
            generate_release_readiness(report, output_dir)
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
        reject: bool,
        completed_stages: List[str],
        start: float,
        execution_mode: Optional[str],
        resume: bool = False,
        checkpoint_mode: str = "single",
        checkpoint_units: Optional[List[RequirementUnitProgress]] = None,
        unit_progress: Optional[RequirementUnitProgress] = None,
        human_decision: Optional[HumanDecision] = None,
        external_reject_targets: Optional[set[str]] = None,
    ) -> str:
        stage_index_by_id = {stage.get("id"): index for index, stage in enumerate(stages)}
        external_reject_targets = external_reject_targets or set()
        loop_counts: Dict[str, int] = {}
        loopback_errors: Dict[str, List[str]] = {}
        index = 0
        extra_feedback = ""
        pending_human_decision = human_decision
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
                self._save_checkpoint(
                    report_dir,
                    report.run_id,
                    completed_stages,
                    worktree_path,
                    mode=checkpoint_mode,
                    units=checkpoint_units,
                    human_decisions=report.human_decisions,
                )
                index += 1
                self._write_report(report, report_dir)
                continue

            if unit_progress:
                unit_progress.status = "in_progress"
                unit_progress.current_stage = stage_id
                unit_progress.completed_stages = list(completed_stages)
                self._save_checkpoint(
                    report_dir,
                    report.run_id,
                    completed_stages,
                    worktree_path,
                    mode=checkpoint_mode,
                    units=checkpoint_units,
                    human_decisions=report.human_decisions,
                )

            entry_error = self._validate_stage_entry(stage_id, artifact_dir, stages)
            if entry_error:
                raise OrchestratorError(f"Stage {stage_id} blocked by schema validation: {entry_error}")

            stage_runs_to_append: List[StageRun]
            if stage.get("type") == "context_scan":
                stage_run = self._run_context_stage(stage, report, artifact_dir, worktree_path)
                stage_runs_to_append = [stage_run]
            elif stage.get("type") == "harness_verify":
                cwd = self._stage_cwd(stage_id, worktree_path)
                stage_run = self._run_harness_verify_stage(stage, report, artifact_dir, cwd)
                stage_runs_to_append = [stage_run]
            elif stage.get("type") == "human_review":
                stage_decision = pending_human_decision
                stage_run = self._run_human_review_stage(stage, report, artifact_dir, yes=yes, reject=reject, human_decision=stage_decision)
                if stage_decision is not None and is_hard_human_gate(stage):
                    pending_human_decision = None
                stage_runs_to_append = [stage_run]
            elif stage.get("type") == "code_apply":
                stage_run = StageRun(
                    stage_id=stage_id,
                    stage_name=stage.get("name", stage_id),
                    status="failed",
                    type="code_apply",
                    error_message="code_apply stage type is deprecated; use develop to implement code changes directly",
                    started_at=utc_now(),
                    completed_at=utc_now(),
                    duration_seconds=0,
                )
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

            if stage_run.status == "waiting":
                if unit_progress:
                    unit_progress.current_stage = stage_id
                self._save_checkpoint(
                    report_dir,
                    report.run_id,
                    completed_stages,
                    worktree_path,
                    mode=checkpoint_mode,
                    units=checkpoint_units,
                    human_decisions=report.human_decisions,
                )
                return "waiting"

            if stage_run.status not in {"completed", "skipped"}:
                raise OrchestratorError(stage_run.error_message or f"Stage failed: {stage_id}")

            if stage_run.human_decision and stage_run.human_decision.decision == "rejected":
                target = stage_run.human_decision.target_stage
                if not target:
                    raise OrchestratorError(f"Human reject target not found: {target}")
                count = self._human_reject_count(report, stage_id)
                extra_feedback = render_reject_feedback(stage_run.human_decision, count)
                feedback_file = artifact_dir / f"human-feedback-{stage_id}-{count}.md"
                feedback_file.write_text(extra_feedback, encoding="utf-8")
                if target not in stage_index_by_id:
                    if target in external_reject_targets:
                        self._save_checkpoint(
                            report_dir,
                            report.run_id,
                            completed_stages,
                            worktree_path,
                            mode=checkpoint_mode,
                            units=checkpoint_units,
                            human_decisions=report.human_decisions,
                        )
                        self._write_report(report, report_dir)
                        return f"loopback:{stage_id}:{target}"
                    raise OrchestratorError(f"Human reject target not found: {target}")
                target_index = stage_index_by_id[target]
                target_stage_ids = {s.get("id") for s in stages[target_index:]}
                completed_stages[:] = [item for item in completed_stages if item not in target_stage_ids]
                if unit_progress:
                    unit_progress.completed_stages = list(completed_stages)
                self._save_checkpoint(
                    report_dir,
                    report.run_id,
                    completed_stages,
                    worktree_path,
                    mode=checkpoint_mode,
                    units=checkpoint_units,
                    human_decisions=report.human_decisions,
                )
                self._write_report(report, report_dir)
                index = target_index
                continue

            if stage_run.status in {"completed", "skipped"}:
                if stage_id not in completed_stages:
                    completed_stages.append(stage_id)
                if unit_progress:
                    unit_progress.completed_stages = list(completed_stages)
                    unit_progress.current_stage = None
                self._save_checkpoint(
                    report_dir,
                    report.run_id,
                    completed_stages,
                    worktree_path,
                    mode=checkpoint_mode,
                    units=checkpoint_units,
                    human_decisions=report.human_decisions,
                )
                self._push_file_changes(report.run_id, worktree_path)

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
                self._save_checkpoint(
                    report_dir,
                    report.run_id,
                    completed_stages,
                    worktree_path,
                    mode=checkpoint_mode,
                    units=checkpoint_units,
                    human_decisions=report.human_decisions,
                )
                self._write_report(report, report_dir)
                index = target_index
                continue

            if stage.get("loopback_to") and stage_id == "review":
                review_info = self._check_review_loopback(stage_id, artifact_dir)
                if review_info:
                    count = loop_counts.get(stage_id, 0) + 1
                    loop_counts[stage_id] = count
                    max_retries = int(stage.get("max_retries") or 0)
                    if count > max_retries:
                        raise OrchestratorError(f"Stage {stage_id} requested loopback more than {max_retries} times")
                    target = stage.get("loopback_to")
                    if target not in stage_index_by_id:
                        raise OrchestratorError(f"Loopback target not found: {target}")
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
                    extra_feedback = (
                        f"## Review 结构化回流\n\n"
                        f"- Verdict: {review_info['verdict']}\n"
                        f"- Blocking findings: {review_info['blocking_count']}\n"
                        f"- 详情: {review_info['summary']}\n\n"
                        f"请根据以上 review 反馈修复问题。"
                    )
                    feedback_file = artifact_dir / f"loopback-feedback-{stage_id}-{count}.md"
                    feedback_file.write_text(extra_feedback, encoding="utf-8")
                    self._save_checkpoint(
                        report_dir,
                        report.run_id,
                        completed_stages,
                        worktree_path,
                        mode=checkpoint_mode,
                        units=checkpoint_units,
                        human_decisions=report.human_decisions,
                    )
                    self._write_report(report, report_dir)
                    index = target_index
                    continue

            index += 1

        return "completed"

    def _validate_stage_selection(self, stages: List[Dict[str, Any]], only_stage: Optional[str], skip_set: set) -> Optional[str]:
        hard_gate_ids = {str(stage.get("id")) for stage in stages if is_hard_human_gate(stage)}
        if not hard_gate_ids:
            return None
        if only_stage:
            gates = ", ".join(sorted(hard_gate_ids))
            return f"only_stage cannot be used because this pipeline contains hard human gates: {gates}"
        skipped_hard_gates = hard_gate_ids.intersection(skip_set)
        if skipped_hard_gates:
            return f"skip_stages cannot skip hard human gates: {', '.join(sorted(skipped_hard_gates))}"
        return None

    def _run_multi_unit_pipeline(
        self,
        units: List[RequirementUnit],
        stages: List[Dict[str, Any]],
        report: RunReport,
        output_dir: Path,
        worktree_path: Optional[Path],
        skip_set: set,
        yes: bool,
        reject: bool,
        completed_stages: List[str],
        start: float,
        execution_mode: Optional[str],
        human_decision: Optional[HumanDecision],
        resume: bool,
    ) -> str:
        pre_stages, unit_stages, post_stages = self._partition_multi_unit_stages(stages)

        if pre_stages:
            status = self._run_stage_sequence(
                pre_stages,
                report,
                artifact_dir=output_dir,
                report_dir=output_dir,
                worktree_path=worktree_path,
                skip_set=skip_set,
                yes=yes,
                reject=reject,
                completed_stages=completed_stages,
                start=start,
                execution_mode=execution_mode,
                human_decision=self._decision_for_stages(human_decision, pre_stages),
                resume=resume,
                checkpoint_mode="multi-unit",
                checkpoint_units=report.units,
            )
            if status == "waiting":
                return status

        unit_stage_ids = {str(stage.get("id")) for stage in unit_stages}
        while True:
            status = self._run_requirement_units(
                units,
                unit_stages,
                report,
                output_dir,
                worktree_path,
                skip_set,
                yes,
                reject,
                completed_stages,
                start,
                execution_mode,
                human_decision=self._decision_for_stages(human_decision, unit_stages),
                resume=resume,
            )
            if status == "waiting":
                return status

            self._write_unit_summary_artifacts(output_dir, report.units)
            for stage in unit_stages:
                stage_id = str(stage.get("id"))
                if stage_id not in completed_stages:
                    completed_stages.append(stage_id)

            if not post_stages:
                return "completed"

            status = self._run_stage_sequence(
                post_stages,
                report,
                artifact_dir=output_dir,
                report_dir=output_dir,
                worktree_path=worktree_path,
                skip_set=skip_set,
                yes=yes,
                reject=reject,
                completed_stages=completed_stages,
                start=start,
                execution_mode=execution_mode,
                human_decision=self._decision_for_stages(human_decision, post_stages),
                resume=True,
                checkpoint_mode="multi-unit",
                checkpoint_units=report.units,
                external_reject_targets=unit_stage_ids,
            )
            if status == "waiting":
                return status
            if status.startswith("loopback:"):
                _, from_stage, target = status.split(":", 2)
                self._reset_requirement_unit_progress(report.units)
                completed_stages[:] = [stage_id for stage_id in completed_stages if stage_id not in unit_stage_ids]
                self._save_checkpoint(
                    output_dir,
                    report.run_id,
                    completed_stages,
                    worktree_path,
                    mode="multi-unit",
                    units=report.units,
                    human_decisions=report.human_decisions,
                )
                self._write_report(report, output_dir)
                self.bus.emit("loopback:triggered", report.run_id, from_stage=from_stage, to_stage=target, iteration=1)
                resume = False
                human_decision = None
                continue

            return "completed"

    def _decision_for_stages(self, decision: Optional[HumanDecision], stages: List[Dict[str, Any]]) -> Optional[HumanDecision]:
        if decision is None:
            return None
        stage_ids = {stage.get("id") for stage in stages}
        return decision if decision.stage_id in stage_ids else None

    def _partition_multi_unit_stages(
        self,
        stages: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        unit_stages = self._unit_stages(stages)
        if not unit_stages:
            raise OrchestratorError("No stages available for requirement units")
        unit_ids = {stage.get("id") for stage in unit_stages}
        first_unit_index = next(index for index, stage in enumerate(stages) if stage.get("id") in unit_ids)
        last_unit_index = max(index for index, stage in enumerate(stages) if stage.get("id") in unit_ids)
        return stages[:first_unit_index], unit_stages, stages[last_unit_index + 1 :]

    def _reset_requirement_unit_progress(self, units: List[RequirementUnitProgress]) -> None:
        for progress in units:
            progress.status = "pending"
            progress.current_stage = None
            progress.completed_stages = []

    def _run_requirement_units(
        self,
        units: List[RequirementUnit],
        stages: List[Dict[str, Any]],
        report: RunReport,
        output_dir: Path,
        worktree_path: Optional[Path],
        skip_set: set,
        yes: bool,
        reject: bool,
        completed_stages: List[str],
        start: float,
        execution_mode: Optional[str],
        human_decision: Optional[HumanDecision],
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
            self._prepare_unit_artifacts(output_dir, unit_dir)
            progress.status = "in_progress"
            self._save_checkpoint(
                output_dir,
                report.run_id,
                completed_stages,
                worktree_path,
                mode="multi-unit",
                units=report.units,
                human_decisions=report.human_decisions,
            )
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
                    reject=reject,
                    completed_stages=progress.completed_stages,
                    start=start,
                    execution_mode=execution_mode,
                    resume=resume and bool(progress.completed_stages),
                    checkpoint_mode="multi-unit",
                    checkpoint_units=report.units,
                    unit_progress=progress,
                    human_decision=human_decision,
                )
            except Exception:
                progress.status = "failed"
                self._save_checkpoint(
                    output_dir,
                    report.run_id,
                    completed_stages,
                    worktree_path,
                    mode="multi-unit",
                    units=report.units,
                    human_decisions=report.human_decisions,
                )
                raise
            if status == "waiting":
                return "waiting"
            progress.status = "completed"
            progress.current_stage = None
            completed_unit_ids.add(unit.id)
            self._save_checkpoint(
                output_dir,
                report.run_id,
                completed_stages,
                worktree_path,
                mode="multi-unit",
                units=report.units,
                human_decisions=report.human_decisions,
            )
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
            selected = [stage for stage in stages if stage.get("id") in wanted]
        else:
            wanted = {"develop", "qa", "review"}
            selected = [stage for stage in stages if stage.get("id") in wanted]
            if not selected:
                excluded = {"plan", "plan_confirm", "accept", "retrospect"}
                selected = [stage for stage in stages if stage.get("id") not in excluded and stage.get("type") != "human_review"]
        hard_unit_gates = [str(stage.get("id")) for stage in selected if is_hard_human_gate(stage)]
        if hard_unit_gates:
            raise OrchestratorError(f"Hard human gates cannot run inside requirement units: {', '.join(hard_unit_gates)}")
        return [self._unit_stage_copy(stage) for stage in selected if stage.get("type") != "human_review"]

    def _unit_stage_copy(self, stage: Dict[str, Any]) -> Dict[str, Any]:
        copied = dict(stage)
        inputs = _as_list(copied.get("input") or "requirement")
        for required in reversed(["requirement", "unit.json"]):
            if required not in inputs:
                inputs.insert(0, required)
        copied["input"] = inputs
        return copied

    def _prepare_unit_artifacts(self, output_dir: Path, unit_dir: Path) -> None:
        skip_names = {"requirement.md", "checkpoint.json", "report.json", "requirement-units.json"}
        for path in output_dir.iterdir():
            if not path.is_file():
                continue
            if path.name in skip_names:
                continue
            if path.suffix not in {".md", ".json"}:
                continue
            shutil.copy2(path, unit_dir / path.name)

    def _write_unit_summary_artifacts(self, output_dir: Path, units: List[RequirementUnitProgress]) -> None:
        unit_payloads: List[Dict[str, Any]] = []
        for progress in units:
            unit_dir = output_dir / "requirement-units" / progress.unit_id
            payload = {
                "unit_id": progress.unit_id,
                "status": progress.status,
                "artifacts": {},
            }
            for name in ("implementation-report.md", "test-report.md", "review-report.md"):
                path = unit_dir / name
                if path.exists():
                    payload["artifacts"][name] = str(path.relative_to(output_dir))
            unit_payloads.append(payload)

        summary_lines = ["# Multi-unit Execution Summary", ""]
        for payload in unit_payloads:
            summary_lines.extend([f"## {payload['unit_id']}", "", f"- Status: `{payload['status']}`"])
            for name, relative_path in payload["artifacts"].items():
                summary_lines.append(f"- {name}: `{relative_path}`")
            summary_lines.append("")
        summary_text = "\n".join(summary_lines).rstrip() + "\n"

        (output_dir / "implementation-report.md").write_text(summary_text, encoding="utf-8")
        (output_dir / "test-report.md").write_text(summary_text, encoding="utf-8")
        (output_dir / "review-report.md").write_text(summary_text, encoding="utf-8")

        evidence = [
            {"source": "requirement-units", "finding": json.dumps(item, ensure_ascii=False)}
            for item in unit_payloads
        ]
        (output_dir / "implementation-report.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "summary": "multi-unit implementation completed",
                    "changed_files": [],
                    "tests_run": [],
                    "acceptance_coverage": [],
                    "evidence": evidence,
                    "risks": [],
                    "units": unit_payloads,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (output_dir / "test-report.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "summary": "multi-unit test reports completed",
                    "commands": [],
                    "results": [],
                    "acceptance_coverage": [],
                    "evidence": evidence,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (output_dir / "review-report.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "summary": "multi-unit review reports completed",
                    "verdict": "Approve",
                    "blocking_findings": [],
                    "findings": [],
                    "evidence": evidence,
                    "risks": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

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

    def _human_reject_count(self, report: RunReport, stage_id: str) -> int:
        return sum(
            1
            for decision in report.human_decisions
            if decision.stage_id == stage_id and decision.decision == "rejected"
        )

    def _load_human_decisions_from_checkpoint(self, checkpoint: Dict[str, Any], report: RunReport) -> List[HumanDecision]:
        decisions: List[HumanDecision] = []
        raw_items = checkpoint.get("human_decisions", [])
        if raw_items is None:
            return decisions
        if not isinstance(raw_items, list):
            report.warnings.append("checkpoint human_decisions is malformed and was skipped")
            return decisions
        for index, item in enumerate(raw_items):
            try:
                decision = (
                    HumanDecision.model_validate(item)
                    if hasattr(HumanDecision, "model_validate")
                    else HumanDecision(**item)
                )
            except Exception as exc:
                report.warnings.append(f"checkpoint human_decisions[{index}] is malformed and was skipped: {exc}")
                continue
            decisions.append(decision)
        return decisions

    def _save_checkpoint(
        self,
        output_dir: Path,
        run_id: str,
        completed_stages: List[str],
        worktree_path: Optional[Path],
        mode: str = "single",
        units: Optional[List[RequirementUnitProgress]] = None,
        human_decisions: Optional[List[HumanDecision]] = None,
    ) -> None:
        """保存 checkpoint 到文件"""
        checkpoint_data = {
            "run_id": run_id,
            "mode": mode,
            "completed_stages": completed_stages,
            "units": [model_to_dict(unit) for unit in units] if units is not None else [],
            "human_decisions": [model_to_dict(item) for item in human_decisions or []],
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
        if stage_id in {"analyse", "plan", "plan_confirm", "architect", "context", "task_plan"}:
            return self.project_root
        return worktree_path

    def _run_context_stage(self, stage: Dict[str, Any], report: RunReport, output_dir: Path, worktree_path: Optional[Path]) -> StageRun:
        stage_id = stage.get("id", "context")
        stage_run = StageRun(stage_id=stage_id, stage_name=stage.get("name", stage_id), status="running", type="context_scan", started_at=utc_now())
        start = time.monotonic()
        self.bus.emit("stage:started", report.run_id, stage_id=stage_id, stage_name=stage_run.stage_name, iteration=stage_run.iteration)
        output_file = output_dir / (stage.get("output_file") or "codebase-context.md")
        output_json = output_dir / str(stage.get("output_json")) if stage.get("output_json") else None
        scan_root = worktree_path or self.project_root
        try:
            scan_codebase(scan_root, None, output_file, self.config.get("context_scanner"))
            if output_json:
                output_json.write_text(scan_to_json(scan_root, self.config.get("context_scanner")), encoding="utf-8")
            validations = validate_required_artifacts(stage, output_dir)
            stage_run.artifact_validations.extend(validations)
            if has_artifact_validation_failure(validations):
                failed = "; ".join(f"{item.artifact}: {item.message}" for item in validations if item.status == "failed")
                stage_run.status = "failed"
                stage_run.error_message = failed
            else:
                stage_run.status = "completed"
            stage_run.output_dir = str(output_dir)
        except Exception as exc:
            stage_run.status = "failed"
            stage_run.error_message = str(exc)
        stage_run.completed_at = utc_now()
        stage_run.duration_seconds = _duration(start)
        self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
        return stage_run

    def _run_harness_verify_stage(
        self,
        stage: Dict[str, Any],
        report: RunReport,
        output_dir: Path,
        cwd: Path,
    ) -> StageRun:
        stage_id = stage.get("id", "harness_verify")
        stage_run = StageRun(
            stage_id=stage_id,
            stage_name=stage.get("name", stage_id),
            status="running",
            type="harness_verify",
            started_at=utc_now(),
            output_dir=str(output_dir),
        )
        start = time.monotonic()
        log_stage_start(report.run_id, stage_id)
        self.bus.emit("stage:started", report.run_id, stage_id=stage_id, stage_name=stage_run.stage_name, iteration=stage_run.iteration)
        try:
            harness_report = run_harness_verification(
                self.project_root,
                run_id=report.run_id,
                stage_id=stage_id,
                artifact_dir=output_dir,
                cwd=cwd,
                production=self._production_run,
            )
            validations = validate_required_artifacts(stage, output_dir)
            stage_run.artifact_validations.extend(validations)
            if harness_report.get("blocking"):
                feedback = render_harness_feedback(harness_report)
                feedback_file = output_dir / "harness-feedback.md"
                feedback_file.write_text(feedback, encoding="utf-8")
                stage_run.status = "failed"
                stage_run.error_message = "Harness checks failed; see harness-feedback.md"
            elif has_artifact_validation_failure(validations):
                failed = "; ".join(f"{item.artifact}: {item.message}" for item in validations if item.status == "failed")
                stage_run.status = "failed"
                stage_run.error_message = failed
            else:
                stage_run.status = "completed"
        except Exception as exc:
            stage_run.status = "failed"
            stage_run.error_message = str(exc)
        stage_run.completed_at = utc_now()
        stage_run.duration_seconds = _duration(start)
        log_stage_complete(report.run_id, stage_id, stage_run.status, stage_run.duration_seconds)
        self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
        return stage_run

    def _run_human_review_stage(
        self,
        stage: Dict[str, Any],
        report: RunReport,
        output_dir: Path,
        yes: bool,
        reject: bool = False,
        human_decision: Optional[HumanDecision] = None,
    ) -> StageRun:
        stage_id = stage.get("id", "accept")
        stage_run = StageRun(stage_id=stage_id, stage_name=stage.get("name", stage_id), status="running", type="human_review", started_at=utc_now())
        start = time.monotonic()
        self.bus.emit("stage:started", report.run_id, stage_id=stage_id, stage_name=stage_run.stage_name, iteration=stage_run.iteration)
        if is_hard_human_gate(stage):
            if human_decision is None:
                decision = waiting_decision(stage)
                write_decision_artifacts(stage, output_dir, decision)
                stage_run.status = "waiting"
                stage_run.human_decision = decision
                stage_run.completed_at = utc_now()
                stage_run.duration_seconds = _duration(start)
                self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
                return stage_run

            try:
                decision = normalize_decision(stage, human_decision)
            except ValueError as exc:
                stage_run.status = "failed"
                stage_run.error_message = str(exc)
                stage_run.completed_at = utc_now()
                stage_run.duration_seconds = _duration(start)
                self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
                return stage_run

            stage_run.human_decision = decision
            report.human_decisions.append(decision)
            write_decision_artifacts(stage, output_dir, decision, history_index=len(report.human_decisions))
            if decision.decision == "approved":
                stage_run.status = "completed"
            elif decision.decision == "rejected":
                stage_run.status = "completed"
                stage_run.loopback_to = decision.target_stage
            else:
                stage_run.status = "waiting"
            stage_run.completed_at = utc_now()
            stage_run.duration_seconds = _duration(start)
            self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
            return stage_run

        blocker_content = ""
        if stage.get("skip_if_no_blocker"):
            if not stage.get("allow_auto_skip"):
                stage_run.status = "failed"
                stage_run.error_message = "skip_if_no_blocker requires allow_auto_skip: true"
                stage_run.completed_at = utc_now()
                stage_run.duration_seconds = _duration(start)
                self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
                return stage_run
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

        if reject:
            decision = "rejected"
        elif yes and stage.get("allow_auto_approve"):
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
        configured_json_artifacts = (stage or {}).get("json_artifacts") or []
        if configured_json_artifacts and len(agent_names) > 1:
            stage_run.status = "failed"
            stage_run.error_message = (
                f"json_artifacts only supports single-agent stages; stage {stage_id} has {len(agent_names)} agents"
            )
            stage_run.completed_at = utc_now()
            stage_run.duration_seconds = _duration(start)
            return stage_run
        try:
            self._json_artifact_paths(output_dir, configured_json_artifacts)
        except ConfigError as exc:
            stage_run.status = "failed"
            stage_run.error_message = str(exc)
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
                self._extract_json_artifacts(output_dir, stage_run, stage)
                validations = validate_required_artifacts(stage, output_dir)
                stage_run.artifact_validations.extend(validations)
                if has_artifact_validation_failure(validations):
                    failed = "; ".join(f"{item.artifact}: {item.message}" for item in validations if item.status == "failed")
                    stage_run.status = "failed"
                    stage_run.error_message = failed
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
        strategy = self.config.get("runner", {}).get("loopback_truncate_strategy", "smart")
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
                        content = truncate_with_fallback(content, remaining, strategy)
                    used_chars += len(content)
                    lines.extend(["", "```text", content, "```"])
        if not stage_run.agents:
            fallback = self._stage_output_text(stage_run)
            if fallback:
                if len(fallback) > max_chars:
                    fallback = truncate_with_fallback(fallback, max_chars, strategy)
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
        max_chars = self.config.get("runner", {}).get("max_input_chars_per_file")
        max_chars = int(max_chars) if max_chars else None
        context = build_stage_context(
            stage=stage,
            output_dir=output_dir,
            cwd=cwd,
            input_items=stage.get("input") or "requirement",
            extra_feedback=extra_feedback,
            schema_hint=stage_schema_hint(stage),
            max_chars=max_chars,
            base_branch=self.config.get("worktree", {}).get("base_branch"),
            max_diff_chars=max_chars,
        )
        parts = [
            base_prompt.rstrip(),
            "",
            context.rstrip(),
        ]
        return "\n".join(parts).rstrip() + "\n"

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

    def _json_artifact_paths(self, output_dir: Path, names: Sequence[Any]) -> List[Path]:
        output_root = output_dir.resolve()
        paths = []
        for raw_name in names:
            name = str(raw_name)
            artifact_path = Path(name)
            if not name.strip() or artifact_path.is_absolute() or ".." in artifact_path.parts:
                raise ConfigError(f"invalid json_artifacts path: {name}")
            resolved = (output_dir / artifact_path).resolve(strict=False)
            try:
                resolved.relative_to(output_root)
            except ValueError as exc:
                raise ConfigError(f"json_artifacts path outside output dir: {name}") from exc
            paths.append(output_dir / artifact_path)
        return paths

    def _extract_json_artifacts(self, output_dir: Path, stage_run: StageRun, stage: Optional[Dict[str, Any]] = None) -> None:
        """从 agent 输出的 Markdown 文件中提取 JSON 代码块，生成伴生 .json 文件。

        支持双输出模式：agent 在 Markdown 末尾以 ```json 代码块输出结构化数据，
        orchestrator 自动提取为独立 .json 文件，供下游 stage 的 input 引用。
        """
        configured_paths = self._json_artifact_paths(output_dir, (stage or {}).get("json_artifacts") or [])
        for agent in stage_run.agents:
            if not agent.output_file:
                continue
            output_path = Path(agent.output_file)
            if not output_path.exists():
                continue
            content = output_path.read_text(encoding="utf-8", errors="replace")
            json_blocks = re.findall(r'```json\s*\n(.*?)```', content, re.DOTALL)
            for i, block in enumerate(json_blocks):
                block = block.strip()
                if not block:
                    continue
                try:
                    parsed = json.loads(block)
                except json.JSONDecodeError:
                    continue
                stem = output_path.stem
                if i < len(configured_paths):
                    json_path = configured_paths[i]
                elif len(json_blocks) > 1:
                    json_path = output_dir / f"{stem}-{i + 1}.json"
                else:
                    json_path = output_dir / f"{stem}.json"
                json_path.parent.mkdir(parents=True, exist_ok=True)
                json_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

    def _deliver_pr(
        self,
        worktree_manager: WorktreeManager,
        worktree_path: Path,
        report: RunReport,
        output_dir: Path,
    ) -> Dict[str, Any]:
        from .pr_manager import PRManager

        ci_cd_config = self.config.get("ci_cd", {})
        logger = get_logger("orchestrator", run_id=report.run_id)

        if worktree_manager.has_changes(worktree_path):
            committed = worktree_manager.commit_all(worktree_path, f"ai-team: {report.run_id}")
            if not committed:
                return {"status": "failed", "error": "git commit failed"}

        try:
            worktree_manager.push_branch(worktree_path)
        except WorktreeError as e:
            logger.error("Push failed: %s", e)
            return {"status": "failed", "error": str(e)}

        pr_manager = PRManager(ci_cd_config)
        report_summary = {
            "run_id": report.run_id,
            "requirement": report.requirement,
            "changed_files": report.changed_files,
            "diff_stat": report.diff_stat,
            "duration_seconds": report.duration_seconds,
            "stages": [s.model_dump(mode="json") for s in report.stages],
        }
        pr_result = pr_manager.create_pr(str(worktree_path), report_summary)

        if pr_result.get("status") not in ("created", "existing"):
            return pr_result

        pr_number = pr_result.get("number")
        if pr_number and ci_cd_config.get("wait_for_checks"):
            timeout = int(ci_cd_config.get("check_timeout", 600))
            interval = int(ci_cd_config.get("check_interval", 30))
            ci_result = pr_manager.wait_ci(pr_number, timeout, interval)
            pr_result["ci_status"] = ci_result
            if ci_result.get("status") in {"failed", "unknown"}:
                pr_result["status"] = "blocked"
                logger.warning("CI checks did not pass for PR #%d", pr_number)
                self.bus.emit("ci_cd:checks_failed", report.run_id, pr_number=pr_number, checks=ci_result.get("failed", []))
            elif ci_result.get("status") == "timeout":
                pr_result["status"] = "blocked"
                logger.warning("CI checks timed out for PR #%d", pr_number)
                self.bus.emit("ci_cd:checks_timeout", report.run_id, pr_number=pr_number)
            else:
                self.bus.emit("ci_cd:checks_passed", report.run_id, pr_number=pr_number)
        else:
            self.bus.emit("ci_cd:pr_created", report.run_id, url=pr_result.get("url"), number=pr_number)

        return pr_result

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

    def _push_file_changes(self, run_id: str, worktree_path: Optional[Path]) -> None:
        """如果 worktree 存在，获取文件变更列表并通过事件总线推送。"""
        if not worktree_path or not worktree_path.exists():
            return
        try:
            from .worktree import WorktreeManager

            mgr = WorktreeManager(self.project_root, self.config.get("worktree"))
            changed = mgr.get_changed_files(worktree_path)
            stat = mgr.get_diff_stat(worktree_path)
            self.bus.emit("files:changed", run_id, changed_files=changed, diff_stat=stat)
        except Exception:
            logger = get_logger("orchestrator", run_id=run_id)
            logger.debug("推送文件变更失败", exc_info=True)

    def _validate_stage_entry(self, stage_id: str, artifact_dir: Path, stages: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
        def _check_schema(artifact_name: str) -> Optional[str]:
            path = artifact_dir / artifact_name
            if not path.exists():
                return None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return f"{artifact_name} malformed: {exc}"
            errors, _ = validate_artifact(payload, artifact_name)
            if errors:
                return f"{artifact_name} schema invalid: {'; '.join(errors[:5])}"
            return None

        if stage_id == "plan":
            path = artifact_dir / "requirement-final.json"
            if path.exists():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    errors = validate_requirement_for_planning(payload)
                    if errors:
                        return "; ".join(errors)
                except json.JSONDecodeError as exc:
                    return f"requirement-final.json malformed: {exc}"
        if stage_id in ("requirement_confirm", "develop", "review", "acceptance_confirm", "retrospect"):
            schema_map = {
                "requirement_confirm": "requirement-final.json",
                "develop": "task-plan.json",
                "review": "test-report.json",
                "acceptance_confirm": "review-report.json",
                "retrospect": "release-readiness.json",
            }
            artifact = schema_map.get(stage_id)
            if artifact:
                err = _check_schema(artifact)
                if err:
                    return err
        return None

    def _check_review_loopback(self, stage_id: str, artifact_dir: Path) -> Optional[Dict[str, Any]]:
        review_path = artifact_dir / "review-report.json"
        if not review_path.exists():
            return None
        try:
            payload = json.loads(review_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if validate_review_for_loopback(payload):
            blocking = payload.get("blocking_findings", [])
            findings_summary = "; ".join(
                f"[{f.get('severity', '?')}] {f.get('file_path', '?')}: {f.get('description', '?')}"
                for f in blocking[:5]
            )
            if not findings_summary:
                critical = [f for f in payload.get("findings", []) if f.get("severity") == "Critical"]
                findings_summary = "; ".join(
                    f"[Critical] {f.get('file_path', '?')}: {f.get('description', '?')}"
                    for f in critical[:5]
                )
            return {
                "verdict": payload.get("verdict"),
                "blocking_count": len(blocking),
                "summary": findings_summary or "Request Changes with no detail",
            }
        return None

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
