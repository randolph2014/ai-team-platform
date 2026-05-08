from __future__ import annotations

import sys
import types
import unittest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch


class TestWebSocketEventHistory(unittest.IsolatedAsyncioTestCase):
    async def test_load_db_events_replays_persisted_history(self) -> None:
        from api.ws import _load_db_events

        created_at = datetime(2026, 5, 8, tzinfo=timezone.utc)
        row = {
            "event_type": "agent:output",
            "run_id": "run-history",
            "payload": '{"text": "hello"}',
            "created_at": created_at,
        }
        conn = AsyncMock()
        conn.fetch.return_value = [row]
        get_connection = AsyncMock(return_value=conn)
        release_connection = AsyncMock()

        with patch("persistence.connection.get_connection", get_connection), \
             patch("persistence.connection.release_connection", release_connection):
            events = await _load_db_events("run-history")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "agent:output")
        self.assertEqual(events[0].payload, {"text": "hello"})
        self.assertEqual(events[0].timestamp, created_at.isoformat())
        release_connection.assert_awaited_once_with(conn)


class TestWebSocketRedisSubscribe(unittest.IsolatedAsyncioTestCase):
    async def test_try_redis_subscribe_forwards_pubsub_messages(self) -> None:
        from api.ws import _try_redis_subscribe

        class FakeWebSocket:
            def __init__(self) -> None:
                self.sent: list[str] = []

            async def send_text(self, data: str) -> None:
                self.sent.append(data)

        class FakePubSub:
            def __init__(self) -> None:
                self.subscribed_channel = None
                self.closed = False
                self._sent = False

            async def subscribe(self, channel: str) -> None:
                self.subscribed_channel = channel

            async def get_message(self, ignore_subscribe_messages: bool, timeout: float):
                if not self._sent:
                    self._sent = True
                    return {"type": "message", "data": b'{"type":"agent:output"}'}
                raise asyncio.CancelledError

            async def unsubscribe(self) -> None:
                pass

            async def close(self) -> None:
                self.closed = True

        class FakeRedisClient:
            def __init__(self, pubsub: FakePubSub) -> None:
                self._pubsub = pubsub
                self.closed = False

            async def ping(self) -> None:
                pass

            def pubsub(self) -> FakePubSub:
                return self._pubsub

            async def aclose(self) -> None:
                self.closed = True

        pubsub = FakePubSub()
        client = FakeRedisClient(pubsub)
        redis_asyncio = types.ModuleType("redis.asyncio")
        redis_asyncio.from_url = lambda url: client
        redis_pkg = types.ModuleType("redis")
        redis_pkg.asyncio = redis_asyncio
        websocket = FakeWebSocket()

        with patch.dict(sys.modules, {"redis": redis_pkg, "redis.asyncio": redis_asyncio}):
            await _try_redis_subscribe("run-redis", websocket)

        self.assertEqual(pubsub.subscribed_channel, "ai-team:events:run-redis")
        self.assertEqual(websocket.sent, ['{"type":"agent:output"}'])
        self.assertTrue(pubsub.closed)
        self.assertTrue(client.closed)
