from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from engine.config import find_project_root
from engine.events import EventBus, InMemoryEventStore
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
) -> Path:
    from engine.task_queue import enqueue_run

    project_root = find_project_root(workdir)
    output_dir = project_root / ".ai" / "team-output" / run_id

    # Try RQ first
    job_id = enqueue_run(requirement, workdir, run_id, yes, config_path, only_stage)
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
            orchestrator.run(requirement=requirement, run_id=run_id, yes=yes, only_stage=only_stage)
        except Exception:
            logger.exception("Run %s failed", run_id)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return output_dir
