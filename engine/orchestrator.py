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
    provider_config,
    read_prompt,
    validate_production_config,
)
from .context_scanner import scan_codebase
from .cost_tracker import CostTracker
from .events import EventBus
from .models import AgentDefinition, AgentRun, RunReport, StageRun, model_to_dict, utc_now
from .quality_gates import (
    has_blocking_failure,
    max_retry_count_for_failures,
    render_gate_feedback,
    run_quality_gates,
)
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
    for item in _as_list(trigger):
        if not item:
            continue
        if isinstance(item, str) and item.startswith("regex:"):
            if re.search(item[len("regex:") :], content, re.MULTILINE):
                return True
        elif str(item) in content:
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
    ) -> RunReport:
        run_id = run_id or new_run_id()
        output_dir = self.output_base / run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "requirement.md").write_text(requirement, encoding="utf-8")
        start = time.monotonic()
        report = RunReport(
            run_id=run_id,
            status="running",
            requirement=requirement,
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source=self.loaded_config.source,
            config_path=self.loaded_config.path,
            started_at=utc_now(),
            warnings=self.config_warnings,
        )
        self._write_report(report, output_dir)
        self.bus.emit("run:started", run_id, pipeline_id=self.config.get("metadata", {}).get("name"), requirement=requirement)

        worktree_manager: Optional[WorktreeManager] = None
        worktree_path: Optional[Path] = None
        if self.config.get("worktree", {}).get("enabled"):
            worktree_manager = WorktreeManager(self.project_root, self.config.get("worktree"))
            worktree_path = worktree_manager.create(run_id)
            report.worktree_path = str(worktree_path)
            self._write_report(report, output_dir)

        skip_set = set(skip_stages or [])
        stages = [stage for stage in self.config.get("pipeline", []) if not only_stage or stage.get("id") == only_stage]
        stage_index_by_id = {stage.get("id"): index for index, stage in enumerate(stages)}
        loop_counts: Dict[str, int] = {}
        index = 0
        extra_feedback = ""

        try:
            while index < len(stages):
                stage = stages[index]
                stage_id = stage.get("id") or f"stage-{index}"
                if stage_id in skip_set:
                    report.stages.append(
                        StageRun(stage_id=stage_id, stage_name=stage.get("name", stage_id), status="skipped", type=stage.get("type", "agent"))
                    )
                    index += 1
                    self._write_report(report, output_dir)
                    continue

                stage_runs_to_append: List[StageRun]
                if stage.get("type") == "context_scan":
                    stage_run = self._run_context_stage(stage, report, output_dir, worktree_path)
                    stage_runs_to_append = [stage_run]
                elif stage.get("type") == "human_review":
                    stage_run = self._run_human_review_stage(stage, report, output_dir, yes=yes)
                    stage_runs_to_append = [stage_run]
                elif stage.get("type") == "code_apply":
                    stage_run = self._run_code_apply_stage(stage, report, output_dir, worktree_path)
                    stage_runs_to_append = [stage_run]
                else:
                    cwd = self._stage_cwd(stage_id, worktree_path)
                    stage_run = self._run_agent_stage(stage, report, output_dir, cwd, extra_feedback)
                    extra_feedback = ""
                    if stage_run.status == "completed" and stage_id == "develop" and self.config.get("quality_gates"):
                        stage_runs_to_append = self._run_develop_quality_loop(stage, stage_run, report, output_dir, cwd)
                        stage_run = stage_runs_to_append[-1]
                    else:
                        stage_runs_to_append = [stage_run]

                report.stages.extend(stage_runs_to_append)
                self._refresh_artifacts(report, output_dir)
                self._write_report(report, output_dir)

                if stage_run.status == "waiting":
                    report.status = "waiting"
                    break
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
                    self.bus.emit(
                        "loopback:triggered",
                        report.run_id,
                        from_stage=stage_id,
                        to_stage=target,
                        iteration=count + 1,
                    )
                    extra_feedback = self._render_loopback_feedback(stage_id, stage_run, count, target)
                    feedback_file = output_dir / f"loopback-feedback-{stage_id}-{count}.md"
                    feedback_file.write_text(extra_feedback, encoding="utf-8")
                    self._write_report(report, output_dir)
                    index = stage_index_by_id[target]
                    continue

                index += 1

            if report.status == "running":
                report.status = "completed"
                if worktree_path and worktree_manager:
                    if merge or self.config.get("worktree", {}).get("merge_on_success"):
                        report.merge_result = worktree_manager.merge(worktree_path)
                    else:
                        report.merge_result = {"status": "skipped", "reason": "merge_on_success disabled"}
                    if self.config.get("worktree", {}).get("auto_cleanup") and report.merge_result.get("status") in {"merged", "no_changes"}:
                        worktree_manager.cleanup(worktree_path)
            report.completed_at = utc_now()
            report.duration_seconds = _duration(start)
            self.bus.emit("run:completed", report.run_id, status=report.status, summary={"duration": report.duration_seconds})
            self._write_report(report, output_dir)
            return report
        except Exception as exc:
            report.status = "failed"
            report.error_message = str(exc)
            report.completed_at = utc_now()
            report.duration_seconds = _duration(start)
            self.bus.emit("run:completed", report.run_id, status="failed", summary={"error": str(exc)})
            self._write_report(report, output_dir)
            if worktree_path and worktree_manager and self.config.get("worktree", {}).get("auto_cleanup_on_failure", False):
                worktree_manager.cleanup(worktree_path)
            return report

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
        if yes:
            decision = "accepted"
        elif sys.stdin.isatty():
            response = input(f"Human review for run {report.run_id}. Accept? [y/N] ").strip().lower()
            decision = "accepted" if response in {"y", "yes"} else "rejected"
        else:
            decision = "waiting"
        (output_dir / "human-review.json").write_text(json.dumps({"decision": decision}, ensure_ascii=False, indent=2), encoding="utf-8")
        stage_run.status = "completed" if decision == "accepted" else ("failed" if decision == "rejected" else "waiting")
        stage_run.error_message = None if decision != "rejected" else "Human review rejected"
        stage_run.completed_at = utc_now()
        stage_run.duration_seconds = _duration(start)
        self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
        return stage_run

    def _run_agent_stage(self, stage: Dict[str, Any], report: RunReport, output_dir: Path, cwd: Path, extra_feedback: str = "") -> StageRun:
        stage_id = stage.get("id")
        stage_run = StageRun(
            stage_id=stage_id,
            stage_name=stage.get("name", stage_id),
            status="running",
            is_parallel=bool(stage.get("parallel")),
            started_at=utc_now(),
            output_dir=str(output_dir),
        )
        start = time.monotonic()
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
            provider = provider_config(self.config, agent.provider)
            output_name = (stage.get("output") or {}).get(agent.name) or f"{agent.name}-output.md"
            output_file = output_dir / output_name
            raw_log_file = output_dir / f"{stage_id}-{agent.name}.raw.log"
            prompt = self._render_prompt(stage, agent, output_dir, cwd, extra_feedback)
            return runner.run(report.run_id, stage_id, agent, provider, prompt, cwd, output_file, raw_log_file)

        try:
            if stage.get("parallel") and len(agent_names) > 1:
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
        self.bus.emit("stage:completed", report.run_id, stage_id=stage_id, status=stage_run.status, duration=stage_run.duration_seconds)
        return stage_run

    def _render_loopback_feedback(self, stage_id: str, stage_run: StageRun, retry_count: int, target: str) -> str:
        max_chars = int(self.config.get("runner", {}).get("max_loopback_feedback_chars") or 20000)
        lines = [f"## Loopback 反馈（第 {retry_count} 次重试）", ""]
        lines.append(f"Stage `{stage_id}` 触发了回退到 `{target}`。以下是该 stage 各 agent 的详细输出：")
        used_chars = 0
        for agent in stage_run.agents:
            lines.extend([
                "",
                f"### Agent: {agent.agent_name}",
                f"- Provider: {agent.provider}",
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
            retry_stage = self._run_agent_stage(stage, report, output_dir, cwd, feedback)
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

        result = subprocess.run(["git", "diff", "--stat"], cwd=cwd, capture_output=True, text=True, check=False)
        stat = result.stdout
        result = subprocess.run(["git", "diff"], cwd=cwd, capture_output=True, text=True, check=False)
        return "\n".join(part for part in [stat, result.stdout] if part.strip())

    def _stage_output_text(self, stage_run: StageRun) -> str:
        chunks = []
        for agent in stage_run.agents:
            if agent.output_file and Path(agent.output_file).exists():
                chunks.append(Path(agent.output_file).read_text(encoding="utf-8", errors="replace"))
        return "\n".join(chunks)

    def _refresh_artifacts(self, report: RunReport, output_dir: Path) -> None:
        artifacts = []
        for path in output_dir.iterdir():
            if path.is_file():
                artifacts.append(path.name)
        report.artifacts = sorted(artifacts)

    def _write_report(self, report: RunReport, output_dir: Path) -> None:
        self._refresh_artifacts(report, output_dir)
        report.write(output_dir / "report.json")
        try:
            from persistence import save_report_sync

            save_report_sync(report, self.config)
        except Exception:
            pass


def load_report(path: Path) -> RunReport:
    return RunReport(**json.loads(path.read_text(encoding="utf-8")))


def find_run_reports(project_root: Path) -> List[Path]:
    output_root = project_root / ".ai" / "team-output"
    if not output_root.exists():
        return []
    return sorted(output_root.glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
