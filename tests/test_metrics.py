"""Tests for engine.metrics module."""
from __future__ import annotations

import json
import unittest

from engine.metrics import (
    _MemoryMetrics,
    get_metrics_output,
    is_prometheus_available,
    record_agent_duration,
    record_gate_result,
    record_run,
    record_stage_duration,
    reset_memory_metrics,
    track_agent,
    track_stage,
)


class TestMemoryMetrics(unittest.TestCase):
    def setUp(self) -> None:
        reset_memory_metrics()

    def test_inc_counter(self) -> None:
        """inc_counter accumulates values."""
        m = _MemoryMetrics()
        m.inc_counter("test_counter", {"label": "a"}, 1)
        m.inc_counter("test_counter", {"label": "a"}, 2)
        snap = m.snapshot()
        self.assertEqual(snap["counters"]["test_counter{label=a}"], 3)

    def test_observe_histogram(self) -> None:
        """observe_histogram stores values and computes stats."""
        m = _MemoryMetrics()
        m.observe_histogram("test_hist", {"stage": "dev"}, 1.0)
        m.observe_histogram("test_hist", {"stage": "dev"}, 3.0)
        snap = m.snapshot()
        key = "test_hist{stage=dev}"
        self.assertEqual(snap["histograms"][key]["count"], 2)
        self.assertAlmostEqual(snap["histograms"][key]["sum"], 4.0)
        self.assertAlmostEqual(snap["histograms"][key]["avg"], 2.0)
        self.assertAlmostEqual(snap["histograms"][key]["min"], 1.0)
        self.assertAlmostEqual(snap["histograms"][key]["max"], 3.0)

    def test_reset_clears_all(self) -> None:
        """reset clears all stored metrics."""
        m = _MemoryMetrics()
        m.inc_counter("c", {"a": "b"}, 1)
        m.observe_histogram("h", {"x": "y"}, 5.0)
        m.reset()
        snap = m.snapshot()
        self.assertEqual(snap["counters"], {})
        self.assertEqual(snap["histograms"], {})

    def test_empty_snapshot(self) -> None:
        """Empty metrics returns empty dict."""
        m = _MemoryMetrics()
        snap = m.snapshot()
        self.assertEqual(snap, {"counters": {}, "histograms": {}})

    def test_key_format(self) -> None:
        """_key produces sorted label string."""
        key = _MemoryMetrics._key("my_metric", {"z": "1", "a": "2"})
        self.assertEqual(key, "my_metric{a=2,z=1}")


class TestRecordFunctions(unittest.TestCase):
    def setUp(self) -> None:
        reset_memory_metrics()

    def test_record_run(self) -> None:
        """record_run increments runs counter."""
        record_run("completed")
        record_run("completed")
        record_run("failed")
        body, content_type = get_metrics_output()
        if is_prometheus_available():
            self.assertIn("ai_team_runs_total", body.decode())
        else:
            data = json.loads(body)
            self.assertEqual(data["counters"]["ai_team_runs_total{status=completed}"], 2)
            self.assertEqual(data["counters"]["ai_team_runs_total{status=failed}"], 1)

    def test_record_stage_duration(self) -> None:
        """record_stage_duration stores duration value."""
        record_stage_duration("develop", 5.5)
        record_stage_duration("develop", 10.0)
        body, _ = get_metrics_output()
        if not is_prometheus_available():
            data = json.loads(body)
            key = "ai_team_stage_duration_seconds{stage_id=develop}"
            self.assertEqual(data["histograms"][key]["count"], 2)

    def test_record_agent_duration(self) -> None:
        """record_agent_duration stores duration with agent_name and model."""
        record_agent_duration("tech-lead", "claude-sonnet", 3.2)
        body, _ = get_metrics_output()
        if not is_prometheus_available():
            data = json.loads(body)
            key = "ai_team_agent_duration_seconds{agent_name=tech-lead,model=claude-sonnet}"
            self.assertEqual(data["histograms"][key]["count"], 1)

    def test_record_gate_result(self) -> None:
        """record_gate_result increments gate result counter."""
        record_gate_result("lint", "passed")
        record_gate_result("lint", "passed")
        record_gate_result("test", "failed")
        body, _ = get_metrics_output()
        if not is_prometheus_available():
            data = json.loads(body)
            self.assertEqual(data["counters"]["ai_team_quality_gate_results{gate_name=lint,status=passed}"], 2)


class TestContextManagers(unittest.TestCase):
    def setUp(self) -> None:
        reset_memory_metrics()

    def test_track_stage(self) -> None:
        """track_stage records duration."""
        import time
        with track_stage("test-stage"):
            time.sleep(0.01)
        body, _ = get_metrics_output()
        if not is_prometheus_available():
            data = json.loads(body)
            key = "ai_team_stage_duration_seconds{stage_id=test-stage}"
            self.assertEqual(data["histograms"][key]["count"], 1)
            self.assertGreater(data["histograms"][key]["sum"], 0)

    def test_track_agent(self) -> None:
        """track_agent records duration with agent_name and model."""
        import time
        with track_agent("qa-agent", model="gpt-4"):
            time.sleep(0.01)
        body, _ = get_metrics_output()
        if not is_prometheus_available():
            data = json.loads(body)
            key = "ai_team_agent_duration_seconds{agent_name=qa-agent,model=gpt-4}"
            self.assertEqual(data["histograms"][key]["count"], 1)

    def test_track_stage_records_on_exception(self) -> None:
        """track_stage records duration even when exception occurs."""
        try:
            with track_stage("fail-stage"):
                raise ValueError("boom")
        except ValueError:
            pass
        body, _ = get_metrics_output()
        if not is_prometheus_available:
            data = json.loads(body)
            key = "ai_team_stage_duration_seconds{stage_id=fail-stage}"
            self.assertEqual(data["histograms"][key]["count"], 1)


class TestMetricsEndpoint(unittest.TestCase):
    def test_get_metrics_output_returns_bytes_and_type(self) -> None:
        """get_metrics_output returns (bytes, content_type)."""
        reset_memory_metrics()
        record_run("completed")
        body, content_type = get_metrics_output()
        self.assertIsInstance(body, bytes)
        self.assertIsInstance(content_type, str)
        if is_prometheus_available():
            self.assertIn("text", content_type)
        else:
            self.assertEqual(content_type, "application/json")
            data = json.loads(body)
            self.assertIn("counters", data)

    def test_is_prometheus_available_returns_bool(self) -> None:
        """is_prometheus_available returns a boolean."""
        result = is_prometheus_available()
        self.assertIsInstance(result, bool)


class TestMetricsViaAPI(unittest.TestCase):
    """Test /metrics endpoint via FastAPI TestClient."""

    def test_metrics_endpoint_returns_200(self) -> None:
        """GET /metrics returns 200 with metrics data."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("FastAPI not installed")

        from api.app import create_app

        reset_memory_metrics()
        record_run("completed")
        app = create_app()
        client = TestClient(app)
        response = client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content), 0)


if __name__ == "__main__":
    unittest.main()
