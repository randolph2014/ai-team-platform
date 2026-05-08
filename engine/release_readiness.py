from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.models import RunReport


def _check_stage_gates(report: RunReport) -> List[Dict[str, str]]:
    failures = []
    for stage in report.stages:
        for gate in stage.quality_gates:
            if gate.required and gate.status == "failed":
                failures.append({
                    "stage_id": stage.stage_id,
                    "gate_name": gate.name,
                    "status": gate.status,
                })
    return failures


def _check_human_approvals(report: RunReport) -> List[Dict[str, str]]:
    missing = []
    for stage in report.stages:
        if stage.type == "human_review":
            if stage.human_decision is None or stage.human_decision.decision != "approved":
                missing.append({
                    "stage_id": stage.stage_id,
                    "decision": stage.human_decision.decision if stage.human_decision else "pending",
                })
    return missing


def _check_artifacts(report: RunReport, output_dir: Path) -> List[Dict[str, str]]:
    missing = []
    for artifact_name in report.artifacts:
        artifact_path = output_dir / artifact_name
        if not artifact_path.exists():
            missing.append({"artifact": artifact_name})
    return missing


def generate_release_readiness(report: RunReport, output_dir: Path) -> Dict[str, Any]:
    gate_failures = _check_stage_gates(report)
    missing_approvals = _check_human_approvals(report)
    missing_artifacts = _check_artifacts(report, output_dir)

    ready = (
        report.status == "completed"
        and len(gate_failures) == 0
        and len(missing_approvals) == 0
        and len(missing_artifacts) == 0
    )

    readiness: Dict[str, Any] = {
        "run_id": report.run_id,
        "ready": ready,
        "run_status": report.status,
        "checks": {
            "quality_gates": {
                "passed": len(gate_failures) == 0,
                "failures": gate_failures,
            },
            "human_approvals": {
                "passed": len(missing_approvals) == 0,
                "missing": missing_approvals,
            },
            "artifacts": {
                "passed": len(missing_artifacts) == 0,
                "missing": missing_artifacts,
            },
        },
        "duration_seconds": report.duration_seconds,
        "stages_completed": sum(1 for s in report.stages if s.status == "completed"),
        "stages_total": len(report.stages),
    }

    readiness_path = output_dir / "release-readiness.json"
    readiness_path.parent.mkdir(parents=True, exist_ok=True)
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return readiness
