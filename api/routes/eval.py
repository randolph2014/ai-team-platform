from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..db import try_persistence

try:
    from fastapi import APIRouter, Depends, HTTPException, Query
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    APIRouter = None
    BaseModel = object

logger = logging.getLogger(__name__)

router = APIRouter() if APIRouter else None


def _get_auth():
    from ..auth import get_current_user
    return Depends(get_current_user)


class RunEvalRequest(BaseModel):
    suite_name: str
    agent_name: str
    model: Optional[str] = None
    outputs_by_task: Dict[str, str] = {}


class EvalSuiteResponse(BaseModel):
    suite_id: str
    name: str
    description: str
    task_count: int


class TaskInfo(BaseModel):
    task_id: str
    description: str
    expected_keywords: List[str]
    min_output_length: int
    expected_sections: List[str]
    require_code_block: bool


class EvalSuiteDetailResponse(BaseModel):
    suite_id: str
    name: str
    description: str
    tasks: List[TaskInfo]


@router.get("/eval/suites", response_model=List[EvalSuiteResponse])
async def list_eval_suites(user: Dict[str, Any] = _get_auth()):
    from engine.agent_eval import BUILTIN_SUITES

    suites = []
    for idx, (name, suite) in enumerate(BUILTIN_SUITES.items()):
        suites.append({
            "suite_id": str(idx),
            "name": suite.name,
            "description": suite.description,
            "task_count": len(suite.tasks),
        })
    return suites


@router.get("/eval/suites/{suite_name}", response_model=EvalSuiteDetailResponse)
async def get_eval_suite(suite_name: str, user: Dict[str, Any] = _get_auth()):
    from engine.agent_eval import BUILTIN_SUITES

    suite = BUILTIN_SUITES.get(suite_name)
    if suite is None:
        raise HTTPException(status_code=404, detail=f"Eval suite not found: {suite_name}")

    tasks = []
    for task in suite.tasks:
        tasks.append({
            "task_id": task.task_id,
            "description": task.description,
            "expected_keywords": task.expected_keywords,
            "min_output_length": task.min_output_length,
            "expected_sections": task.expected_sections,
            "require_code_block": task.require_code_block,
        })

    return {
        "suite_id": "0",
        "name": suite.name,
        "description": suite.description,
        "tasks": tasks,
    }


@router.post("/eval/run")
async def run_evaluation(request: RunEvalRequest, user: Dict[str, Any] = _get_auth()):
    from engine.agent_eval import BUILTIN_SUITES, run_eval_suite

    suite = BUILTIN_SUITES.get(request.suite_name)
    if suite is None:
        raise HTTPException(status_code=404, detail=f"Eval suite not found: {request.suite_name}")

    result = run_eval_suite(
        request.outputs_by_task,
        suite=suite,
        agent_name=request.agent_name,
        model=request.model,
    )

    result_dict = {
        "suite_id": result.suite_id,
        "suite_name": result.suite_name,
        "agent_name": result.agent_name,
        "model": result.model,
        "tasks_total": result.tasks_total,
        "tasks_completed": result.tasks_completed,
        "completion_rate": result.completion_rate,
        "quality_score": result.quality_score,
        "response_time_ms": result.response_time_ms,
        "token_usage": result.token_usage,
        "task_details": result.task_details,
        "overall_score": result.overall_score,
    }

    try:
        await _save_eval_result(result_dict)
    except Exception:
        logger.debug("Failed to persist eval result", exc_info=True)

    return result_dict


@router.get("/eval/results/{result_id}")
async def get_eval_result(result_id: str, user: Dict[str, Any] = _get_auth()):
    result = await _load_eval_result(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Eval result not found")
    return result


@router.get("/eval/results")
async def list_eval_results(
    agent_name: Optional[str] = Query(None),
    suite_name: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: Dict[str, Any] = _get_auth(),
):
    results = await _list_eval_results(agent_name=agent_name, suite_name=suite_name, limit=limit)
    return results


async def _save_eval_result(result_dict: Dict[str, Any]) -> None:
    db = try_persistence()
    if db is None:
        return
    get_connection, release_connection = db[0], db[1]

    conn = await get_connection()
    if conn is None:
        return
    try:
        from persistence.repository import EvalResultRepo
        repo = EvalResultRepo()
        await repo.create(
            conn,
            suite_name=result_dict.get("suite_name", ""),
            agent_name=result_dict.get("agent_name", ""),
            model=result_dict.get("model"),
            scores=result_dict,
        )
    finally:
        await release_connection(conn)


async def _load_eval_result(result_id: str) -> Optional[Dict[str, Any]]:
    db = try_persistence()
    if db is None:
        return None
    get_connection, release_connection = db[0], db[1]

    conn = await get_connection()
    if conn is None:
        return None
    try:
        from persistence.repository import EvalResultRepo
        repo = EvalResultRepo()
        result = await repo.get_by_id(conn, result_id)
        if result:
            result["scores"] = _parse_jsonb(result.get("scores"))
        return result
    except Exception:
        return None
    finally:
        await release_connection(conn)


async def _list_eval_results(
    agent_name: Optional[str] = None,
    suite_name: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    db = try_persistence()
    if db is None:
        return []
    get_connection, release_connection = db[0], db[1]

    conn = await get_connection()
    if conn is None:
        return []
    try:
        from persistence.repository import EvalResultRepo
        repo = EvalResultRepo()
        results = await repo.list_all(conn, agent_name=agent_name, suite_name=suite_name, limit=limit)
        for r in results:
            r["scores"] = _parse_jsonb(r.get("scores"))
        return results
    except Exception:
        return []
    finally:
        await release_connection(conn)


def _parse_jsonb(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return value
