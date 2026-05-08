from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.models import RequirementUnit
from engine.requirement_splitter import estimate_prompt_size, parse_requirement_units, select_splitter_agent, should_split


class RequirementSplitterTests(unittest.TestCase):
    def test_estimate_prompt_size_counts_requirement_and_artifacts(self) -> None:
        """估算上下文时同时计算原始需求和已存在 artifact 内容"""
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "context.md"
            artifact.write_text("artifact text", encoding="utf-8")

            size = estimate_prompt_size("requirement", [artifact])

            self.assertEqual(size, len("requirement") + len("artifact text"))

    def test_should_split_requires_flag_and_threshold(self) -> None:
        """只有显式启用自动拆分且达到阈值时才拆分"""
        self.assertFalse(should_split({"runner": {"auto_split_requirements": False, "context_threshold_chars": 10}}, 20))
        self.assertFalse(should_split({"runner": {"auto_split_requirements": True, "context_threshold_chars": 10}}, 9))
        self.assertTrue(should_split({"runner": {"auto_split_requirements": True, "context_threshold_chars": 10}}, 10))

    def test_select_splitter_agent_prefers_planner(self) -> None:
        config = {
            "agents": [
                {"name": "planner", "runtime_id": "auto", "role": "planner"},
                {"name": "solution-architect", "runtime_id": "legacy", "role": "architect"},
            ]
        }

        self.assertEqual(select_splitter_agent(config).name, "planner")

    def test_select_splitter_agent_supports_legacy_solution_architect(self) -> None:
        config = {"agents": [{"name": "solution-architect", "runtime_id": "legacy", "role": "architect"}]}

        self.assertEqual(select_splitter_agent(config).name, "solution-architect")

    def test_parse_requirement_units_validates_required_fields(self) -> None:
        """拆分结果必须是带 units 的 JSON，并校验每个单元必需字段"""
        raw = json.dumps(
            {
                "units": [
                    {
                        "id": "unit-1",
                        "title": "登录",
                        "description": "实现登录",
                        "priority": 1,
                        "depends_on": [],
                        "requirement_text": "用户可以登录",
                    }
                ]
            },
            ensure_ascii=False,
        )

        units = parse_requirement_units(raw)

        self.assertEqual(units, [RequirementUnit(id="unit-1", title="登录", description="实现登录", priority=1, depends_on=[], requirement_text="用户可以登录")])

    def test_parse_requirement_units_rejects_invalid_json(self) -> None:
        """无法解析的拆分结果必须显式失败，不能静默回退到原需求"""
        with self.assertRaises(ValueError):
            parse_requirement_units("not json")


if __name__ == "__main__":
    unittest.main()
