from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.production_guard import is_production_mode

from ..db import try_persistence

try:
    from fastapi import APIRouter, Depends, HTTPException
    from pydantic import BaseModel
except ImportError:
    APIRouter = None
    BaseModel = object

logger = logging.getLogger(__name__)

router = APIRouter() if APIRouter else None


def _get_auth():
    from ..auth import get_current_user
    return Depends(get_current_user)


class CreateProjectRequest(BaseModel):
    name: str
    root_path: str


def _get_allowed_roots() -> List[str]:
    raw = os.environ.get("AI_TEAM_ALLOWED_ROOTS", "").strip()
    if not raw:
        return []
    return [r.strip() for r in raw.split(",") if r.strip()]


def _is_within_path(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_root_path(root_path: str) -> str:
    resolved_path = Path(root_path).resolve()
    allowed = _get_allowed_roots()
    if not allowed:
        return str(resolved_path)
    for prefix in allowed:
        if _is_within_path(resolved_path, Path(prefix).resolve()):
            return str(resolved_path)
    raise HTTPException(
        status_code=403,
        detail=f"root_path '{resolved_path}' is not within allowed roots",
    )


def _get_project_repo():
    from persistence.repository import ProjectRepo
    return ProjectRepo()


async def _db_get_project(project_id: str) -> Optional[Dict[str, Any]]:
    db = try_persistence()
    if db is None:
        return None
    get_connection, release_connection, *_ = db
    conn = await get_connection()
    if conn is None:
        return None
    try:
        repo = _get_project_repo()
        return await repo.get_by_id(conn, project_id)
    except Exception:
        logger.debug("DB get_project failed for %s", project_id, exc_info=True)
        return None
    finally:
        await release_connection(conn)


if router:

    @router.get("/projects")
    async def list_projects(user: Dict[str, Any] = _get_auth()):
        db = try_persistence()
        if db is None:
            return []
        get_connection, release_connection, *_ = db
        conn = await get_connection()
        if conn is None:
            return []
        try:
            repo = _get_project_repo()
            return await repo.list_all(conn)
        except Exception:
            logger.debug("DB list_projects failed", exc_info=True)
            return []
        finally:
            await release_connection(conn)

    @router.post("/projects")
    async def create_project(body: CreateProjectRequest, user: Dict[str, Any] = _get_auth()):
        resolved = _validate_root_path(body.root_path)
        if not Path(resolved).is_dir():
            raise HTTPException(status_code=400, detail=f"path '{resolved}' does not exist or is not a directory")

        db = try_persistence()
        if db is None:
            raise HTTPException(status_code=503, detail="database not available")
        get_connection, release_connection, *_ = db
        conn = await get_connection()
        if conn is None:
            raise HTTPException(status_code=503, detail="database not available")
        try:
            repo = _get_project_repo()
            existing = await repo.get_by_root_path(conn, resolved)
            if existing:
                raise HTTPException(status_code=409, detail="project with this root_path already exists")
            project_id = await repo.create(conn, name=body.name, root_path=resolved)
            return await repo.get_by_id(conn, project_id)
        except HTTPException:
            raise
        except Exception:
            logger.exception("DB create_project failed")
            raise HTTPException(status_code=500, detail="failed to create project")
        finally:
            await release_connection(conn)

    @router.get("/projects/{project_id}")
    async def get_project(project_id: str, user: Dict[str, Any] = _get_auth()):
        project = await _db_get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return project

    @router.delete("/projects/{project_id}")
    async def delete_project(project_id: str, user: Dict[str, Any] = _get_auth()):
        db = try_persistence()
        if db is None:
            raise HTTPException(status_code=503, detail="database not available")
        get_connection, release_connection, *_ = db
        conn = await get_connection()
        if conn is None:
            raise HTTPException(status_code=503, detail="database not available")
        try:
            repo = _get_project_repo()
            if not await repo.delete(conn, project_id):
                raise HTTPException(status_code=404, detail="project not found")
            return {"status": "deleted"}
        except HTTPException:
            raise
        except Exception:
            logger.exception("DB delete_project failed")
            raise HTTPException(status_code=500, detail="failed to delete project")
        finally:
            await release_connection(conn)
