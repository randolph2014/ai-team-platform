"""RQ task queue wrapper with production-mode Redis enforcement."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_REDIS_URL_ENV = "AI_TEAM_REDIS_URL"
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"

_queue = None


def _redis_url() -> str:
    return os.environ.get(_REDIS_URL_ENV, _DEFAULT_REDIS_URL)


def _is_production() -> bool:
    return os.environ.get("AI_TEAM_PRODUCTION", "").lower() in {"1", "true", "yes"}


def get_redis_conn():
    from redis import Redis
    return Redis.from_url(_redis_url())


def get_queue():
    global _queue
    if _queue is not None:
        return _queue
    try:
        from rq import Queue

        conn = get_redis_conn()
        conn.ping()
        _queue = Queue(connection=conn)
        return _queue
    except Exception as exc:
        if _is_production():
            raise RuntimeError(f"Redis unavailable in production: {exc}") from exc
        logger.debug("Redis not available (%s), task queue disabled", exc)
        return None


def reset_queue() -> None:
    global _queue
    _queue = None


def _store_run_job(run_id: str, job_id: str) -> None:
    try:
        conn = get_redis_conn()
        conn.setex(f"ai-team:run_job:{run_id}", 86400, job_id)
    except Exception:
        pass


def _handle_pipeline_failure(job, exc_type, exc_value, traceback):
    try:
        run_id = job.kwargs.get("run_id") or (job.args[2] if len(job.args) > 2 else None)
        if run_id:
            logger.error("Pipeline run %s failed: %s", run_id, exc_value)
            try:
                from pathlib import Path

                from engine.config import find_project_root
                from engine.models import RunReport, utc_now
                from persistence import save_report_sync

                requirement = job.kwargs.get("requirement") or (job.args[0] if job.args else "")
                workdir = job.kwargs.get("workdir") or (job.args[1] if len(job.args) > 1 else ".")
                project_root = Path(find_project_root(workdir))
                config_path = job.kwargs.get("config_path")
                report = RunReport(
                    run_id=run_id,
                    status="failed",
                    requirement=requirement,
                    project_root=str(project_root),
                    output_dir=str(project_root / ".ai" / "team-output" / run_id),
                    config_source="project" if config_path else "default",
                    config_path=config_path,
                    error_message=str(exc_value),
                    started_at=utc_now(),
                    completed_at=utc_now(),
                )
                save_report_sync(report, {})
            except Exception:
                logger.warning("Failed to persist failure status for run %s", run_id)
    except Exception:
        logger.exception("failure callback error")


def _handle_resume_failure(job, exc_type, exc_value, traceback):
    try:
        run_id = job.kwargs.get("run_id") or (job.args[0] if job.args else None)
        if run_id:
            logger.error("Resume run %s failed: %s", run_id, exc_value)
            try:
                from pathlib import Path

                from engine.config import find_project_root
                from engine.models import RunReport, utc_now
                from persistence import save_report_sync

                workdir = job.kwargs.get("workdir", ".")
                config_path = job.kwargs.get("config_path")
                project_root = Path(find_project_root(workdir))
                output_dir = project_root / ".ai" / "team-output" / run_id
                requirement = ""
                req_file = output_dir / "requirement.md"
                if req_file.exists():
                    requirement = req_file.read_text(encoding="utf-8")
                report = RunReport(
                    run_id=run_id,
                    status="failed",
                    requirement=requirement,
                    project_root=str(project_root),
                    output_dir=str(output_dir),
                    config_source="project" if config_path else "default",
                    config_path=config_path,
                    error_message=str(exc_value),
                    started_at=utc_now(),
                    completed_at=utc_now(),
                )
                save_report_sync(report, {})
            except Exception:
                logger.warning("Failed to persist failure status for resume run %s", run_id)
    except Exception:
        logger.exception("resume failure callback error")


def enqueue_run(
    requirement: str,
    workdir: str,
    run_id: str,
    yes: bool = False,
    config_path: Optional[str] = None,
    only_stage: Optional[str] = None,
    execution_mode: Optional[str] = None,
) -> Optional[str]:
    q = get_queue()
    if q is None:
        return None
    from engine.tasks import execute_pipeline

    try:
        job = q.enqueue(
            execute_pipeline,
            requirement=requirement,
            workdir=workdir,
            run_id=run_id,
            yes=yes,
            config_path=config_path,
            only_stage=only_stage,
            execution_mode=execution_mode,
            job_timeout="24h",
            result_ttl=86400,
            on_failure=_handle_pipeline_failure,
        )
        _store_run_job(run_id, job.id)
        return job.id
    except Exception as exc:
        logger.warning("RQ enqueue failed (%s), resetting queue", exc)
        reset_queue()
        if _is_production():
            raise RuntimeError(f"RQ enqueue failed in production: {exc}") from exc
        return None


def enqueue_resume(
    run_id: str,
    workdir: str,
    yes: bool = False,
    reject: bool = False,
    config_path: Optional[str] = None,
    execution_mode: Optional[str] = None,
    human_decision: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    q = get_queue()
    if q is None:
        return None
    from engine.tasks import execute_resume

    try:
        job = q.enqueue(
            execute_resume,
            run_id=run_id,
            workdir=workdir,
            yes=yes,
            reject=reject,
            config_path=config_path,
            execution_mode=execution_mode,
            human_decision=human_decision,
            job_timeout="24h",
            result_ttl=86400,
            on_failure=_handle_resume_failure,
        )
        _store_run_job(run_id, job.id)
        return job.id
    except Exception as exc:
        logger.warning("RQ resume enqueue failed (%s), resetting queue", exc)
        reset_queue()
        if _is_production():
            raise RuntimeError(f"RQ enqueue failed in production: {exc}") from exc
        return None


def cancel_rq_job(job_id: str) -> Dict[str, Any]:
    from rq.job import Job, JobStatus

    conn = get_redis_conn()
    try:
        job = Job.fetch(job_id, connection=conn)
    except Exception:
        return {"cancelled": False, "reason": "job not found"}

    status = job.get_status()
    cancellable = {JobStatus.QUEUED, JobStatus.DEFERRED, JobStatus.SCHEDULED}
    if status in cancellable:
        try:
            job.cancel()
            return {"cancelled": True, "job_id": job_id, "previous_status": status}
        except Exception as exc:
            return {"cancelled": False, "job_id": job_id, "reason": str(exc)}
    if status == JobStatus.STARTED or status == "started":
        from rq.command import send_kill_horse_command
        try:
            send_kill_horse_command(conn, job_id)
            return {"cancelled": True, "job_id": job_id, "previous_status": status}
        except Exception:
            try:
                job.cancel()
                return {"cancelled": True, "job_id": job_id, "previous_status": status}
            except Exception as exc:
                return {"cancelled": False, "job_id": job_id, "reason": str(exc)}
    return {"cancelled": False, "job_id": job_id, "status": status, "reason": f"job is {status}"}


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    try:
        from rq.job import Job

        conn = get_redis_conn()
        job = Job.fetch(job_id, connection=conn)
        return {
            "job_id": job.id,
            "status": job.get_status(),
            "result": job.result,
            "exc_info": job.exc_info,
        }
    except Exception:
        return None
