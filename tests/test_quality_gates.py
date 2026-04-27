from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine.quality_gates import (
    has_blocking_failure,
    max_retry_count_for_failures,
    render_gate_feedback,
    run_quality_gate,
)
from engine.models import QualityGateRun


class TestQualityGateCommand(unittest.TestCase):
    def test_command_success(self) -> None:
        """command 类型门禁：命令成功 → passed"""
        with tempfile.TemporaryDirectory() as tmp:
            result = run_quality_gate(
                {"name": "echo", "type": "command", "command": "echo ok", "required": True},
                Path(tmp),
                "run-1",
            )
            self.assertEqual(result.status, "passed")
            self.assertEqual(result.exit_code, 0)

    def test_command_failure(self) -> None:
        """command 类型门禁：命令失败 → failed"""
        with tempfile.TemporaryDirectory() as tmp:
            result = run_quality_gate(
                {"name": "fail", "type": "command", "command": "exit 1", "required": True},
                Path(tmp),
                "run-1",
            )
            self.assertEqual(result.status, "failed")
            self.assertNotEqual(result.exit_code, 0)


class TestQualityGateThreshold(unittest.TestCase):
    def test_threshold_success(self) -> None:
        """threshold 类型门禁：实际值满足阈值 → passed"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "out.txt").write_text("Coverage: 92.5%\n", encoding="utf-8")
            result = run_quality_gate(
                {
                    "name": "coverage",
                    "type": "threshold",
                    "command": f"cat {root / 'out.txt'}",
                    "parse": "regex:Coverage:\\s*([\\d.]+)%",
                    "operator": ">=",
                    "threshold": 80,
                    "required": True,
                },
                root,
                "run-1",
            )
            self.assertEqual(result.status, "passed")
            self.assertEqual(result.actual, 92.5)

    def test_threshold_failure(self) -> None:
        """threshold 类型门禁：实际值不满足阈值 → failed"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "out.txt").write_text("Coverage: 45.0%\n", encoding="utf-8")
            result = run_quality_gate(
                {
                    "name": "coverage",
                    "type": "threshold",
                    "command": f"cat {root / 'out.txt'}",
                    "parse": "regex:Coverage:\\s*([\\d.]+)%",
                    "operator": ">=",
                    "threshold": 80,
                    "required": True,
                },
                root,
                "run-1",
            )
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.actual, 45.0)


class TestQualityGateRequiredFalse(unittest.TestCase):
    def test_required_false_produces_warning(self) -> None:
        """required=false 的门禁失败时 → warning 而非 failed"""
        with tempfile.TemporaryDirectory() as tmp:
            result = run_quality_gate(
                {"name": "optional", "type": "command", "command": "exit 1", "required": False},
                Path(tmp),
                "run-1",
            )
            self.assertEqual(result.status, "warning")

    def test_has_blocking_failure_ignores_warning(self) -> None:
        """has_blocking_failure 不将 warning 视为阻塞"""
        warning_result = QualityGateRun(name="opt", type="command", status="warning", required=False)
        self.assertFalse(has_blocking_failure([warning_result]))


class TestQualityGateMaxRetries(unittest.TestCase):
    def test_max_retry_count_for_failures(self) -> None:
        """max_retry_count_for_failures 返回失败门禁中最大的 max_retries"""
        gates = [
            {"name": "gate-a", "type": "command", "max_retries": 3},
            {"name": "gate-b", "type": "command", "max_retries": 1},
        ]
        results = [
            QualityGateRun(name="gate-a", type="command", status="failed", required=True),
            QualityGateRun(name="gate-b", type="command", status="passed", required=True),
        ]
        self.assertEqual(max_retry_count_for_failures(gates, results), 3)

    def test_render_gate_feedback_includes_details(self) -> None:
        """render_gate_feedback 输出包含失败门禁详细信息"""
        results = [
            QualityGateRun(name="lint", type="command", status="failed", required=True, command="pylint", exit_code=1, output="E: syntax error"),
        ]
        feedback = render_gate_feedback(results, retry_count=1)
        self.assertIn("lint", feedback)
        self.assertIn("pylint", feedback)
        self.assertIn("syntax error", feedback)
        self.assertIn("第 1 次重试", feedback)


if __name__ == "__main__":
    unittest.main()
