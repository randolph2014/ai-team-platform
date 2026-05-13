"""Structured logging configuration for AI Team Platform.

Tries structlog first for JSON output; falls back to standard logging
with a custom JSON formatter so that every log line includes
``run_id``, ``stage_id``, and ``agent_name`` context fields.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

_log_initialized = False

LOGGER_NAME = "ai-team"
_default_level = logging.INFO

try:
    import structlog  # type: ignore[import-untyped]

    _HAS_STRUCTLOG = True
except ImportError:
    _HAS_STRUCTLOG = False


# ---------------------------------------------------------------------------
# JSON formatter (standard logging fallback)
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line with extra context fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Inject context fields attached via ``extra=``
        for key in ("run_id", "stage_id", "agent_name"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.Message) -> str:
        return f"{record.levelname}: {record.getMessage()}"


# ---------------------------------------------------------------------------
# structlog configuration
# ---------------------------------------------------------------------------

def _configure_structlog() -> None:
    """Configure structlog for JSON output with shared context fields."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ---------------------------------------------------------------------------
# Logger factory
# ---------------------------------------------------------------------------

class _ContextLogger:
    """Wrapper that binds run_id / stage_id / agent_name context to every log call."""

    def __init__(self, logger: Any, run_id: str, stage_id: Optional[str] = None, agent_name: Optional[str] = None) -> None:
        self._logger = logger
        self._run_id = run_id
        self._stage_id = stage_id
        self._agent_name = agent_name

    def _extra(self) -> Dict[str, str]:
        ctx: Dict[str, str] = {"run_id": self._run_id}
        if self._stage_id:
            ctx["stage_id"] = self._stage_id
        if self._agent_name:
            ctx["agent_name"] = self._agent_name
        return ctx

    def _uses_stdlib_extra(self) -> bool:
        return isinstance(self._logger, logging.Logger)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        if self._uses_stdlib_extra():
            self._logger.info(msg, *args, extra=self._extra(), **kwargs)
        else:
            self._logger.info(msg, *args, **self._extra(), **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        if self._uses_stdlib_extra():
            self._logger.warning(msg, *args, extra=self._extra(), **kwargs)
        else:
            self._logger.warning(msg, *args, **self._extra(), **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        if self._uses_stdlib_extra():
            self._logger.error(msg, *args, extra=self._extra(), **kwargs)
        else:
            self._logger.error(msg, *args, **self._extra(), **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        if self._uses_stdlib_extra():
            self._logger.debug(msg, *args, extra=self._extra(), **kwargs)
        else:
            self._logger.debug(msg, *args, **self._extra(), **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        if self._uses_stdlib_extra():
            self._logger.exception(msg, *args, extra=self._extra(), **kwargs)
        else:
            self._logger.exception(msg, *args, **self._extra(), **kwargs)


def get_logger(
    name: str = LOGGER_NAME,
    run_id: Optional[str] = None,
    stage_id: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> Any:
    """Return a logger bound to the given context fields.

    When ``run_id`` is provided, returns a ``_ContextLogger`` wrapper that
    automatically injects ``run_id`` / ``stage_id`` / ``agent_name`` into
    every log record.  Otherwise returns a plain stdlib logger (backward
    compatible).
    """
    ensure_initialized()
    if _HAS_STRUCTLOG:
        logger = structlog.get_logger(f"{LOGGER_NAME}.{name}" if name != LOGGER_NAME else LOGGER_NAME)
        if run_id:
            return logger.bind(run_id=run_id, stage_id=stage_id, agent_name=agent_name)
        return logger
    else:
        logger = logging.getLogger(f"{LOGGER_NAME}.{name}" if name != LOGGER_NAME else LOGGER_NAME)
        if run_id:
            return _ContextLogger(logger, run_id, stage_id, agent_name)
        return logger


def ensure_initialized(level: int = _default_level, log_file: Optional[Path] = None, json_output: bool = False) -> None:
    global _log_initialized
    if _log_initialized:
        return
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(level)
    root.handlers.clear()

    if _HAS_STRUCTLOG:
        _configure_structlog()
        # Add a stdlib handler so structlog output reaches stderr
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        root.addHandler(handler)
    else:
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(level)
        if json_output or not sys.stderr.isatty():
            console.setFormatter(JsonFormatter())
        else:
            console.setFormatter(logging.Formatter(
                "[%(asctime)s] %(levelname)-7s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            ))
        root.addHandler(console)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        if _HAS_STRUCTLOG:
            # structlog handles its own formatting; use a pass-through
            file_handler.setFormatter(logging.Formatter("%(message)s"))
        else:
            file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)

    root.propagate = False
    _log_initialized = True


def set_level(level: int) -> None:
    ensure_initialized()
    logging.getLogger(LOGGER_NAME).setLevel(level)


# ---------------------------------------------------------------------------
# Convenience helpers (backward compatible)
# ---------------------------------------------------------------------------

def log_engine_start(project_root: str, config_source: str) -> None:
    logger = get_logger("engine")
    logger.info("引擎启动 project_root=%s config=%s", project_root, config_source)


def log_stage_start(run_id: str, stage_id: str) -> None:
    get_logger("orchestrator", run_id=run_id, stage_id=stage_id).info("stage start: %s", stage_id)


def log_stage_complete(run_id: str, stage_id: str, status: str, duration: float) -> None:
    get_logger("orchestrator", run_id=run_id, stage_id=stage_id).info(
        "stage done: %s status=%s duration=%.1fs", stage_id, status, duration
    )


def log_agent_start(run_id: str, agent_name: str, runtime_id: str) -> None:
    get_logger("agent", run_id=run_id, agent_name=agent_name).info(
        "agent start: %s (runtime=%s)", agent_name, runtime_id
    )


def log_agent_complete(run_id: str, agent_name: str, status: str, exit_code: Optional[int]) -> None:
    get_logger("agent", run_id=run_id, agent_name=agent_name).info(
        "agent done: %s status=%s exit=%s", agent_name, status, exit_code
    )


def log_gate_result(run_id: str, gate_name: str, status: str, exit_code: Optional[int]) -> None:
    get_logger("gate", run_id=run_id).info("gate: %s status=%s exit=%s", gate_name, status, exit_code)


def log_loopback(run_id: str, from_stage: str, to_stage: str, iteration: int) -> None:
    get_logger("orchestrator", run_id=run_id).warning(
        "loopback: %s->%s iteration=%d", from_stage, to_stage, iteration
    )


def is_structlog_available() -> bool:
    return _HAS_STRUCTLOG
