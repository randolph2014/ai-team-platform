from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from engine.webhook import SUPPORTED_EVENTS, normalize_trigger_info, parse_event, verify_signature

try:
    from fastapi import APIRouter, Depends, HTTPException, Query, Request
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover
    APIRouter = None
    BaseModel = object

logger = logging.getLogger(__name__)

router = APIRouter() if APIRouter else None


def _get_auth():
    from ..auth import get_current_user
    return Depends(get_current_user)


class WebhookCreate(BaseModel):
    url: str
    secret: str
    events: List[str] = Field(default_factory=list)
    pipeline_id: Optional[str] = None
    enabled: bool = True


class WebhookResponse(BaseModel):
    id: str
    url: str
    secret: str
    events: List[str] = Field(default_factory=list)
    pipeline_id: Optional[str] = None
    enabled: bool = True
    created_at: Optional[str] = None


async def _get_webhook_repo():
    try:
        from persistence.repository import WebhookRepo
        return WebhookRepo()
    except ImportError:
        return None


async def _get_conn():
    try:
        from persistence.connection import get_connection, release_connection
        conn = await get_connection()
        return conn, release_connection
    except ImportError:
        return None, None


if router:

    @router.post("/webhooks")
    async def create_webhook(body: WebhookCreate, user: Dict[str, Any] = _get_auth()):
        for e in body.events:
            if e not in SUPPORTED_EVENTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported event type: {e}. Supported: {', '.join(SUPPORTED_EVENTS)}",
                )

        repo = await _get_webhook_repo()
        if repo is None:
            raise HTTPException(status_code=503, detail="Persistence layer not available")

        conn, release = await _get_conn()
        if conn is None:
            raise HTTPException(status_code=503, detail="Database not available")

        try:
            webhook_id = str(uuid.uuid4())
            await repo.create(
                conn,
                id=webhook_id,
                url=body.url,
                secret=body.secret,
                events=body.events,
                pipeline_id=body.pipeline_id,
                enabled=body.enabled,
            )
            record = await repo.get_by_id(conn, webhook_id)
            return record
        except Exception as exc:
            logger.exception("Failed to create webhook")
            raise HTTPException(status_code=500, detail=f"Failed to create webhook: {exc}")
        finally:
            await release(conn)

    @router.get("/webhooks")
    async def list_webhooks(user: Dict[str, Any] = _get_auth()):
        repo = await _get_webhook_repo()
        if repo is None:
            return []

        conn, release = await _get_conn()
        if conn is None:
            return []

        try:
            return await repo.list_all(conn)
        except Exception:
            logger.exception("Failed to list webhooks")
            return []
        finally:
            await release(conn)

    @router.get("/webhooks/{webhook_id}")
    async def get_webhook(webhook_id: str, user: Dict[str, Any] = _get_auth()):
        repo = await _get_webhook_repo()
        if repo is None:
            raise HTTPException(status_code=503, detail="Persistence layer not available")

        conn, release = await _get_conn()
        if conn is None:
            raise HTTPException(status_code=503, detail="Database not available")

        try:
            record = await repo.get_by_id(conn, webhook_id)
            if record is None:
                raise HTTPException(status_code=404, detail="Webhook not found")
            return record
        finally:
            await release(conn)

    @router.delete("/webhooks/{webhook_id}")
    async def delete_webhook(webhook_id: str, user: Dict[str, Any] = _get_auth()):
        repo = await _get_webhook_repo()
        if repo is None:
            raise HTTPException(status_code=503, detail="Persistence layer not available")

        conn, release = await _get_conn()
        if conn is None:
            raise HTTPException(status_code=503, detail="Database not available")

        try:
            deleted = await repo.delete(conn, webhook_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Webhook not found")
            return {"status": "deleted", "id": webhook_id}
        finally:
            await release(conn)

    @router.post("/webhooks/trigger")
    async def trigger_webhook(request: Request):
        raw_body = await request.body()
        headers = dict(request.headers)

        event_type_header = headers.get("x-github-event") or headers.get("x-gitlab-event")
        if not event_type_header:
            raise HTTPException(status_code=400, detail="No webhook event header found")

        signature = headers.get("x-hub-signature-256") or headers.get("x-gitlab-token") or ""

        repo = await _get_webhook_repo()
        if repo is not None:
            conn, release = await _get_conn()
            if conn is not None:
                try:
                    all_hooks = await repo.list_all(conn)
                    for hook in all_hooks:
                        if not hook.get("enabled", True):
                            continue
                        hook_events = hook.get("events", [])
                        if isinstance(hook_events, str):
                            try:
                                hook_events = json.loads(hook_events)
                            except Exception:
                                hook_events = []
                        if hook_events and event_type_header not in (hook_events or []):
                            continue
                        hook_secret = hook.get("secret", "")
                        try:
                            body_json = json.loads(raw_body) if raw_body else {}
                        except json.JSONDecodeError:
                            body_json = {}
                        event_info = parse_event(headers, body_json)
                        if event_info:
                            trigger_info = normalize_trigger_info(event_info)
                            trigger_info["webhook_id"] = hook.get("id")
                            logger.info(
                                "Webhook triggered: hook_id=%s event=%s branch=%s repository=%s",
                                hook.get("id"),
                                trigger_info.get("event"),
                                trigger_info.get("branch"),
                                trigger_info.get("repository"),
                            )
                except Exception:
                    logger.exception("Failed to process webhook trigger")
                finally:
                    await release(conn)

        return {"status": "processed", "event": event_type_header}
