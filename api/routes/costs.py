from __future__ import annotations

from typing import Optional

from engine.config import find_project_root
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
    def get_costs(run_id: str = Query(...), workdir: str = Query(default="."), auth: dict = _get_auth()):
        project_root = find_project_root(workdir)
        tracker = CostTracker(project_root)
        return tracker.get_run_costs(run_id)

    @router.get("/costs/summary")
    def get_cost_summary(period: str = Query(default="daily"), workdir: str = Query(default="."), auth: dict = _get_auth()):
        if period not in {"daily", "weekly", "monthly"}:
            raise HTTPException(status_code=400, detail="period must be one of: daily, weekly, monthly")

        project_root = find_project_root(workdir)
        tracker = CostTracker(project_root)
        return tracker.get_summary(period, project_root)
