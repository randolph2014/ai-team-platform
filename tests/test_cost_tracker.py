from __future__ import annotations

import json
import os
import unittest

from engine.cost_tracker import (
    CostTracker,
    estimate_tokens,
    estimate_cost,
    get_pricing,
    MODEL_PRICING,
    DEFAULT_PRICING,
)


class TokenEstimationTests(unittest.TestCase):

    def test_empty_text_returns_zero(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)

    def test_short_text_minimum_one(self) -> None:
        self.assertEqual(estimate_tokens("hi"), max(1, len("hi") // 4))

    def test_typical_text_estimation(self) -> None:
        text = "hello world this is a test"
        expected = max(1, len(text) // 4)
        self.assertEqual(estimate_tokens(text), expected)

    def test_large_text_estimation(self) -> None:
        text = "x" * 10000
        self.assertEqual(estimate_tokens(text), 10000 // 4)


class PricingTests(unittest.TestCase):

    def test_known_model_claude_sonnet(self) -> None:
        pricing = get_pricing("claude-sonnet")
        self.assertEqual(pricing["input"], MODEL_PRICING["claude-sonnet"]["input"])
        self.assertEqual(pricing["output"], MODEL_PRICING["claude-sonnet"]["output"])

    def test_known_model_gpt4o(self) -> None:
        pricing = get_pricing("gpt-4o")
        self.assertEqual(pricing["input"], 2.5)
        self.assertEqual(pricing["output"], 10.0)

    def test_case_insensitive_lookup(self) -> None:
        pricing_lower = get_pricing("claude-sonnet")
        pricing_upper = get_pricing("CLAUDE-SONNET")
        self.assertEqual(pricing_lower, pricing_upper)

    def test_underscore_hyphen_interchangeable(self) -> None:
        pricing_hyphen = get_pricing("claude-sonnet")
        pricing_underscore = get_pricing("claude_sonnet")
        self.assertEqual(pricing_hyphen, pricing_underscore)

    def test_unknown_model_returns_default(self) -> None:
        pricing = get_pricing("unknown-model-xyz")
        self.assertEqual(pricing["input"], DEFAULT_PRICING["input"])
        self.assertEqual(pricing["output"], DEFAULT_PRICING["output"])


class CostCalculationTests(unittest.TestCase):

    def test_zero_tokens_zero_cost(self) -> None:
        cost = estimate_cost("claude-sonnet", 0, 0)
        self.assertEqual(cost, 0.0)

    def test_prompt_tokens_only(self) -> None:
        cost = estimate_cost("claude-sonnet", 1_000_000, 0)
        expected = (1_000_000 / 1_000_000) * MODEL_PRICING["claude-sonnet"]["input"]
        self.assertEqual(cost, round(expected, 8))

    def test_completion_tokens_only(self) -> None:
        cost = estimate_cost("claude-sonnet", 0, 1_000_000)
        expected = (1_000_000 / 1_000_000) * MODEL_PRICING["claude-sonnet"]["output"]
        self.assertEqual(cost, round(expected, 8))

    def test_mixed_tokens(self) -> None:
        cost = estimate_cost("gpt-4o", 500_000, 300_000)
        expected = (500_000 / 1_000_000) * 2.5 + (300_000 / 1_000_000) * 10.0
        self.assertEqual(cost, round(expected, 8))

    def test_gpt4o_mini_cheaper(self) -> None:
        cost_4o = estimate_cost("gpt-4o", 1_000_000, 1_000_000)
        cost_mini = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        self.assertLess(cost_mini, cost_4o)


class CostTrackerNoDBTests(unittest.TestCase):

    def test_get_run_costs_no_db(self) -> None:
        tracker = CostTracker()
        summary = tracker.get_run_costs("nonexistent-run")
        self.assertEqual(summary["run_id"], "nonexistent-run")
        self.assertEqual(summary["count"], 0)
        self.assertEqual(summary["total_cost"], 0.0)

    def test_get_summary_no_db(self) -> None:
        tracker = CostTracker()
        summary = tracker.get_summary("daily")
        self.assertEqual(summary["period"], "daily")
        self.assertIn("total_cost", summary)
        self.assertIn("by_model", summary)

    def test_get_aggregate_no_db(self) -> None:
        tracker = CostTracker()
        result = tracker.get_aggregate("model", "daily")
        self.assertEqual(result["group_by"], "model")
        self.assertEqual(result["groups"], [])

    def test_track_usage_no_db(self) -> None:
        tracker = CostTracker()
        tracker.track_usage(
            run_id="test-run-no-db",
            agent_name="dev",
            model="claude-sonnet",
            prompt_tokens=100,
            completion_tokens=50,
        )

    def test_env_pricing_overrides_model_pricing(self) -> None:
        from engine.cost_tracker import _load_env_pricing

        orig = os.environ.get("AI_TEAM_MODEL_PRICING")
        try:
            os.environ["AI_TEAM_MODEL_PRICING"] = json.dumps({
                "claude-sonnet": {"input": 99.0, "output": 99.0},
            })
            pricing = _load_env_pricing()
            self.assertEqual(pricing["claude-sonnet"]["input"], 99.0)
            self.assertEqual(pricing["claude-sonnet"]["output"], 99.0)
        finally:
            if orig is not None:
                os.environ["AI_TEAM_MODEL_PRICING"] = orig
            else:
                os.environ.pop("AI_TEAM_MODEL_PRICING", None)

    def test_invalid_env_pricing_graceful_fallback(self) -> None:
        from engine.cost_tracker import _load_env_pricing

        orig = os.environ.get("AI_TEAM_MODEL_PRICING")
        try:
            os.environ["AI_TEAM_MODEL_PRICING"] = "not-valid-json"
            pricing = _load_env_pricing()
            self.assertIn("claude-sonnet", pricing)
        finally:
            if orig is not None:
                os.environ["AI_TEAM_MODEL_PRICING"] = orig
            else:
                os.environ.pop("AI_TEAM_MODEL_PRICING", None)


class TestCostsApiAggregateValidation(unittest.TestCase):
    def test_aggregate_invalid_group_by(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("FastAPI not installed")
            return

        from api.app import create_app
        app = create_app()
        client = TestClient(app)
        response = client.get("/api/costs/aggregate?group_by=invalid")
        self.assertEqual(response.status_code, 400)

    def test_aggregate_invalid_period(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("FastAPI not installed")
            return

        from api.app import create_app
        app = create_app()
        client = TestClient(app)
        response = client.get("/api/costs/aggregate?period=invalid")
        self.assertEqual(response.status_code, 400)

    def test_aggregate_valid_params(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("FastAPI not installed")
            return

        from api.app import create_app
        app = create_app()
        client = TestClient(app)
        response = client.get("/api/costs/aggregate?group_by=model&period=daily")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["group_by"], "model")
        self.assertIsInstance(data["groups"], list)


if __name__ == "__main__":
    unittest.main()
