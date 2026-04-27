from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

_log_initialized = False

LOGGER_NAME = "ai-team"
_default_level = logging.INFO


def _default_formatter() -> logging.Formatter:
    return logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.Message) -> str:
        return f"{record.levelname}: {record.getMessage()}"


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    ensure_initialized()
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name != LOGGER_NAME else LOGGER_NAME)


def ensure_initialized(level: int = _default_level, log_file: Optional[Path] = None) -> None:
    global _log_initialized
    if _log_initialized:
        return
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    if sys.stderr.isatty():
        console.setFormatter(_default_formatter())
    else:
        console.setFormatter(PlainFormatter())
    root.addHandler(console)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(_default_formatter())
        root.addHandler(file_handler)

    root.propagate = False
    _log_initialized = True


def set_level(level: int) -> None:
    ensure_initialized()
    logging.getLogger(LOGGER_NAME).setLevel(level)


def log_engine_start(project_root: str, config_source: str) -> None:
    logger = get_logger("engine")
    logger.info("引擎启动 project_root=%s config=%s", project_root, config_source)


def log_stage_start(run_id: str, stage_id: str) -> None:
    get_logger("orchestrator").info("[%s] stage start: %s", run_id, stage_id)


def log_stage_complete(run_id: str, stage_id: str, status: str, duration: float) -> None:
    get_logger("orchestrator").info("[%s] stage done: %s status=%s duration=%.1fs", run_id, stage_id, status, duration)


def log_agent_start(run_id: str, agent_name: str, provider: str) -> None:
    get_logger("agent").info("[%s] agent start: %s (provider=%s)", run_id, agent_name, provider)


def log_agent_complete(run_id: str, agent_name: str, status: str, exit_code: Optional[int]) -> None:
    get_logger("agent").info("[%s] agent done: %s status=%s exit=%s", run_id, agent_name, status, exit_code)


def log_gate_result(run_id: str, gate_name: str, status: str, exit_code: Optional[int]) -> None:
    get_logger("gate").info("[%s] gate: %s status=%s exit=%s", run_id, gate_name, status, exit_code)


def log_loopback(run_id: str, from_stage: str, to_stage: str, iteration: int) -> None:
    get_logger("orchestrator").warning("[%s] loopback: %s->%s iteration=%d", run_id, from_stage, to_stage, iteration)
