from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


RunStatus = Literal["pending", "running", "completed", "failed", "cancelled", "waiting"]
StageStatus = Literal["pending", "running", "completed", "failed", "skipped", "cancelled", "waiting"]
AgentStatus = Literal["pending", "running", "completed", "failed", "timeout", "cancelled"]
GateStatus = Literal["pending", "running", "passed", "failed", "skipped", "warning"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class Event(BaseModel):
    type: str
    run_id: str
    timestamp: str = Field(default_factory=utc_now)
    payload: Dict[str, Any] = Field(default_factory=dict)


class LoadedConfig(BaseModel):
    config: Dict[str, Any]
    source: Literal["project", "platform", "default"]
    path: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class AgentDefinition(BaseModel):
    name: str
    provider: str = "Auto"
    role: Optional[str] = None
    prompt: Optional[str] = None
    timeout: Optional[int] = None
    model: Optional[str] = None
    fallback_models: List[str] = Field(default_factory=list)


class AgentRun(BaseModel):
    agent_name: str
    provider: str
    role: Optional[str] = None
    model_used: Optional[str] = None
    status: AgentStatus = "pending"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    output_file: Optional[str] = None
    raw_log_file: Optional[str] = None
    exit_code: Optional[int] = None
    error_message: Optional[str] = None


class QualityGateRun(BaseModel):
    name: str
    type: str
    status: GateStatus = "pending"
    command: Optional[str] = None
    output: Optional[str] = None
    exit_code: Optional[int] = None
    required: bool = True
    retry_count: int = 0
    threshold: Optional[float] = None
    actual: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None


class StageRun(BaseModel):
    stage_id: str
    stage_name: str
    iteration: int = 1
    status: StageStatus = "pending"
    is_parallel: bool = False
    type: str = "agent"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    output_dir: Optional[str] = None
    agents: List[AgentRun] = Field(default_factory=list)
    quality_gates: List[QualityGateRun] = Field(default_factory=list)
    error_message: Optional[str] = None


class RunReport(BaseModel):
    run_id: str
    status: RunStatus = "pending"
    requirement: str
    project_root: str
    output_dir: str
    config_source: Literal["project", "platform", "default"]
    config_path: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    worktree_path: Optional[str] = None
    merge_result: Optional[Dict[str, Any]] = None
    stages: List[StageRun] = Field(default_factory=list)
    artifacts: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None

    def write(self, path: Path) -> None:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(model_to_dict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
