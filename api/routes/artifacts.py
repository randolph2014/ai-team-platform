from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

from engine.orchestrator import find_run_reports

from ..db import run_db_id, try_persistence
from ..runtime import project_for_run

try:
    from fastapi import APIRouter, Depends, HTTPException, Query
    from fastapi.responses import FileResponse, Response
except ImportError:  # pragma: no cover
    APIRouter = None

_TEXT_MIME_MAP: Dict[str, str] = {
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".mdx": "text/markdown; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".yaml": "text/yaml; charset=utf-8",
    ".yml": "text/yaml; charset=utf-8",
    ".toml": "text/plain; charset=utf-8",
    ".xml": "text/xml; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".py": "text/plain; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".ts": "text/plain; charset=utf-8",
    ".tsx": "text/plain; charset=utf-8",
    ".jsx": "text/plain; charset=utf-8",
    ".sh": "text/plain; charset=utf-8",
    ".bash": "text/plain; charset=utf-8",
    ".sql": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".out": "text/plain; charset=utf-8",
    ".err": "text/plain; charset=utf-8",
    ".ini": "text/plain; charset=utf-8",
    ".cfg": "text/plain; charset=utf-8",
    ".conf": "text/plain; charset=utf-8",
    ".go": "text/plain; charset=utf-8",
    ".rs": "text/plain; charset=utf-8",
    ".java": "text/plain; charset=utf-8",
    ".rb": "text/plain; charset=utf-8",
    ".php": "text/plain; charset=utf-8",
    ".c": "text/plain; charset=utf-8",
    ".cpp": "text/plain; charset=utf-8",
    ".h": "text/plain; charset=utf-8",
    ".hpp": "text/plain; charset=utf-8",
}

logger = logging.getLogger(__name__)

router = APIRouter() if APIRouter else None


def _get_auth():
    from ..auth import get_current_user
    return Depends(get_current_user)


async def _db_run_exists(run_id: str) -> Optional[bool]:
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


def _get_project_repo():
    from persistence.repository import ProjectRepo
    return ProjectRepo()


async def _validate_project_ownership(run_id: str, project_id: Optional[str]) -> None:
    if not project_id:
        return
    db = try_persistence()
    if db is None:
        return
    get_connection, release_connection, PipelineRunRepo, _, _ = db
    conn = await get_connection()
    if conn is None:
        return
    try:
        project = await _get_project_repo().get_by_id(conn, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        from .projects import _validate_root_path
        _validate_root_path(project["root_path"])
        repo = PipelineRunRepo()
        run = await repo.get_by_id(conn, run_db_id(run_id))
        if run is None:
            return
        if run.get("project_root") != project["root_path"]:
            raise HTTPException(status_code=403, detail="run does not belong to the specified project")
    except HTTPException:
        raise
    except Exception:
        logger.debug("DB project ownership check failed for run %s", run_id, exc_info=True)
    finally:
        await release_connection(conn)


def _run_dir(workdir: Optional[str], run_id: str) -> Path:
    project_root = project_for_run(run_id, workdir)
    for path in find_run_reports(Path(project_root)):
        if path.parent.name == run_id:
            return path.parent
    raise FileNotFoundError(run_id)


def _is_within_path(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_artifact_path(run_dir: Path, filename: str) -> Path:
    run_root = run_dir.resolve()
    path = (run_dir / filename).resolve()
    if not _is_within_path(path, run_root) or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return path


if router:

    @router.get("/runs/{run_id}/artifacts")
    async def list_artifacts(run_id: str, workdir: Optional[str] = Query(default=None), project_id: Optional[str] = Query(default=None), user: Dict[str, Any] = _get_auth()):
        await _validate_project_ownership(run_id, project_id)

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
    async def get_artifact(run_id: str, filename: str, workdir: Optional[str] = Query(default=None), project_id: Optional[str] = Query(default=None), user: Dict[str, Any] = _get_auth()):
        await _validate_project_ownership(run_id, project_id)

        db_exists = await _db_run_exists(run_id)
        if db_exists is False:
            raise HTTPException(status_code=404, detail="run not found")

        try:
            run_dir = _run_dir(workdir, run_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="run not found")
        path = _resolve_artifact_path(run_dir, filename)

        suffix = path.suffix.lower()
        media_type = _TEXT_MIME_MAP.get(suffix)

        if media_type:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                content = path.read_bytes().decode("utf-8", errors="replace")
            return Response(content, media_type=media_type)
        else:
            guessed_type = mimetypes.guess_type(str(path))[0]
            return FileResponse(path, media_type=guessed_type)
