"""Tests for engine.task_queue module."""
from __future__ import annotations

import inspect
import os
import unittest
from unittest.mock import patch


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
        with patch("redis.Redis.from_url", side_effect=Exception("Connection refused")):
            self.assertIsNone(task_queue.get_queue())

    def test_get_job_status_returns_none_on_error(self):
        """get_job_status returns None when Redis is unavailable."""
        from engine import task_queue

        with patch("redis.Redis.from_url", side_effect=Exception("Connection refused")):
            self.assertIsNone(task_queue.get_job_status("nonexistent-job"))


if __name__ == "__main__":
    unittest.main()
