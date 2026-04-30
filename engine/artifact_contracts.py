from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set

from .models import ArtifactValidationRun

COMMON_JSON_REQUIRED = {"status", "summary"}

ARTIFACT_REQUIRED_FIELDS: Dict[str, Set[str]] = {
    "codebase-context.json": {"project_root", "project_types", "tree"},
    "requirement-final.json": {
        "status",
        "summary",
        "inputs_used",
        "decisions",
        "open_questions",
        "risks",
        "acceptance_coverage",
        "evidence",
        "next_stage_contract",
    },
    "solution-plan.json": {
        "status",
        "summary",
        "decisions",
        "alternatives_considered",
        "impact_scope",
        "configuration_strategy",
        "risks",
        "rollback_strategy",
        "verification_strategy",
        "evidence",
        "next_stage_contract",
    },
    "task-plan.json": {
        "status",
        "summary",
        "tasks",
        "execution_order",
        "file_boundaries",
        "test_plan",
        "rollback_considerations",
        "acceptance_coverage",
        "evidence",
        "next_stage_contract",
    },
    "implementation-report.json": {
        "status",
        "summary",
        "changed_files",
        "tests_run",
        "acceptance_coverage",
        "evidence",
        "risks",
    },
    "test-report.json": {"status", "summary", "commands", "results", "acceptance_coverage", "evidence"},
    "review-report.json": {"status", "summary", "verdict", "findings", "evidence", "risks"},
    "retrospect-report.json": {"status", "summary", "completion", "changes", "quality", "remaining_issues", "evidence"},
}


def required_fields_for_artifact(artifact: str) -> Set[str]:
    return set(ARTIFACT_REQUIRED_FIELDS.get(Path(artifact).name, COMMON_JSON_REQUIRED))


def artifact_schema(artifact: str) -> Dict[str, Any]:
    return {
        "artifact": artifact,
        "type": "object",
        "required": sorted(required_fields_for_artifact(artifact)),
    }


def stage_schema_hint(stage: Dict[str, Any]) -> Dict[str, Any]:
    names: List[str] = []
    for key in ("json_artifacts", "required_artifacts"):
        for item in stage.get(key) or []:
            name = str(item)
            if name.endswith(".json") and name not in names:
                names.append(name)
    return {"artifacts": [artifact_schema(name) for name in names]}


def _validate_json_artifact(path: Path, required_fields: Set[str]) -> ArtifactValidationRun:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ArtifactValidationRun(artifact=path.name, status="failed", message=f"invalid json: {exc}")
    if not isinstance(payload, dict):
        return ArtifactValidationRun(artifact=path.name, status="failed", message="json artifact must be an object")
    missing = sorted(required_fields - set(payload))
    if missing:
        return ArtifactValidationRun(artifact=path.name, status="failed", message=f"missing required fields: {', '.join(missing)}")
    return ArtifactValidationRun(artifact=path.name, status="passed", message="ok")


def validate_required_artifacts(stage: Dict[str, Any], output_dir: Path) -> List[ArtifactValidationRun]:
    results: List[ArtifactValidationRun] = []
    for artifact in stage.get("required_artifacts") or []:
        path = output_dir / str(artifact)
        if not path.exists():
            results.append(ArtifactValidationRun(artifact=str(artifact), status="failed", message="required artifact missing"))
            continue
        if path.suffix == ".json":
            results.append(_validate_json_artifact(path, required_fields_for_artifact(str(artifact))))
        else:
            results.append(ArtifactValidationRun(artifact=str(artifact), status="passed", message="exists"))
    return results


def has_artifact_validation_failure(results: List[ArtifactValidationRun]) -> bool:
    return any(item.status == "failed" for item in results)
