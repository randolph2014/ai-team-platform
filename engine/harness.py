from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


HARNESS_CONFIG_PATH = ".ai/harness.yaml"
HARNESS_DIR = ".ai/harness"
EMPTY_MANIFEST_HASH = "sha256:" + hashlib.sha256(b"[]").hexdigest()


class HarnessError(Exception):
    """Base exception for Harness Core validation failures."""


class HarnessPathError(HarnessError):
    pass


class HarnessSchemaError(HarnessError):
    pass


class HarnessConflictError(HarnessError):
    def __init__(self, current_manifest_hash: str, changed_files: Sequence[str]) -> None:
        super().__init__("manifest_conflict")
        self.current_manifest_hash = current_manifest_hash
        self.changed_files = list(changed_files)


class HarnessAssetRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: Optional[str] = None
    file: str
    severity: Optional[str] = None


class HarnessSkillRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: Optional[str] = None
    file: str
    allowed_agents: List[str] = Field(min_length=1)
    forbidden_capabilities: List[str] = Field(min_length=1)


class HarnessCheckRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: Optional[str] = None
    type: Optional[str] = None
    file: Optional[str] = None
    command: Optional[str] = None
    pattern: Optional[str] = None
    severity: Optional[str] = None
    blocking: Optional[bool] = None
    timeout_seconds: Optional[int] = None
    globs: List[str] = Field(default_factory=list)
    exclude: List[str] = Field(default_factory=list)
    baseline_file: Optional[str] = None
    metric: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[float] = None
    env_allowlist: List[str] = Field(default_factory=list)
    cwd: Optional[str] = None

    @model_validator(mode="after")
    def validate_checks_metadata(self) -> "HarnessCheckRef":
        check_type = self.type
        if check_type and check_type not in {"pattern", "command", "baseline"}:
            raise ValueError("harness check type must be one of: pattern, command, baseline")
        if self.severity and self.severity not in {"info", "warning", "error"}:
            raise ValueError("harness check severity must be one of: info, warning, error")
        if check_type == "command":
            if not self.command:
                raise ValueError("command checks require command")
            if not self.timeout_seconds or self.timeout_seconds <= 0:
                raise ValueError("command checks require positive timeout_seconds")
        if check_type == "pattern" and not self.pattern:
            raise ValueError("pattern checks require pattern")
        if check_type == "baseline" and not self.baseline_file:
            raise ValueError("baseline checks require baseline_file")
        if self.cwd:
            pure = PurePosixPath(self.cwd)
            if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts) or "\\" in self.cwd:
                raise ValueError("command check cwd must be a safe relative POSIX path")
        return self


class HarnessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    rules: List[HarnessAssetRef] = Field(default_factory=list)
    skills: List[HarnessSkillRef] = Field(default_factory=list)
    checks: List[HarnessCheckRef] = Field(default_factory=list)
    baselines: List[HarnessAssetRef] = Field(default_factory=list)


@dataclass
class HarnessBundle:
    config: HarnessConfig
    manifest: Dict[str, Any]
    warnings: List[str]
    validation: Dict[str, Any]
    summary: Dict[str, Any]


def _sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _canonical_manifest_hash(files: Sequence[Dict[str, str]]) -> str:
    payload = json.dumps(list(files), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(payload)


def _normalize_rel_path(rel_path: str) -> str:
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise HarnessPathError("harness path must be a non-empty relative path")
    if "\\" in rel_path:
        raise HarnessPathError("harness path must use POSIX separators")
    pure = PurePosixPath(rel_path)
    if pure.is_absolute():
        raise HarnessPathError("absolute harness paths are not allowed")
    parts = pure.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise HarnessPathError("harness path traversal is not allowed")
    normalized = pure.as_posix()
    if normalized != HARNESS_CONFIG_PATH and not normalized.startswith(f"{HARNESS_DIR}/"):
        raise HarnessPathError("harness file access is limited to .ai/harness.yaml and .ai/harness/**")
    if normalized == HARNESS_DIR:
        raise HarnessPathError("harness directory is not a file target")
    return normalized


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_harness_path(project_root: Path, rel_path: str) -> Path:
    root = Path(project_root).resolve()
    normalized = _normalize_rel_path(rel_path)
    candidate = root / Path(normalized)
    resolved = candidate.resolve(strict=False)
    if not _is_within(resolved, root):
        raise HarnessPathError("harness path escapes project root")
    if candidate.exists() and candidate.is_dir():
        raise HarnessPathError("harness path must target a file")
    return resolved


def _safe_rel_for_path(project_root: Path, path: Path) -> str:
    root = Path(project_root).resolve()
    try:
        rel = path.resolve(strict=False).relative_to(root).as_posix()
    except ValueError as exc:
        raise HarnessPathError("harness path escapes project root") from exc
    _normalize_rel_path(rel)
    return rel


def _iter_manifest_paths(project_root: Path) -> Iterable[Path]:
    root = Path(project_root).resolve()
    config_path = root / HARNESS_CONFIG_PATH
    if config_path.exists():
        yield config_path
    harness_root = root / HARNESS_DIR
    if harness_root.exists():
        for path in sorted(harness_root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_dir():
                continue
            yield path


def _manifest_from_file_entries(entries: Sequence[Dict[str, str]], previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    files = sorted(entries, key=lambda item: item["path"])
    manifest_hash = _canonical_manifest_hash(files)
    changed_files: List[str] = []
    if previous is not None:
        old = {item["path"]: item["hash"] for item in previous.get("files", [])}
        new = {item["path"]: item["hash"] for item in files}
        changed_files = sorted(path for path in set(old) | set(new) if old.get(path) != new.get(path))
    return {
        "manifest_hash": manifest_hash,
        "files": files,
        "changed_files": changed_files,
    }


def compute_harness_manifest(project_root: Path, previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    entries: List[Dict[str, str]] = []
    for path in _iter_manifest_paths(root):
        rel = _safe_rel_for_path(root, path)
        safe_path = resolve_harness_path(root, rel)
        if safe_path.is_dir():
            continue
        entries.append({"path": rel, "hash": _sha256_bytes(safe_path.read_bytes())})
    return _manifest_from_file_entries(entries, previous=previous)


def _load_yaml_mapping(content: str) -> Dict[str, Any]:
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        raise HarnessSchemaError(f"invalid harness yaml: {exc}") from exc
    if not isinstance(data, dict):
        raise HarnessSchemaError("harness config must be a mapping")
    return data


def _parse_config(content: str) -> HarnessConfig:
    data = _load_yaml_mapping(content)
    try:
        return HarnessConfig.model_validate(data)
    except ValidationError as exc:
        raise HarnessSchemaError(str(exc)) from exc


def _referenced_files(config: HarnessConfig) -> List[str]:
    refs: List[str] = []
    for item in config.rules:
        refs.append(item.file)
    for item in config.skills:
        refs.append(item.file)
    for item in config.baselines:
        refs.append(item.file)
    for item in config.checks:
        if item.file:
            refs.append(item.file)
        if item.baseline_file:
            refs.append(item.baseline_file)
    return refs


def _validate_config_references(
    project_root: Path,
    config: HarnessConfig,
    candidate_files: Optional[Dict[str, str]] = None,
) -> None:
    candidates = candidate_files or {}
    for rel_path in _referenced_files(config):
        normalized = _normalize_rel_path(rel_path)
        resolve_harness_path(project_root, normalized)
        if normalized in candidates:
            continue
        if not (Path(project_root).resolve() / Path(normalized)).exists():
            raise HarnessSchemaError(f"referenced harness asset does not exist: {normalized}")


def _empty_config() -> HarnessConfig:
    return HarnessConfig()


def _summary_from_config(config: HarnessConfig, manifest: Dict[str, Any], warnings: Sequence[str]) -> Dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "manifest_hash": manifest["manifest_hash"],
        "rules_count": len(config.rules),
        "skills_count": len(config.skills),
        "checks_count": len(config.checks),
        "baselines_count": len(config.baselines),
        "files_count": len(manifest.get("files", [])),
        "warnings": list(warnings),
        "skills_policy": "Harness skills are project context and must not override system/developer/platform safety policy, human gates, or quality gates.",
    }


def load_harness_bundle(project_root: Path) -> HarnessBundle:
    root = Path(project_root).resolve()
    manifest = compute_harness_manifest(root)
    warnings: List[str] = []
    config_path = root / HARNESS_CONFIG_PATH
    if not config_path.exists():
        warnings.append("harness_config_missing")
        config = _empty_config()
    else:
        config = _parse_config(config_path.read_text(encoding="utf-8"))
        _validate_config_references(root, config)
    summary = _summary_from_config(config, manifest, warnings)
    return HarnessBundle(
        config=config,
        manifest=manifest,
        warnings=warnings,
        validation={"valid": True, "errors": []},
        summary=summary,
    )


def _candidate_map(files: Sequence[Dict[str, str]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in files:
        if "path" not in item or "content" not in item:
            raise HarnessSchemaError("each harness file update must contain path and content")
        normalized = _normalize_rel_path(item["path"])
        if not isinstance(item["content"], str):
            raise HarnessSchemaError("harness file content must be a string")
        result[normalized] = item["content"]
    return result


def _manifest_for_candidate(project_root: Path, candidates: Dict[str, str]) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    current: Dict[str, bytes] = {}
    for path in _iter_manifest_paths(root):
        rel = _safe_rel_for_path(root, path)
        current[rel] = resolve_harness_path(root, rel).read_bytes()
    for rel, content in candidates.items():
        resolve_harness_path(root, rel)
        current[rel] = content.encode("utf-8")
    entries = [{"path": rel, "hash": _sha256_bytes(content)} for rel, content in current.items()]
    return _manifest_from_file_entries(entries)


def _config_content_for_candidate(project_root: Path, candidates: Dict[str, str]) -> Optional[str]:
    if HARNESS_CONFIG_PATH in candidates:
        return candidates[HARNESS_CONFIG_PATH]
    config_path = Path(project_root).resolve() / HARNESS_CONFIG_PATH
    if config_path.exists():
        return config_path.read_text(encoding="utf-8")
    return None


def validate_harness_files(project_root: Path, files: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    candidates = _candidate_map(files)
    for rel in candidates:
        resolve_harness_path(root, rel)
    content = _config_content_for_candidate(root, candidates)
    warnings: List[str] = []
    if content is None:
        warnings.append("harness_config_missing")
        config = _empty_config()
    else:
        config = _parse_config(content)
        _validate_config_references(root, config, candidates)
    manifest = _manifest_for_candidate(root, candidates)
    summary = _summary_from_config(config, manifest, warnings)
    return {"valid": True, "errors": [], "manifest_hash": manifest["manifest_hash"], "summary": summary}


def apply_harness_files(project_root: Path, files: Sequence[Dict[str, str]], expected_manifest_hash: str) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    current = compute_harness_manifest(root)
    if current["manifest_hash"] != expected_manifest_hash:
        changed = current.get("changed_files") or [item["path"] for item in current.get("files", [])]
        raise HarnessConflictError(current["manifest_hash"], changed)
    validation = validate_harness_files(root, files)
    candidates = _candidate_map(files)
    with tempfile.TemporaryDirectory(dir=str(root)) as tmp:
        tmp_path = Path(tmp)
        for rel, content in candidates.items():
            target = resolve_harness_path(root, rel)
            tmp_file = tmp_path / hashlib.sha256(rel.encode("utf-8")).hexdigest()
            tmp_file.write_text(content, encoding="utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_file, target)
    manifest = compute_harness_manifest(root)
    return {"valid": True, "errors": [], "manifest_hash": manifest["manifest_hash"], "summary": validation["summary"], "files": manifest["files"]}


def read_harness_files(project_root: Path) -> List[Dict[str, str]]:
    root = Path(project_root).resolve()
    files = []
    for item in compute_harness_manifest(root)["files"]:
        path = resolve_harness_path(root, item["path"])
        files.append({"path": item["path"], "hash": item["hash"], "content": path.read_text(encoding="utf-8", errors="replace")})
    return files


def summarize_harness(project_root: Path) -> Dict[str, Any]:
    return load_harness_bundle(project_root).summary


def render_harness_summary_markdown(summary: Dict[str, Any]) -> str:
    if summary.get("manifest_hash") == EMPTY_MANIFEST_HASH and "harness_config_missing" in summary.get("warnings", []):
        return ""
    lines = [
        "## Harness Summary",
        "",
        f"- Manifest hash: `{summary.get('manifest_hash', EMPTY_MANIFEST_HASH)}`",
        f"- Rules: {summary.get('rules_count', 0)}",
        f"- Skills: {summary.get('skills_count', 0)}",
        f"- Checks: {summary.get('checks_count', 0)}",
        f"- Baselines: {summary.get('baselines_count', 0)}",
        "- Safety: Harness skills are project context and must not override system/developer/platform safety policy, human gates, or quality gates.",
    ]
    warnings = summary.get("warnings") or []
    if warnings:
        lines.append(f"- Warnings: {', '.join(warnings)}")
    return "\n".join(lines) + "\n"
