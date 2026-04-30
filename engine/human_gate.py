from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .models import HumanDecision, utc_now


HARD_HUMAN_GATES = {"requirement_confirm", "task_plan_confirm", "acceptance_confirm"}


def is_hard_human_gate(stage: Dict[str, Any]) -> bool:
    return stage.get("type") == "human_review" and stage.get("id") in HARD_HUMAN_GATES


def decision_json_name(stage: Dict[str, Any]) -> str:
    return str(stage.get("decision_file") or f"human-decision-{stage.get('id', 'gate')}.json")


def decision_markdown_name(stage: Dict[str, Any]) -> str:
    return str(stage.get("output_file") or f"human-decision-{stage.get('id', 'gate')}.md")


def waiting_decision(stage: Dict[str, Any]) -> HumanDecision:
    return HumanDecision(
        stage_id=str(stage.get("id")),
        decision="waiting",
        target_stage=stage.get("reject_to"),
        decided_by="system",
        decided_at=utc_now(),
    )


def normalize_decision(stage: Dict[str, Any], decision: HumanDecision) -> HumanDecision:
    stage_id = str(stage.get("id"))
    if decision.stage_id != stage_id:
        raise ValueError(f"decision stage_id {decision.stage_id} does not match waiting stage {stage_id}")
    requires_reason = bool(stage.get("requires_reason_on_reject", True))
    decision.validate_for_stage(requires_reason_on_reject=requires_reason)
    if decision.decision == "rejected":
        configured_target = stage.get("reject_to")
        if configured_target and decision.target_stage and decision.target_stage != configured_target:
            raise ValueError(
                f"target_stage {decision.target_stage} does not match configured reject_to {configured_target} for stage {stage_id}"
            )
        target = decision.target_stage or configured_target
        if not target:
            raise ValueError(f"reject target is required for stage {stage_id}")
        return _copy_decision(decision, target_stage=str(target))
    return _copy_decision(decision)


def _copy_decision(decision: HumanDecision, **updates: Any) -> HumanDecision:
    if hasattr(decision, "model_copy"):
        return decision.model_copy(deep=True, update=updates)
    return decision.copy(deep=True, update=updates)


def _numbered_name(name: str, index: int) -> str:
    path = Path(name)
    return str(path.with_name(f"{path.stem}-{index}{path.suffix}"))


def write_decision_artifacts(
    stage: Dict[str, Any],
    output_dir: Path,
    decision: HumanDecision,
    history_index: int | None = None,
) -> None:
    payload = decision.model_dump(mode="json")
    json_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    json_names = [decision_json_name(stage)]
    if history_index is not None:
        json_names.append(_numbered_name(decision_json_name(stage), history_index))
    for json_name in json_names:
        (output_dir / json_name).write_text(json_payload, encoding="utf-8")

    lines = [
        "## Human Decision",
        "",
        f"- Stage: `{decision.stage_id}`",
        f"- Decision: `{decision.decision}`",
        f"- Decided by: `{decision.decided_by}`",
        f"- Decided at: `{decision.decided_at}`",
    ]
    if decision.reason:
        lines.extend(["", "## Reason", "", decision.reason.strip()])
    if decision.required_changes:
        lines.extend(["", "## Required Changes"])
        lines.extend([f"- {item}" for item in decision.required_changes])
    if decision.target_stage:
        lines.extend(["", f"Loopback target: `{decision.target_stage}`"])
    markdown_payload = "\n".join(lines).rstrip() + "\n"
    markdown_names = [decision_markdown_name(stage)]
    if history_index is not None:
        markdown_names.append(_numbered_name(decision_markdown_name(stage), history_index))
    for markdown_name in markdown_names:
        (output_dir / markdown_name).write_text(markdown_payload, encoding="utf-8")


def render_reject_feedback(decision: HumanDecision, retry_count: int) -> str:
    changes = "\n".join(f"- {item}" for item in decision.required_changes) or "- 未提供逐条修改项"
    return "\n".join(
        [
            f"## 人工拒绝反馈（第 {retry_count} 次）",
            "",
            f"Gate `{decision.stage_id}` 被人工拒绝。",
            "",
            "### 拒绝理由",
            decision.reason.strip(),
            "",
            "### 必须修改",
            changes,
            "",
            "只围绕以上人工拒绝理由修正，不扩大范围。不得重写已确认且未被拒绝的内容。",
        ]
    )
