from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestCiReleaseGate(unittest.TestCase):
    def test_critical_ci_steps_are_not_soft_failed(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("mypy engine/ api/ persistence/ --ignore-missing-imports --no-error-summary || true", workflow)
        self.assertIn("mypy engine/release_readiness.py engine/audit.py", workflow)
        self.assertIn("--follow-imports=silent --no-error-summary", workflow)
        self.assertNotIn("pip-audit --desc 2>/dev/null || true", workflow)
        self.assertIn("pip-audit --desc", workflow)
        self.assertNotIn("detect-secrets audit --report --fail-on-unaudited /tmp/baseline.json || true", workflow)
        self.assertIn("python scripts/fail_on_detect_secrets.py /tmp/baseline.json", workflow)

    def test_ci_contains_release_gate_jobs(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for marker in (
            "Lint & Typecheck",
            "Python Tests",
            "Frontend Build",
            "Dependency Audit",
            "Secret Scan",
            "Docker Build Test",
        ):
            self.assertIn(marker, workflow)


class TestDetectSecretsGate(unittest.TestCase):
    def test_detect_secrets_gate_passes_empty_results(self) -> None:
        script = ROOT / "scripts" / "fail_on_detect_secrets.py"
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "baseline.json"
            baseline.write_text(json.dumps({"results": {}}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(script), str(baseline)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)

    def test_detect_secrets_gate_fails_findings(self) -> None:
        script = ROOT / "scripts" / "fail_on_detect_secrets.py"
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "baseline.json"
            baseline.write_text(
                json.dumps({"results": {"app.py": [{"line_number": 7, "type": "Secret Keyword"}]}}),
                encoding="utf-8",
            )
            result = subprocess.run([sys.executable, str(script), str(baseline)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("app.py:7", result.stderr)


class TestOpsRunbook(unittest.TestCase):
    def test_backup_restore_rollback_runbook_exists(self) -> None:
        runbook = ROOT / "docs" / "ops" / "backup-restore-rollback.md"
        content = runbook.read_text(encoding="utf-8")
        for marker in ("pg_dump", "pg_restore", "release-readiness.json", "Rollback", "Stop Conditions"):
            self.assertIn(marker, content)
        self.assertNotIn("\\\\1=***REDACTED***", content)
        self.assertNotIn("docker stop ai-team-api || true", content)


if __name__ == "__main__":
    unittest.main()
