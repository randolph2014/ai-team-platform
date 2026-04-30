from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

from engine.orchestrator import find_run_reports

from ..db import run_db_id, try_persistence
from ..runtime import project_for_run

try:
    from fastapi import APIRouter, Depends, HTTPException, Query
    from fastapi.responses import FileResponse, Response
except ImportError:  # pragma: no cover
    APIRouter = None

# 文本类型扩展名 → Content-Type 映射
_TEXT_MIME_MAP: Dict[str, str] = {
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".mdx": "text/markdown; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".yaml": "text/yaml; charset=utf-8",
    ".yml": "text/yaml; charset=utf-8",
    ".toml": "text/plain; charset=utf-8",
    ".xml": "text/xml; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".py": "text/plain; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".ts": "text/plain; charset=utf-8",
    ".tsx": "text/plain; charset=utf-8",
    ".jsx": "text/plain; charset=utf-8",
    ".sh": "text/plain; charset=utf-8",
    ".bash": "text/plain; charset=utf-8",
    ".sql": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".out": "text/plain; charset=utf-8",
    ".err": "text/plain; charset=utf-8",
    ".ini": "text/plain; charset=utf-8",
    ".cfg": "text/plain; charset=utf-8",
    ".conf": "text/plain; charset=utf-8",
    ".go": "text/plain; charset=utf-8",
    ".rs": "text/plain; charset=utf-8",
    ".java": "text/plain; charset=utf-8",
    ".rb": "text/plain; charset=utf-8",
    ".php": "text/plain; charset=utf-8",
    ".c": "text/plain; charset=utf-8",
    ".cpp": "text/plain; charset=utf-8",
    ".h": "text/plain; charset=utf-8",
    ".hpp": "text/plain; charset=utf-8",
}

logger = logging.getLogger(__name__)

router = APIRouter() if APIRouter else None


def _get_auth():
    """Lazy import of auth dependency."""
    from ..auth import get_current_user
    return Depends(get_current_user)


async def _db_run_exists(run_id: str) -> Optional[bool]:
    """通过 DB 检查 run 是否存在。DB 不可用返回 None。"""
    db = try_persistence()
    if db is None:
        return None
    get_connection, release_connection, PipelineRunRepo, _, _ = db

    conn = await get_connection()
    if conn is None:
        return None
    try:
        repo = PipelineRunRepo()
        return await repo.run_exists(conn, run_db_id(run_id))
    except Exception:
        logger.debug("DB run_exists check failed for %s", run_id, exc_info=True)
        return None
    finally:
        await release_connection(conn)


def _run_dir(workdir: Optional[str], run_id: str) -> Path:
    project_root = project_for_run(run_id, workdir)
    for path in find_run_reports(Path(project_root)):
        if path.parent.name == run_id:
            return path.parent
    raise FileNotFoundError(run_id)


if router:

    @router.get("/runs/{run_id}/artifacts")
    async def list_artifacts(run_id: str, workdir: Optional[str] = Query(default=None), user: Dict[str, Any] = _get_auth()):
        db_exists = await _db_run_exists(run_id)
        if db_exists is False:
            raise HTTPException(status_code=404, detail="run not found")

        try:
            run_dir = _run_dir(workdir, run_id)
        except FileNotFoundError:
            if db_exists is True:
                return []
            raise HTTPException(status_code=404, detail="run not found")
        return [{"name": path.name, "size": path.stat().st_size} for path in sorted(run_dir.iterdir()) if path.is_file()]

    @router.get("/runs/{run_id}/artifacts/{filename}")
    async def get_artifact(run_id: str, filename: str, workdir: Optional[str] = Query(default=None), user: Dict[str, Any] = _get_auth()):
        db_exists = await _db_run_exists(run_id)
        if db_exists is False:
            raise HTTPException(status_code=404, detail="run not found")

        try:
            run_dir = _run_dir(workdir, run_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="run not found")
        path = (run_dir / filename).resolve()
        if not str(path).startswith(str(run_dir.resolve())) or not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="artifact not found")

        # 根据扩展名选择合适的 Content-Type
        suffix = path.suffix.lower()
        media_type = _TEXT_MIME_MAP.get(suffix)

        if media_type:
            # 文本类型：直接返回内容，支持在线浏览
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                content = path.read_bytes().decode("utf-8", errors="replace")
            return Response(content, media_type=media_type)
        else:
            # 二进制类型：使用 FileResponse
            guessed_type = mimetypes.guess_type(str(path))[0]
            return FileResponse(path, media_type=guessed_type)
