from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from engine.harness import (
    HarnessConflictError,
    HarnessError,
    apply_harness_files,
    compute_harness_manifest,
    load_harness_bundle,
    read_harness_files,
    validate_harness_files,
)
from engine.harness_checks import run_harness_verification
from engine.production_guard import is_production_mode
from engine.task_board import TaskBoardError, TaskEvent, TaskStateError, build_snapshot, find_related_tasks, record_task_event

from ..db import try_persistence

try:
    from fastapi import APIRouter, Depends, HTTPException, Request
    from fastapi.responses import JSONResponse
    from pydantic import ValidationError
except ImportError:  # pragma: no cover
    APIRouter = None
    Request = object
    ValidationError = Exception


router = APIRouter() if APIRouter else None


def _get_auth():
    from ..auth import get_current_user

    return Depends(get_current_user)


def _get_project_repo():
    from persistence.repository import ProjectRepo

    return ProjectRepo()


def _validate_project_root(root_path: str) -> str:
    from .projects import _validate_root_path

    return _validate_root_path(root_path)


def _auth_enabled() -> bool:
    from ..auth import auth_enabled

    return auth_enabled()


def auth_enabled() -> bool:
    return _auth_enabled()


def _reject_workdir(request: Request, body: Optional[Dict[str, Any]] = None) -> None:
    if "workdir" in request.query_params or (body is not None and "workdir" in body):
        raise HTTPException(status_code=400, detail="Harness public APIs require project_id and do not accept workdir")
    if is_production_mode() and (body is not None and "workdir" in body):
        raise HTTPException(status_code=400, detail="workdir is not allowed in production Harness APIs")


async def _request_json(request: Request) -> Dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return body


def _claim_values(user: Dict[str, Any], *names: str) -> set[str]:
    values: set[str] = set()
    for name in names:
        raw = user.get(name)
        if isinstance(raw, str):
            values.add(raw)
        elif isinstance(raw, list):
            values.update(str(item) for item in raw)
    return values


def _validate_project_permission(project_id: str, user: Optional[Dict[str, Any]]) -> None:
    if not auth_enabled():
        return
    claims = user or {}
    if claims.get("is_admin") is True or claims.get("role") == "admin":
        return
    allowed = _claim_values(claims, "project_ids", "projects", "allowed_projects")
    if "*" in allowed or project_id in allowed:
        return
    raise HTTPException(status_code=403, detail="user is not authorized for this project")


async def _resolve_project_root(project_id: str, user: Optional[Dict[str, Any]]) -> Path:
    db = try_persistence()
    if db is None:
        raise HTTPException(status_code=503, detail="database not available")
    get_connection, release_connection, *_ = db
    conn = await get_connection()
    if conn is None:
        raise HTTPException(status_code=503, detail="database not available")
    try:
        project = await _get_project_repo().get_by_id(conn, project_id)
    finally:
        await release_connection(conn)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    _validate_project_permission(project_id, user)
    resolved = Path(_validate_project_root(project["root_path"]))
    if not resolved.is_dir():
        raise HTTPException(status_code=404, detail="project root not found")
    return resolved


def _harness_400(exc: HarnessError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


if router:

    @router.get("/projects/{project_id}/harness")
    async def get_harness(project_id: str, request: Request, user: Dict[str, Any] = _get_auth()):
        _reject_workdir(request)
        project_root = await _resolve_project_root(project_id, user)
        try:
            bundle = load_harness_bundle(project_root)
            return {
                "project_id": project_id,
                "manifest_hash": bundle.manifest["manifest_hash"],
                "files": read_harness_files(project_root),
                "summary": bundle.summary,
                "validation": bundle.validation,
            }
        except HarnessError as exc:
            raise _harness_400(exc) from exc

    @router.post("/projects/{project_id}/harness/validate")
    async def validate_harness(project_id: str, request: Request, user: Dict[str, Any] = _get_auth()):
        body = await _request_json(request)
        _reject_workdir(request, body)
        project_root = await _resolve_project_root(project_id, user)
        try:
            return validate_harness_files(project_root, body.get("files") or [])
        except HarnessError as exc:
            raise _harness_400(exc) from exc

    @router.post("/projects/{project_id}/harness/checks/run")
    async def run_harness_checks(project_id: str, request: Request, user: Dict[str, Any] = _get_auth()):
        body = await _request_json(request)
        _reject_workdir(request, body)
        disallowed = {"checks", "command", "commands", "cwd"}
        provided = sorted(disallowed.intersection(body))
        if provided:
            raise HTTPException(status_code=400, detail=f"Harness checks must come from repository files, not request body: {', '.join(provided)}")
        project_root = await _resolve_project_root(project_id, user)
        run_id = str(body.get("run_id") or f"harness-api-{project_id}")
        try:
            report = run_harness_verification(
                project_root,
                run_id=run_id,
                project_id=project_id,
                cwd=project_root,
                production=is_production_mode(),
            )
            return report
        except HarnessError as exc:
            raise _harness_400(exc) from exc

    @router.get("/projects/{project_id}/task-board")
    async def get_task_board(project_id: str, request: Request, q: Optional[str] = None, user: Dict[str, Any] = _get_auth()):
        _reject_workdir(request)
        project_root = await _resolve_project_root(project_id, user)
        try:
            snapshot = build_snapshot(project_root, write=False)
            related = find_related_tasks(project_root, q or "") if q else []
            return {
                "project_id": project_id,
                "summary": snapshot["summary"],
                "tasks": snapshot["tasks"],
                "related_tasks": related,
            }
        except TaskBoardError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/projects/{project_id}/task-board/events")
    async def post_task_board_event(project_id: str, request: Request, user: Dict[str, Any] = _get_auth()):
        body = await _request_json(request)
        _reject_workdir(request, body)
        project_root = await _resolve_project_root(project_id, user)
        try:
            event = TaskEvent.model_validate(body)
            if event.state == "accepted":
                raise TaskStateError("accepted task state is written only by final pipeline acceptance")
            task = record_task_event(project_root, event)
            return {
                "project_id": project_id,
                "task": task.model_dump(mode="json"),
            }
        except (ValidationError, TaskStateError, TaskBoardError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/projects/{project_id}/harness")
    async def update_harness(project_id: str, request: Request, user: Dict[str, Any] = _get_auth()):
        body = await _request_json(request)
        _reject_workdir(request, body)
        if "manifest_hash" not in body:
            raise HTTPException(status_code=400, detail="manifest_hash is required")
        project_root = await _resolve_project_root(project_id, user)
        try:
            result = apply_harness_files(project_root, body.get("files") or [], body["manifest_hash"])
            return {
                "project_id": project_id,
                "manifest_hash": result["manifest_hash"],
                "files": result["files"],
                "summary": result["summary"],
                "validation": {"valid": True, "errors": []},
            }
        except HarnessConflictError as exc:
            current = compute_harness_manifest(project_root)
            return JSONResponse(
                status_code=409,
                content={
                    "error": "manifest_conflict",
                    "current_manifest_hash": exc.current_manifest_hash,
                    "changed_files": exc.changed_files or current.get("changed_files", []),
                },
            )
        except HarnessError as exc:
            raise _harness_400(exc) from exc
