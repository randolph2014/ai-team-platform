from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from engine.orchestrator import find_run_reports

from ..db import run_db_id, try_persistence
from ..runtime import project_for_run

try:
    from fastapi import APIRouter, Depends, HTTPException, Query
    from fastapi.responses import FileResponse
except ImportError:  # pragma: no cover
    APIRouter = None

logger = logging.getLogger(__name__)

router = APIRouter() if APIRouter else None


def _get_auth():
    """Lazy import of auth dependency."""
    from ..auth import get_current_user
    return Depends(get_current_user)


async def _db_run_exists(run_id: str) -> Optional[bool]:
    """通过 DB 检查 run 是否存在。DB 不可用返回 None。"""
    db = try_persistence()
    if db is None:
        return None
    get_connection, release_connection, PipelineRunRepo, _, _ = db

    conn = await get_connection()
    if conn is None:
        return None
    try:
        repo = PipelineRunRepo()
        return await repo.run_exists(conn, run_db_id(run_id))
    except Exception:
        logger.debug("DB run_exists check failed for %s", run_id, exc_info=True)
        return None
    finally:
        await release_connection(conn)


def _run_dir(workdir: Optional[str], run_id: str) -> Path:
    project_root = project_for_run(run_id, workdir)
    for path in find_run_reports(Path(project_root)):
        if path.parent.name == run_id:
            return path.parent
    raise FileNotFoundError(run_id)


if router:

    @router.get("/runs/{run_id}/artifacts")
    async def list_artifacts(run_id: str, workdir: Optional[str] = Query(default=None), user: Dict[str, Any] = _get_auth()):
        db_exists = await _db_run_exists(run_id)
        if db_exists is False:
            raise HTTPException(status_code=404, detail="run not found")

        try:
            run_dir = _run_dir(workdir, run_id)
        except FileNotFoundError:
            if db_exists is True:
                return []
            raise HTTPException(status_code=404, detail="run not found")
        return [{"name": path.name, "size": path.stat().st_size} for path in sorted(run_dir.iterdir()) if path.is_file()]

    @router.get("/runs/{run_id}/artifacts/{filename}")
    async def get_artifact(run_id: str, filename: str, workdir: Optional[str] = Query(default=None), user: Dict[str, Any] = _get_auth()):
        db_exists = await _db_run_exists(run_id)
        if db_exists is False:
            raise HTTPException(status_code=404, detail="run not found")

        try:
            run_dir = _run_dir(workdir, run_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="run not found")
        path = (run_dir / filename).resolve()
        if not str(path).startswith(str(run_dir.resolve())) or not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(path)
