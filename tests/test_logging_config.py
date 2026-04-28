from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.logging_config import (
    JsonFormatter,
    PlainFormatter,
    _ContextLogger,
    ensure_initialized,
    get_logger,
    is_structlog_available,
    log_agent_complete,
    log_agent_start,
    log_engine_start,
    log_gate_result,
    log_loopback,
    log_stage_complete,
    log_stage_start,
    set_level,
)


class TestLoggingInit(unittest.TestCase):
    def setUp(self) -> None:
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()

    def test_get_logger_returns_logger(self) -> None:
        logger = get_logger("test")
        self.assertIsNotNone(logger)

    def test_get_logger_root_name(self) -> None:
        logger = get_logger()
        if hasattr(logger, "name"):
            self.assertEqual(logger.name, "ai-team")

    def test_ensure_initialized_adds_handler(self) -> None:
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()
        ensure_initialized()
        self.assertGreater(len(logger.handlers), 0)

    def test_ensure_initialized_with_log_file(self) -> None:
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "test.log"
            ensure_initialized(log_file=log_file)
            self.assertTrue(log_file.exists())

    def test_set_level(self) -> None:
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()
        ensure_initialized()
        set_level(logging.DEBUG)
        self.assertEqual(logger.level, logging.DEBUG)

    def test_ensure_initialized_json_output(self) -> None:
        """ensure_initialized with json_output=True uses JsonFormatter."""
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()
        ensure_initialized(json_output=True)
        # At least one handler should have JsonFormatter (if not structlog)
        if not is_structlog_available():
            has_json = any(
                isinstance(h.formatter, JsonFormatter)
                for h in logger.handlers
                if hasattr(h, "formatter") and h.formatter
            )
            self.assertTrue(has_json)


class TestJsonFormatter(unittest.TestCase):
    def test_format_produces_json(self) -> None:
        """JsonFormatter produces valid JSON output."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="ai-team.test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        result = formatter.format(record)
        data = json.loads(result)
        self.assertEqual(data["level"], "INFO")
        self.assertEqual(data["message"], "test message")
        self.assertIn("timestamp", data)

    def test_format_includes_context_fields(self) -> None:
        """JsonFormatter includes run_id, stage_id, agent_name when present."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="ai-team.test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None,
        )
        record.run_id = "run-123"
        record.stage_id = "develop"
        record.agent_name = "tech-lead"
        result = formatter.format(record)
        data = json.loads(result)
        self.assertEqual(data["run_id"], "run-123")
        self.assertEqual(data["stage_id"], "develop")
        self.assertEqual(data["agent_name"], "tech-lead")

    def test_format_excludes_none_context(self) -> None:
        """JsonFormatter omits context fields that are None."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="ai-team.test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None,
        )
        result = formatter.format(record)
        data = json.loads(result)
        self.assertNotIn("run_id", data)
        self.assertNotIn("stage_id", data)

    def test_format_with_exception(self) -> None:
        """JsonFormatter includes exception info."""
        formatter = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="ai-team.test", level=logging.ERROR, pathname="", lineno=0,
            msg="error occurred", args=(), exc_info=exc_info,
        )
        result = formatter.format(record)
        data = json.loads(result)
        self.assertIn("exception", data)
        self.assertIn("ValueError", data["exception"])


class TestPlainFormatter(unittest.TestCase):
    def test_format(self) -> None:
        formatter = PlainFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        result = formatter.format(record)
        self.assertEqual(result, "INFO: hello")


class TestContextLogger(unittest.TestCase):
    def setUp(self) -> None:
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()

    def test_context_logger_info(self) -> None:
        """_ContextLogger.info injects extra fields."""
        import engine.logging_config as lc
        lc._log_initialized = False
        base_logger = logging.getLogger(lc.LOGGER_NAME)
        base_logger.setLevel(logging.DEBUG)
        # Add a handler that captures records
        records = []
        class CaptureHandler(logging.Handler):
            def emit(self, record):
                records.append(record)
        handler = CaptureHandler()
        handler.setLevel(logging.DEBUG)
        base_logger.addHandler(handler)

        ctx_logger = _ContextLogger(base_logger, "run-42", stage_id="develop", agent_name="dev")
        ctx_logger.info("test message %s", "arg1")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].run_id, "run-42")
        self.assertEqual(records[0].stage_id, "develop")
        self.assertEqual(records[0].agent_name, "dev")
        self.assertIn("arg1", records[0].getMessage())

    def test_context_logger_warning(self) -> None:
        """_ContextLogger.warning works."""
        import engine.logging_config as lc
        lc._log_initialized = False
        base_logger = logging.getLogger(lc.LOGGER_NAME)
        base_logger.setLevel(logging.DEBUG)
        records = []
        class CaptureHandler(logging.Handler):
            def emit(self, record):
                records.append(record)
        base_logger.addHandler(CaptureHandler())

        ctx_logger = _ContextLogger(base_logger, "run-1")
        ctx_logger.warning("warn msg")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].levelno, logging.WARNING)

    def test_context_logger_error(self) -> None:
        """_ContextLogger.error works."""
        import engine.logging_config as lc
        lc._log_initialized = False
        base_logger = logging.getLogger(lc.LOGGER_NAME)
        base_logger.setLevel(logging.DEBUG)
        records = []
        class CaptureHandler(logging.Handler):
            def emit(self, record):
                records.append(record)
        base_logger.addHandler(CaptureHandler())

        ctx_logger = _ContextLogger(base_logger, "run-1")
        ctx_logger.error("error msg")
        self.assertEqual(records[0].levelno, logging.ERROR)

    def test_context_logger_debug(self) -> None:
        """_ContextLogger.debug works."""
        import engine.logging_config as lc
        lc._log_initialized = False
        base_logger = logging.getLogger(lc.LOGGER_NAME)
        base_logger.setLevel(logging.DEBUG)
        records = []
        class CaptureHandler(logging.Handler):
            def emit(self, record):
                records.append(record)
        base_logger.addHandler(CaptureHandler())

        ctx_logger = _ContextLogger(base_logger, "run-1")
        ctx_logger.debug("debug msg")
        self.assertEqual(records[0].levelno, logging.DEBUG)

    def test_get_logger_with_run_id_returns_context_logger(self) -> None:
        """get_logger with run_id returns _ContextLogger (when structlog absent)."""
        import engine.logging_config as lc
        lc._log_initialized = False
        if not is_structlog_available():
            logger = get_logger("test", run_id="run-99")
            self.assertIsInstance(logger, _ContextLogger)

    def test_get_logger_without_run_id_returns_plain_logger(self) -> None:
        """get_logger without run_id returns plain logger."""
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = get_logger("test")
        if not is_structlog_available():
            self.assertIsInstance(logger, logging.Logger)


class TestLogHelpers(unittest.TestCase):
    def setUp(self) -> None:
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()

    def test_log_engine_start(self) -> None:
        log_engine_start("/tmp/project", "platform")

    def test_log_stage_start(self) -> None:
        log_stage_start("run-1", "develop")

    def test_log_stage_complete(self) -> None:
        log_stage_complete("run-1", "develop", "completed", 1.5)

    def test_log_agent_start(self) -> None:
        log_agent_start("run-1", "tech-lead", "claude")

    def test_log_agent_complete(self) -> None:
        log_agent_complete("run-1", "tech-lead", "completed", 0)

    def test_log_gate_result(self) -> None:
        log_gate_result("run-1", "lint", "passed", 0)

    def test_log_loopback(self) -> None:
        log_loopback("run-1", "qa", "develop", 1)

    def test_is_structlog_available_returns_bool(self) -> None:
        self.assertIsInstance(is_structlog_available(), bool)


class TestStructlogIntegration(unittest.TestCase):
    """Test structlog integration when available."""

    def test_structlog_logger_bind(self) -> None:
        """When structlog is available, get_logger with run_id returns bound logger."""
        if not is_structlog_available():
            self.skipTest("structlog not installed")

        import engine.logging_config as lc
        lc._log_initialized = False
        logger = get_logger("test", run_id="run-42", stage_id="dev")
        # structlog bound logger should have bind method
        self.assertTrue(hasattr(logger, "bind") or hasattr(logger, "info"))

    def test_structlog_configured(self) -> None:
        """When structlog is available, ensure_initialized configures it."""
        if not is_structlog_available():
            self.skipTest("structlog not installed")

        import engine.logging_config as lc
        lc._log_initialized = False
        import structlog
        # Reset structlog configuration
        structlog.reset_defaults()
        ensure_initialized()
        # Should not raise
        logger = structlog.get_logger("test")
        self.assertIsNotNone(logger)


if __name__ == "__main__":
    unittest.main()
