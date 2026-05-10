from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


RunStatus = Literal["queued", "running", "paused", "resuming", "completed", "failed", "cancelled", "archived", "blocked"]
StageStatus = Literal["pending", "running", "completed", "failed", "skipped", "cancelled", "waiting"]
AgentStatus = Literal["pending", "running", "completed", "failed", "timeout", "cancelled"]
GateStatus = Literal["pending", "running", "passed", "failed", "skipped", "warning"]

RUN_STATUS_ALIASES: Dict[str, str] = {
    "pending": "queued",
    "waiting": "paused",
}

RUN_TRANSITIONS: Dict[str, set] = {
    "queued": {"running", "cancelled"},
    "running": {"completed", "failed", "cancelled", "paused", "blocked"},
    "paused": {"resuming", "cancelled"},
    "resuming": {"running", "failed", "cancelled", "paused"},
    "failed": {"resuming", "running", "archived"},
    "completed": {"archived"},
    "cancelled": {"archived"},
    "blocked": {"resuming", "running", "cancelled", "failed", "archived"},
    "archived": set(),
}


class InvalidStatusTransition(ValueError):
    pass


def normalize_run_status(status: str) -> str:
    return RUN_STATUS_ALIASES.get(status, status)


def validate_run_transition(current: str, target: str) -> None:
    current = normalize_run_status(current)
    target = normalize_run_status(target)
    allowed = RUN_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidStatusTransition(
            f"invalid status transition: {current} → {target}"
        )


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
    source: Literal["project", "platform", "default", "customized"]
    path: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class AgentDefinition(BaseModel):
    name: str
    runtime_id: str = "auto"
    role: Optional[str] = None
    prompt: Optional[str] = None
    timeout: Optional[int] = None


class AgentRun(BaseModel):
    agent_name: str
    runtime_id: str
    runtime_cli: Optional[str] = None
    role: Optional[str] = None
    model_requested: Optional[str] = None
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
    cwd: Optional[str] = None
    output_truncated: bool = False
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None


class ArtifactValidationRun(BaseModel):
    artifact: str
    status: Literal["passed", "failed"] = "passed"
    message: str = ""


HumanDecisionValue = Literal["waiting", "approved", "rejected"]


class HumanDecision(BaseModel):
    stage_id: str
    decision: HumanDecisionValue
    reason: str = ""
    required_changes: List[str] = Field(default_factory=list)
    target_stage: Optional[str] = None
    decided_by: str = "human"
    decided_at: str = Field(default_factory=utc_now)

    def validate_for_stage(self, requires_reason_on_reject: bool = True) -> None:
        if self.decision == "rejected" and requires_reason_on_reject and not self.reason.strip():
            raise ValueError("reject reason is required")


class RequirementUnit(BaseModel):
    id: str
    title: str
    description: str
    priority: int = 0
    depends_on: List[str] = Field(default_factory=list)
    requirement_text: str


class RequirementUnitProgress(BaseModel):
    unit_id: str
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    completed_stages: List[str] = Field(default_factory=list)
    current_stage: Optional[str] = None


class TargetUser(BaseModel):
    role: str
    needs: str
    scenarios: str


class BusinessScenario(BaseModel):
    name: str
    trigger: str
    flow: str
    frequency: str = "medium"


class EdgeCase(BaseModel):
    case: str
    impact: str
    mitigation: str = ""


class Constraint(BaseModel):
    type: Literal["technical", "business", "time", "resource", "security", "compliance", "other"]
    description: str


class AcceptanceCriterion(BaseModel):
    id: str
    description: str
    verification_method: str


class RequirementAnalysis(BaseModel):
    target_users: List[TargetUser] = Field(default_factory=list)
    business_scenarios: List[BusinessScenario] = Field(default_factory=list)
    must_have: List[str] = Field(default_factory=list)
    edge_cases: List[EdgeCase] = Field(default_factory=list)
    constraints: List[Constraint] = Field(default_factory=list)
    acceptance_criteria: List[AcceptanceCriterion] = Field(default_factory=list)


class PlannedTask(BaseModel):
    id: str
    title: str
    description: str
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
    depends_on: List[str] = Field(default_factory=list)
    deliverable: Optional[Dict[str, str]] = None
    estimated_effort: Literal["S", "M", "L", "XL"] = "M"
    acceptance_criteria: List[str] = Field(default_factory=list)


class TaskPlan(BaseModel):
    tasks: List[PlannedTask] = Field(default_factory=list)
    execution_order: List[List[str]] = Field(default_factory=list)
    risk_items: List[str] = Field(default_factory=list)


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
    artifact_validations: List[ArtifactValidationRun] = Field(default_factory=list)
    human_decision: Optional[HumanDecision] = None
    loopback_to: Optional[str] = None
    error_message: Optional[str] = None


class StatusTimelineEntry(BaseModel):
    status: str
    timestamp: str = Field(default_factory=utc_now)
    reason: Optional[str] = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Any) -> Any:
        if isinstance(value, str):
            return normalize_run_status(value)
        return value


class StructuredError(BaseModel):
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    traceback: Optional[str] = None


class RunReport(BaseModel):
    run_id: str
    status: RunStatus = "queued"
    mode: Literal["single", "multi-unit"] = "single"
    requirement: str
    project_root: str
    output_dir: str
    config_source: Literal["project", "platform", "default", "customized"]
    config_path: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    worktree_path: Optional[str] = None
    merge_result: Optional[Dict[str, Any]] = None
    changed_files: List[str] = Field(default_factory=list)
    diff_stat: str = ""
    stages: List[StageRun] = Field(default_factory=list)
    units: List[RequirementUnitProgress] = Field(default_factory=list)
    human_decisions: List[HumanDecision] = Field(default_factory=list)
    artifacts: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    error_detail: Optional[StructuredError] = None
    status_timeline: List[StatusTimelineEntry] = Field(default_factory=list)
    pr_info: Optional[Dict[str, Any]] = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Any) -> Any:
        if isinstance(value, str):
            return normalize_run_status(value)
        return value

    def write(self, path: Path) -> None:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(model_to_dict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
