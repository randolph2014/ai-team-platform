from __future__ import annotations

import json
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _wait_for_report(output_dir: Path, timeout: float = 5.0) -> dict | None:
    report_path = output_dir / "report.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if report_path.exists():
            data = json.loads(report_path.read_text(encoding="utf-8"))
            if data.get("status") in ("completed", "failed"):
                return data
        time.sleep(0.1)
    return None


class ApiTests(unittest.TestCase):
    def test_background_run_records_project_and_artifacts(self) -> None:
        from api import runtime
        from engine.orchestrator import find_run_reports, load_report

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai" / "agents").mkdir(parents=True)
            (root / ".ai" / "agents" / "dev.md").write_text("You are a test agent.", encoding="utf-8")
            (root / "test-config.yaml").write_text(
                """
runtimes:
  mock:
    name: Mock
    cli: mock
    response: "done"
agents:
  - name: dev
    runtime_id: mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: dev-output.md
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            run_id = "api-test-run"
            # Force threading fallback so the test doesn't depend on RQ worker
            with patch("engine.task_queue.enqueue_run", return_value=None):
                output_dir = runtime.start_run_background("api smoke", str(root), run_id=run_id, yes=True, config_path=str(root / "test-config.yaml"))

            report_data = _wait_for_report(output_dir)
            self.assertIsNotNone(report_data)
            self.assertEqual(report_data["status"], "completed")

            reports = find_run_reports(root)
            self.assertEqual(len(reports), 1)
            report = load_report(reports[0])
            self.assertEqual(report.status, "completed")
            self.assertEqual(report.config_source, "project")
            self.assertEqual(runtime.project_for_run(run_id, str(root)), root.resolve())
            artifact_names = set(report.artifacts)
            self.assertIn("dev-output.md", artifact_names)
            self.assertIn("report.json", artifact_names)

    def test_expected_output_dir_detects_duplicate_run_id(self) -> None:
        from api import runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = runtime.expected_output_dir("duplicate", str(root))
            existing.mkdir(parents=True)
            self.assertTrue(existing.exists())

    def test_background_failure_report_has_required_fields(self) -> None:
        from api import runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / ".ai" / "team-output" / "failed-run"
            save_report = MagicMock()
            persistence_mod = types.SimpleNamespace(save_report_sync=save_report)
            with patch.dict("sys.modules", {"persistence": persistence_mod}):
                runtime._persist_background_failure(
                    run_id="failed-run",
                    requirement="req",
                    project_root=root,
                    output_dir=output_dir,
                    error_message="boom",
                    config_path="/tmp/custom.yaml",
                )

            report = save_report.call_args.args[0]
            self.assertEqual(report.status, "failed")
            self.assertEqual(report.requirement, "req")
            self.assertEqual(report.project_root, str(root))
            self.assertEqual(report.output_dir, str(output_dir))
            self.assertEqual(report.config_path, "/tmp/custom.yaml")


if __name__ == "__main__":
    unittest.main()
