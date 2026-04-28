"""Metrics collection for AI Team Platform.

Tries prometheus_client first; falls back to an in-memory dict
that can be scraped via ``/metrics`` (JSON format).
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional

try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST  # type: ignore[import-untyped]

    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False

# ---------------------------------------------------------------------------
# Prometheus metrics (when available)
# ---------------------------------------------------------------------------

if _HAS_PROMETHEUS:
    runs_total = Counter(
        "ai_team_runs_total",
        "Total pipeline runs",
        ["status"],
    )
    stage_duration = Histogram(
        "ai_team_stage_duration_seconds",
        "Stage execution duration",
        ["stage_id"],
        buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),
    )
    agent_duration = Histogram(
        "ai_team_agent_duration_seconds",
        "Agent execution duration",
        ["agent_name", "model"],
        buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),
    )
    quality_gate_results = Counter(
        "ai_team_quality_gate_results",
        "Quality gate evaluation results",
        ["gate_name", "status"],
    )


# ---------------------------------------------------------------------------
# In-memory fallback collector
# ---------------------------------------------------------------------------

class _MemoryMetrics:
    """Thread-safe in-memory metrics store used when prometheus_client is absent."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, float] = {}
        self._histograms: Dict[str, list] = {}

    def inc_counter(self, name: str, labels: Dict[str, str], value: float = 1) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value

    def observe_histogram(self, name: str, labels: Dict[str, str], value: float) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._histograms.setdefault(key, []).append(value)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            histograms = {}
            for key, values in self._histograms.items():
                histograms[key] = {
                    "count": len(values),
                    "sum": sum(values),
                    "avg": sum(values) / len(values) if values else 0,
                    "min": min(values) if values else 0,
                    "max": max(values) if values else 0,
                }
        return {"counters": counters, "histograms": histograms}

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()

    @staticmethod
    def _key(name: str, labels: Dict[str, str]) -> str:
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


_mem = _MemoryMetrics()


# ---------------------------------------------------------------------------
# Public API (works with or without prometheus_client)
# ---------------------------------------------------------------------------

def record_run(status: str) -> None:
    """Increment the runs counter."""
    if _HAS_PROMETHEUS:
        runs_total.labels(status=status).inc()
    else:
        _mem.inc_counter("ai_team_runs_total", {"status": status})


def record_stage_duration(stage_id: str, duration: float) -> None:
    """Observe a stage execution duration."""
    if _HAS_PROMETHEUS:
        stage_duration.labels(stage_id=stage_id).observe(duration)
    else:
        _mem.observe_histogram("ai_team_stage_duration_seconds", {"stage_id": stage_id}, duration)


def record_agent_duration(agent_name: str, model: str, duration: float) -> None:
    """Observe an agent execution duration."""
    if _HAS_PROMETHEUS:
        agent_duration.labels(agent_name=agent_name, model=model).observe(duration)
    else:
        _mem.observe_histogram("ai_team_agent_duration_seconds", {"agent_name": agent_name, "model": model}, duration)


def record_gate_result(gate_name: str, status: str) -> None:
    """Increment the quality gate results counter."""
    if _HAS_PROMETHEUS:
        quality_gate_results.labels(gate_name=gate_name, status=status).inc()
    else:
        _mem.inc_counter("ai_team_quality_gate_results", {"gate_name": gate_name, "status": status})


@contextmanager
def track_stage(stage_id: str) -> Generator[None, None, None]:
    """Context manager that records stage duration."""
    start = time.monotonic()
    try:
        yield
    finally:
        record_stage_duration(stage_id, time.monotonic() - start)


@contextmanager
def track_agent(agent_name: str, model: str = "unknown") -> Generator[None, None, None]:
    """Context manager that records agent duration."""
    start = time.monotonic()
    try:
        yield
    finally:
        record_agent_duration(agent_name, model, time.monotonic() - start)


def get_metrics_output() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics endpoint.

    With prometheus_client: Prometheus text exposition format.
    Without: pretty-printed JSON.
    """
    if _HAS_PROMETHEUS:
        return generate_latest(), CONTENT_TYPE_LATEST
    return json.dumps(_mem.snapshot(), indent=2, ensure_ascii=False).encode("utf-8"), "application/json"


def is_prometheus_available() -> bool:
    return _HAS_PROMETHEUS


def reset_memory_metrics() -> None:
    """Reset in-memory metrics (for testing)."""
    _mem.reset()
