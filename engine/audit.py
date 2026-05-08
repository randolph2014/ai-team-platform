from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from engine.logging_config import get_logger

logger = get_logger("audit")

_AUDIT_DB_AVAILABLE: Optional[bool] = None


def _is_db_available() -> bool:
    global _AUDIT_DB_AVAILABLE
    if _AUDIT_DB_AVAILABLE is not None:
        return _AUDIT_DB_AVAILABLE
    try:
        from persistence.connection import is_available
        _AUDIT_DB_AVAILABLE = is_available()
    except ImportError:
        _AUDIT_DB_AVAILABLE = False
    return _AUDIT_DB_AVAILABLE


async def _write_audit_db(entry: Dict[str, Any]) -> None:
    try:
        from persistence.connection import get_connection, release_connection
        conn = await get_connection()
        if conn is None:
            return
        try:
            await conn.execute(
                "INSERT INTO audit_logs (id, action, actor, resource_type, resource_id, detail, ip_address, user_agent, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                entry["id"],
                entry["action"],
                entry["actor"],
                entry.get("resource_type"),
                entry.get("resource_id"),
                json.dumps(entry.get("detail"), ensure_ascii=False),
                entry.get("ip_address"),
                entry.get("user_agent"),
                entry["created_at"],
            )
        finally:
            await release_connection(conn)
    except Exception:
        logger.warning("Failed to write audit log to DB", exc_info=True)


def _write_audit_file(entry: Dict[str, Any]) -> None:
    try:
        audit_dir = Path(os.environ.get("AI_TEAM_OUTPUT_DIR", ".ai/team-output")) / "_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        audit_file = audit_dir / f"audit-{date_str}.jsonl"
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logger.warning("Failed to write audit log to file", exc_info=True)


async def record_audit(
    action: str,
    actor: str = "system",
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "action": action,
        "actor": actor,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "detail": detail or {},
        "ip_address": ip_address,
        "user_agent": user_agent,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        "audit: action=%s actor=%s resource=%s/%s",
        action, actor, resource_type, resource_id,
    )
    if _is_db_available():
        await _write_audit_db(entry)
    else:
        _write_audit_file(entry)
    return entry


def record_audit_sync(
    action: str,
    actor: str = "system",
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return loop.run_in_executor(
                pool,
                lambda: asyncio.run(record_audit(action, actor, resource_type, resource_id, detail)),
            )
    except RuntimeError:
        return asyncio.run(record_audit(action, actor, resource_type, resource_id, detail))
