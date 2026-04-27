from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .db import run_db_id, try_persistence
from .runtime import event_store

try:
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect
except ImportError:  # pragma: no cover
    APIRouter = None

logger = logging.getLogger(__name__)

router = APIRouter() if APIRouter else None


async def _load_db_events(run_id: str):
    """从 DB 加载历史事件（如果可用）。返回 Event 对象列表。"""
    db = try_persistence()
    if db is None:
        return []
    get_connection, release_connection, PipelineRunRepo, _, _ = db

    conn = await get_connection()
    if conn is None:
        return []
    try:
        from engine.models import Event

        db_id = run_db_id(run_id)
        repo = PipelineRunRepo()
        detail = await repo.get_run_with_details(conn, db_id)
        if detail is None:
            return []

        events = []
        events.append(Event(
            type="run_status",
            run_id=run_id,
            payload={
                "status": detail.get("status"),
                "started_at": str(detail.get("started_at")) if detail.get("started_at") else None,
                "completed_at": str(detail.get("completed_at")) if detail.get("completed_at") else None,
            },
        ))
        for stage in detail.get("stages", []):
            events.append(Event(
                type="stage_status",
                run_id=run_id,
                payload={
                    "stage_id": stage.get("stage_id"),
                    "stage_name": stage.get("stage_name"),
                    "status": stage.get("status"),
                },
            ))
            for agent in stage.get("agents", []):
                events.append(Event(
                    type="agent_status",
                    run_id=run_id,
                    payload={
                        "stage_id": stage.get("stage_id"),
                        "agent_name": agent.get("agent_name"),
                        "status": agent.get("status"),
                    },
                ))
        return events
    except Exception:
        logger.debug("DB event loading failed for run %s", run_id, exc_info=True)
        return []
    finally:
        await release_connection(conn)


if router:

    @router.websocket("/ws/runs/{run_id}")
    async def run_events(websocket: WebSocket, run_id: str, token: Optional[str] = None):
        try:
            from ..auth import verify_ws_token
            await verify_ws_token(token)
        except Exception:
            await websocket.accept()
            await websocket.close(code=4001, reason="Unauthorized")
            return

        await websocket.accept()

        db_events = await _load_db_events(run_id)

        mem_history = list(event_store.history(run_id))
        if mem_history:
            for event in mem_history:
                try:
                    await websocket.send_json(event.model_dump(mode="json"))
                except Exception:
                    return
        elif db_events:
            for event in db_events:
                try:
                    await websocket.send_json(event.model_dump(mode="json"))
                except Exception:
                    return

        queue = event_store.subscribe(run_id)
        try:
            while True:
                event = await asyncio.to_thread(queue.get)
                await websocket.send_json(event.model_dump(mode="json"))
        except WebSocketDisconnect:
            event_store.unsubscribe(run_id, queue)
        except Exception:
            event_store.unsubscribe(run_id, queue)
