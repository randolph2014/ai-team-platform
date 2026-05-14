from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from engine.models import RunReport


def _check_stage_gates(report: RunReport) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    failures = []
    missing_evidence = []
    for stage in report.stages:
        if stage.stage_id == "develop" and stage.status == "completed" and not stage.quality_gates:
            missing_evidence.append({
                "stage_id": stage.stage_id,
                "status": stage.status,
            })
        for gate in stage.quality_gates:
            if gate.required and gate.status == "failed":
                failures.append({
                    "stage_id": stage.stage_id,
                    "gate_name": gate.name,
                    "status": gate.status,
                })
    return failures, missing_evidence


def _check_human_approvals(report: RunReport) -> List[Dict[str, str]]:
    missing = []
    decisions_by_stage = {decision.stage_id: decision for decision in report.human_decisions}
    for stage in report.stages:
        if stage.type == "human_review":
            decision = stage.human_decision or decisions_by_stage.get(stage.stage_id)
            if decision is None or decision.decision != "approved":
                missing.append({
                    "stage_id": stage.stage_id,
                    "decision": decision.decision if decision else "pending",
                })
    return missing


def _check_artifacts(report: RunReport, output_dir: Path) -> List[Dict[str, str]]:
    missing = []
    for artifact_name in report.artifacts:
        artifact_path = output_dir / artifact_name
        if not artifact_path.exists():
            missing.append({"artifact": artifact_name})
    return missing


def _check_status(name: str, passed: bool, message: str) -> Dict[str, str]:
    return {
        "name": name,
        "status": "passed" if passed else "failed",
        "source_artifact": "report.json",
        "message": message,
    }


def _blocking_issue(source: str, issue: str, severity: str = "Critical") -> Dict[str, str]:
    return {"source": source, "issue": issue, "severity": severity}


def generate_release_readiness(report: RunReport, output_dir: Path) -> Dict[str, Any]:
    gate_failures, missing_gate_evidence = _check_stage_gates(report)
    missing_approvals = _check_human_approvals(report)
    missing_artifacts = _check_artifacts(report, output_dir)
    run_completed = report.status == "completed"

    ready = (
        run_completed
        and len(gate_failures) == 0
        and len(missing_gate_evidence) == 0
        and len(missing_approvals) == 0
        and len(missing_artifacts) == 0
    )

    checks = [
        _check_status(
            "run_status",
            run_completed,
            f"run status is {report.status}",
        ),
        _check_status(
            "quality_gates",
            len(gate_failures) == 0 and len(missing_gate_evidence) == 0,
            (
                f"{len(gate_failures)} required quality gate failure(s), "
                f"{len(missing_gate_evidence)} missing quality gate evidence item(s)"
            ),
        ),
        _check_status(
            "human_approvals",
            len(missing_approvals) == 0,
            f"{len(missing_approvals)} human approval(s) missing",
        ),
        _check_status(
            "artifacts",
            len(missing_artifacts) == 0,
            f"{len(missing_artifacts)} artifact(s) missing",
        ),
    ]

    blocking_issues: List[Dict[str, str]] = []
    if not run_completed:
        blocking_issues.append(_blocking_issue("report.json", f"run status is {report.status}"))
    for failure in gate_failures:
        blocking_issues.append(
            _blocking_issue(
                "report.json",
                f"quality gate {failure['gate_name']} failed in stage {failure['stage_id']}",
            )
        )
    for missing in missing_gate_evidence:
        blocking_issues.append(
            _blocking_issue(
                "report.json",
                f"quality gate evidence is missing for completed stage {missing['stage_id']}",
            )
        )
    for approval in missing_approvals:
        blocking_issues.append(
            _blocking_issue(
                "report.json",
                f"human review {approval['stage_id']} is {approval['decision']}",
            )
        )
    for artifact in missing_artifacts:
        blocking_issues.append(_blocking_issue("report.json", f"artifact {artifact['artifact']} is missing"))

    if ready:
        status = "completed"
    elif report.status == "failed" or gate_failures or missing_gate_evidence or missing_artifacts:
        status = "failed"
    else:
        status = "partial"

    readiness: Dict[str, Any] = {
        "status": status,
        "verdict": "Ready" if ready else "Not Ready",
        "summary": (
            f"Release readiness for {report.run_id}: "
            f"{'ready' if ready else 'not ready'}; "
            f"{sum(1 for s in report.stages if s.status == 'completed')}/{len(report.stages)} stages completed."
        ),
        "checks": checks,
    }
    if blocking_issues:
        readiness["blocking_issues"] = blocking_issues

    readiness_path = output_dir / "release-readiness.json"
    readiness_path.parent.mkdir(parents=True, exist_ok=True)
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return readiness
