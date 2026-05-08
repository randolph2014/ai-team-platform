from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from engine.events import DBEventStore, EventBus, InMemoryEventStore, RedisEventBus


class TestEventBusSubscribeEmit(unittest.TestCase):
    def test_subscriber_receives_events(self) -> None:
        bus = EventBus()
        received = []

        def callback(event):
            received.append(event)

        bus.subscribe(callback)
        bus.emit("test:event", "run-1", key="value")

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].type, "test:event")
        self.assertEqual(received[0].run_id, "run-1")
        self.assertEqual(received[0].payload["key"], "value")


class TestEventBusUnsubscribe(unittest.TestCase):
    def test_unsubscribe_stops_receiving(self) -> None:
        bus = EventBus()
        received = []

        def callback(event):
            received.append(event)

        unsub = bus.subscribe(callback)
        bus.emit("first", "run-1")
        unsub()
        bus.emit("second", "run-1")

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].type, "first")


class TestInMemoryEventStore(unittest.TestCase):
    def test_history_returns_published_events(self) -> None:
        from engine.models import Event

        store = InMemoryEventStore()
        store.publish(Event(type="a", run_id="r1"))
        store.publish(Event(type="b", run_id="r1"))
        history = list(store.history("r1"))
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].type, "a")
        self.assertEqual(history[1].type, "b")

    def test_subscribe_queue_receives_events(self) -> None:
        from engine.models import Event

        store = InMemoryEventStore()
        q = store.subscribe("r1")
        evt = Event(type="test", run_id="r1", payload={"x": 1})
        store.publish(evt)
        self.assertEqual(q.get(timeout=1), evt)


class TestDBEventStore(unittest.TestCase):
    def test_publish_without_redis_does_not_raise(self) -> None:
        store = DBEventStore.__new__(DBEventStore)
        store._redis = None
        from engine.models import Event

        event = Event(type="test", run_id="r1", payload={"k": "v"})
        with patch.object(store, "_write_db"):
            store.publish(event)

    def test_publish_to_redis(self) -> None:
        mock_redis = MagicMock()
        store = DBEventStore.__new__(DBEventStore)
        store._redis = mock_redis

        from engine.models import Event

        event = Event(type="test", run_id="r1", payload={"k": "v"})
        with patch.object(store, "_write_db"):
            store.publish(event)

        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args
        self.assertEqual(args[0][0], "ai-team:events:r1")


class TestRedisEventBus(unittest.TestCase):
    def test_bus_events_forwarded_to_store(self) -> None:
        bus = EventBus()
        with patch("engine.events.DBEventStore") as MockStore:
            mock_store = MagicMock()
            MockStore.return_value = mock_store
            redis_bus = RedisEventBus(bus)

            bus.emit("test:event", "run-1", key="value")

            mock_store.publish.assert_called_once()
            event = mock_store.publish.call_args[0][0]
            self.assertEqual(event.type, "test:event")
            self.assertEqual(event.run_id, "run-1")

            redis_bus.close()


if __name__ == "__main__":
    unittest.main()
