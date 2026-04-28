"""RQ task queue wrapper with graceful Redis fallback."""
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


def get_queue():
    """Return an rq.Queue instance. Returns None if Redis is unavailable."""
    global _queue
    if _queue is not None:
        return _queue
    try:
        from redis import Redis
        from rq import Queue

        conn = Redis.from_url(_redis_url())
        conn.ping()
        _queue = Queue(connection=conn)
        return _queue
    except Exception as exc:
        logger.debug("Redis not available (%s), task queue disabled", exc)
        return None


def reset_queue() -> None:
    """Reset cached queue instance (for testing)."""
    global _queue
    _queue = None


def _handle_pipeline_failure(job, exc_type, exc_value, traceback):
    """RQ failure callback: 更新 run.status 为 failed"""
    try:
        run_id = job.kwargs.get("run_id") or (job.args[2] if len(job.args) > 2 else None)
        if run_id:
            logger.error("Pipeline run %s failed: %s", run_id, exc_value)
            # 尝试更新数据库状态
            try:
                from pathlib import Path

                from engine.config import find_project_root
                from persistence import save_report_sync
                from engine.models import RunReport, utc_now
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
                logger.warning("无法更新数据库状态 for run %s", run_id)
    except Exception:
        logger.exception("failure callback 异常")


def enqueue_run(
    requirement: str,
    workdir: str,
    run_id: str,
    yes: bool = False,
    config_path: Optional[str] = None,
    only_stage: Optional[str] = None,
    execution_mode: Optional[str] = None,
) -> Optional[str]:
    """Enqueue a pipeline run via RQ. Returns job_id or None if Redis unavailable."""
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
        return job.id
    except Exception as exc:
        logger.warning("RQ enqueue failed (%s), resetting queue", exc)
        reset_queue()
        return None


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Query RQ job status. Returns dict with status info or None if unavailable."""
    try:
        from redis import Redis
        from rq.job import Job

        conn = Redis.from_url(_redis_url())
        job = Job.fetch(job_id, connection=conn)
        return {
            "job_id": job.id,
            "status": job.get_status(),
            "result": job.result,
            "exc_info": job.exc_info,
        }
    except Exception:
        return None
