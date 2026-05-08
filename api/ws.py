from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from .db import run_db_id, try_persistence

try:
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect
except ImportError:  # pragma: no cover
    APIRouter = None

logger = logging.getLogger(__name__)

router = APIRouter() if APIRouter else None

REDIS_CHANNEL_PREFIX = "ai-team:events:"


async def _load_db_events(run_id: str):
    from engine.models import Event

    try:
        from persistence.connection import get_connection, release_connection

        conn = await get_connection()
        if conn is None:
            return []
        try:
            rows = await conn.fetch(
                "SELECT event_type, run_id, payload, created_at FROM run_events WHERE run_id = $1 ORDER BY id",
                run_id,
            )
            return [
                Event(
                    type=row["event_type"],
                    run_id=row["run_id"],
                    payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
                    timestamp=row["created_at"].isoformat() if row["created_at"] else None,
                )
                for row in rows
            ]
        finally:
            await release_connection(conn)
    except Exception:
        logger.debug("DB event loading failed for run %s", run_id, exc_info=True)
        return []


async def _load_legacy_db_events(run_id: str):
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
        logger.debug("Legacy DB event loading failed for run %s", run_id, exc_info=True)
        return []
    finally:
        await release_connection(conn)


async def _try_redis_subscribe(run_id: str, websocket: "WebSocket"):
    url = os.environ.get("AI_TEAM_REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return

    client = None
    pubsub = None
    try:
        client = aioredis.from_url(url)
        await client.ping()
        pubsub = client.pubsub()
        channel = f"{REDIS_CHANNEL_PREFIX}{run_id}"
        await pubsub.subscribe(channel)

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await websocket.send_text(data)
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        return
    except Exception:
        logger.debug("Redis subscribe failed for run %s", run_id, exc_info=True)
    finally:
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.close()
            except Exception:
                pass
        if client:
            try:
                await client.aclose()
            except Exception:
                pass


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
        if db_events:
            for event in db_events:
                try:
                    await websocket.send_json(event.model_dump(mode="json"))
                except Exception:
                    return
        else:
            legacy_events = await _load_legacy_db_events(run_id)
            for event in legacy_events:
                try:
                    await websocket.send_json(event.model_dump(mode="json"))
                except Exception:
                    return

        from .runtime import event_store

        mem_history = list(event_store.history(run_id))
        for event in mem_history:
            try:
                await websocket.send_json(event.model_dump(mode="json"))
            except Exception:
                return

        redis_task = asyncio.create_task(_try_redis_subscribe(run_id, websocket))

        queue = event_store.subscribe(run_id)
        try:
            while True:
                event = await asyncio.to_thread(queue.get)
                await websocket.send_json(event.model_dump(mode="json"))
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            event_store.unsubscribe(run_id, queue)
            redis_task.cancel()
            try:
                await redis_task
            except (asyncio.CancelledError, Exception):
                pass
