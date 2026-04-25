from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, Optional

from engine.config import find_project_root
from engine.events import EventBus, InMemoryEventStore
from engine.orchestrator import Orchestrator


event_store = InMemoryEventStore()
active_runs: Dict[str, threading.Thread] = {}
run_projects: Dict[str, Path] = {}


def project_for_run(run_id: str, workdir: Optional[str] = None) -> Path:
    if workdir:
        return find_project_root(workdir)
    if run_id in run_projects:
        return run_projects[run_id]
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
    project_root = find_project_root(workdir)
    run_projects[run_id] = project_root
    bus = EventBus()
    bus.subscribe(event_store.publish)
    orchestrator = Orchestrator(Path(project_root), config_path=config_path, event_bus=bus)

    def target() -> None:
        try:
            orchestrator.run(requirement=requirement, run_id=run_id, yes=yes, only_stage=only_stage)
        finally:
            active_runs.pop(run_id, None)

    thread = threading.Thread(target=target, daemon=True)
    active_runs[run_id] = thread
    thread.start()
    return project_root / ".ai" / "team-output" / run_id
