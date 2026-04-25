from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from engine.config import find_project_root
from engine.orchestrator import find_run_reports, load_report

from ..runtime import active_runs, expected_output_dir, project_for_run, run_projects, start_run_background

try:
    from fastapi import APIRouter, HTTPException, Query
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    APIRouter = None
    BaseModel = object


router = APIRouter() if APIRouter else None


class CreateRunRequest(BaseModel):
    requirement: str
    workdir: str
    run_id: Optional[str] = None
    yes: bool = False
    config_path: Optional[str] = None
    only_stage: Optional[str] = None


if router:

    @router.post("/runs")
    def create_run(body: CreateRunRequest):
        run_id = body.run_id or f"api-{uuid.uuid4().hex[:12]}"
        if run_id in active_runs:
            raise HTTPException(status_code=409, detail="run id is already active")
        if expected_output_dir(run_id, body.workdir).exists():
            raise HTTPException(status_code=409, detail="run id already exists")
        output_dir = start_run_background(
            body.requirement,
            body.workdir,
            run_id=run_id,
            yes=body.yes,
            config_path=body.config_path,
            only_stage=body.only_stage,
        )
        return {
            "run_id": run_id,
            "status": "running",
            "project_root": str(project_for_run(run_id, body.workdir)),
            "output_dir": str(output_dir),
        }

    @router.get("/runs")
    def list_runs(workdir: str = Query(default=".")):
        project_root = find_project_root(workdir)
        reports = []
        for path in find_run_reports(Path(project_root)):
            report = load_report(path)
            reports.append(
                {
                    "run_id": report.run_id,
                    "status": report.status,
                    "pipeline": report.config_path,
                    "output_dir": report.output_dir,
                    "started_at": report.started_at,
                    "completed_at": report.completed_at,
                }
            )
        for run_id, thread in active_runs.items():
            if not thread.is_alive() or any(item["run_id"] == run_id for item in reports):
                continue
            run_project = run_projects.get(run_id)
            if run_project and run_project != project_root:
                continue
            reports.insert(
                0,
                {
                    "run_id": run_id,
                    "status": "running",
                    "pipeline": None,
                    "project_root": str(run_project or project_root),
                    "output_dir": str(expected_output_dir(run_id, str(run_project or project_root))),
                },
            )
        return reports

    @router.get("/runs/{run_id}")
    def get_run(run_id: str, workdir: Optional[str] = Query(default=None)):
        project_root = project_for_run(run_id, workdir)
        for path in find_run_reports(Path(project_root)):
            if path.parent.name == run_id:
                return load_report(path).model_dump(mode="json")
        raise HTTPException(status_code=404, detail="run not found")
