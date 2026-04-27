from __future__ import annotations

from .connection import close_pool, get_connection
from .migration import run_migrations
from .models import (
    AgentRunRecord,
    PipelineRecord,
    PipelineRunRecord,
    PipelineVersionRecord,
    QualityGateRecord,
    StageRunRecord,
)
from .repository import (
    AgentRunRepo,
    PipelineRepo,
    PipelineRunRepo,
    PipelineVersionRepo,
    QualityGateRunRepo,
    StageRunRepo,
    save_report,
    save_report_sync,
)

__all__ = [
    # ORM models
    "PipelineRecord",
    "PipelineVersionRecord",
    "PipelineRunRecord",
    "StageRunRecord",
    "AgentRunRecord",
    "QualityGateRecord",
    # Repository classes
    "PipelineRunRepo",
    "StageRunRepo",
    "AgentRunRepo",
    "QualityGateRunRepo",
    "PipelineRepo",
    "PipelineVersionRepo",
    # Connection & migration
    "run_migrations",
    "get_connection",
    "close_pool",
    # Report persistence
    "save_report",
    "save_report_sync",
]
