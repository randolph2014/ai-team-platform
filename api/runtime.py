from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from engine.config import find_project_root
from engine.models import HumanDecision

logger = logging.getLogger(__name__)


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

    job_id = enqueue_run(requirement, workdir, run_id, yes, config_path, only_stage, execution_mode)
    if job_id is None:
        raise RuntimeError("Task queue unavailable (Redis not reachable)")
    logger.info("Run %s enqueued via RQ (job_id=%s)", run_id, job_id)
    return output_dir


def resume_run_background(
    run_id: str,
    workdir: str,
    yes: bool = False,
    reject: bool = False,
    config_path: Optional[str] = None,
    execution_mode: Optional[str] = None,
    human_decision: Optional[HumanDecision] = None,
) -> Path:
    from engine.task_queue import enqueue_resume

    project_root = find_project_root(workdir)
    output_dir = project_root / ".ai" / "team-output" / run_id

    if not output_dir.exists():
        raise ValueError(f"Run {run_id} not found")

    requirement_file = output_dir / "requirement.md"
    if not requirement_file.exists():
        raise ValueError(f"requirement.md not found for run {run_id}")

    decision_dict = None
    if human_decision is not None:
        if hasattr(human_decision, "model_dump"):
            decision_dict = human_decision.model_dump(mode="json")
        else:
            decision_dict = {
                "stage_id": human_decision.stage_id,
                "decision": human_decision.decision,
                "reason": human_decision.reason,
                "required_changes": human_decision.required_changes,
                "target_stage": human_decision.target_stage,
            }

    job_id = enqueue_resume(
        run_id=run_id,
        workdir=workdir,
        yes=yes,
        reject=reject,
        config_path=config_path,
        execution_mode=execution_mode,
        human_decision=decision_dict,
    )
    if job_id is None:
        raise RuntimeError("Task queue unavailable (Redis not reachable)")
    logger.info("Resume run %s enqueued via RQ (job_id=%s)", run_id, job_id)
    return output_dir
