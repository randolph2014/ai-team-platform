from __future__ import annotations

import json
import logging
import os
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from queue import Queue
from typing import Callable, Deque, Dict, Iterable, List, Optional

from .models import Event

logger = logging.getLogger(__name__)

Subscriber = Callable[[Event], None]

REDIS_CHANNEL_PREFIX = "ai-team:events:"


class EventBus:
    def __init__(self) -> None:
        self._subscribers: List[Subscriber] = []
        self._lock = threading.Lock()

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def emit(self, event_type: str, run_id: str, **payload) -> Event:
        event = Event(type=event_type, run_id=run_id, payload=payload)
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            callback(event)
        return event


class InMemoryEventStore:
    def __init__(self, max_events_per_run: int = 2000) -> None:
        self._max_events = max_events_per_run
        self._events: Dict[str, Deque[Event]] = defaultdict(lambda: deque(maxlen=max_events_per_run))
        self._queues: Dict[str, List[Queue]] = defaultdict(list)
        self._lock = threading.Lock()

    def publish(self, event: Event) -> None:
        with self._lock:
            self._events[event.run_id].append(event)
            queues = list(self._queues[event.run_id])
        for queue in queues:
            queue.put(event)

    def history(self, run_id: str) -> Iterable[Event]:
        with self._lock:
            return list(self._events.get(run_id, ()))

    def subscribe(self, run_id: str) -> Queue:
        queue: Queue = Queue()
        with self._lock:
            self._queues[run_id].append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: Queue) -> None:
        with self._lock:
            queues = self._queues.get(run_id)
            if queues and queue in queues:
                queues.remove(queue)


class DBEventStore:
    def __init__(self, redis_url: Optional[str] = None) -> None:
        self._redis = None
        url = redis_url or os.environ.get("AI_TEAM_REDIS_URL", "redis://localhost:6379/0")
        try:
            from redis import Redis
            self._redis = Redis.from_url(url)
            self._redis.ping()
        except Exception:
            self._redis = None

    def publish(self, event: Event) -> None:
        if self._redis:
            try:
                channel = f"{REDIS_CHANNEL_PREFIX}{event.run_id}"
                self._redis.publish(channel, event.model_dump_json())
            except Exception:
                logger.debug("Redis publish failed for run %s", event.run_id, exc_info=True)

        threading.Thread(target=self._write_db, args=(event,), daemon=True).start()

    def _write_db(self, event: Event) -> None:
        try:
            from persistence.connection import is_available
            if not is_available():
                return
            import asyncio
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self._async_write(event))
            else:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(lambda: asyncio.run(self._async_write(event))).result(timeout=10)
        except Exception:
            logger.debug("DB event write failed for run %s", event.run_id, exc_info=True)

    async def _async_write(self, event: Event) -> None:
        from persistence.connection import get_connection, release_connection
        conn = await get_connection()
        if conn is None:
            return
        try:
            await conn.execute(
                "INSERT INTO run_events (run_id, event_type, payload, created_at) VALUES ($1, $2, $3, $4)",
                event.run_id,
                event.type,
                json.dumps(event.payload, ensure_ascii=False),
                datetime.fromisoformat(event.timestamp) if event.timestamp else datetime.now(timezone.utc),
            )
        except Exception:
            logger.debug("DB event insert failed for run %s", event.run_id, exc_info=True)
        finally:
            await release_connection(conn)

    async def history(self, run_id: str) -> List[Event]:
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
            logger.debug("DB event history failed for run %s", run_id, exc_info=True)
            return []


class RedisEventBus:
    def __init__(self, bus: EventBus, redis_url: Optional[str] = None) -> None:
        self._bus = bus
        self._store = DBEventStore(redis_url=redis_url)
        self._unsubscribe = bus.subscribe(self._on_event)

    def _on_event(self, event: Event) -> None:
        self._store.publish(event)

    def close(self) -> None:
        self._unsubscribe()
