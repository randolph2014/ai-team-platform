from __future__ import annotations

import asyncio

from .runtime import event_store

try:
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect
except ImportError:  # pragma: no cover
    APIRouter = None


router = APIRouter() if APIRouter else None


if router:

    @router.websocket("/ws/runs/{run_id}")
    async def run_events(websocket: WebSocket, run_id: str):
        await websocket.accept()
        for event in event_store.history(run_id):
            await websocket.send_json(event.model_dump(mode="json"))
        queue = event_store.subscribe(run_id)
        try:
            while True:
                event = await asyncio.to_thread(queue.get)
                await websocket.send_json(event.model_dump(mode="json"))
        except WebSocketDisconnect:
            event_store.unsubscribe(run_id, queue)
