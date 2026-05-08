from __future__ import annotations

from typing import Optional

from engine.cost_tracker import CostTracker

try:
    from fastapi import APIRouter, Depends, HTTPException, Query
except ImportError:  # pragma: no cover
    APIRouter = None

router = APIRouter() if APIRouter else None


def _get_auth():
    from ..auth import get_current_user
    return Depends(get_current_user)


if router:

    @router.get("/costs")
    def get_costs(run_id: str = Query(...), auth: dict = _get_auth()):
        tracker = CostTracker()
        return tracker.get_run_costs(run_id)

    @router.get("/costs/summary")
    def get_cost_summary(period: str = Query(default="daily"), auth: dict = _get_auth()):
        if period not in {"daily", "weekly", "monthly"}:
            raise HTTPException(status_code=400, detail="period must be one of: daily, weekly, monthly")

        tracker = CostTracker()
        return tracker.get_summary(period)

    @router.get("/costs/aggregate")
    def get_cost_aggregate(
        group_by: str = Query(default="model"),
        period: str = Query(default="daily"),
        auth: dict = _get_auth(),
    ):
        if group_by not in {"project", "run", "agent", "model"}:
            raise HTTPException(status_code=400, detail="group_by must be one of: project, run, agent, model")
        if period not in {"daily", "weekly", "monthly"}:
            raise HTTPException(status_code=400, detail="period must be one of: daily, weekly, monthly")

        tracker = CostTracker()
        return tracker.get_aggregate(group_by, period)
