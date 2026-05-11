"""RQ worker task definitions and worker entry point."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional


def _persist_run_failure(
    run_id: str,
    requirement: str,
    workdir: str,
    config_path: Optional[str],
    error_message: str,
) -> None:
    try:
        from engine.config import find_project_root
        from engine.models import RunReport, utc_now
        from persistence import save_report_sync

        project_root = Path(find_project_root(workdir))
        report = RunReport(
            run_id=run_id,
            status="failed",
            requirement=requirement,
            project_root=str(project_root),
            output_dir=str(project_root / ".ai" / "team-output" / run_id),
            config_source="project" if config_path else "default",
            config_path=config_path,
            error_message=error_message,
            started_at=utc_now(),
            completed_at=utc_now(),
        )
        save_report_sync(report, {})
    except Exception:
        pass


def execute_pipeline(
    requirement: str,
    workdir: str,
    run_id: str,
    yes: bool = False,
    config_path: str | None = None,
    only_stage: str | None = None,
    execution_mode: str | None = None,
) -> str:
    from engine.config import find_project_root
    from engine.events import EventBus, RedisEventBus
    from engine.orchestrator import Orchestrator

    project_root = find_project_root(workdir)
    bus = EventBus()
    redis_bus = RedisEventBus(bus)
    orchestrator = Orchestrator(
        Path(project_root),
        config_path=config_path,
        event_bus=bus,
    )
    try:
        report = orchestrator.run(
            requirement=requirement,
            run_id=run_id,
            yes=yes,
            only_stage=only_stage,
            execution_mode=execution_mode,
        )
        return str(report.output_dir)
    except Exception as exc:
        _persist_run_failure(run_id, requirement, workdir, config_path, str(exc))
        raise
    finally:
        redis_bus.close()


def execute_resume(
    run_id: str,
    workdir: str,
    yes: bool = False,
    reject: bool = False,
    config_path: Optional[str] = None,
    execution_mode: Optional[str] = None,
    human_decision: Optional[Dict[str, Any]] = None,
) -> str:
    from engine.config import find_project_root
    from engine.events import EventBus, RedisEventBus
    from engine.models import HumanDecision
    from engine.orchestrator import Orchestrator

    project_root = find_project_root(workdir)
    output_dir = Path(project_root) / ".ai" / "team-output" / run_id
    requirement_file = output_dir / "requirement.md"
    if not requirement_file.exists():
        raise FileNotFoundError(f"requirement.md not found for run {run_id}")
    requirement = requirement_file.read_text(encoding="utf-8")

    decision = None
    if human_decision:
        if hasattr(HumanDecision, "model_validate"):
            decision = HumanDecision.model_validate(human_decision)
        else:
            decision = HumanDecision(**human_decision)

    bus = EventBus()
    redis_bus = RedisEventBus(bus)
    orchestrator = Orchestrator(
        Path(project_root),
        config_path=config_path,
        event_bus=bus,
    )
    try:
        report = orchestrator.run(
            requirement=requirement,
            run_id=run_id,
            yes=yes,
            reject=reject,
            resume=True,
            execution_mode=execution_mode,
            human_decision=decision,
        )
        return str(report.output_dir)
    except Exception as exc:
        _persist_run_failure(run_id, requirement, workdir, config_path, str(exc))
        raise
    finally:
        redis_bus.close()


def build_worker(redis_url: str | None = None):
    from redis import Redis
    from rq import Queue, Worker

    resolved_url = redis_url or os.environ.get("AI_TEAM_REDIS_URL", "redis://localhost:6379/0")
    conn = Redis.from_url(resolved_url)
    queue = Queue("default", connection=conn)
    return Worker([queue], connection=conn)


def run_worker(redis_url: str | None = None) -> None:
    worker = build_worker(redis_url)
    worker.work()


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    run_worker()
