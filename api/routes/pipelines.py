from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.config import TEMPLATES_ROOT

try:
    from fastapi import APIRouter, HTTPException, Query
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover
    APIRouter = None
    BaseModel = object

logger = logging.getLogger(__name__)

router = APIRouter() if APIRouter else None

PIPELINES_DIR = TEMPLATES_ROOT / "pipelines"

BUILTIN_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "ios",
        "name": "iOS 开发流水线",
        "description": "适用于 Swift/iOS 项目的需求分析、方案设计、代码实现、测试和审查",
        "stages": ["plan", "architect", "context", "develop", "qa", "review", "accept"],
    },
    {
        "id": "web",
        "name": "Web 前端流水线",
        "description": "适用于 React/Vue/Next.js 前端项目的全流程开发",
        "stages": ["plan", "architect", "context", "develop", "qa", "review", "accept"],
    },
    {
        "id": "backend",
        "name": "后端开发流水线",
        "description": "适用于 Python/Java/Go 后端服务的开发流程",
        "stages": ["plan", "architect", "context", "develop", "qa", "review", "accept"],
    },
]


class PipelineCreate(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    yaml_config: Dict[str, Any] = Field(default_factory=dict)


class PipelineUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    yaml_config: Optional[Dict[str, Any]] = None


def _get_db():
    try:
        from persistence.db import get_db
        return get_db()
    except Exception:
        return None


def _load_pipelines_from_files() -> List[Dict[str, Any]]:
    pipelines = []
    if not PIPELINES_DIR.exists():
        return []
    for path in sorted(PIPELINES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("id", path.stem)
            pipelines.append(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return pipelines


def _load_pipelines() -> List[Dict[str, Any]]:
    db = _get_db()
    if db is not None:
        try:
            cursor = db.execute("SELECT id, name, description, yaml_config FROM pipelines ORDER BY name")
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "description": r[2],
                    "yaml_config": json.loads(r[3]) if isinstance(r[3], str) else (r[3] or {}),
                }
                for r in rows
            ]
        except Exception:
            pass
    return _load_pipelines_from_files()


def _save_pipeline_to_file(pipeline_id: str, data: Dict[str, Any]) -> None:
    PIPELINES_DIR.mkdir(parents=True, exist_ok=True)
    filepath = PIPELINES_DIR / f"{pipeline_id}.json"
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _delete_pipeline_file(pipeline_id: str) -> bool:
    filepath = PIPELINES_DIR / f"{pipeline_id}.json"
    if filepath.exists():
        filepath.unlink()
        return True
    return False


def _find_pipeline(pipeline_id: str) -> Optional[Dict[str, Any]]:
    for p in _load_pipelines():
        if p.get("id") == pipeline_id:
            return p
    return None


if router:

    @router.get("/pipelines")
    def list_pipelines():
        return _load_pipelines()

    @router.get("/pipelines/templates")
    def list_templates():
        return BUILTIN_TEMPLATES

    @router.get("/pipelines/{pipeline_id}")
    def get_pipeline(pipeline_id: str):
        pipeline = _find_pipeline(pipeline_id)
        if not pipeline:
            raise HTTPException(status_code=404, detail="Pipeline not found")
        return pipeline

    @router.post("/pipelines")
    def create_pipeline(body: PipelineCreate):
        if _find_pipeline(body.id):
            raise HTTPException(status_code=409, detail="Pipeline with this id already exists")

        data = {
            "id": body.id,
            "name": body.name,
            "description": body.description or "",
            "yaml_config": body.yaml_config,
        }

        db = _get_db()
        if db is not None:
            try:
                db.execute(
                    "INSERT INTO pipelines (id, name, description, yaml_config) VALUES (?, ?, ?, ?)",
                    (data["id"], data["name"], data["description"], json.dumps(data["yaml_config"], ensure_ascii=False)),
                )
                db.commit()
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"DB error: {exc}")
        else:
            _save_pipeline_to_file(body.id, data)

        return data

    @router.put("/pipelines/{pipeline_id}")
    def update_pipeline(pipeline_id: str, body: PipelineUpdate):
        existing = _find_pipeline(pipeline_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Pipeline not found")

        updates = body.model_dump(exclude_none=True)
        for key, value in updates.items():
            if value is not None:
                existing[key] = value

        db = _get_db()
        if db is not None:
            try:
                db.execute(
                    "UPDATE pipelines SET name = ?, description = ?, yaml_config = ? WHERE id = ?",
                    (existing["name"], existing.get("description", ""), json.dumps(existing.get("yaml_config", {}), ensure_ascii=False), pipeline_id),
                )
                db.commit()
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"DB error: {exc}")
        else:
            _save_pipeline_to_file(pipeline_id, existing)

        return existing

    @router.delete("/pipelines/{pipeline_id}")
    def delete_pipeline(pipeline_id: str):
        if not _find_pipeline(pipeline_id):
            raise HTTPException(status_code=404, detail="Pipeline not found")

        db = _get_db()
        if db is not None:
            try:
                db.execute("DELETE FROM pipelines WHERE id = ?", (pipeline_id,))
                db.commit()
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"DB error: {exc}")
        else:
            if not _delete_pipeline_file(pipeline_id):
                raise HTTPException(status_code=500, detail="Failed to delete pipeline file")

        return {"status": "deleted", "id": pipeline_id}
