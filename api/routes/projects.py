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


class ImportProjectRequest(BaseModel):
    root_path: str
    name: Optional[str] = None


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


def _unique_existing_dirs(paths: List[Path]) -> List[Path]:
    seen = set()
    results = []
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            continue
        key = str(resolved)
        if key in seen or not resolved.is_dir():
            continue
        seen.add(key)
        results.append(resolved)
    return results


def _browse_roots() -> List[Path]:
    allowed = _get_allowed_roots()
    if allowed:
        return _unique_existing_dirs([Path(root) for root in allowed])
    return _unique_existing_dirs([Path.home(), Path.cwd()])


def _is_browse_root(path: Path) -> bool:
    roots = _browse_roots()
    if not roots:
        return path.parent == path
    return any(path == root for root in roots)


def _browse_parent(path: Path) -> Optional[str]:
    if _is_browse_root(path):
        return None
    parent = path.parent
    try:
        if _get_allowed_roots():
            _validate_root_path(str(parent))
    except HTTPException:
        return None
    return str(parent)


def _directory_entry(path: Path) -> Dict[str, str]:
    return {"name": path.name or str(path), "path": str(path)}


def _list_directory_entries(path: Path) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    try:
        children = list(path.iterdir())
    except PermissionError:
        return entries
    for child in sorted(children, key=lambda item: item.name.lower()):
        if child.name.startswith("."):
            continue
        try:
            resolved = child.resolve()
        except OSError:
            continue
        if resolved.is_dir():
            entries.append(_directory_entry(resolved))
    return entries


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

    @router.get("/projects/browse")
    async def browse_project_directories(path: Optional[str] = None, user: Dict[str, Any] = _get_auth()):
        if not path:
            return {
                "path": None,
                "parent": None,
                "entries": [_directory_entry(root) for root in _browse_roots()],
            }
        resolved = Path(_validate_root_path(path))
        if not resolved.is_dir():
            raise HTTPException(status_code=400, detail=f"path '{resolved}' does not exist or is not a directory")
        return {
            "path": str(resolved),
            "parent": _browse_parent(resolved),
            "entries": _list_directory_entries(resolved),
        }

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

    @router.post("/projects/import")
    async def import_project(body: ImportProjectRequest, user: Dict[str, Any] = _get_auth()):
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
                return existing
            name = (body.name or "").strip() or Path(resolved).name or resolved
            project_id = await repo.create(conn, name=name, root_path=resolved)
            return await repo.get_by_id(conn, project_id)
        except HTTPException:
            raise
        except Exception:
            logger.exception("DB import_project failed")
            raise HTTPException(status_code=500, detail="failed to import project")
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
