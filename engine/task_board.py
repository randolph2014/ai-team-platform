from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import RunReport, utc_now


TASK_BOARD_DIR = ".ai/harness"
TASKS_DIR = ".ai/harness/tasks"
TASK_EVENTS_DIR = ".ai/harness/task-events"
TASK_BOARD_SNAPSHOT = ".ai/harness/task-board.json"
TASK_BOARD_LOCK = ".ai/harness/.task-board.lock"

TaskState = Literal[
    "proposed",
    "planned",
    "in_progress",
    "blocked",
    "qa_failed",
    "review_changes_requested",
    "accepted",
    "rejected",
    "cancelled",
    "archived",
]


class TaskBoardError(Exception):
    pass


class TaskStateError(TaskBoardError):
    pass


class TaskEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    title: str = ""
    state: TaskState
    source_stage: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    artifact_dir: str = Field(min_length=1)
    decision_ids: List[str] = Field(min_length=1)
    event_id: str = ""
    event_type: str = "state_changed"
    decision: Optional[str] = None
    requirement: str = ""
    summary: str = ""
    tags: List[str] = Field(default_factory=list)
    related_files: List[str] = Field(default_factory=list)
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    risks: List[Dict[str, Any]] = Field(default_factory=list)
    message: str = ""
    created_at: str = Field(default_factory=utc_now)

    @field_validator("task_id", "source_stage", "run_id", "artifact_dir")
    @classmethod
    def _traceability_fields_not_blank(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("task event traceability fields must not be blank")
        return cleaned

    @field_validator("decision_ids")
    @classmethod
    def _decision_ids_not_blank(cls, value: List[str]) -> List[str]:
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if not cleaned:
            raise ValueError("decision_ids must contain at least one non-empty item")
        return cleaned


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    id: str
    title: str
    state: TaskState
    run_id: str
    artifact_dir: str
    decision_ids: List[str] = Field(default_factory=list)
    run_ids: List[str] = Field(default_factory=list)
    artifact_dirs: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    related_files: List[str] = Field(default_factory=list)
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    risks: List[Dict[str, Any]] = Field(default_factory=list)
    requirement: str = ""
    summary: str = ""
    state_history: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    accepted_at: Optional[str] = None


def _root(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve()


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    return slug or uuid.uuid4().hex


def task_id_for_run(run_id: str) -> str:
    return f"run-{_slug(run_id)}"


def _path(project_root: Path, rel_path: str) -> Path:
    root = _root(project_root)
    candidate = (root / rel_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise TaskBoardError(f"task board path escapes project root: {rel_path}") from exc
    return candidate


def _tasks_dir(project_root: Path) -> Path:
    return _path(project_root, TASKS_DIR)


def _events_dir(project_root: Path) -> Path:
    return _path(project_root, TASK_EVENTS_DIR)


def _task_path(project_root: Path, task_id: str) -> Path:
    return _tasks_dir(project_root) / f"{_slug(task_id)}.json"


def _snapshot_path(project_root: Path) -> Path:
    return _path(project_root, TASK_BOARD_SNAPSHOT)


def _event_filename(event: TaskEvent) -> str:
    stamp = re.sub(r"[^0-9]", "", event.created_at)[:20] or str(int(time.time() * 1000))
    event_id = _slug(event.event_id or f"{event.run_id}-{event.source_stage}-{event.state}-{uuid.uuid4().hex[:8]}")
    return f"{stamp}-{event_id}.json"


class _TaskBoardLock:
    def __init__(self, project_root: Path, timeout_seconds: float = 5.0) -> None:
        self.path = _path(project_root, TASK_BOARD_LOCK)
        self.timeout_seconds = timeout_seconds
        self.fd: Optional[int] = None

    def __enter__(self) -> "_TaskBoardLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode("utf-8"))
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TaskBoardError("task board lock timeout")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.fd is not None:
            os.close(self.fd)
        self.path.unlink(missing_ok=True)


def _dump_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TaskBoardError(f"task board json must be an object: {path}")
    return data


def _unique_append(items: List[str], values: Iterable[str]) -> List[str]:
    seen = set(items)
    for raw in values:
        value = str(raw).strip()
        if value and value not in seen:
            items.append(value)
            seen.add(value)
    return items


def _merge_dicts(existing: List[Dict[str, Any]], incoming: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = list(existing)
    seen = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in result}
    for item in incoming:
        if not isinstance(item, dict):
            continue
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


def _validate_transition(event: TaskEvent) -> None:
    if event.state != "accepted":
        return
    if event.source_stage != "acceptance_confirm" or event.decision != "approved":
        raise TaskStateError("accepted task state requires approved acceptance_confirm human decision")


def _load_task(path: Path) -> TaskRecord:
    return TaskRecord.model_validate(_read_json(path))


def _new_record(event: TaskEvent) -> TaskRecord:
    now = event.created_at
    return TaskRecord(
        id=event.task_id,
        title=event.title or event.summary or event.requirement or event.task_id,
        state=event.state,
        run_id=event.run_id,
        artifact_dir=event.artifact_dir,
        decision_ids=list(event.decision_ids),
        run_ids=[event.run_id],
        artifact_dirs=[event.artifact_dir],
        tags=list(event.tags),
        related_files=list(event.related_files),
        decisions=list(event.decisions),
        risks=list(event.risks),
        requirement=event.requirement,
        summary=event.summary,
        state_history=[],
        created_at=now,
        updated_at=now,
        accepted_at=now if event.state == "accepted" else None,
    )


def _apply_event(record: TaskRecord, event: TaskEvent) -> TaskRecord:
    now = event.created_at
    record.title = event.title or record.title
    record.run_id = event.run_id
    record.artifact_dir = event.artifact_dir
    _unique_append(record.run_ids, [event.run_id])
    _unique_append(record.artifact_dirs, [event.artifact_dir])
    _unique_append(record.decision_ids, event.decision_ids)
    _unique_append(record.tags, event.tags)
    _unique_append(record.related_files, event.related_files)
    record.decisions = _merge_dicts(record.decisions, event.decisions)
    record.risks = _merge_dicts(record.risks, event.risks)
    record.requirement = event.requirement or record.requirement
    record.summary = event.summary or record.summary
    if event.state == "accepted":
        record.state = "accepted"
        record.accepted_at = now
    elif record.state != "accepted":
        record.state = event.state
    record.updated_at = now
    record.state_history.append(
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "state": event.state,
            "source_stage": event.source_stage,
            "decision": event.decision,
            "run_id": event.run_id,
            "artifact_dir": event.artifact_dir,
            "decision_ids": list(event.decision_ids),
            "message": event.message,
            "created_at": now,
        }
    )
    return record


def append_event(project_root: Path, event: TaskEvent) -> Path:
    event.event_id = event.event_id or f"{event.run_id}:{event.source_stage}:{event.state}:{uuid.uuid4().hex[:8]}"
    path = _events_dir(project_root) / _event_filename(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(path), flags)
    try:
        payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return path


def record_task_event(project_root: Path, event: TaskEvent, *, update_snapshot: bool = True) -> TaskRecord:
    _validate_transition(event)
    event.event_id = event.event_id or f"{event.run_id}:{event.source_stage}:{event.state}:{uuid.uuid4().hex[:8]}"
    with _TaskBoardLock(project_root):
        task_path = _task_path(project_root, event.task_id)
        record = _load_task(task_path) if task_path.exists() else _new_record(event)
        record = _apply_event(record, event)
        _dump_json(task_path, record.model_dump(mode="json"))
        append_event(project_root, event)
        if update_snapshot:
            build_snapshot(project_root, write=True)
        return record


def load_tasks(project_root: Path) -> List[TaskRecord]:
    tasks_path = _tasks_dir(project_root)
    if not tasks_path.exists():
        return []
    tasks = [_load_task(path) for path in sorted(tasks_path.glob("*.json"), key=lambda item: item.name)]
    return tasks


def build_snapshot(project_root: Path, *, write: bool = False) -> Dict[str, Any]:
    tasks = load_tasks(project_root)
    by_state: Dict[str, int] = {}
    for task in tasks:
        by_state[task.state] = by_state.get(task.state, 0) + 1
    snapshot = {
        "schema_version": "1.0",
        "generated_at": utc_now(),
        "summary": {
            "total": len(tasks),
            "by_state": by_state,
        },
        "tasks": [task.model_dump(mode="json") for task in tasks],
    }
    if write:
        _dump_json(_snapshot_path(project_root), snapshot)
    return snapshot


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    tokens = {token for token in re.findall(r"[a-z0-9_]+", lowered) if len(token) >= 2}
    tokens.update(token for token in re.findall(r"[\u4e00-\u9fff]{2,}", text) if len(token) >= 2)
    return tokens


def _task_search_text(task: TaskRecord) -> str:
    decisions_text = " ".join(
        str(item.get("summary") or item.get("decision") or item.get("topic") or item.get("id") or "")
        for item in task.decisions
    )
    risks_text = " ".join(str(item.get("risk") or item.get("impact") or "") for item in task.risks)
    return " ".join([task.id, task.title, task.requirement, task.summary, " ".join(task.tags), decisions_text, risks_text])


def find_related_tasks(
    project_root: Path,
    requirement_text: str,
    *,
    tags: Optional[Sequence[str]] = None,
    related_files: Optional[Sequence[str]] = None,
    decision_ids: Optional[Sequence[str]] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    query_tokens = _tokens(requirement_text)
    query_tags = {str(item).strip() for item in tags or [] if str(item).strip()}
    query_files = {str(item).strip() for item in related_files or [] if str(item).strip()}
    query_decisions = {str(item).strip() for item in decision_ids or [] if str(item).strip()}
    related: List[Dict[str, Any]] = []
    for task in load_tasks(project_root):
        score = 0
        reasons: List[str] = []
        overlap = sorted(query_tokens.intersection(_tokens(_task_search_text(task))))
        if overlap:
            score += min(len(overlap), 6)
            reasons.extend(f"text:{token}" for token in overlap[:5])
        for tag in sorted(query_tags.intersection(task.tags)):
            score += 3
            reasons.append(f"tag:{tag}")
        for file_path in sorted(query_files.intersection(task.related_files)):
            score += 4
            reasons.append(f"file:{file_path}")
        for decision_id in sorted(query_decisions.intersection(task.decision_ids)):
            score += 5
            reasons.append(f"decision:{decision_id}")
        if score <= 0:
            continue
        state_bonus = 2 if task.state == "accepted" else 0
        related.append(
            {
                "task_id": task.id,
                "title": task.title,
                "state": task.state,
                "summary": task.summary,
                "requirement": task.requirement,
                "tags": task.tags,
                "related_files": task.related_files,
                "run_ids": task.run_ids,
                "artifact_dirs": task.artifact_dirs,
                "decision_ids": task.decision_ids,
                "decisions": task.decisions,
                "risks": task.risks,
                "updated_at": task.updated_at,
                "match_score": score + state_bonus,
                "match_reasons": reasons,
            }
        )
    related.sort(key=lambda item: (-item["match_score"], item["state"] != "accepted", item["updated_at"], item["task_id"]))
    return related[: max(limit, 0)]


def render_related_tasks_markdown(related_tasks: Sequence[Dict[str, Any]]) -> str:
    if not related_tasks:
        return ""
    lines = ["## Harness Related Tasks", ""]
    for task in related_tasks:
        lines.append(f"- `{task['task_id']}` [{task['state']}]: {task.get('title') or task.get('summary') or ''}")
        if task.get("match_reasons"):
            lines.append(f"  - Match: {', '.join(task['match_reasons'])}")
        if task.get("decision_ids"):
            lines.append(f"  - Decisions: {', '.join(task['decision_ids'][:5])}")
        if task.get("artifact_dirs"):
            lines.append(f"  - Artifacts: {', '.join(task['artifact_dirs'][:3])}")
    return "\n".join(lines) + "\n"


def related_tasks_for_context(project_root: Path, requirement_text: str, *, limit: int = 5) -> List[Dict[str, Any]]:
    if not requirement_text.strip():
        return []
    try:
        return find_related_tasks(project_root, requirement_text, limit=limit)
    except TaskBoardError:
        return []


def _load_artifact(artifact_dir: Path, name: str) -> Dict[str, Any]:
    path = artifact_dir / name
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _list_dicts(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _list_strings(value: Any) -> List[str]:
    return [str(item) for item in value if str(item).strip()] if isinstance(value, list) else []


def _decision_ids_for_report(report: RunReport, source_stage: str, state: TaskState) -> List[str]:
    ids: List[str] = []
    for index, decision in enumerate(report.human_decisions, start=1):
        if decision.stage_id == source_stage:
            ids.append(f"human:{report.run_id}:{decision.stage_id}:{index}")
    if not ids:
        ids.append(f"run:{report.run_id}:{source_stage}:{state}")
    return ids


def _decision_for_report(report: RunReport, source_stage: str) -> Optional[str]:
    for decision in reversed(report.human_decisions):
        if decision.stage_id == source_stage:
            return decision.decision
    return None


def _task_event_from_report(
    report: RunReport,
    artifact_dir: Path,
    *,
    state: TaskState,
    source_stage: str,
    message: str = "",
) -> TaskEvent:
    requirement = _load_artifact(artifact_dir, "requirement-final.json")
    task_plan = _load_artifact(artifact_dir, "task-plan.json")
    title = str(requirement.get("summary") or task_plan.get("summary") or report.requirement or report.run_id)
    related_files = list(report.changed_files)
    for boundary in _list_dicts(task_plan.get("file_boundaries")):
        related_files.extend(_list_strings(boundary.get("allowed_files")))
    decisions = _list_dicts(requirement.get("decisions"))
    decisions.extend(_list_dicts(requirement.get("related_task_decisions")))
    decisions.extend(_list_dicts(task_plan.get("related_task_decisions")))
    risks = _list_dicts(requirement.get("risks"))
    for risk in _list_strings(task_plan.get("risk_items")):
        risks.append({"risk": risk, "impact": risk})
    tags = sorted(_tokens(" ".join([title, report.requirement])))[:10]
    return TaskEvent(
        task_id=task_id_for_run(report.run_id),
        title=title,
        state=state,
        source_stage=source_stage,
        decision=_decision_for_report(report, source_stage),
        run_id=report.run_id,
        artifact_dir=str(artifact_dir),
        decision_ids=_decision_ids_for_report(report, source_stage, state),
        requirement=report.requirement,
        summary=str(requirement.get("summary") or task_plan.get("summary") or ""),
        tags=tags,
        related_files=related_files,
        decisions=decisions,
        risks=risks,
        message=message,
    )


def record_run_task_event(
    project_root: Path,
    report: RunReport,
    artifact_dir: Path,
    *,
    state: TaskState,
    source_stage: str,
    message: str = "",
) -> TaskRecord:
    event = _task_event_from_report(report, Path(artifact_dir), state=state, source_stage=source_stage, message=message)
    return record_task_event(project_root, event)


def record_run_task_event_from_report_file(
    project_root: Path,
    output_dir: Path,
    *,
    state: TaskState,
    source_stage: str,
    message: str = "",
) -> Optional[TaskRecord]:
    report_file = Path(output_dir) / "report.json"
    if not report_file.exists():
        return None
    report = RunReport.model_validate(_read_json(report_file))
    return record_run_task_event(project_root, report, Path(output_dir), state=state, source_stage=source_stage, message=message)
