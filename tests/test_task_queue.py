"""Tests for engine.task_queue module."""
from __future__ import annotations

import inspect
import os
import types
import unittest
from unittest.mock import MagicMock, patch


class TestTaskQueue(unittest.TestCase):
    def test_module_importable(self):
        """engine.task_queue can be imported and exposes expected functions."""
        from engine import task_queue

        self.assertTrue(hasattr(task_queue, "get_queue"))
        self.assertTrue(hasattr(task_queue, "enqueue_run"))
        self.assertTrue(hasattr(task_queue, "get_job_status"))
        self.assertTrue(callable(task_queue.get_queue))
        self.assertTrue(callable(task_queue.enqueue_run))
        self.assertTrue(callable(task_queue.get_job_status))

    def test_enqueue_run_signature(self):
        """enqueue_run accepts the expected parameters."""
        from engine import task_queue

        sig = inspect.signature(task_queue.enqueue_run)
        params = list(sig.parameters.keys())
        self.assertIn("requirement", params)
        self.assertIn("workdir", params)
        self.assertIn("run_id", params)
        self.assertIn("yes", params)
        self.assertIn("config_path", params)
        self.assertIn("only_stage", params)
        self.assertIn("execution_mode", params)

    def test_redis_unavailable_enqueue_returns_none(self):
        """When Redis is unavailable, enqueue_run returns None without raising."""
        from engine import task_queue

        task_queue.reset_queue()
        with patch("engine.task_queue.get_queue", return_value=None):
            result = task_queue.enqueue_run("test requirement", "/tmp", "test-run")
            self.assertIsNone(result)

    def test_get_queue_returns_none_on_connection_error(self):
        """get_queue returns None when Redis connection fails."""
        from engine import task_queue

        task_queue.reset_queue()
        mock_redis_cls = MagicMock()
        mock_redis_cls.from_url.side_effect = Exception("Connection refused")
        with patch.dict("sys.modules", {"redis": MagicMock(Redis=mock_redis_cls)}):
            self.assertIsNone(task_queue.get_queue())

    def test_get_job_status_returns_none_on_error(self):
        """get_job_status returns None when Redis is unavailable."""
        from engine import task_queue

        mock_redis_cls = MagicMock()
        mock_redis_cls.from_url.side_effect = Exception("Connection refused")
        with patch.dict("sys.modules", {"redis": MagicMock(Redis=mock_redis_cls)}):
            self.assertIsNone(task_queue.get_job_status("nonexistent-job"))

    def test_reset_queue_clears_cache(self):
        """reset_queue clears the cached queue instance."""
        from engine import task_queue

        task_queue._queue = MagicMock()
        task_queue.reset_queue()
        self.assertIsNone(task_queue._queue)

    def test_enqueue_run_with_real_queue(self):
        """enqueue_run with a mock queue returns a job id."""
        from engine import task_queue

        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "test-job-123"
        mock_queue.enqueue.return_value = mock_job

        with patch("engine.task_queue.get_queue", return_value=mock_queue):
            result = task_queue.enqueue_run("requirement", "/tmp", "run-1", yes=True)
            self.assertEqual(result, "test-job-123")
            mock_queue.enqueue.assert_called_once()
            self.assertEqual(mock_queue.enqueue.call_args.kwargs["execution_mode"], None)

    def test_failure_callback_persists_valid_failed_report(self):
        """RQ failure callback 构造完整 RunReport，避免状态落库因字段缺失失效"""
        from engine import task_queue

        job = MagicMock()
        job.kwargs = {
            "requirement": "req",
            "workdir": "/tmp/project",
            "run_id": "run-fail",
            "config_path": "/tmp/project/.ai/team.yaml",
        }
        job.args = ()

        save_report = MagicMock()
        persistence_mod = types.SimpleNamespace(save_report_sync=save_report)
        with patch("engine.config.find_project_root", return_value="/tmp/project"), patch.dict("sys.modules", {"persistence": persistence_mod}):
            task_queue._handle_pipeline_failure(job, RuntimeError, RuntimeError("boom"), None)

        report = save_report.call_args.args[0]
        self.assertEqual(report.run_id, "run-fail")
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.requirement, "req")
        self.assertEqual(report.project_root, "/tmp/project")
        self.assertEqual(report.output_dir, "/tmp/project/.ai/team-output/run-fail")

    def test_enqueue_run_exception_resets_queue(self):
        """enqueue_run resets queue when enqueue raises."""
        from engine import task_queue

        mock_queue = MagicMock()
        mock_queue.enqueue.side_effect = Exception("enqueue failed")

        with patch("engine.task_queue.get_queue", return_value=mock_queue):
            result = task_queue.enqueue_run("req", "/tmp", "run-1")
            self.assertIsNone(result)
            self.assertIsNone(task_queue._queue)

    def test_get_job_status_with_mock_redis(self):
        """get_job_status returns status dict when Redis is available."""
        from engine import task_queue

        mock_job = MagicMock()
        mock_job.id = "job-1"
        mock_job.get_status.return_value = "finished"
        mock_job.result = "output"
        mock_job.exc_info = None

        mock_conn = MagicMock()
        mock_redis_cls = MagicMock()
        mock_redis_cls.from_url.return_value = mock_conn

        mock_rq_job = MagicMock()
        mock_rq_job.fetch.return_value = mock_job

        redis_mod = MagicMock()
        redis_mod.Redis = mock_redis_cls
        rq_job_mod = MagicMock()
        rq_job_mod.Job = mock_rq_job

        with patch.dict("sys.modules", {"redis": redis_mod, "rq.job": rq_job_mod}):
            result = task_queue.get_job_status("job-1")
            self.assertIsNotNone(result)
            self.assertEqual(result["job_id"], "job-1")
            self.assertEqual(result["status"], "finished")

    def test_redis_url_from_env(self):
        """_redis_url reads from environment variable."""
        from engine import task_queue

        with patch.dict(os.environ, {"AI_TEAM_REDIS_URL": "redis://custom:6379/1"}):
            self.assertEqual(task_queue._redis_url(), "redis://custom:6379/1")

    def test_redis_url_default(self):
        """_redis_url returns default when env not set."""
        from engine import task_queue

        with patch.dict(os.environ, {}, clear=True):
            url = task_queue._redis_url()
            self.assertIn("localhost", url)


if __name__ == "__main__":
    unittest.main()
