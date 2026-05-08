from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from engine.webhook import SUPPORTED_EVENTS, mask_secret, normalize_trigger_info, parse_event, verify_signature

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


async def _audit(action: str, user: dict, resource_id: str = None, detail: dict = None) -> None:
    from engine.audit import record_audit
    actor = (user or {}).get("sub", "anonymous")
    await record_audit(
        action=action,
        actor=actor,
        resource_type="webhook",
        resource_id=resource_id,
        detail=detail or {},
    )


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


class SecretRotation(BaseModel):
    new_secret: str


async def _get_webhook_repo():
    try:
        from persistence.repository import WebhookRepo
        return WebhookRepo()
    except ImportError:
        return None


async def _get_delivery_repo():
    try:
        from persistence.repository import WebhookDeliveryRepo
        return WebhookDeliveryRepo()
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
            record = await repo.get_by_id(conn, webhook_id, mask_secret=False)
            if record and record.get("secret"):
                record["secret"] = mask_secret(record["secret"])
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
            return await repo.list_all(conn, mask_secret=True)
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
            record = await repo.get_by_id(conn, webhook_id, mask_secret=True)
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

    @router.post("/webhooks/{webhook_id}/rotate-secret")
    async def rotate_secret(webhook_id: str, body: SecretRotation, user: Dict[str, Any] = _get_auth()):
        repo = await _get_webhook_repo()
        if repo is None:
            raise HTTPException(status_code=503, detail="Persistence layer not available")

        conn, release = await _get_conn()
        if conn is None:
            raise HTTPException(status_code=503, detail="Database not available")

        try:
            existing = await repo.get_by_id(conn, webhook_id, mask_secret=False)
            if existing is None:
                raise HTTPException(status_code=404, detail="Webhook not found")

            updated = await repo.rotate_secret(conn, webhook_id, body.new_secret)
            if not updated:
                raise HTTPException(status_code=500, detail="Failed to rotate secret")

            return {"id": webhook_id, "secret": mask_secret(body.new_secret)}
        finally:
            await release(conn)

    @router.get("/webhooks/{webhook_id}/deliveries")
    async def list_deliveries(webhook_id: str, limit: int = Query(default=50, ge=1, le=200), user: Dict[str, Any] = _get_auth()):
        delivery_repo = await _get_delivery_repo()
        if delivery_repo is None:
            raise HTTPException(status_code=503, detail="Persistence layer not available")

        conn, release = await _get_conn()
        if conn is None:
            raise HTTPException(status_code=503, detail="Database not available")

        try:
            return await delivery_repo.get_by_webhook(conn, webhook_id, limit=limit)
        finally:
            await release(conn)

    @router.post("/webhooks/deliveries/retry-due")
    async def retry_due_deliveries(limit: int = Query(default=100, ge=1, le=500), user: Dict[str, Any] = _get_auth()):
        from engine.webhook_delivery import process_due_webhook_deliveries

        result = await process_due_webhook_deliveries(limit=limit)
        await _audit("retry_webhook_deliveries", user, detail=result)
        return result

    @router.post("/webhooks/trigger")
    async def trigger_webhook(request: Request):
        raw_body = await request.body()
        headers = dict(request.headers)

        event_type_header = headers.get("x-github-event") or headers.get("x-gitlab-event")
        if not event_type_header:
            raise HTTPException(status_code=400, detail="No webhook event header found")

        signature = headers.get("x-hub-signature-256") or headers.get("x-gitlab-token") or ""

        repo = await _get_webhook_repo()
        delivery_repo = await _get_delivery_repo()
        conn = None
        release = None

        if repo is not None:
            conn, release = await _get_conn()

        if conn is not None:
            try:
                all_hooks = await repo.list_all(conn, mask_secret=False)
                signature_valid = False

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
                    if hook_secret:
                        if not verify_signature(raw_body, signature, hook_secret):
                            continue
                    signature_valid = True

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

                        if delivery_repo is not None:
                            try:
                                await delivery_repo.create(
                                    conn,
                                    webhook_id=hook.get("id"),
                                    event_type=event_type_header,
                                    status="delivered",
                                    request_url=hook.get("url"),
                                    request_body=body_json,
                                    response_status=200,
                                )
                            except Exception:
                                logger.exception("Failed to record delivery for webhook %s", hook.get("id"))

                if not signature_valid and all_hooks:
                    if delivery_repo is not None:
                        try:
                            await delivery_repo.create(
                                conn,
                                webhook_id=all_hooks[0].get("id"),
                                event_type=event_type_header,
                                status="failed",
                                error_message="Invalid signature",
                            )
                        except Exception:
                            pass
                    raise HTTPException(status_code=401, detail="Invalid webhook signature")
            except HTTPException:
                raise
            except Exception:
                logger.exception("Failed to process webhook trigger")
            finally:
                await release(conn)

        from engine.audit import record_audit
        await record_audit(
            action="webhook_trigger",
            actor="external",
            resource_type="webhook",
            detail={"event": event_type_header},
        )
        return {"status": "processed", "event": event_type_header}
