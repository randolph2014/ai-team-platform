from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from engine.models import (
    InvalidStatusTransition,
    RunReport,
    StatusTimelineEntry,
    StructuredError,
    validate_run_transition,
)


class TestRunStateMachine(unittest.TestCase):
    def test_pending_to_running(self):
        validate_run_transition("pending", "running")

    def test_pending_to_cancelled(self):
        validate_run_transition("pending", "cancelled")

    def test_running_to_completed(self):
        validate_run_transition("running", "completed")

    def test_running_to_failed(self):
        validate_run_transition("running", "failed")

    def test_running_to_cancelled(self):
        validate_run_transition("running", "cancelled")

    def test_running_to_waiting(self):
        validate_run_transition("running", "waiting")

    def test_waiting_to_running(self):
        validate_run_transition("waiting", "running")

    def test_waiting_to_cancelled(self):
        validate_run_transition("waiting", "cancelled")

    def test_failed_to_running(self):
        validate_run_transition("failed", "running")

    def test_failed_to_archived(self):
        validate_run_transition("failed", "archived")

    def test_completed_to_archived(self):
        validate_run_transition("completed", "archived")

    def test_cancelled_to_archived(self):
        validate_run_transition("cancelled", "archived")

    def test_archived_has_no_transitions(self):
        with self.assertRaises(InvalidStatusTransition):
            validate_run_transition("archived", "running")

    def test_invalid_transition_raises(self):
        with self.assertRaises(InvalidStatusTransition) as ctx:
            validate_run_transition("completed", "running")
        self.assertIn("completed", str(ctx.exception))
        self.assertIn("running", str(ctx.exception))

    def test_invalid_transition_same_status(self):
        with self.assertRaises(InvalidStatusTransition):
            validate_run_transition("running", "running")

    def test_cancel_completed_raises(self):
        with self.assertRaises(InvalidStatusTransition):
            validate_run_transition("completed", "cancelled")

    def test_cancel_failed_raises(self):
        with self.assertRaises(InvalidStatusTransition):
            validate_run_transition("failed", "cancelled")

    def test_retry_completed_raises(self):
        with self.assertRaises(InvalidStatusTransition):
            validate_run_transition("completed", "running")

    def test_archive_running_raises(self):
        with self.assertRaises(InvalidStatusTransition):
            validate_run_transition("running", "archived")


class TestStructuredError(unittest.TestCase):
    def test_structured_error_fields(self):
        err = StructuredError(
            error_type="RuntimeError",
            error_message="agent exited with code 1",
            traceback="Traceback...",
        )
        self.assertEqual(err.error_type, "RuntimeError")
        self.assertEqual(err.error_message, "agent exited with code 1")
        self.assertEqual(err.traceback, "Traceback...")

    def test_structured_error_optional(self):
        err = StructuredError()
        self.assertIsNone(err.error_type)


class TestStatusTimelineEntry(unittest.TestCase):
    def test_entry_has_timestamp(self):
        entry = StatusTimelineEntry(status="running")
        self.assertEqual(entry.status, "running")
        self.assertIsNotNone(entry.timestamp)

    def test_entry_with_reason(self):
        entry = StatusTimelineEntry(status="failed", reason="timeout")
        self.assertEqual(entry.reason, "timeout")


class TestRunReportNewFields(unittest.TestCase):
    def test_report_default_error_detail(self):
        report = RunReport(
            run_id="test",
            requirement="req",
            project_root="/tmp",
            output_dir="/tmp/out",
            config_source="default",
        )
        self.assertIsNone(report.error_detail)
        self.assertEqual(report.status_timeline, [])

    def test_report_with_error_detail(self):
        report = RunReport(
            run_id="test",
            requirement="req",
            project_root="/tmp",
            output_dir="/tmp/out",
            config_source="default",
            error_detail=StructuredError(
                error_type="ValueError",
                error_message="bad input",
            ),
        )
        self.assertEqual(report.error_detail.error_type, "ValueError")

    def test_report_with_timeline(self):
        report = RunReport(
            run_id="test",
            requirement="req",
            project_root="/tmp",
            output_dir="/tmp/out",
            config_source="default",
            status_timeline=[
                StatusTimelineEntry(status="pending"),
                StatusTimelineEntry(status="running"),
            ],
        )
        self.assertEqual(len(report.status_timeline), 2)

    def test_report_serialization_includes_new_fields(self):
        report = RunReport(
            run_id="test",
            requirement="req",
            project_root="/tmp",
            output_dir="/tmp/out",
            config_source="default",
            error_detail=StructuredError(error_type="Err"),
            status_timeline=[StatusTimelineEntry(status="pending")],
        )
        data = report.model_dump(mode="json")
        self.assertIn("error_detail", data)
        self.assertIn("status_timeline", data)
        self.assertEqual(data["error_detail"]["error_type"], "Err")

    def test_report_json_roundtrip(self):
        import tempfile
        from pathlib import Path

        report = RunReport(
            run_id="roundtrip",
            requirement="req",
            project_root="/tmp",
            output_dir="/tmp/out",
            config_source="default",
            error_detail=StructuredError(error_type="TestErr", error_message="msg"),
            status_timeline=[
                StatusTimelineEntry(status="pending"),
                StatusTimelineEntry(status="running"),
                StatusTimelineEntry(status="failed", reason="timeout"),
            ],
        )
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "report.json"
            report.write(p)
            data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data["error_detail"]["error_type"], "TestErr")
        self.assertEqual(len(data["status_timeline"]), 3)
        self.assertEqual(data["status_timeline"][2]["reason"], "timeout")


try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


class BaseRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_FASTAPI:
            raise unittest.SkipTest("FastAPI not installed")

    def setUp(self):
        import tempfile
        from pathlib import Path
        import yaml

        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        (root / ".git").mkdir(parents=True)
        (root / ".ai").mkdir(parents=True)
        (root / ".ai" / "agents").mkdir(parents=True)
        (root / ".ai" / "agents" / "dev.md").write_text("You are a dev agent.", encoding="utf-8")
        self.project_root = root
        self.pipelines_dir = root / ".ai" / "pipelines"

        initial_config = """
runtimes:
  mock:
    name: Mock
    cli: mock
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
"""
        self.settings_store = yaml.safe_load(initial_config) or {}

        async def fake_db_get_settings():
            return json.loads(json.dumps(self.settings_store))

        async def fake_db_save_settings(config):
            self.settings_store = json.loads(json.dumps(config))
            return True

        def fake_try_load_db_config():
            return json.loads(json.dumps(self.settings_store)) if self.settings_store else None

        self._config_patches = [
            patch("engine.config._try_load_db_config", side_effect=fake_try_load_db_config),
            patch("api.routes.settings._db_get_settings", side_effect=fake_db_get_settings),
            patch("api.routes.settings._db_save_settings", side_effect=fake_db_save_settings),
            patch("api.routes.pipelines.PIPELINES_DIR", self.pipelines_dir),
        ]
        for p in self._config_patches:
            p.start()

        from api.app import create_app
        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self):
        for p in reversed(self._config_patches):
            p.stop()
        self.temp_dir.cleanup()


class TestArchiveEndpoint(BaseRoutesTest):
    def test_archive_completed_run(self):
        run_id = "archive-completed-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="completed",
            requirement="req",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")

        response = self.client.post(
            f"/api/runs/{run_id}/archive",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "archived")

    def test_archive_failed_run(self):
        run_id = "archive-failed-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="failed",
            requirement="req",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")

        response = self.client.post(
            f"/api/runs/{run_id}/archive",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 200)

    def test_archive_running_returns_409(self):
        run_id = "archive-running-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="running",
            requirement="req",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")

        response = self.client.post(
            f"/api/runs/{run_id}/archive",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("invalid status transition", response.json()["detail"])

    def test_archive_nonexistent_returns_404(self):
        response = self.client.post(
            "/api/runs/nonexistent-archive/archive",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 404)

    def test_archive_already_archived_returns_409(self):
        run_id = "archive-twice-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="archived",
            requirement="req",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")

        response = self.client.post(
            f"/api/runs/{run_id}/archive",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 409)


class TestCancelStateMachine(BaseRoutesTest):
    def test_cancel_completed_returns_409(self):
        run_id = "sm-cancel-completed"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="completed",
            requirement="req",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")

        response = self.client.post(
            f"/api/runs/{run_id}/cancel",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 409)

    def test_cancel_failed_returns_409(self):
        run_id = "sm-cancel-failed"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="failed",
            requirement="req",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")

        response = self.client.post(
            f"/api/runs/{run_id}/cancel",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 409)


class TestRetryStateMachine(BaseRoutesTest):
    def test_retry_completed_returns_409(self):
        run_id = "sm-retry-completed"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="completed",
            requirement="req",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")

        response = self.client.post(
            f"/api/runs/{run_id}/retry",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 409)


class TestListRunsStatusFilter(BaseRoutesTest):
    def test_list_runs_with_status_filter(self):
        from engine.models import RunReport

        for status_val, rid in [("completed", "filter-completed"), ("failed", "filter-failed")]:
            output_dir = self.project_root / ".ai" / "team-output" / rid
            output_dir.mkdir(parents=True)
            report = RunReport(
                run_id=rid,
                status=status_val,
                requirement="req",
                project_root=str(self.project_root),
                output_dir=str(output_dir),
                config_source="default",
            )
            report.write(output_dir / "report.json")

        response = self.client.get(
            "/api/runs",
            params={"workdir": str(self.project_root), "status": "completed"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        run_ids = [r["run_id"] for r in items]
        self.assertIn("filter-completed", run_ids)
        self.assertNotIn("filter-failed", run_ids)

    def test_list_runs_paginated_response(self):
        response = self.client.get(
            "/api/runs",
            params={"workdir": str(self.project_root), "page": 1, "size": 5},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertIn("page", data)
        self.assertIn("size", data)


if __name__ == "__main__":
    unittest.main()
