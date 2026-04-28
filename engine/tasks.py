"""RQ worker task definitions and worker entry point."""
from __future__ import annotations

import os
from pathlib import Path


def execute_pipeline(
    requirement: str,
    workdir: str,
    run_id: str,
    yes: bool = False,
    config_path: str | None = None,
    only_stage: str | None = None,
    execution_mode: str | None = None,
) -> str:
    """RQ task function: execute a pipeline run and return the output directory path."""
    from engine.config import find_project_root
    from engine.events import EventBus
    from engine.orchestrator import Orchestrator

    project_root = find_project_root(workdir)
    bus = EventBus()
    orchestrator = Orchestrator(
        Path(project_root),
        config_path=config_path,
        event_bus=bus,
    )
    report = orchestrator.run(
        requirement=requirement,
        run_id=run_id,
        yes=yes,
        only_stage=only_stage,
        execution_mode=execution_mode,
    )
    return str(report.output_dir)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from redis import Redis
    from rq import Connection, Worker

    redis_url = os.environ.get("AI_TEAM_REDIS_URL", "redis://localhost:6379/0")
    with Connection(Redis.from_url(redis_url)):
        w = Worker(["default"])
        w.work()
