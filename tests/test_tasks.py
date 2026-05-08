from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestExecutePipeline(unittest.TestCase):
    @patch("engine.orchestrator.Orchestrator")
    @patch("engine.config.find_project_root", return_value="/tmp/project")
    def test_execute_pipeline_returns_output_dir(self, mock_find_root, MockOrch) -> None:
        from engine.tasks import execute_pipeline

        mock_report = MagicMock()
        mock_report.output_dir = "/tmp/project/.ai-team/runs/run-123"
        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_report
        MockOrch.return_value = mock_instance

        result = execute_pipeline(
            requirement="build a REST API",
            workdir="/tmp/project",
            run_id="run-123",
            yes=True,
        )

        self.assertEqual(result, "/tmp/project/.ai-team/runs/run-123")
        mock_find_root.assert_called_once_with("/tmp/project")
        MockOrch.assert_called_once()
        mock_instance.run.assert_called_once_with(
            requirement="build a REST API",
            run_id="run-123",
            yes=True,
            only_stage=None,
            execution_mode=None,
        )

    @patch("engine.orchestrator.Orchestrator")
    @patch("engine.config.find_project_root", return_value="/tmp/project")
    def test_execute_pipeline_passes_config_path(self, mock_find_root, MockOrch) -> None:
        from engine.tasks import execute_pipeline

        mock_report = MagicMock()
        mock_report.output_dir = "/tmp/out"
        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_report
        MockOrch.return_value = mock_instance

        result = execute_pipeline(
            requirement="add tests",
            workdir="/tmp/project",
            run_id="run-456",
            config_path="/tmp/project/ai-team.yaml",
            only_stage="coding",
            execution_mode="serial",
        )

        self.assertEqual(result, "/tmp/out")
        call_kwargs = MockOrch.call_args[1]
        self.assertEqual(call_kwargs["config_path"], "/tmp/project/ai-team.yaml")
        mock_instance.run.assert_called_once()
        self.assertEqual(mock_instance.run.call_args.kwargs["execution_mode"], "serial")

    @patch("engine.orchestrator.Orchestrator")
    @patch("engine.config.find_project_root", return_value="/tmp/p")
    def test_execute_pipeline_returns_string(self, mock_find_root, MockOrch) -> None:
        from engine.tasks import execute_pipeline

        mock_report = MagicMock()
        mock_report.output_dir = Path("/tmp/p/.ai-team/runs/r1")
        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_report
        MockOrch.return_value = mock_instance

        result = execute_pipeline("req", "/tmp/p", "r1")
        self.assertIsInstance(result, str)

    @patch("engine.orchestrator.Orchestrator")
    @patch("engine.config.find_project_root", return_value="/tmp/p")
    def test_execute_pipeline_persists_failure_on_exception(self, mock_find_root, MockOrch) -> None:
        from engine.tasks import execute_pipeline

        mock_instance = MagicMock()
        mock_instance.run.side_effect = RuntimeError("boom")
        MockOrch.return_value = mock_instance

        save_report = MagicMock()
        import types
        persistence_mod = types.SimpleNamespace(save_report_sync=save_report)
        with patch.dict("sys.modules", {"persistence": persistence_mod}):
            with self.assertRaises(RuntimeError):
                execute_pipeline("req", "/tmp/p", "r-fail")

        report = save_report.call_args.args[0]
        self.assertEqual(report.run_id, "r-fail")
        self.assertEqual(report.status, "failed")
        self.assertIn("boom", report.error_message)

    @patch("engine.events.RedisEventBus")
    @patch("engine.orchestrator.Orchestrator")
    @patch("engine.config.find_project_root", return_value="/tmp/project")
    def test_execute_pipeline_wires_worker_events_to_redis_bus(self, mock_find_root, MockOrch, MockRedisBus) -> None:
        from engine.tasks import execute_pipeline

        mock_report = MagicMock()
        mock_report.output_dir = "/tmp/project/.ai/team-output/run-events"
        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_report
        MockOrch.return_value = mock_instance

        execute_pipeline("req", "/tmp/project", "run-events")

        event_bus = MockRedisBus.call_args.args[0]
        self.assertIs(MockOrch.call_args.kwargs["event_bus"], event_bus)
        MockRedisBus.return_value.close.assert_called_once()


class TestExecuteResume(unittest.TestCase):
    @patch("engine.orchestrator.Orchestrator")
    @patch("engine.config.find_project_root", return_value="/tmp/project")
    def test_execute_resume_reads_requirement_and_runs(self, mock_find_root, MockOrch) -> None:
        from engine.tasks import execute_resume

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / ".ai" / "team-output" / "resume-run"
            output_dir.mkdir(parents=True)
            (output_dir / "requirement.md").write_text("test requirement", encoding="utf-8")

            mock_report = MagicMock()
            mock_report.output_dir = str(output_dir)
            mock_instance = MagicMock()
            mock_instance.run.return_value = mock_report
            MockOrch.return_value = mock_instance

            with patch("engine.config.find_project_root", return_value=tmp):
                result = execute_resume("resume-run", tmp, yes=True)

            self.assertEqual(result, str(output_dir))
            call_kwargs = mock_instance.run.call_args.kwargs
            self.assertTrue(call_kwargs["resume"])
            self.assertEqual(call_kwargs["requirement"], "test requirement")

    @patch("engine.config.find_project_root", return_value="/tmp/project")
    def test_execute_resume_raises_if_requirement_missing(self, mock_find_root) -> None:
        from engine.tasks import execute_resume

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / ".ai" / "team-output" / "no-req-run"
            output_dir.mkdir(parents=True)

            with self.assertRaises(FileNotFoundError):
                execute_resume("no-req-run", tmp)

    @patch("engine.orchestrator.Orchestrator")
    def test_execute_resume_passes_human_decision(self, MockOrch) -> None:
        from engine.tasks import execute_resume

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / ".ai" / "team-output" / "decision-run"
            output_dir.mkdir(parents=True)
            (output_dir / "requirement.md").write_text("req", encoding="utf-8")

            mock_report = MagicMock()
            mock_report.output_dir = str(output_dir)
            mock_instance = MagicMock()
            mock_instance.run.return_value = mock_report
            MockOrch.return_value = mock_instance

            decision = {"stage_id": "s1", "decision": "approved", "reason": "", "required_changes": [], "target_stage": None}
            with patch("engine.config.find_project_root", return_value=tmp):
                execute_resume("decision-run", tmp, human_decision=decision)

            call_kwargs = mock_instance.run.call_args.kwargs
            self.assertIsNotNone(call_kwargs["human_decision"])
            self.assertEqual(call_kwargs["human_decision"].stage_id, "s1")


if __name__ == "__main__":
    unittest.main()
