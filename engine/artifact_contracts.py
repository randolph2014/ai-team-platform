from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .models import ArtifactValidationRun

COMMON_JSON_REQUIRED = {"status", "summary"}


def _validate_json_artifact(path: Path) -> ArtifactValidationRun:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ArtifactValidationRun(artifact=path.name, status="failed", message=f"invalid json: {exc}")
    if not isinstance(payload, dict):
        return ArtifactValidationRun(artifact=path.name, status="failed", message="json artifact must be an object")
    missing = sorted(COMMON_JSON_REQUIRED - set(payload))
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
            results.append(_validate_json_artifact(path))
        else:
            results.append(ArtifactValidationRun(artifact=str(artifact), status="passed", message="exists"))
    return results


def has_artifact_validation_failure(results: List[ArtifactValidationRun]) -> bool:
    return any(item.status == "failed" for item in results)
