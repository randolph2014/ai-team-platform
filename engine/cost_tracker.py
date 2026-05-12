from __future__ import annotations

import json
import logging
import os
import uuid as _uuid_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .events import EventBus

logger = logging.getLogger(__name__)

MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "claude-opus": {"input": 15.0, "output": 75.0},
    "claude-sonnet": {"input": 3.0, "output": 15.0},
    "claude-haiku": {"input": 0.25, "output": 1.25},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
}

DEFAULT_PRICING = {"input": 3.0, "output": 15.0}

ESTIMATE_CHARS_PER_TOKEN = 4
COST_TRACKING_SOURCE = "cost_tracking"
COST_TOKEN_BASIS = "estimated_from_prompt_and_output_text"
COST_PRICING_BASIS = "model_pricing_table_with_optional_AI_TEAM_MODEL_PRICING_overrides"


def _load_env_pricing() -> Dict[str, Dict[str, float]]:
    pricing = dict(MODEL_PRICING)
    raw = os.environ.get("AI_TEAM_MODEL_PRICING", "")
    if raw:
        try:
            overrides = json.loads(raw)
            if isinstance(overrides, dict):
                for model, rates in overrides.items():
                    if isinstance(rates, dict):
                        pricing[model] = {
                            "input": float(rates.get("input", DEFAULT_PRICING["input"])),
                            "output": float(rates.get("output", DEFAULT_PRICING["output"])),
                        }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return pricing


def get_pricing(model: str) -> Dict[str, float]:
    pricing = _load_env_pricing()
    for key in (model, model.lower(), model.replace("-", "_")):
        if key in pricing:
            return pricing[key]
    for key, rates in pricing.items():
        if key.replace("-", "_") == model.lower().replace("-", "_"):
            return rates
    return dict(DEFAULT_PRICING)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // ESTIMATE_CHARS_PER_TOKEN)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = get_pricing(model)
    input_cost = (prompt_tokens / 1_000_000) * rates["input"]
    output_cost = (completion_tokens / 1_000_000) * rates["output"]
    return round(input_cost + output_cost, 8)


def _to_db_run_id(run_id: str) -> str:
    return str(_uuid_mod.uuid5(_uuid_mod.NAMESPACE_OID, f"ai-team:pipeline_run:{run_id}"))


def _is_db_available() -> bool:
    try:
        from persistence.connection import is_available
        return is_available()
    except ImportError:
        return False


class CostTracker:
    def __init__(self, project_root: Optional[Path] = None, bus: Optional[EventBus] = None) -> None:
        self._bus = bus

    def track_usage(
        self,
        run_id: str,
        agent_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        stage_id: str = "",
    ) -> None:
        cost = estimate_cost(model, prompt_tokens, completion_tokens)
        if _is_db_available():
            try:
                from persistence.connection import run_sync
                run_sync(self._async_track(run_id, agent_name, model, prompt_tokens, completion_tokens, cost))
            except Exception:
                logger.exception("Failed to track cost in DB for run %s", run_id)
        else:
            logger.warning("Database not available, cost tracking skipped for run %s", run_id)

        if self._bus:
            self._bus.emit(
                "cost:tracked",
                run_id,
                agent_name=agent_name,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost=cost,
                stage_id=stage_id,
            )

    async def _async_track(
        self,
        run_id: str,
        agent_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
    ) -> None:
        from persistence.connection import get_connection, release_connection
        conn = await get_connection()
        if conn is None:
            return
        try:
            db_run_id = _to_db_run_id(run_id)
            await conn.execute(
                "INSERT INTO cost_tracking (run_id, agent_name, model, prompt_tokens, completion_tokens, total_tokens, cost_usd) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                db_run_id, agent_name, model, prompt_tokens, completion_tokens,
                prompt_tokens + completion_tokens, cost,
            )
        finally:
            await release_connection(conn)

    def get_run_costs(self, run_id: str) -> dict:
        records: List[dict] = []
        if _is_db_available():
            try:
                from persistence.connection import run_sync
                records = run_sync(self._async_get_run_costs(run_id))
            except Exception:
                logger.exception("Failed to get run costs from DB for run %s", run_id)
                records = []

        total_prompt = sum(r.get("prompt_tokens", 0) for r in records)
        total_completion = sum(r.get("completion_tokens", 0) for r in records)
        total_cost = sum(r.get("estimated_cost", 0.0) for r in records)

        return {
            "run_id": run_id,
            "source": COST_TRACKING_SOURCE,
            "token_basis": COST_TOKEN_BASIS,
            "pricing_basis": COST_PRICING_BASIS,
            "is_estimate": True,
            "records": records,
            "count": len(records),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "total_cost": round(total_cost, 8),
        }

    async def _async_get_run_costs(self, run_id: str) -> List[dict]:
        from persistence.connection import get_connection, release_connection
        conn = await get_connection()
        if conn is None:
            return []
        try:
            db_run_id = _to_db_run_id(run_id)
            rows = await conn.fetch(
                "SELECT agent_name, model, prompt_tokens, completion_tokens, cost_usd, created_at "
                "FROM cost_tracking WHERE run_id = $1 ORDER BY created_at",
                db_run_id,
            )
            return [
                {
                    "agent_name": r["agent_name"],
                    "model": r["model"],
                    "prompt_tokens": r["prompt_tokens"],
                    "completion_tokens": r["completion_tokens"],
                    "estimated_cost": float(r["cost_usd"]) if r["cost_usd"] is not None else 0.0,
                    "stage_id": "",
                    "timestamp": r["created_at"].isoformat() if r["created_at"] else "",
                }
                for r in rows
            ]
        finally:
            await release_connection(conn)

    def get_summary(self, period: str = "daily") -> dict:
        records: List[dict] = []

        if _is_db_available():
            try:
                from persistence.connection import run_sync
                records = run_sync(self._async_get_summary(period))
            except Exception:
                logger.exception("Failed to get cost summary from DB")
                records = []

        total_prompt = sum(r.get("prompt_tokens", 0) for r in records)
        total_completion = sum(r.get("completion_tokens", 0) for r in records)
        total_cost = sum(r.get("estimated_cost", 0.0) for r in records)
        runs = list({r["run_id"] for r in records})

        by_model: Dict[str, Dict[str, Any]] = {}
        for r in records:
            model = r.get("model", "unknown")
            if model not in by_model:
                by_model[model] = {"prompt_tokens": 0, "completion_tokens": 0, "estimated_cost": 0.0, "calls": 0}
            by_model[model]["prompt_tokens"] += r.get("prompt_tokens", 0)
            by_model[model]["completion_tokens"] += r.get("completion_tokens", 0)
            by_model[model]["estimated_cost"] += r.get("estimated_cost", 0.0)
            by_model[model]["calls"] += 1

        return {
            "period": period,
            "source": COST_TRACKING_SOURCE,
            "token_basis": COST_TOKEN_BASIS,
            "pricing_basis": COST_PRICING_BASIS,
            "is_estimate": True,
            "runs": sorted(runs),
            "run_count": len(runs),
            "total_calls": len(records),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "total_cost": round(total_cost, 8),
            "by_model": {
                m: {
                    "prompt_tokens": d["prompt_tokens"],
                    "completion_tokens": d["completion_tokens"],
                    "estimated_cost": round(d["estimated_cost"], 8),
                    "calls": d["calls"],
                }
                for m, d in by_model.items()
            },
        }

    async def _async_get_summary(self, period: str) -> List[dict]:
        from persistence.connection import get_connection, release_connection
        conn = await get_connection()
        if conn is None:
            return []
        try:
            date_filter = {
                "daily": "created_at::date = CURRENT_DATE",
                "weekly": "created_at >= NOW() - INTERVAL '7 days'",
                "monthly": "date_trunc('month', created_at) = date_trunc('month', NOW())",
            }.get(period, "created_at::date = CURRENT_DATE")
            rows = await conn.fetch(
                f"SELECT run_id, agent_name, model, prompt_tokens, completion_tokens, cost_usd, created_at "
                f"FROM cost_tracking WHERE {date_filter} ORDER BY created_at"
            )
            return [
                {
                    "run_id": str(r["run_id"]),
                    "agent_name": r["agent_name"],
                    "model": r["model"],
                    "prompt_tokens": r["prompt_tokens"],
                    "completion_tokens": r["completion_tokens"],
                    "estimated_cost": float(r["cost_usd"]) if r["cost_usd"] is not None else 0.0,
                    "stage_id": "",
                    "timestamp": r["created_at"].isoformat() if r["created_at"] else "",
                }
                for r in rows
            ]
        finally:
            await release_connection(conn)

    def get_aggregate(self, group_by: str = "model", period: str = "daily") -> dict:
        if not _is_db_available():
            return {
                "period": period,
                "group_by": group_by,
                "source": COST_TRACKING_SOURCE,
                "token_basis": COST_TOKEN_BASIS,
                "pricing_basis": COST_PRICING_BASIS,
                "is_estimate": True,
                "groups": [],
            }
        try:
            from persistence.connection import run_sync
            return run_sync(self._async_get_aggregate(group_by, period))
        except Exception:
            logger.exception("Failed to get cost aggregate from DB")
            return {
                "period": period,
                "group_by": group_by,
                "source": COST_TRACKING_SOURCE,
                "token_basis": COST_TOKEN_BASIS,
                "pricing_basis": COST_PRICING_BASIS,
                "is_estimate": True,
                "groups": [],
            }

    async def _async_get_aggregate(self, group_by: str, period: str) -> dict:
        from persistence.connection import get_connection, release_connection
        conn = await get_connection()
        if conn is None:
            return {
                "period": period,
                "group_by": group_by,
                "source": COST_TRACKING_SOURCE,
                "token_basis": COST_TOKEN_BASIS,
                "pricing_basis": COST_PRICING_BASIS,
                "is_estimate": True,
                "groups": [],
            }
        try:
            date_filter = {
                "daily": "ct.created_at::date = CURRENT_DATE",
                "weekly": "ct.created_at >= NOW() - INTERVAL '7 days'",
                "monthly": "date_trunc('month', ct.created_at) = date_trunc('month', NOW())",
            }.get(period, "ct.created_at::date = CURRENT_DATE")

            if group_by == "project":
                query = (
                    f"SELECT COALESCE(p.name, pr.project_root) AS key, "
                    f"SUM(ct.prompt_tokens) AS total_prompt_tokens, "
                    f"SUM(ct.completion_tokens) AS total_completion_tokens, "
                    f"SUM(ct.total_tokens) AS total_tokens, "
                    f"SUM(ct.cost_usd) AS total_cost, "
                    f"COUNT(*) AS calls "
                    f"FROM cost_tracking ct "
                    f"JOIN pipeline_run pr ON ct.run_id = pr.id "
                    f"LEFT JOIN pipeline p ON pr.pipeline_id = p.id "
                    f"WHERE {date_filter} "
                    f"GROUP BY key ORDER BY total_cost DESC"
                )
            elif group_by == "run":
                query = (
                    f"SELECT CAST(ct.run_id AS TEXT) AS key, "
                    f"SUM(ct.prompt_tokens) AS total_prompt_tokens, "
                    f"SUM(ct.completion_tokens) AS total_completion_tokens, "
                    f"SUM(ct.total_tokens) AS total_tokens, "
                    f"SUM(ct.cost_usd) AS total_cost, "
                    f"COUNT(*) AS calls "
                    f"FROM cost_tracking ct "
                    f"WHERE {date_filter} "
                    f"GROUP BY ct.run_id ORDER BY total_cost DESC"
                )
            elif group_by == "agent":
                query = (
                    f"SELECT ct.agent_name AS key, "
                    f"SUM(ct.prompt_tokens) AS total_prompt_tokens, "
                    f"SUM(ct.completion_tokens) AS total_completion_tokens, "
                    f"SUM(ct.total_tokens) AS total_tokens, "
                    f"SUM(ct.cost_usd) AS total_cost, "
                    f"COUNT(*) AS calls "
                    f"FROM cost_tracking ct "
                    f"WHERE {date_filter} "
                    f"GROUP BY ct.agent_name ORDER BY total_cost DESC"
                )
            else:
                query = (
                    f"SELECT ct.model AS key, "
                    f"SUM(ct.prompt_tokens) AS total_prompt_tokens, "
                    f"SUM(ct.completion_tokens) AS total_completion_tokens, "
                    f"SUM(ct.total_tokens) AS total_tokens, "
                    f"SUM(ct.cost_usd) AS total_cost, "
                    f"COUNT(*) AS calls "
                    f"FROM cost_tracking ct "
                    f"WHERE {date_filter} "
                    f"GROUP BY ct.model ORDER BY total_cost DESC"
                )

            rows = await conn.fetch(query)
            groups = [
                {
                    "key": r["key"],
                    "total_prompt_tokens": r["total_prompt_tokens"] or 0,
                    "total_completion_tokens": r["total_completion_tokens"] or 0,
                    "total_tokens": r["total_tokens"] or 0,
                    "total_cost": round(float(r["total_cost"] or 0), 8),
                    "calls": r["calls"] or 0,
                }
                for r in rows
            ]
            return {
                "period": period,
                "group_by": group_by,
                "source": COST_TRACKING_SOURCE,
                "token_basis": COST_TOKEN_BASIS,
                "pricing_basis": COST_PRICING_BASIS,
                "is_estimate": True,
                "groups": groups,
            }
        finally:
            await release_connection(conn)
