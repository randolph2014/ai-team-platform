"""Pydantic v2 ORM models mapping to database tables.

Each model corresponds to a table defined in persistence/migrations/001_init.up.sql
and provides ``from_row()`` for asyncpg Record conversion and ``to_dict()`` for
serialisation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


def _coerce_uuid(value: Any) -> Optional[str]:
    """Convert UUID or string to string, returning None for null values."""
    if value is None:
        return None
    return str(value)


class PipelineRecord(BaseModel):
    """Maps to ``pipeline`` table."""

    id: str
    name: str
    description: Optional[str] = None
    project_path: str
    config: Dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Any) -> "PipelineRecord":
        data = dict(row)
        data["id"] = _coerce_uuid(data.get("id"))
        if isinstance(data.get("config"), str):
            import json
            data["config"] = json.loads(data["config"])
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class PipelineVersionRecord(BaseModel):
    """Maps to ``pipeline_version`` table."""

    id: str
    pipeline_id: str
    version: int
    config: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Any) -> "PipelineVersionRecord":
        data = dict(row)
        data["id"] = _coerce_uuid(data.get("id"))
        data["pipeline_id"] = _coerce_uuid(data.get("pipeline_id"))
        if isinstance(data.get("config"), str):
            import json
            data["config"] = json.loads(data["config"])
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class PipelineRunRecord(BaseModel):
    """Maps to ``pipeline_run`` table."""

    id: str
    pipeline_id: Optional[str] = None
    status: str = "pending"
    project_root: str = ""
    main_branch: str = "main"
    requirement: Optional[str] = None
    trigger_source: str = "manual"
    worktree_path: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    @classmethod
    def from_row(cls, row: Any) -> "PipelineRunRecord":
        data = dict(row)
        data["id"] = _coerce_uuid(data.get("id"))
        data["pipeline_id"] = _coerce_uuid(data.get("pipeline_id"))
        if isinstance(data.get("context"), str):
            import json
            data["context"] = json.loads(data["context"])
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class StageRunRecord(BaseModel):
    """Maps to ``stage_run`` table."""

    id: str
    pipeline_run_id: str
    stage_id: str
    stage_name: str
    iteration: int = 1
    status: str = "pending"
    is_parallel: bool = False
    loopback_from: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    output_dir: Optional[str] = None

    @classmethod
    def from_row(cls, row: Any) -> "StageRunRecord":
        data = dict(row)
        data["id"] = _coerce_uuid(data.get("id"))
        data["pipeline_run_id"] = _coerce_uuid(data.get("pipeline_run_id"))
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class AgentRunRecord(BaseModel):
    """Maps to ``agent_run`` table."""

    id: str
    stage_run_id: str
    agent_name: str
    runtime_id: str
    runtime_cli: Optional[str] = None
    role: Optional[str] = None
    model_requested: Optional[str] = None
    model_used: Optional[str] = None
    status: str = "pending"
    output_file: Optional[str] = None
    raw_log_file: Optional[str] = None
    exit_code: Optional[int] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    @classmethod
    def from_row(cls, row: Any) -> "AgentRunRecord":
        data = dict(row)
        data["id"] = _coerce_uuid(data.get("id"))
        data["stage_run_id"] = _coerce_uuid(data.get("stage_run_id"))
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class QualityGateRecord(BaseModel):
    """Maps to ``quality_gate_run`` table."""

    id: str
    stage_run_id: str
    gate_name: str
    gate_type: str
    status: str = "pending"
    command: Optional[str] = None
    exit_code: Optional[int] = None
    output: Optional[str] = None
    required: bool = True
    retry_count: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Any) -> "QualityGateRecord":
        data = dict(row)
        data["id"] = _coerce_uuid(data.get("id"))
        data["stage_run_id"] = _coerce_uuid(data.get("stage_run_id"))
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class WebhookRecord(BaseModel):
    """Maps to ``webhook`` table."""

    id: str
    url: str
    secret: str
    events: List[str] = Field(default_factory=list)
    pipeline_id: Optional[str] = None
    enabled: bool = True
    created_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Any) -> "WebhookRecord":
        data = dict(row)
        data["id"] = _coerce_uuid(data.get("id"))
        data["pipeline_id"] = _coerce_uuid(data.get("pipeline_id"))
        if isinstance(data.get("events"), str):
            import json
            data["events"] = json.loads(data["events"])
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")
