from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from engine.logging_config import (
    PlainFormatter,
    ensure_initialized,
    get_logger,
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
        # Reset logging state before each test
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()

    def test_get_logger_returns_logger(self) -> None:
        """get_logger 返回配置好的 logger"""
        logger = get_logger("test")
        self.assertIsInstance(logger, logging.Logger)
        self.assertIn("ai-team", logger.name)

    def test_get_logger_root_name(self) -> None:
        """get_logger 无参返回根 logger"""
        logger = get_logger()
        self.assertEqual(logger.name, "ai-team")

    def test_ensure_initialized_adds_handler(self) -> None:
        """ensure_initialized 添加控制台 handler"""
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()
        ensure_initialized()
        self.assertGreater(len(logger.handlers), 0)

    def test_ensure_initialized_with_log_file(self) -> None:
        """ensure_initialized 带 log_file 添加文件 handler"""
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "test.log"
            ensure_initialized(log_file=log_file)
            self.assertTrue(log_file.exists())
            self.assertEqual(len(logger.handlers), 2)

    def test_set_level(self) -> None:
        """set_level 改变日志级别"""
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()
        ensure_initialized()
        set_level(logging.DEBUG)
        self.assertEqual(logger.level, logging.DEBUG)


class TestPlainFormatter(unittest.TestCase):
    def test_format(self) -> None:
        """PlainFormatter 格式化日志记录"""
        formatter = PlainFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        result = formatter.format(record)
        self.assertEqual(result, "INFO: hello")


class TestLogHelpers(unittest.TestCase):
    def setUp(self) -> None:
        import engine.logging_config as lc
        lc._log_initialized = False
        logger = logging.getLogger(lc.LOGGER_NAME)
        logger.handlers.clear()

    def test_log_engine_start(self) -> None:
        """log_engine_start 不抛出异常"""
        log_engine_start("/tmp/project", "platform")

    def test_log_stage_start(self) -> None:
        """log_stage_start 不抛出异常"""
        log_stage_start("run-1", "develop")

    def test_log_stage_complete(self) -> None:
        """log_stage_complete 不抛出异常"""
        log_stage_complete("run-1", "develop", "completed", 1.5)

    def test_log_agent_start(self) -> None:
        """log_agent_start 不抛出异常"""
        log_agent_start("run-1", "tech-lead", "claude")

    def test_log_agent_complete(self) -> None:
        """log_agent_complete 不抛出异常"""
        log_agent_complete("run-1", "tech-lead", "completed", 0)

    def test_log_gate_result(self) -> None:
        """log_gate_result 不抛出异常"""
        log_gate_result("run-1", "lint", "passed", 0)

    def test_log_loopback(self) -> None:
        """log_loopback 不抛出异常"""
        log_loopback("run-1", "qa", "develop", 1)


if __name__ == "__main__":
    unittest.main()
