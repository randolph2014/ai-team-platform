from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from engine.config import find_project_root
from engine.events import EventBus, InMemoryEventStore
from engine.models import RunReport, utc_now
from engine.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

event_store = InMemoryEventStore()


def project_for_run(run_id: str, workdir: Optional[str] = None) -> Path:
    if workdir:
        return find_project_root(workdir)
    return find_project_root(".")


def expected_output_dir(run_id: str, workdir: str) -> Path:
    project_root = find_project_root(workdir)
    return project_root / ".ai" / "team-output" / run_id


def start_run_background(
    requirement: str,
    workdir: str,
    run_id: str,
    yes: bool = False,
    config_path: Optional[str] = None,
    only_stage: Optional[str] = None,
    execution_mode: Optional[str] = None,
) -> Path:
    from engine.task_queue import enqueue_run

    project_root = find_project_root(workdir)
    output_dir = project_root / ".ai" / "team-output" / run_id

    # Try RQ first
    job_id = enqueue_run(requirement, workdir, run_id, yes, config_path, only_stage, execution_mode)
    if job_id is not None:
        logger.info("Run %s enqueued via RQ (job_id=%s)", run_id, job_id)
        return output_dir

    # Fallback to threading (dev mode)
    logger.info("RQ unavailable, starting run %s in thread", run_id)
    bus = EventBus()
    bus.subscribe(event_store.publish)
    orchestrator = Orchestrator(Path(project_root), config_path=config_path, event_bus=bus)

    def target() -> None:
        try:
            orchestrator.run(requirement=requirement, run_id=run_id, yes=yes, only_stage=only_stage, execution_mode=execution_mode)
        except Exception:
            logger.exception("Run %s failed", run_id)
            _persist_background_failure(
                run_id=run_id,
                requirement=requirement,
                project_root=Path(project_root),
                output_dir=output_dir,
                error_message="Pipeline execution failed (thread mode)",
                config_path=config_path,
            )

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return output_dir


def resume_run_background(
    run_id: str,
    workdir: str,
    yes: bool = False,
    config_path: Optional[str] = None,
    execution_mode: Optional[str] = None,
) -> Path:
    """恢复中断的 pipeline run"""
    from engine.task_queue import enqueue_run

    project_root = find_project_root(workdir)
    output_dir = project_root / ".ai" / "team-output" / run_id

    if not output_dir.exists():
        raise ValueError(f"Run {run_id} not found")

    # 读取 requirement.md
    requirement_file = output_dir / "requirement.md"
    if not requirement_file.exists():
        raise ValueError(f"Run {run_id} has no requirement.md")
    requirement = requirement_file.read_text(encoding="utf-8")

    # 尝试通过 RQ 恢复
    # 注意：RQ 模式下 resume 需要特殊处理，这里先用线程模式
    logger.info("Resuming run %s in thread", run_id)
    bus = EventBus()
    bus.subscribe(event_store.publish)
    orchestrator = Orchestrator(Path(project_root), config_path=config_path, event_bus=bus)

    def target() -> None:
        try:
            orchestrator.run(requirement=requirement, run_id=run_id, yes=yes, resume=True, execution_mode=execution_mode)
        except Exception:
            logger.exception("Resume run %s failed", run_id)
            _persist_background_failure(
                run_id=run_id,
                requirement=requirement,
                project_root=Path(project_root),
                output_dir=output_dir,
                error_message="Pipeline resume failed",
                config_path=config_path,
            )

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return output_dir


def _persist_background_failure(
    run_id: str,
    requirement: str,
    project_root: Path,
    output_dir: Path,
    error_message: str,
    config_path: Optional[str] = None,
) -> None:
    try:
        from persistence import save_report_sync

        report = RunReport(
            run_id=run_id,
            status="failed",
            requirement=requirement,
            project_root=str(project_root),
            output_dir=str(output_dir),
            config_source="project" if config_path else "default",
            config_path=config_path,
            error_message=error_message,
            started_at=utc_now(),
            completed_at=utc_now(),
        )
        save_report_sync(report, {})
    except Exception:
        logger.warning("无法更新数据库状态 for run %s", run_id)
