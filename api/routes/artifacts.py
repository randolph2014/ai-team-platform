from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from engine.orchestrator import find_run_reports
from ..runtime import project_for_run

try:
    from fastapi import APIRouter, Depends, HTTPException, Query
    from fastapi.responses import FileResponse
except ImportError:  # pragma: no cover
    APIRouter = None

router = APIRouter() if APIRouter else None


def _get_auth():
    """Lazy import of auth dependency."""
    from ..auth import get_current_user
    return Depends(get_current_user)


def _run_dir(workdir: Optional[str], run_id: str) -> Path:
    project_root = project_for_run(run_id, workdir)
    for path in find_run_reports(Path(project_root)):
        if path.parent.name == run_id:
            return path.parent
    raise FileNotFoundError(run_id)


if router:

    @router.get("/runs/{run_id}/artifacts")
    def list_artifacts(run_id: str, workdir: Optional[str] = Query(default=None), user: Dict[str, Any] = _get_auth()):
        try:
            run_dir = _run_dir(workdir, run_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="run not found")
        return [{"name": path.name, "size": path.stat().st_size} for path in sorted(run_dir.iterdir()) if path.is_file()]

    @router.get("/runs/{run_id}/artifacts/{filename}")
    def get_artifact(run_id: str, filename: str, workdir: Optional[str] = Query(default=None), user: Dict[str, Any] = _get_auth()):
        try:
            run_dir = _run_dir(workdir, run_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="run not found")
        path = (run_dir / filename).resolve()
        if not str(path).startswith(str(run_dir.resolve())) or not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(path)
