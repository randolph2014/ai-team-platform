from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import ArtifactValidationRun

SCHEMAS_DIR = Path(__file__).parent / "schemas"

SCHEMA_FILE_MAP: Dict[str, str] = {
    "requirement-final.json": "requirement-final.json",
    "task-plan.json": "task-plan.json",
    "test-report.json": "test-report.json",
    "review-report.json": "review-report.json",
    "release-readiness.json": "release-readiness.json",
    "harness-report.json": "harness-report.json",
}


class SchemaValidationError(Exception):
    def __init__(self, artifact: str, errors: List[str]) -> None:
        self.artifact = artifact
        self.errors = errors
        super().__init__(f"Schema validation failed for {artifact}: {'; '.join(errors)}")


def _load_schema(schema_name: str) -> Dict[str, Any]:
    path = SCHEMAS_DIR / schema_name
    if not path.exists():
        raise FileNotFoundError(f"Schema file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True


def _validate_schema(data: Any, schema: Dict[str, Any], path_prefix: str = "$") -> List[str]:
    errors: List[str] = []

    if not isinstance(data, dict):
        return [f"{path_prefix}: expected object, got {type(data).__name__}"]

    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])
    additional_properties = schema.get("additionalProperties", True)

    for field in required_fields:
        if field not in data:
            errors.append(f"{path_prefix}.{field}: required field missing")

    for field_name, field_schema in properties.items():
        if field_name not in data:
            continue
        value = data[field_name]
        field_path = f"{path_prefix}.{field_name}"
        field_type = field_schema.get("type")

        if field_type and not _validate_type(value, field_type):
            errors.append(f"{field_path}: expected {field_type}, got {type(value).__name__}")
            continue

        if field_type == "string":
            if "enum" in field_schema and value not in field_schema["enum"]:
                errors.append(f"{field_path}: value '{value}' not in {field_schema['enum']}")
            if "minLength" in field_schema and len(value) < field_schema["minLength"]:
                errors.append(f"{field_path}: string too short (min {field_schema['minLength']})")
            if "pattern" in field_schema:
                import re
                if not re.search(field_schema["pattern"], value):
                    errors.append(f"{field_path}: does not match pattern '{field_schema['pattern']}'")

        if field_type == "integer" or field_type == "number":
            if "minimum" in field_schema and value < field_schema["minimum"]:
                errors.append(f"{field_path}: value {value} below minimum {field_schema['minimum']}")

        if field_type == "array":
            items_schema = field_schema.get("items", {})
            if "minItems" in field_schema and len(value) < field_schema["minItems"]:
                errors.append(f"{field_path}: array too short (min {field_schema['minItems']})")
            for i, item in enumerate(value):
                item_path = f"{field_path}[{i}]"
                item_type = items_schema.get("type")
                if item_type and not _validate_type(item, item_type):
                    errors.append(f"{item_path}: expected {item_type}, got {type(item).__name__}")
                    continue
                if item_type == "object" and isinstance(item, dict):
                    errors.extend(_validate_schema(item, items_schema, item_path))
                elif item_type == "string":
                    if "enum" in items_schema and item not in items_schema["enum"]:
                        errors.append(f"{item_path}: value '{item}' not in {items_schema['enum']}")
                    if "pattern" in items_schema:
                        import re
                        if not re.search(items_schema["pattern"], str(item)):
                            errors.append(f"{item_path}: does not match pattern '{items_schema['pattern']}'")

        if field_type == "object" and isinstance(value, dict) and "properties" in field_schema:
            errors.extend(_validate_schema(value, field_schema, field_path))

    if additional_properties is False:
        allowed = set(properties.keys())
        for key in data:
            if key not in allowed:
                errors.append(f"{path_prefix}.{key}: additional property not allowed")

    return errors


def load_schema_for_artifact(artifact_name: str) -> Optional[Dict[str, Any]]:
    schema_file = SCHEMA_FILE_MAP.get(Path(artifact_name).name)
    if not schema_file:
        return None
    try:
        return _load_schema(schema_file)
    except FileNotFoundError:
        return None


def validate_artifact_schema(data: Dict[str, Any], artifact_name: str) -> List[str]:
    schema = load_schema_for_artifact(artifact_name)
    if not schema:
        return []
    return _validate_schema(data, schema)


def validate_task_plan_acceptance_refs(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    tasks = data.get("tasks", [])
    for task in tasks:
        refs = task.get("acceptance_criteria_refs", [])
        if not refs:
            errors.append(f"task '{task.get('id', '?')}': acceptance_criteria_refs is empty")
        for ref in refs:
            if not str(ref).startswith("AC-"):
                errors.append(f"task '{task.get('id', '?')}': acceptance_criteria_ref '{ref}' does not match AC-xxx pattern")
    return errors


def validate_review_verdict_consistency(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    verdict = data.get("verdict")
    blocking = data.get("blocking_findings", [])
    if verdict == "Approve" and len(blocking) > 0:
        errors.append("verdict is 'Approve' but blocking_findings is not empty")
    if verdict == "Request Changes" and len(blocking) == 0:
        critical_in_findings = [f for f in data.get("findings", []) if f.get("severity") == "Critical"]
        if not critical_in_findings:
            errors.append("verdict is 'Request Changes' but no blocking_findings or Critical findings")
    return errors


def validate_artifact(data: Dict[str, Any], artifact_name: str) -> Tuple[List[str], str]:
    errors: List[str] = []

    schema_errors = validate_artifact_schema(data, artifact_name)
    errors.extend(schema_errors)

    if Path(artifact_name).name == "task-plan.json":
        errors.extend(validate_task_plan_acceptance_refs(data))

    if Path(artifact_name).name == "review-report.json":
        errors.extend(validate_review_verdict_consistency(data))

    status = "passed" if not errors else "failed"
    return errors, status


def validate_required_artifacts(stage: Dict[str, Any], output_dir: Path) -> List[ArtifactValidationRun]:
    results: List[ArtifactValidationRun] = []
    for artifact in stage.get("required_artifacts") or []:
        path = output_dir / str(artifact)
        if not path.exists():
            results.append(ArtifactValidationRun(artifact=str(artifact), status="failed", message="required artifact missing"))
            continue
        if path.suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                results.append(ArtifactValidationRun(artifact=str(artifact), status="failed", message=f"invalid json: {exc}"))
                continue
            if not isinstance(payload, dict):
                results.append(ArtifactValidationRun(artifact=str(artifact), status="failed", message="json artifact must be an object"))
                continue
            errors, status = validate_artifact(payload, str(artifact))
            if errors:
                results.append(ArtifactValidationRun(artifact=str(artifact), status="failed", message="; ".join(errors[:5])))
            else:
                results.append(ArtifactValidationRun(artifact=str(artifact), status="passed", message="schema valid"))
        else:
            results.append(ArtifactValidationRun(artifact=str(artifact), status="passed", message="exists"))
    return results


def has_artifact_validation_failure(results: List[ArtifactValidationRun]) -> bool:
    return any(item.status == "failed" for item in results)


def stage_schema_hint(stage: Dict[str, Any]) -> Dict[str, Any]:
    names: List[str] = []
    for key in ("json_artifacts", "required_artifacts"):
        for item in stage.get(key) or []:
            name = str(item)
            if name.endswith(".json") and name not in names:
                names.append(name)
    return {"artifacts": [artifact_schema_hint_for(name) for name in names]}


def artifact_schema_hint_for(artifact: str) -> Dict[str, Any]:
    schema = load_schema_for_artifact(artifact)
    if schema:
        return {
            "artifact": artifact,
            "type": "object",
            "required": sorted(schema.get("required", [])),
            "schema_ref": f"engine/schemas/{SCHEMA_FILE_MAP.get(Path(artifact).name, '')}",
        }
    return {"artifact": artifact, "type": "object", "required": []}


def validate_requirement_for_planning(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    criteria = data.get("acceptance_criteria", [])
    if not criteria:
        errors.append("acceptance_criteria is empty: cannot enter planning without acceptance criteria")
    return errors


def validate_review_for_loopback(data: Dict[str, Any]) -> bool:
    if data.get("verdict") == "Request Changes":
        return True
    blocking = data.get("blocking_findings", [])
    if any(f.get("severity") == "Critical" for f in blocking):
        return True
    return False
