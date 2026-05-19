from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.quality_gates import (
    QualityGateExecutionPolicy,
    QualityGateError,
    has_blocking_failure,
    inject_default_gates,
    max_retry_count_for_failures,
    render_gate_feedback,
    run_quality_gate,
    validate_gates_config,
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


class TestQualityGateExecutionPolicy(unittest.TestCase):
    def test_policy_rejects_cwd_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as root_tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(root_tmp)
            outside = Path(outside_tmp)
            result = run_quality_gate(
                {"name": "safe-cwd", "type": "command", "command": "echo ok", "required": True, "timeout_seconds": 1},
                outside,
                "run-policy",
                execution_policy=QualityGateExecutionPolicy(allowed_cwd_roots=[root], require_timeout=True),
            )

        self.assertEqual(result.status, "failed")
        self.assertIsNone(result.exit_code)
        self.assertIn("outside allowed roots", result.output or "")

    def test_policy_requires_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_quality_gate(
                {"name": "timeout-required", "type": "command", "command": "echo ok", "required": True},
                root,
                "run-policy",
                execution_policy=QualityGateExecutionPolicy(allowed_cwd_roots=[root], require_timeout=True),
            )

        self.assertEqual(result.status, "failed")
        self.assertIsNone(result.exit_code)
        self.assertIn("timeout is required", result.output or "")

    def test_policy_rejects_missing_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing"
            result = run_quality_gate(
                {"name": "missing-cwd", "type": "command", "command": "echo ok", "required": True, "timeout_seconds": 1},
                missing,
                "run-policy",
                execution_policy=QualityGateExecutionPolicy(allowed_cwd_roots=[root], require_timeout=True),
            )

        self.assertEqual(result.status, "failed")
        self.assertIsNone(result.exit_code)
        self.assertIn("does not exist", result.output or "")

    def test_policy_truncates_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_quality_gate(
                {
                    "name": "truncate",
                    "type": "command",
                    "command": f'"{sys.executable}" -c "print(\'x\' * 100)"',
                    "required": True,
                    "timeout_seconds": 5,
                },
                root,
                "run-policy",
                execution_policy=QualityGateExecutionPolicy(
                    allowed_cwd_roots=[root],
                    require_timeout=True,
                    output_limit=10,
                    env_allowlist=["PATH"],
                ),
            )

        self.assertEqual(result.status, "passed")
        self.assertTrue(result.output_truncated)
        self.assertLessEqual(len(result.output or ""), 10)

    def test_policy_env_uses_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HARNESS_SECRET_TOKEN": "secret"}, clear=False):
            root = Path(tmp)
            result = run_quality_gate(
                {
                    "name": "env",
                    "type": "command",
                    "command": f'"{sys.executable}" -c "import os; print(os.getenv(\'HARNESS_SECRET_TOKEN\', \'missing\'))"',
                    "required": True,
                    "timeout_seconds": 5,
                },
                root,
                "run-policy",
                execution_policy=QualityGateExecutionPolicy(
                    allowed_cwd_roots=[root],
                    require_timeout=True,
                    env_allowlist=["PATH"],
                ),
            )

        self.assertEqual(result.status, "passed")
        self.assertIn("missing", result.output or "")
        self.assertNotIn("secret", result.output or "")

    def test_default_env_filters_platform_service_vars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "AI_TEAM_DB_URL": "postgresql://platform/db",
                "AI_TEAM_REDIS_URL": "redis://platform/0",
                "DATABASE_URL": "postgresql://generic/db",
                "REDIS_URL": "redis://generic/0",
            },
            clear=False,
        ):
            root = Path(tmp)
            keys = "['AI_TEAM_DB_URL','AI_TEAM_REDIS_URL','DATABASE_URL','REDIS_URL']"
            result = run_quality_gate(
                {
                    "name": "env-clean",
                    "type": "command",
                    "command": f'"{sys.executable}" -c "import os; print(\',\'.join(os.getenv(k, \'missing\') for k in {keys}))"',
                    "required": True,
                    "timeout_seconds": 5,
                },
                root,
                "run-policy",
            )

        self.assertEqual(result.status, "passed")
        self.assertIn("missing,missing,missing,missing", result.output or "")

    def test_gate_env_can_explicitly_restore_filtered_var(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"DATABASE_URL": "postgresql://platform/db"}, clear=False):
            root = Path(tmp)
            result = run_quality_gate(
                {
                    "name": "env-override",
                    "type": "command",
                    "command": f'"{sys.executable}" -c "import os; print(os.getenv(\'DATABASE_URL\', \'missing\'))"',
                    "required": True,
                    "timeout_seconds": 5,
                    "env": {"DATABASE_URL": "postgresql://gate/db"},
                },
                root,
                "run-policy",
            )

        self.assertEqual(result.status, "passed")
        self.assertIn("postgresql://gate/db", result.output or "")


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

    def test_render_gate_feedback_preserves_scope_constraints(self) -> None:
        results = [
            QualityGateRun(name="pytest", type="command", status="failed", required=True, command="pytest", exit_code=1, output="failed"),
        ]
        feedback = render_gate_feedback(
            results,
            retry_count=1,
            scope_note="- T-1: allowed_files=README.md; forbidden_scope=禁止修改任何文件",
        )

        self.assertIn("已确认任务边界", feedback)
        self.assertIn("forbidden_scope=禁止修改任何文件", feedback)
        self.assertIn("如果修复需要越过授权边界", feedback)


class TestValidateGatesConfig(unittest.TestCase):
    def test_empty_gates_in_production_raises(self) -> None:
        with self.assertRaises(QualityGateError) as ctx:
            validate_gates_config([], production=True)
        self.assertIn("empty", str(ctx.exception))

    def test_empty_gates_in_dev_ok(self) -> None:
        validate_gates_config([], production=False)

    def test_required_gate_with_or_true_raises(self) -> None:
        gates = [{"name": "lint", "type": "command", "command": "eslint . || true", "required": True}]
        with self.assertRaises(QualityGateError) as ctx:
            validate_gates_config(gates)
        self.assertIn("|| true", str(ctx.exception))
        self.assertIn("lint", str(ctx.exception))

    def test_required_gate_with_or_true_no_space_raises(self) -> None:
        gates = [{"name": "check", "type": "command", "command": "cmd ||true", "required": True}]
        with self.assertRaises(QualityGateError):
            validate_gates_config(gates)

    def test_optional_gate_with_or_true_ok(self) -> None:
        gates = [{"name": "coverage", "type": "command", "command": "cover || true", "required": False}]
        validate_gates_config(gates)

    def test_required_gate_without_or_true_ok(self) -> None:
        gates = [{"name": "lint", "type": "command", "command": "eslint .", "required": True}]
        validate_gates_config(gates)

    def test_missing_command_gate_ok(self) -> None:
        gates = [{"name": "bad", "type": "command", "required": True}]
        validate_gates_config(gates)

    def test_multiple_gates_one_with_or_true_raises(self) -> None:
        gates = [
            {"name": "good", "type": "command", "command": "echo ok", "required": True},
            {"name": "bad", "type": "command", "command": "test || true", "required": True},
        ]
        with self.assertRaises(QualityGateError):
            validate_gates_config(gates)


class TestInjectDefaultGates(unittest.TestCase):
    def test_existing_gates_returned_unchanged(self) -> None:
        existing = [{"name": "custom", "command": "echo ok"}]
        result = inject_default_gates(Path("/tmp"), existing)
        self.assertEqual(result, existing)

    def test_python_project_gets_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").touch()
            result = inject_default_gates(root, [])
            self.assertGreater(len(result), 0)
            names = [g["name"] for g in result]
            self.assertIn("python-syntax", names)
            self.assertIn("pytest", names)

    def test_node_project_gets_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")
            result = inject_default_gates(root, [])
            self.assertGreater(len(result), 0)
            names = [g["name"] for g in result]
            commands = [g["command"] for g in result]
            self.assertIn("node-build", names)
            self.assertIn("typescript-check", names)
            self.assertIn("test", names)
            self.assertIn("npm run build 2>&1", commands)

    def test_python_project_with_web_app_gets_repo_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").touch()
            (root / "web").mkdir()
            (root / "web" / "package.json").write_text("{}", encoding="utf-8")
            (root / "scripts").mkdir()
            (root / "scripts" / "check_repo_hygiene.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            result = inject_default_gates(root, [])

            names = [g["name"] for g in result]
            self.assertIn("pytest", names)
            self.assertIn("web-test", names)
            self.assertIn("web-build", names)
            self.assertIn("repo-hygiene", names)

    def test_go_project_gets_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "go.mod").write_text("module test\n", encoding="utf-8")
            result = inject_default_gates(root, [])
            self.assertGreater(len(result), 0)
            names = [g["name"] for g in result]
            self.assertIn("go-vet", names)
            self.assertIn("go-test", names)

    def test_java_project_gets_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pom.xml").touch()
            result = inject_default_gates(root, [])
            self.assertGreater(len(result), 0)
            names = [g["name"] for g in result]
            self.assertIn("maven-compile", names)
            self.assertIn("maven-test", names)

    def test_unknown_language_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = inject_default_gates(Path(tmp), [])
            self.assertEqual(result, [])


class TestRunGateRequiredFailureLogging(unittest.TestCase):
    def test_required_gate_failure_logs_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertLogs("engine.quality_gates", level="ERROR") as cm:
                result = run_quality_gate(
                    {"name": "must-pass", "type": "command", "command": "exit 1", "required": True},
                    Path(tmp),
                    "run-log-1",
                )
            self.assertEqual(result.status, "failed")
            self.assertTrue(any("must-pass" in msg for msg in cm.output))
            self.assertTrue(any("Required gate FAILED" in msg for msg in cm.output))


if __name__ == "__main__":
    unittest.main()
