from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from engine.config import (
    DEFAULT_CONFIG,
    DEFAULT_TEAM_FILE,
    ConfigError,
    _deep_merge,
    _read_yaml,
    agent_map,
    find_project_root,
    load_config,
    normalize_config,
    resolve_prompt_path,
    resolve_prompt_write_path,
)

try:
    from fastapi import APIRouter, Depends, HTTPException, Query
    from pydantic import BaseModel, ConfigDict
except ImportError:  # pragma: no cover
    APIRouter = None
    BaseModel = object
    ConfigDict = dict

router = APIRouter() if APIRouter else None


def _get_auth():
    from ..auth import get_current_user
    return Depends(get_current_user)


async def _audit(action: str, user: dict, detail: dict = None) -> None:
    from engine.audit import record_audit
    actor = (user or {}).get("sub", "anonymous")
    await record_audit(
        action=action,
        actor=actor,
        resource_type="settings",
        resource_id="default",
        detail=detail or {},
    )

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

    merged: Dict[str, Any] = dict(existing)
    for runtime_id, runtime_update in updates.items():
        existing_runtime = existing.get(runtime_id)
        merged[runtime_id] = _merge_preserving_masks(existing_runtime, runtime_update)
    return merged


def _replace_runtime_updates(existing: Any, updates: Any) -> Any:
    if not isinstance(existing, dict) or not isinstance(updates, dict):
        return updates

    replaced: Dict[str, Any] = {}
    for runtime_id, runtime_update in updates.items():
        replaced[runtime_id] = _replace_preserving_masks(existing.get(runtime_id), runtime_update)
    return replaced


def _replace_preserving_masks(existing: Any, updates: Any) -> Any:
    if isinstance(updates, dict):
        existing_dict = existing if isinstance(existing, dict) else {}
        replaced: Dict[str, Any] = {}
        for key, value in updates.items():
            if isinstance(value, str) and value == MASK and _is_sensitive_key(key):
                if key in existing_dict:
                    replaced[key] = existing_dict[key]
                continue
            replaced[key] = _replace_preserving_masks(existing_dict.get(key), value)
        return replaced
    if isinstance(updates, list):
        return [_replace_preserving_masks(None, item) for item in updates]
    return updates


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


class PromptUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str


async def _db_get_settings() -> Optional[Dict[str, Any]]:
    """从数据库读取配置，返回原始 dict 或 None。"""
    try:
        from persistence.connection import get_connection, release_connection
        from persistence.repository import SettingsRepo
    except ImportError:
        return None
    conn = await get_connection()
    if conn is None:
        return None
    try:
        repo = SettingsRepo()
        return await repo.get(conn)
    finally:
        await release_connection(conn)


async def _db_save_settings(config: Dict[str, Any]) -> bool:
    """将配置写入数据库，返回是否成功。"""
    try:
        from persistence.connection import get_connection, release_connection
        from persistence.repository import SettingsRepo
    except ImportError:
        return False
    conn = await get_connection()
    if conn is None:
        return False
    try:
        repo = SettingsRepo()
        await repo.upsert(conn, "default", config)
        return True
    finally:
        await release_connection(conn)


async def _db_delete_settings() -> bool:
    """从数据库删除配置，返回是否成功。"""
    try:
        from persistence.connection import get_connection, release_connection
        from persistence.repository import SettingsRepo
    except ImportError:
        return False
    conn = await get_connection()
    if conn is None:
        return False
    try:
        repo = SettingsRepo()
        return await repo.delete(conn)
    finally:
        await release_connection(conn)


def _safe_read_yaml(path: Path):
    try:
        import yaml
    except ImportError:
        raise HTTPException(status_code=500, detail="PyYAML is not installed")

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}")


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


async def _do_update(body: SettingsUpdate, workdir: str, *, replace_runtimes: bool = False) -> Dict[str, Any]:
    """共享的更新逻辑，POST 和 PUT 共用。唯一数据源：DB。"""
    project_root = find_project_root(workdir)

    # 基础配置始终从平台模板读取
    if DEFAULT_TEAM_FILE.exists():
        existing = _safe_read_yaml(DEFAULT_TEAM_FILE)
    else:
        existing = dict(DEFAULT_CONFIG)

    # 从 DB 读取用户个性化配置
    db_config = await _db_get_settings()
    if db_config and isinstance(db_config, dict):
        _deep_merge(existing, db_config)

    existing = normalize_config(existing, project_root)

    updates = body.model_dump(exclude_none=True)
    for key, value in updates.items():
        if value is not None:
            if key == "runtimes":
                if replace_runtimes:
                    existing[key] = _replace_runtime_updates(existing.get(key), value)
                else:
                    existing[key] = _merge_runtime_updates(existing.get(key), value)
            elif isinstance(existing.get(key), dict) and isinstance(value, dict):
                existing[key] = _merge_preserving_masks(existing.get(key), value)
            else:
                existing[key] = value

    try:
        existing = normalize_config(existing, project_root)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 唯一数据源：只写 DB
    db_ok = await _db_save_settings(existing)
    if not db_ok:
        raise HTTPException(status_code=503, detail="数据库不可用，无法保存配置")

    return {
        "status": "saved",
        "source": "customized",
        "path": "db:default",
        "warnings": [],
        "config": _mask_sensitive(_structured_response(existing)),
    }


if router:

    @router.get("/settings")
    async def get_settings(workdir: str = Query(default="."), auth: dict = _get_auth()):
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
    async def update_settings_put(body: SettingsUpdate, workdir: str = Query(default="."), auth: dict = _get_auth()):
        await _audit("update_settings_put", auth, {"keys": list(body.model_dump(exclude_none=True).keys())})
        return await _do_update(body, workdir, replace_runtimes=True)

    @router.post("/settings")
    async def update_settings(body: SettingsUpdate, workdir: str = Query(default="."), auth: dict = _get_auth()):
        await _audit("update_settings", auth, {"keys": list(body.model_dump(exclude_none=True).keys())})
        return await _do_update(body, workdir)

    @router.post("/settings/reset")
    async def reset_settings(workdir: str = Query(default="."), auth: dict = _get_auth()):
        await _audit("reset_settings", auth)
        project_root = find_project_root(workdir)

        db_ok = await _db_delete_settings()
        if not db_ok:
            raise HTTPException(status_code=503, detail="数据库不可用，无法重置配置")

        loaded = load_config(project_root)
        return {
            "status": "reset",
            "source": loaded.source,
            "path": loaded.path,
            "warnings": loaded.warnings,
            "config": _structured_response(loaded.config),
        }

    @router.get("/settings/agents/{agent_name}/prompt")
    def get_agent_prompt(agent_name: str, workdir: str = Query(default="."), auth: dict = _get_auth()):
        project_root = find_project_root(workdir)
        loaded = load_config(project_root)
        agents = agent_map(loaded.config)
        agent = agents.get(agent_name)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_name}")
        try:
            read_path = resolve_prompt_path(project_root, loaded.path, agent, loaded.warnings)
            content = read_path.read_text(encoding="utf-8")
            path = resolve_prompt_write_path(project_root, loaded.path, agent)
        except ConfigError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "agent_name": agent_name,
            "path": str(path),
            "source_path": str(read_path),
            "content": content,
        }

    @router.put("/settings/agents/{agent_name}/prompt")
    def update_agent_prompt(agent_name: str, body: PromptUpdate, workdir: str = Query(default="."), auth: dict = _get_auth()):
        project_root = find_project_root(workdir)
        loaded = load_config(project_root)
        agents = agent_map(loaded.config)
        agent = agents.get(agent_name)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_name}")
        try:
            path = resolve_prompt_write_path(project_root, loaded.path, agent)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(body.content, encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to write prompt: {exc}")
        return {
            "status": "saved",
            "agent_name": agent_name,
            "path": str(path),
            "content": body.content,
        }
