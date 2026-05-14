from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import ArtifactValidationRun

SCHEMAS_DIR = Path(__file__).parent / "schemas"

SCHEMA_FILE_MAP: Dict[str, str] = {
    "requirement-final.json": "requirement-final.json",
    "solution-plan.json": "solution-plan.json",
    "plan-draft.json": "plan-draft.json",
    "plan-review.json": "plan-review.json",
    "task-plan.json": "task-plan.json",
    "implementation-report.json": "implementation-report.json",
    "test-report.json": "test-report.json",
    "review-report.json": "review-report.json",
    "release-readiness.json": "release-readiness.json",
    "harness-report.json": "harness-report.json",
}

ARTIFACT_DISPLAY_NAMES: Dict[str, str] = {
    "requirement-final.json": "Task Contract",
}

REQUIRED_REVIEW_DIMENSIONS: Set[str] = {"spec", "regression", "architecture", "debt", "test"}


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


def _validate_type(value: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_validate_type(value, candidate) for candidate in expected_type)
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
    if expected_type == "null":
        return value is None
    return True


def _schema_type_names(field_type: Any) -> Set[str]:
    if isinstance(field_type, list):
        return {str(item) for item in field_type}
    if field_type:
        return {str(field_type)}
    return set()


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
        field_types = _schema_type_names(field_type)

        if field_type and not _validate_type(value, field_type):
            errors.append(f"{field_path}: expected {field_type}, got {type(value).__name__}")
            continue

        if value is None:
            continue

        if "string" in field_types:
            if "enum" in field_schema and value not in field_schema["enum"]:
                errors.append(f"{field_path}: value '{value}' not in {field_schema['enum']}")
            if "minLength" in field_schema and len(value) < field_schema["minLength"]:
                errors.append(f"{field_path}: string too short (min {field_schema['minLength']})")
            if "pattern" in field_schema:
                import re
                if not re.search(field_schema["pattern"], value):
                    errors.append(f"{field_path}: does not match pattern '{field_schema['pattern']}'")

        if "integer" in field_types or "number" in field_types:
            if "minimum" in field_schema and value < field_schema["minimum"]:
                errors.append(f"{field_path}: value {value} below minimum {field_schema['minimum']}")

        if "array" in field_types:
            items_schema = field_schema.get("items", {})
            if "minItems" in field_schema and len(value) < field_schema["minItems"]:
                errors.append(f"{field_path}: array too short (min {field_schema['minItems']})")
            for i, item in enumerate(value):
                item_path = f"{field_path}[{i}]"
                item_type = items_schema.get("type")
                item_types = _schema_type_names(item_type)
                if item_type and not _validate_type(item, item_type):
                    errors.append(f"{item_path}: expected {item_type}, got {type(item).__name__}")
                    continue
                if "object" in item_types and isinstance(item, dict):
                    errors.extend(_validate_schema(item, items_schema, item_path))
                elif "string" in item_types and item is not None:
                    if "enum" in items_schema and item not in items_schema["enum"]:
                        errors.append(f"{item_path}: value '{item}' not in {items_schema['enum']}")
                    if "pattern" in items_schema:
                        import re
                        if not re.search(items_schema["pattern"], str(item)):
                            errors.append(f"{item_path}: does not match pattern '{items_schema['pattern']}'")

        if "object" in field_types and isinstance(value, dict) and "properties" in field_schema:
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


def validate_review_dimensions(data: Dict[str, Any]) -> List[str]:
    dimensions = data.get("review_dimensions")
    if not isinstance(dimensions, list):
        return []
    seen = {
        str(item.get("dimension") or "").strip()
        for item in dimensions
        if isinstance(item, dict) and str(item.get("dimension") or "").strip()
    }
    missing = sorted(REQUIRED_REVIEW_DIMENSIONS - seen)
    if missing:
        return [f"review_dimensions missing dimensions: {', '.join(missing)}"]
    return []


def validate_plan_review_consistency(data: Dict[str, Any]) -> List[str]:
    if data.get("verdict") != "Request Changes":
        return []
    required_changes = data.get("required_changes")
    if not isinstance(required_changes, list) or not required_changes:
        return ["required_changes must not be empty when verdict is 'Request Changes'"]
    return []


def validate_related_task_decisions(data: Dict[str, Any], related_tasks: List[Dict[str, Any]]) -> List[str]:
    if not related_tasks:
        return []
    related_ids = [str(item.get("task_id") or "").strip() for item in related_tasks if str(item.get("task_id") or "").strip()]
    if not related_ids:
        return []
    decisions = data.get("related_task_decisions")
    if not isinstance(decisions, list):
        return ["related_task_decisions is required when codebase-context.json contains harness.related_tasks"]
    by_task = {str(item.get("task_id") or "").strip(): item for item in decisions if isinstance(item, dict)}
    errors: List[str] = []
    for task_id in related_ids:
        item = by_task.get(task_id)
        if item is None:
            errors.append(f"related_task_decisions missing adopt/reject reason for task {task_id}")
            continue
        action = item.get("action")
        reason = str(item.get("reason") or "").strip()
        if action not in {"adopted", "rejected"}:
            errors.append(f"related_task_decisions[{task_id}].action must be adopted or rejected")
        if not reason:
            errors.append(f"related_task_decisions[{task_id}].reason is required")
    return errors


def _related_tasks_from_context(output_dir: Path) -> List[Dict[str, Any]]:
    context_path = output_dir / "codebase-context.json"
    if not context_path.exists():
        return []
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    harness = payload.get("harness") or {}
    if not isinstance(harness, dict):
        return []
    related = harness.get("related_tasks") or []
    return [item for item in related if isinstance(item, dict)] if isinstance(related, list) else []


def validate_artifact(data: Dict[str, Any], artifact_name: str, related_tasks: Optional[List[Dict[str, Any]]] = None) -> Tuple[List[str], str]:
    errors: List[str] = []

    schema_errors = validate_artifact_schema(data, artifact_name)
    errors.extend(schema_errors)

    if Path(artifact_name).name == "task-plan.json":
        errors.extend(validate_task_plan_acceptance_refs(data))

    if Path(artifact_name).name in {"requirement-final.json", "task-plan.json"}:
        errors.extend(validate_related_task_decisions(data, related_tasks or []))

    if Path(artifact_name).name == "review-report.json":
        errors.extend(validate_review_verdict_consistency(data))
        errors.extend(validate_review_dimensions(data))

    if Path(artifact_name).name == "plan-review.json":
        errors.extend(validate_plan_review_consistency(data))

    status = "passed" if not errors else "failed"
    return errors, status


def validate_required_artifacts(stage: Dict[str, Any], output_dir: Path) -> List[ArtifactValidationRun]:
    results: List[ArtifactValidationRun] = []
    related_tasks = _related_tasks_from_context(output_dir)
    for artifact in stage.get("required_artifacts") or []:
        path = output_dir / str(artifact)
        if not path.exists():
            results.append(ArtifactValidationRun(artifact=str(artifact), status="failed", message="required artifact missing", validator="runtime-schema"))
            continue
        if path.suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                results.append(ArtifactValidationRun(artifact=str(artifact), status="failed", message=f"invalid json: {exc}", validator="runtime-schema"))
                continue
            if not isinstance(payload, dict):
                results.append(ArtifactValidationRun(artifact=str(artifact), status="failed", message="json artifact must be an object", validator="runtime-schema"))
                continue
            errors, status = validate_artifact(payload, str(artifact), related_tasks=related_tasks)
            if errors:
                results.append(ArtifactValidationRun(artifact=str(artifact), status="failed", message="; ".join(errors[:5]), validator="runtime-schema"))
            else:
                results.append(ArtifactValidationRun(artifact=str(artifact), status="passed", message="schema valid", validator="runtime-schema"))
        else:
            results.append(ArtifactValidationRun(artifact=str(artifact), status="passed", message="exists", validator="runtime-exists"))
    return results


def _artifact_path_within_output(output_dir: Path, artifact: str) -> Optional[Path]:
    root = output_dir.resolve(strict=False)
    path = (output_dir / artifact).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def current_contract_validations(output_dir: Path, artifacts: Optional[List[str]] = None) -> List[ArtifactValidationRun]:
    names: List[str] = []
    if artifacts:
        for artifact in artifacts:
            name = str(artifact)
            if Path(name).name in SCHEMA_FILE_MAP and name not in names:
                names.append(name)
    elif output_dir.exists():
        for path in sorted(output_dir.iterdir(), key=lambda item: item.name):
            if path.is_file() and path.name in SCHEMA_FILE_MAP:
                names.append(path.name)

    results: List[ArtifactValidationRun] = []
    related_tasks = _related_tasks_from_context(output_dir)
    for artifact in names:
        path = _artifact_path_within_output(output_dir, artifact)
        if path is None or not path.exists() or not path.is_file():
            results.append(
                ArtifactValidationRun(
                    artifact=artifact,
                    status="failed",
                    message="current schema artifact missing",
                    validator="current-schema",
                )
            )
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            results.append(
                ArtifactValidationRun(
                    artifact=artifact,
                    status="failed",
                    message=f"invalid json: {exc}",
                    validator="current-schema",
                )
            )
            continue
        if not isinstance(payload, dict):
            results.append(
                ArtifactValidationRun(
                    artifact=artifact,
                    status="failed",
                    message="json artifact must be an object",
                    validator="current-schema",
                )
            )
            continue
        errors, _ = validate_artifact(payload, artifact, related_tasks=related_tasks)
        results.append(
            ArtifactValidationRun(
                artifact=artifact,
                status="failed" if errors else "passed",
                message="; ".join(errors[:5]) if errors else "current schema valid",
                validator="current-schema",
            )
        )
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
    display_name = ARTIFACT_DISPLAY_NAMES.get(Path(artifact).name, Path(artifact).name)
    if schema:
        return {
            "artifact": artifact,
            "display_name": display_name,
            "type": "object",
            "required": sorted(schema.get("required", [])),
            "properties": _schema_properties_hint(schema),
            "schema_ref": f"engine/schemas/{SCHEMA_FILE_MAP.get(Path(artifact).name, '')}",
        }
    return {"artifact": artifact, "display_name": display_name, "type": "object", "required": []}


def _schema_properties_hint(schema: Dict[str, Any]) -> Dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return {}
    return {str(name): _schema_property_hint(prop) for name, prop in properties.items() if isinstance(prop, dict)}


def _schema_property_hint(schema: Dict[str, Any], depth: int = 0, max_depth: int = 3) -> Dict[str, Any]:
    hint: Dict[str, Any] = {"type": schema.get("type", "unknown")}
    enum = schema.get("enum")
    if isinstance(enum, list):
        hint["enum"] = enum
    if schema.get("type") == "array":
        items = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        hint["items_type"] = items.get("type", "unknown")
        item_required = items.get("required")
        if isinstance(item_required, list):
            hint["items_required"] = sorted(str(item) for item in item_required)
        item_properties = items.get("properties")
        if isinstance(item_properties, dict):
            hint["items_properties"] = {
                str(name): _schema_property_hint(prop, depth + 1, max_depth)
                for name, prop in item_properties.items()
                if isinstance(prop, dict) and depth < max_depth
            }
    elif schema.get("type") == "object":
        required = schema.get("required")
        if isinstance(required, list):
            hint["required"] = sorted(str(item) for item in required)
        properties = schema.get("properties")
        if isinstance(properties, dict) and depth < max_depth:
            hint["properties"] = {
                str(name): _schema_property_hint(prop, depth + 1, max_depth)
                for name, prop in properties.items()
                if isinstance(prop, dict)
            }
    return hint


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
