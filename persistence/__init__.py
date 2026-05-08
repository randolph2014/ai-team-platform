from __future__ import annotations

from .connection import close_pool, get_connection
from .migration import get_schema_version, run_migrations
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
    EvalResultRepo,
    EvalSuiteRepo,
    PipelineRepo,
    PipelineRunRepo,
    PipelineVersionRepo,
    ProjectRepo,
    QualityGateRunRepo,
    StageRunRepo,
    WebhookRepo,
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
    "ProjectRepo",
    "WebhookRepo",
    "EvalSuiteRepo",
    "EvalResultRepo",
    # Connection & migration
    "run_migrations",
    "get_schema_version",
    "get_connection",
    "close_pool",
    # Report persistence
    "save_report",
    "save_report_sync",
]
