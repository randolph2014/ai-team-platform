from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from engine.config import (
    DEFAULT_CONFIG,
    DEFAULT_TEAM_FILE,
    ConfigError,
    _read_yaml,
    find_project_root,
    load_config,
    normalize_config,
)

try:
    from fastapi import APIRouter, HTTPException, Query
    from pydantic import BaseModel, ConfigDict
except ImportError:  # pragma: no cover
    APIRouter = None
    BaseModel = object
    ConfigDict = dict

router = APIRouter() if APIRouter else None

SENSITIVE_KEY_PATTERNS: List[re.Pattern] = [
    re.compile(r"(api[_-]?key|apikey)", re.IGNORECASE),
    re.compile(r"(secret|token|password|passwd|credential)", re.IGNORECASE),
    re.compile(r"(auth[_-]?token|access[_-]?token)", re.IGNORECASE),
    re.compile(r"(jwt[_-]?secret|signing[_-]?key)", re.IGNORECASE),
]

MASK = "***"


def _is_sensitive_key(key: str) -> bool:
    return any(pattern.search(key) for pattern in SENSITIVE_KEY_PATTERNS)


def _mask_sensitive(value: Any, depth: int = 0) -> Any:
    """递归脱敏：对 dict 中匹配敏感 key 模式的值替换为 ***。"""
    if depth > 10:
        return value
    if isinstance(value, dict):
        masked = {}
        for k, v in value.items():
            if isinstance(v, str) and len(v) > 0 and _is_sensitive_key(k):
                masked[k] = MASK
            else:
                masked[k] = _mask_sensitive(v, depth + 1)
        return masked
    if isinstance(value, list):
        return [_mask_sensitive(item, depth + 1) for item in value]
    return value


def _merge_runtime_updates(existing: Any, updates: Any) -> Any:
    if not isinstance(existing, dict) or not isinstance(updates, dict):
        return updates

    merged: Dict[str, Any] = {}
    for runtime_id, runtime_update in updates.items():
        existing_runtime = existing.get(runtime_id)
        merged[runtime_id] = _merge_preserving_masks(existing_runtime, runtime_update)
    return merged


def _merge_preserving_masks(existing: Any, updates: Any) -> Any:
    if isinstance(existing, dict) and isinstance(updates, dict):
        merged = dict(existing)
        for key, value in updates.items():
            if isinstance(value, str) and value == MASK and _is_sensitive_key(key):
                if key in existing:
                    continue
                merged.pop(key, None)
                continue
            merged[key] = _merge_preserving_masks(existing.get(key), value)
        return merged
    return updates


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtimes: Optional[Dict[str, Any]] = None
    agents: Optional[list] = None
    pipeline: Optional[list] = None
    runner: Optional[Dict[str, Any]] = None
    worktree: Optional[Dict[str, Any]] = None
    quality_gates: Optional[list] = None
    context_scanner: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


def _project_config_path(project_root: Path) -> Path:
    return project_root / ".ai" / "team.yaml"


def _safe_read_yaml(path: Path):
    try:
        import yaml
    except ImportError:
        raise HTTPException(status_code=500, detail="PyYAML is not installed")

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}")


def _safe_write_yaml(path: Path, data: Dict[str, Any]):
    try:
        import yaml
    except ImportError:
        raise HTTPException(status_code=500, detail="PyYAML is not installed")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")


def _structured_response(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "runtimes": config.get("runtimes", {}),
        "agents": config.get("agents", []),
        "pipeline": config.get("pipeline", []),
        "runner": config.get("runner", {}),
        "worktree": config.get("worktree", {}),
        "quality_gates": config.get("quality_gates", []),
        "context_scanner": config.get("context_scanner", {}),
        "metadata": config.get("metadata", {}),
    }


def _do_update(body: SettingsUpdate, workdir: str) -> Dict[str, Any]:
    """共享的更新逻辑，POST 和 PUT 共用。"""
    project_root = find_project_root(workdir)
    config_path = _project_config_path(project_root)

    if config_path.exists():
        try:
            existing = _safe_read_yaml(config_path)
        except HTTPException:
            raise
        existing = normalize_config(existing, project_root)
    else:
        if DEFAULT_TEAM_FILE.exists():
            try:
                existing = _safe_read_yaml(DEFAULT_TEAM_FILE)
            except HTTPException:
                raise
            existing = normalize_config(existing, project_root)
        else:
            existing = normalize_config(dict(DEFAULT_CONFIG), project_root)

    updates = body.model_dump(exclude_none=True)
    for key, value in updates.items():
        if value is not None:
            if key == "runtimes":
                existing[key] = _merge_runtime_updates(existing.get(key), value)
            elif isinstance(existing.get(key), dict) and isinstance(value, dict):
                existing[key] = _merge_preserving_masks(existing.get(key), value)
            else:
                existing[key] = value

    try:
        existing = normalize_config(existing, project_root)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _safe_write_yaml(config_path, existing)
    return {
        "status": "saved",
        "path": str(config_path),
        "config": _mask_sensitive(_structured_response(existing)),
    }


if router:

    @router.get("/settings")
    def get_settings(workdir: str = Query(default=".")):
        project_root = find_project_root(workdir)
        loaded = load_config(project_root)
        config = _structured_response(loaded.config)
        config = _mask_sensitive(config)
        return {
            "source": loaded.source,
            "path": loaded.path,
            "warnings": loaded.warnings,
            "config": config,
        }

    @router.put("/settings")
    def update_settings_put(body: SettingsUpdate, workdir: str = Query(default=".")):
        return _do_update(body, workdir)

    @router.post("/settings")
    def update_settings(body: SettingsUpdate, workdir: str = Query(default=".")):
        return _do_update(body, workdir)

    @router.post("/settings/reset")
    def reset_settings(workdir: str = Query(default=".")):
        project_root = find_project_root(workdir)
        config_path = _project_config_path(project_root)

        if config_path.exists():
            try:
                config_path.unlink()
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"Failed to remove config: {exc}")

        loaded = load_config(project_root)
        return {
            "status": "reset",
            "source": loaded.source,
            "path": loaded.path,
            "config": _structured_response(loaded.config),
        }
