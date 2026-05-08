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
    def test_background_run_enqueues_and_returns_output_dir(self) -> None:
        from api import runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = "api-enqueue-test"
            with patch("engine.task_queue.enqueue_run", return_value="fake-job-id"):
                output_dir = runtime.start_run_background("api smoke", str(root), run_id=run_id, yes=True)
            self.assertEqual(output_dir, (root / ".ai" / "team-output" / run_id).resolve())

    def test_background_run_raises_when_enqueue_fails(self) -> None:
        from api import runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("engine.task_queue.enqueue_run", return_value=None):
                with self.assertRaises(RuntimeError):
                    runtime.start_run_background("req", str(root), run_id="fail-run", yes=True)

    def test_expected_output_dir_detects_duplicate_run_id(self) -> None:
        from api import runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = runtime.expected_output_dir("duplicate", str(root))
            existing.mkdir(parents=True)
            self.assertTrue(existing.exists())

    def test_persist_run_failure_has_required_fields(self) -> None:
        from engine.tasks import _persist_run_failure

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_report = MagicMock()
            persistence_mod = types.SimpleNamespace(save_report_sync=save_report)
            with patch("engine.config.find_project_root", return_value=str(root)), \
                 patch.dict("sys.modules", {"persistence": persistence_mod}):
                _persist_run_failure(
                    run_id="failed-run",
                    requirement="req",
                    workdir=str(root),
                    config_path="/tmp/custom.yaml",
                    error_message="boom",
                )

            report = save_report.call_args.args[0]
            self.assertEqual(report.status, "failed")
            self.assertEqual(report.requirement, "req")
            self.assertEqual(report.project_root, str(root))
            self.assertEqual(report.config_path, "/tmp/custom.yaml")


if __name__ == "__main__":
    unittest.main()
