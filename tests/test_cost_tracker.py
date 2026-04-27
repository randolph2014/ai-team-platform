"""
CostTracker 单元测试。

测试范围：
- token 估算精度
- 费用计算
- 模型定价查找
- 文件系统降级模式（无数据库时的 JSONL 持久化）
- 运行成本汇总查询
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from engine.cost_tracker import (
    CostTracker,
    estimate_tokens,
    estimate_cost,
    get_pricing,
    MODEL_PRICING,
    DEFAULT_PRICING,
)


class TokenEstimationTests(unittest.TestCase):
    """测试 token 估算精度"""

    def test_empty_text_returns_zero(self) -> None:
        """空文本应返回 0 tokens"""
        self.assertEqual(estimate_tokens(""), 0)

    def test_short_text_minimum_one(self) -> None:
        """短文本至少返回 1 token"""
        self.assertEqual(estimate_tokens("hi"), max(1, len("hi") // 4))

    def test_typical_text_estimation(self) -> None:
        """典型文本按 4 字符/token 估算"""
        text = "hello world this is a test"
        expected = max(1, len(text) // 4)
        self.assertEqual(estimate_tokens(text), expected)

    def test_large_text_estimation(self) -> None:
        """大文本按比例估算"""
        text = "x" * 10000
        self.assertEqual(estimate_tokens(text), 10000 // 4)


class PricingTests(unittest.TestCase):
    """测试模型定价查找"""

    def test_known_model_claude_sonnet(self) -> None:
        """已知模型 claude-sonnet 定价正确"""
        pricing = get_pricing("claude-sonnet")
        self.assertEqual(pricing["input"], MODEL_PRICING["claude-sonnet"]["input"])
        self.assertEqual(pricing["output"], MODEL_PRICING["claude-sonnet"]["output"])

    def test_known_model_gpt4o(self) -> None:
        """已知模型 gpt-4o 定价正确"""
        pricing = get_pricing("gpt-4o")
        self.assertEqual(pricing["input"], 2.5)
        self.assertEqual(pricing["output"], 10.0)

    def test_case_insensitive_lookup(self) -> None:
        """模型名大小写不敏感"""
        pricing_lower = get_pricing("claude-sonnet")
        pricing_upper = get_pricing("CLAUDE-SONNET")
        self.assertEqual(pricing_lower, pricing_upper)

    def test_underscore_hyphen_interchangeable(self) -> None:
        """下划线和连字符等价"""
        pricing_hyphen = get_pricing("claude-sonnet")
        pricing_underscore = get_pricing("claude_sonnet")
        self.assertEqual(pricing_hyphen, pricing_underscore)

    def test_unknown_model_returns_default(self) -> None:
        """未知模型返回默认定价"""
        pricing = get_pricing("unknown-model-xyz")
        self.assertEqual(pricing["input"], DEFAULT_PRICING["input"])
        self.assertEqual(pricing["output"], DEFAULT_PRICING["output"])


class CostCalculationTests(unittest.TestCase):
    """测试费用计算"""

    def test_zero_tokens_zero_cost(self) -> None:
        """0 token 应产生 0 费用"""
        cost = estimate_cost("claude-sonnet", 0, 0)
        self.assertEqual(cost, 0.0)

    def test_prompt_tokens_only(self) -> None:
        """仅 prompt token 的费用计算"""
        cost = estimate_cost("claude-sonnet", 1_000_000, 0)
        expected = (1_000_000 / 1_000_000) * MODEL_PRICING["claude-sonnet"]["input"]
        self.assertEqual(cost, round(expected, 8))

    def test_completion_tokens_only(self) -> None:
        """仅 completion token 的费用计算"""
        cost = estimate_cost("claude-sonnet", 0, 1_000_000)
        expected = (1_000_000 / 1_000_000) * MODEL_PRICING["claude-sonnet"]["output"]
        self.assertEqual(cost, round(expected, 8))

    def test_mixed_tokens(self) -> None:
        """混合 prompt 和 completion token 的费用"""
        cost = estimate_cost("gpt-4o", 500_000, 300_000)
        expected = (500_000 / 1_000_000) * 2.5 + (300_000 / 1_000_000) * 10.0
        self.assertEqual(cost, round(expected, 8))

    def test_gpt4o_mini_cheaper(self) -> None:
        """gpt-4o-mini 比 gpt-4o 便宜"""
        cost_4o = estimate_cost("gpt-4o", 1_000_000, 1_000_000)
        cost_mini = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        self.assertLess(cost_mini, cost_4o)


class FileSystemFallbackTests(unittest.TestCase):
    """测试文件系统降级模式（无真实数据库时使用 JSONL 文件）"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        (root / ".git").mkdir(parents=True)
        self.project_root = root

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_track_usage_writes_jsonl_file(self) -> None:
        """track_usage 在无数据库时将记录写入 JSONL 文件"""
        tracker = CostTracker(self.project_root)
        run_id = "test-run-001"
        tracker.track_usage(
            run_id=run_id,
            agent_name="dev",
            model="claude-sonnet",
            prompt_tokens=1000,
            completion_tokens=500,
            stage_id="develop",
        )
        jsonl_path = self.project_root / ".ai" / "costs" / f"{run_id}.jsonl"
        self.assertTrue(jsonl_path.exists(), "JSONL 文件应被创建")

        with jsonl_path.open("r", encoding="utf-8") as f:
            record = json.loads(f.readline())
        self.assertEqual(record["run_id"], run_id)
        self.assertEqual(record["agent_name"], "dev")
        self.assertEqual(record["model"], "claude-sonnet")
        self.assertEqual(record["prompt_tokens"], 1000)
        self.assertEqual(record["completion_tokens"], 500)
        self.assertEqual(record["stage_id"], "develop")
        self.assertIn("estimated_cost", record)
        self.assertIn("timestamp", record)

    def test_multiple_records_append_to_same_file(self) -> None:
        """同一 run_id 的多条记录追加到同一 JSONL 文件"""
        tracker = CostTracker(self.project_root)
        run_id = "test-run-002"
        tracker.track_usage(run_id, "dev", "claude-sonnet", 100, 50)
        tracker.track_usage(run_id, "qa", "gpt-4o", 200, 100)
        tracker.track_usage(run_id, "reviewer", "claude-haiku", 300, 150)

        jsonl_path = self.project_root / ".ai" / "costs" / f"{run_id}.jsonl"
        lines = list(jsonl_path.read_text(encoding="utf-8").strip().split("\n"))
        self.assertEqual(len(lines), 3)

    def test_get_run_costs_aggregates_correctly(self) -> None:
        """get_run_costs 正确汇总单次运行的成本"""
        tracker = CostTracker(self.project_root)
        run_id = "test-run-003"
        tracker.track_usage(run_id, "dev", "claude-sonnet", 1_000_000, 500_000)
        tracker.track_usage(run_id, "qa", "claude-haiku", 500_000, 200_000)

        summary = tracker.get_run_costs(run_id)
        self.assertEqual(summary["run_id"], run_id)
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["total_prompt_tokens"], 1_500_000)
        self.assertEqual(summary["total_completion_tokens"], 700_000)
        self.assertEqual(summary["total_tokens"], 2_200_000)
        self.assertGreater(summary["total_cost"], 0)

    def test_get_run_costs_nonexistent_run_returns_empty(self) -> None:
        """不存在的 run_id 返回空记录"""
        tracker = CostTracker(self.project_root)
        summary = tracker.get_run_costs("nonexistent-run")
        self.assertEqual(summary["count"], 0)
        self.assertEqual(summary["total_cost"], 0.0)

    def test_get_summary_daily(self) -> None:
        """get_summary daily 汇总今日成本"""
        tracker = CostTracker(self.project_root)
        run_id = "test-run-004"
        tracker.track_usage(run_id, "dev", "claude-sonnet", 1000, 500)
        summary = tracker.get_summary("daily", self.project_root)
        self.assertEqual(summary["period"], "daily")
        self.assertIn("daily", summary["period"])
        self.assertIn("by_model", summary)
        self.assertIn("total_cost", summary)

    def test_env_pricing_overrides_model_pricing(self) -> None:
        """环境变量 AI_TEAM_MODEL_PRICING 可以覆盖模型定价"""
        # 注意：get_pricing 在模块加载时缓存，因此此测试通过直接验证 _load_env_pricing 行为来覆盖
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
        """无效的环境变量定价配置不会导致崩溃"""
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


if __name__ == "__main__":
    unittest.main()
