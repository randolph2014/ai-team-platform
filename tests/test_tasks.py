from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestExecutePipeline(unittest.TestCase):
    @patch("engine.orchestrator.Orchestrator")
    @patch("engine.config.find_project_root", return_value="/tmp/project")
    def test_execute_pipeline_returns_output_dir(self, mock_find_root, MockOrch) -> None:
        """execute_pipeline 返回 orchestrator report 的 output_dir 字符串"""
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
        """execute_pipeline 正确传递 config_path 和 only_stage 参数"""
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
        """execute_pipeline 返回值类型为 str"""
        from engine.tasks import execute_pipeline

        mock_report = MagicMock()
        mock_report.output_dir = Path("/tmp/p/.ai-team/runs/r1")
        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_report
        MockOrch.return_value = mock_instance

        result = execute_pipeline("req", "/tmp/p", "r1")
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
