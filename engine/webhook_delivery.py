from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict

from persistence.repository import webhook_next_retry_at

logger = logging.getLogger(__name__)


def _json_or_default(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


def _post_json(url: str, payload: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= response.status < 300,
                "status": response.status,
                "body": response_body,
            }
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status": exc.code, "body": response_body}
    except Exception as exc:
        return {"ok": False, "status": None, "body": "", "error": str(exc)}


async def process_due_webhook_deliveries(limit: int = 100) -> Dict[str, Any]:
    from persistence.connection import get_connection, release_connection
    from persistence.repository import WebhookDeliveryRepo

    repo = WebhookDeliveryRepo()
    conn = await get_connection()
    if conn is None:
        raise RuntimeError("Database not available")

    processed = 0
    delivered = 0
    failed = 0
    try:
        rows = await repo.list_pending_retries(conn, limit=limit)
        for row in rows:
            processed += 1
            attempts = int(row.get("attempts") or 0)
            request_url = row.get("request_url")
            payload = _json_or_default(row.get("request_body"), {})
            if not request_url:
                await repo.mark_status(conn, row["id"], "failed", error_message="missing request_url")
                failed += 1
                continue

            result = await asyncio.to_thread(_post_json, request_url, payload)
            if result["ok"]:
                await repo.mark_status(
                    conn,
                    row["id"],
                    "delivered",
                    response_status=result.get("status"),
                    response_body=result.get("body"),
                    next_retry_at=None,
                )
                delivered += 1
            else:
                next_retry_at = webhook_next_retry_at(attempts + 1)
                await repo.mark_status(
                    conn,
                    row["id"],
                    "failed",
                    response_status=result.get("status"),
                    response_body=result.get("body"),
                    error_message=result.get("error") or f"HTTP {result.get('status')}",
                    next_retry_at=next_retry_at,
                )
                failed += 1
    finally:
        await release_connection(conn)

    logger.info("webhook delivery retry processed=%s delivered=%s failed=%s", processed, delivered, failed)
    return {"processed": processed, "delivered": delivered, "failed": failed}
