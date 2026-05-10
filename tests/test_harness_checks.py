from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.artifact_contracts import validate_artifact
from engine.harness_checks import HarnessCheckError, run_harness_verification
from engine.models import QualityGateRun


class HarnessChecksTempProject(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / ".ai" / "harness").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_harness(self, content: str) -> None:
        (self.root / ".ai" / "harness.yaml").write_text(content, encoding="utf-8")

    def write_baseline(self, coverage: float) -> None:
        baseline_dir = self.root / ".ai" / "harness" / "baselines"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        (baseline_dir / "coverage.json").write_text(
            json.dumps({"mode": "raise_only", "metrics": {"coverage": coverage}}, indent=2),
            encoding="utf-8",
        )

    def init_git_commit(self) -> None:
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "baseline"], cwd=self.root, check=True, capture_output=True, text=True)


class TestHarnessCommandChecks(HarnessChecksTempProject):
    def test_command_checks_reuse_quality_gate_runner(self) -> None:
        command = 'echo ok'
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: cmd.ok\n"
            "    type: command\n"
            f"    command: {json.dumps(command)}\n"
            "    timeout_seconds: 5\n"
        )
        gate_run = QualityGateRun(
            name="cmd.ok",
            type="command",
            command=command,
            status="passed",
            required=True,
            exit_code=0,
            output="ok",
            duration_seconds=0.01,
        )

        with patch("engine.harness_checks.run_quality_gates", return_value=[gate_run]) as run_spy:
            report = run_harness_verification(self.root, run_id="run-1")

        run_spy.assert_called_once()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["checks"][0]["id"], "cmd.ok")

    def test_command_timeout_failure_blocks_pipeline(self) -> None:
        command = f'"{sys.executable}" -c "import time; time.sleep(2)"'
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: cmd.timeout\n"
            "    type: command\n"
            f"    command: {json.dumps(command)}\n"
            "    timeout_seconds: 1\n"
        )

        report = run_harness_verification(self.root, run_id="run-2")

        self.assertEqual(report["status"], "fail")
        self.assertTrue(report["blocking"])
        self.assertEqual(report["checks"][0]["exit_code"], 124)
        self.assertIn("timed out", report["checks"][0]["output_excerpt"])

    def test_command_env_allowlist_prevents_secret_inheritance(self) -> None:
        command = f'"{sys.executable}" -c "import os; print(os.getenv(\'HARNESS_SECRET_TOKEN\', \'missing\'))"'
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: cmd.env\n"
            "    type: command\n"
            f"    command: {json.dumps(command)}\n"
            "    timeout_seconds: 5\n"
        )

        with patch.dict(os.environ, {"HARNESS_SECRET_TOKEN": "secret-value"}, clear=False):
            report = run_harness_verification(self.root, run_id="run-3")

        self.assertEqual(report["status"], "pass")
        self.assertIn("missing", report["checks"][0]["output_excerpt"])
        self.assertNotIn("secret-value", report["checks"][0]["output_excerpt"])

    def test_command_check_cwd_is_limited_to_safe_relative_path(self) -> None:
        (self.root / "tools").mkdir()
        command = f'"{sys.executable}" -c "import pathlib; print(pathlib.Path.cwd().name)"'
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: cmd.cwd\n"
            "    type: command\n"
            f"    command: {json.dumps(command)}\n"
            "    timeout_seconds: 5\n"
            "    cwd: tools\n"
        )

        report = run_harness_verification(self.root, run_id="run-cwd")

        self.assertEqual(report["status"], "pass")
        self.assertIn("tools", report["checks"][0]["output_excerpt"])

    def test_verification_loads_harness_config_from_stage_cwd_when_available(self) -> None:
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: cmd.base\n"
            "    type: command\n"
            "    command: \"echo base\"\n"
            "    timeout_seconds: 5\n"
        )
        worktree = self.root / "worktree"
        (worktree / ".ai" / "harness").mkdir(parents=True)
        (worktree / ".ai" / "harness.yaml").write_text(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: cmd.worktree\n"
            "    type: command\n"
            "    command: \"echo worktree\"\n"
            "    timeout_seconds: 5\n",
            encoding="utf-8",
        )

        report = run_harness_verification(self.root, run_id="run-worktree", cwd=worktree)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["checks"][0]["id"], "cmd.worktree")
        self.assertIn("worktree", report["checks"][0]["output_excerpt"])

    def test_production_dirty_command_config_fails_closed(self) -> None:
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: cmd.prod\n"
            "    type: command\n"
            "    command: \"echo ok\"\n"
            "    timeout_seconds: 5\n"
        )

        with self.assertRaises(HarnessCheckError) as ctx:
            run_harness_verification(self.root, run_id="run-4", production=True)

        self.assertIn("clean committed Harness command config", str(ctx.exception))

    def test_command_output_is_truncated_in_report(self) -> None:
        command = f'"{sys.executable}" -c "print(\'x\' * 21050)"'
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: cmd.truncate\n"
            "    type: command\n"
            f"    command: {json.dumps(command)}\n"
            "    timeout_seconds: 5\n"
        )

        report = run_harness_verification(self.root, run_id="run-5")

        self.assertEqual(report["status"], "pass")
        self.assertLessEqual(len(report["checks"][0]["output_excerpt"]), 20_000)
        self.assertIn("quality_gate:cmd.truncate:output_truncated", report["checks"][0]["evidence_refs"])


class TestHarnessPatternChecks(HarnessChecksTempProject):
    def test_warning_pattern_check_reports_without_blocking(self) -> None:
        source = self.root / "src" / "app.py"
        source.parent.mkdir()
        source.write_text("MessageBox.show('debug')\n", encoding="utf-8")
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: pattern.ui\n"
            "    type: pattern\n"
            "    severity: warning\n"
            "    pattern: MessageBox\n"
            "    globs: ['src/**/*.py']\n"
        )

        report = run_harness_verification(self.root, run_id="run-pattern-1")

        self.assertEqual(report["status"], "warning")
        self.assertFalse(report["blocking"])
        self.assertEqual(report["checks"][0]["status"], "warning")
        self.assertEqual(report["rule_violations"][0]["file"], "src/app.py")

    def test_error_pattern_check_blocks_pipeline(self) -> None:
        source = self.root / "src" / "app.py"
        source.parent.mkdir()
        source.write_text("eval(user_input)\n", encoding="utf-8")
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: pattern.eval\n"
            "    type: pattern\n"
            "    severity: error\n"
            "    pattern: eval\\(\n"
            "    globs: ['src/**/*.py']\n"
        )

        report = run_harness_verification(self.root, run_id="run-pattern-2")

        self.assertEqual(report["status"], "fail")
        self.assertTrue(report["blocking"])
        self.assertEqual(report["checks"][0]["status"], "fail")


class TestHarnessBaselineChecks(HarnessChecksTempProject):
    def test_baseline_raise_only_allows_equal_or_raise(self) -> None:
        self.write_baseline(80)
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: baseline.coverage\n"
            "    type: baseline\n"
            "    baseline_file: .ai/harness/baselines/coverage.json\n"
        )
        self.init_git_commit()
        self.write_baseline(85)

        report = run_harness_verification(self.root, run_id="run-baseline-1")

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["baseline_results"][0]["changes"][0]["previous"], 80)
        self.assertEqual(report["baseline_results"][0]["changes"][0]["current"], 85)

    def test_baseline_lowering_blocks_without_approval(self) -> None:
        self.write_baseline(80)
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: baseline.coverage\n"
            "    type: baseline\n"
            "    baseline_file: .ai/harness/baselines/coverage.json\n"
        )
        self.init_git_commit()
        self.write_baseline(70)

        report = run_harness_verification(self.root, run_id="run-baseline-2")

        self.assertEqual(report["status"], "fail")
        self.assertTrue(report["blocking"])
        self.assertEqual(report["baseline_results"][0]["changes"][0]["previous"], 80)
        self.assertEqual(report["baseline_results"][0]["changes"][0]["current"], 70)

    def test_missing_committed_baseline_warns_without_auto_lowering(self) -> None:
        self.write_baseline(80)
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: baseline.coverage\n"
            "    type: baseline\n"
            "    baseline_file: .ai/harness/baselines/coverage.json\n"
        )

        report = run_harness_verification(self.root, run_id="run-baseline-3")

        self.assertEqual(report["status"], "warning")
        self.assertFalse(report["blocking"])
        self.assertEqual(report["baseline_results"][0]["reason"], "committed baseline not found")


class TestHarnessReportContract(HarnessChecksTempProject):
    def test_report_is_written_and_validates_contract(self) -> None:
        self.write_harness("schema_version: '1.0'\n")
        artifact_dir = self.root / ".ai" / "team-output" / "run-report"

        report = run_harness_verification(self.root, run_id="run-report", project_id="proj-1", artifact_dir=artifact_dir)
        payload = json.loads((artifact_dir / "harness-report.json").read_text(encoding="utf-8"))
        errors, status = validate_artifact(payload, "harness-report.json")

        self.assertEqual(report["status"], "pass")
        self.assertEqual(status, "passed", errors)
        self.assertEqual(errors, [])


class TestHarnessChecksNoSecondRunner(unittest.TestCase):
    def test_harness_checks_does_not_import_subprocess_or_os_system(self) -> None:
        source = (Path(__file__).resolve().parent.parent / "engine" / "harness_checks.py").read_text(encoding="utf-8")

        self.assertNotIn("import subprocess", source)
        self.assertNotIn("os.system", source)


if __name__ == "__main__":
    unittest.main()
