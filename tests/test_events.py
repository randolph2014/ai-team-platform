from __future__ import annotations

import unittest

from engine.events import EventBus, InMemoryEventStore


class TestEventBusSubscribeEmit(unittest.TestCase):
    def test_subscriber_receives_events(self) -> None:
        """subscribe 后 emit 的事件能被回调接收"""
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
        """unsubscribe 后不再收到事件"""
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
        """history 返回已发布的事件列表"""
        from engine.models import Event

        store = InMemoryEventStore()
        store.publish(Event(type="a", run_id="r1"))
        store.publish(Event(type="b", run_id="r1"))
        history = list(store.history("r1"))
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].type, "a")
        self.assertEqual(history[1].type, "b")

    def test_subscribe_queue_receives_events(self) -> None:
        """subscribe 返回的 queue 能接收 publish 的事件"""
        from engine.models import Event

        store = InMemoryEventStore()
        q = store.subscribe("r1")
        evt = Event(type="test", run_id="r1", payload={"x": 1})
        store.publish(evt)
        self.assertEqual(q.get(timeout=1), evt)


if __name__ == "__main__":
    unittest.main()
