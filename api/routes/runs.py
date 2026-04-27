from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.config import find_project_root
from engine.orchestrator import find_run_reports, load_report

from ..db import run_db_id, try_persistence
from ..runtime import expected_output_dir, project_for_run, start_run_background

try:
    from fastapi import APIRouter, Depends, HTTPException, Query
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    APIRouter = None
    BaseModel = object

logger = logging.getLogger(__name__)

router = APIRouter() if APIRouter else None


def _get_auth():
    """Lazy import of auth dependency to keep module safe when auth is absent."""
    from ..auth import get_current_user
    return Depends(get_current_user)


class CreateRunRequest(BaseModel):
    requirement: str
    workdir: str
    run_id: Optional[str] = None
    yes: bool = False
    config_path: Optional[str] = None
    only_stage: Optional[str] = None


async def _db_list_runs(workdir: str, page: int, size: int) -> Optional[List[Dict[str, Any]]]:
    """从 DB 查询 run 列表，DB 不可用时返回 None。"""
    db = try_persistence()
    if db is None:
        return None
    get_connection, release_connection, PipelineRunRepo, run_row_to_summary, _ = db

    conn = await get_connection()
    if conn is None:
        return None
    try:
        project_root = str(find_project_root(workdir))
        repo = PipelineRunRepo()
        rows = await repo.list_paginated(conn, page=page, size=size)
        # 按 project_root 过滤（与文件系统行为一致）
        results = []
        for r in rows:
            if r.get("project_root") == project_root:
                results.append(run_row_to_summary(r))
        return results
    except Exception:
        logger.debug("DB list_runs failed, falling back to filesystem", exc_info=True)
        return None
    finally:
        await release_connection(conn)


async def _db_get_run(run_id: str) -> Optional[Dict[str, Any]]:
    """从 DB 查询单个 run 详情，DB 不可用或不存在时返回 None。"""
    db = try_persistence()
    if db is None:
        return None
    get_connection, release_connection, PipelineRunRepo, _, run_detail_to_response = db

    conn = await get_connection()
    if conn is None:
        return None
    try:
        db_id = run_db_id(run_id)
        repo = PipelineRunRepo()
        detail = await repo.get_run_with_details(conn, db_id)
        if detail is None:
            return None
        result = run_detail_to_response(detail)
        result["run_id"] = run_id
        return result
    except Exception:
        logger.debug("DB get_run failed, falling back to filesystem", exc_info=True)
        return None
    finally:
        await release_connection(conn)


async def _db_create_pending(run_id: str, workdir: str, requirement: str) -> None:
    """在 DB 中创建 pending 状态的 run 记录。失败静默跳过。"""
    db = try_persistence()
    if db is None:
        return
    get_connection, release_connection, PipelineRunRepo, _, _ = db

    conn = await get_connection()
    if conn is None:
        return
    try:
        db_id = run_db_id(run_id)
        project_root = find_project_root(workdir)
        repo = PipelineRunRepo()
        await repo.create_pending(
            conn,
            id=db_id,
            pipeline_id=None,
            project_root=str(project_root),
            main_branch="main",
            requirement=requirement,
            trigger_source="api",
            app_run_id=run_id,
        )
    except Exception:
        logger.debug("DB create_pending failed for run %s", run_id, exc_info=True)
    finally:
        await release_connection(conn)


if router:

    @router.post("/runs")
    async def create_run(body: CreateRunRequest, user: Dict[str, Any] = _get_auth()):
        run_id = body.run_id or f"api-{uuid.uuid4().hex[:12]}"
        if expected_output_dir(run_id, body.workdir).exists():
            raise HTTPException(status_code=409, detail="run id already exists")

        await _db_create_pending(run_id, body.workdir, body.requirement)

        output_dir = start_run_background(
            body.requirement,
            body.workdir,
            run_id=run_id,
            yes=body.yes,
            config_path=body.config_path,
            only_stage=body.only_stage,
        )
        return {
            "run_id": run_id,
            "status": "running",
            "project_root": str(project_for_run(run_id, body.workdir)),
            "output_dir": str(output_dir),
        }

    @router.get("/runs")
    async def list_runs(
        workdir: str = Query(default="."),
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        user: Dict[str, Any] = _get_auth(),
    ):
        db_results = await _db_list_runs(workdir, page, size)
        if db_results is not None:
            return db_results

        # Fallback: 文件系统扫描
        project_root = find_project_root(workdir)
        reports = []
        for path in find_run_reports(Path(project_root)):
            report = load_report(path)
            reports.append(
                {
                    "run_id": report.run_id,
                    "status": report.status,
                    "pipeline": report.config_path,
                    "output_dir": report.output_dir,
                    "started_at": report.started_at,
                    "completed_at": report.completed_at,
                }
            )
        return reports

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str, workdir: Optional[str] = Query(default=None), user: Dict[str, Any] = _get_auth()):
        db_result = await _db_get_run(run_id)
        if db_result is not None:
            return db_result

        # Fallback: 文件系统
        project_root = project_for_run(run_id, workdir)
        for path in find_run_reports(Path(project_root)):
            if path.parent.name == run_id:
                return load_report(path).model_dump(mode="json")
        raise HTTPException(status_code=404, detail="run not found")
