from __future__ import annotations

import threading
from collections import defaultdict, deque
from queue import Queue
from typing import Callable, Deque, Dict, Iterable, List

from .models import Event


Subscriber = Callable[[Event], None]


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
