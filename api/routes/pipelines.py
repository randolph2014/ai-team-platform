from __future__ import annotations

import copy
import json
import logging
import uuid as _uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from engine.config import DEFAULT_CONFIG, TEMPLATES_ROOT, load_config
from engine.human_gate import HARD_HUMAN_GATES

try:
    from fastapi import APIRouter, Depends, HTTPException, Query
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover
    APIRouter = None
    BaseModel = object

logger = logging.getLogger(__name__)

router = APIRouter() if APIRouter else None


def _get_auth():
    from ..auth import get_current_user
    return Depends(get_current_user)

PIPELINES_DIR = TEMPLATES_ROOT / "pipelines"

DEFAULT_STAGE_BY_ID = {stage.get("id"): stage for stage in DEFAULT_CONFIG.get("pipeline", []) if stage.get("id")}
StageTemplateItem = Union[str, Dict[str, Any]]


def _hydrate_stage(stage: Any) -> Dict[str, Any]:
    if isinstance(stage, str):
        stage_data: Dict[str, Any] = {"id": stage}
    elif isinstance(stage, dict):
        stage_data = copy.deepcopy(stage)
    else:
        return {"id": str(stage)}

    stage_id = stage_data.get("id")
    base = copy.deepcopy(DEFAULT_STAGE_BY_ID.get(stage_id))
    if base:
        base.update(stage_data)
        stage_data = base

    if stage_id in HARD_HUMAN_GATES:
        stage_data["type"] = "human_review"
        stage_data["allow_auto_approve"] = False
        stage_data["requires_reason_on_reject"] = True
        if base and base.get("reject_to"):
            stage_data["reject_to"] = base["reject_to"]

    if stage_id == "context_scan":
        stage_data["type"] = "context_scan"
        stage_data.setdefault("output_file", "codebase-context.md")
        stage_data.setdefault("output_json", "codebase-context.json")
        stage_data.setdefault("required_artifacts", ["codebase-context.md", "codebase-context.json"])

    if "parallel" in stage_data and "is_parallel" not in stage_data:
        stage_data["is_parallel"] = bool(stage_data["parallel"])

    return stage_data


def _hydrate_yaml_config(config: Dict[str, Any]) -> Dict[str, Any]:
    hydrated = copy.deepcopy(config or {})
    raw_stages = hydrated.get("stages", [])
    if isinstance(raw_stages, list):
        hydrated["stages"] = [_hydrate_stage(stage) for stage in raw_stages]
    return hydrated


def _stage_id(stage: StageTemplateItem) -> str:
    return stage if isinstance(stage, str) else str(stage.get("id", ""))


def _stage(stage_id: str, **overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {"id": stage_id}
    data.update(overrides)
    return data


def _count_agents(stages: List[Dict[str, Any]]) -> int:
    agents = set()
    for stage in stages:
        for agent in stage.get("agents") or []:
            agents.add(str(agent))
    return len(agents)


def _builtin_template(
    template_id: str,
    name: str,
    description: str,
    stages: List[StageTemplateItem],
    *,
    category: str,
    tags: Optional[List[str]] = None,
    recommended: bool = False,
    estimated_effort: str = "M",
    execution_mode: str = "parallel",
) -> Dict[str, Any]:
    yaml_config = _hydrate_yaml_config(
        {
            "name": name,
            "description": description,
            "version": "1.0",
            "execution_mode": execution_mode,
            "stages": stages,
            "metadata": {
                "pipeline_id": template_id,
                "pipeline_source": "builtin",
                "category": category,
            },
        }
    )
    hydrated_stages = yaml_config.get("stages", [])
    stage_ids = [_stage_id(stage) for stage in hydrated_stages]
    return {
        "id": template_id,
        "name": name,
        "description": description,
        "category": category,
        "source": "builtin",
        "is_builtin": True,
        "tags": tags or [],
        "recommended": recommended,
        "estimated_effort": estimated_effort,
        "stage_count": len(stage_ids),
        "agent_count": _count_agents(hydrated_stages),
        "human_gate_count": sum(1 for stage_id in stage_ids if stage_id in HARD_HUMAN_GATES),
        "quality_gate_count": 0,
        "stage_summary": [stage.get("name", stage.get("id")) for stage in hydrated_stages],
        "stages": stage_ids,
        "yaml_config": yaml_config,
    }


BUILTIN_TEMPLATES: List[Dict[str, Any]] = [
    _builtin_template(
        "project-delivery",
        "项目研发流水线",
        "适用于完整功能研发：代码库扫描、需求定稿、任务规划、开发、测试、审查、人工验收和复盘全闭环。",
        [
            "context_scan",
            "requirement_analysis",
            "requirement_synthesis",
            "requirement_confirm",
            "planning",
            "task_plan_confirm",
            "develop",
            "qa",
            "review",
            "acceptance_confirm",
            "retrospect",
        ],
        category="delivery",
        tags=["feature", "full-cycle", "review", "qa"],
        recommended=True,
        estimated_effort="L",
    ),
    _builtin_template(
        "bugfix",
        "修复 bug 流水线",
        "适用于缺陷修复：先定位影响面和修复范围，再实施、回归测试、代码审查和最终验收。",
        [
            "context_scan",
            _stage(
                "requirement_synthesis",
                name="问题定位与修复范围确认",
                input=[
                    "requirement",
                    "codebase-context.md",
                    "codebase-context.json",
                    "human-decision-requirement*.json",
                ],
            ),
            _stage("requirement_confirm", name="修复范围人工确认"),
            _stage(
                "planning",
                name="修复方案与回归计划",
                input=[
                    "requirement-final.md",
                    "requirement-final.json",
                    "codebase-context.md",
                    "codebase-context.json",
                ],
            ),
            _stage(
                "develop",
                name="修复实施",
                input=[
                    "requirement-final.md",
                    "requirement-final.json",
                    "codebase-context.md",
                    "codebase-context.json",
                    "solution-plan.json",
                    "task-plan.md",
                    "task-plan.json",
                    "human-decision-acceptance*.json",
                ],
            ),
            _stage("qa", name="回归测试"),
            _stage("review", name="修复审查与风险识别"),
            _stage("acceptance_confirm", name="修复结果人工验收"),
        ],
        category="bugfix",
        tags=["bugfix", "regression", "root-cause", "review"],
        estimated_effort="M",
    ),
    _builtin_template(
        "requirement",
        "需求流水线",
        "适用于需求澄清和范围定稿：只做代码库扫描、需求分析、需求综合和人工确认，不进入开发实施。",
        ["context_scan", "requirement_analysis", "requirement_synthesis", "requirement_confirm"],
        category="requirement",
        tags=["requirement", "analysis", "scope"],
        estimated_effort="S",
    ),
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


def _pipeline_db_id(api_id: str) -> str:
    return str(_uuid.uuid5(_uuid.NAMESPACE_OID, f"ai-team:pipeline:{api_id}"))


def _load_pipelines() -> List[Dict[str, Any]]:
    from persistence.connection import is_available
    if not is_available():
        return _load_pipelines_from_files()
    try:
        from persistence.connection import run_sync
        return run_sync(_async_list_pipelines())
    except Exception:
        logger.exception("Failed to list pipelines from DB")
        raise


async def _async_list_pipelines() -> List[Dict[str, Any]]:
    from persistence.connection import get_connection, release_connection
    from persistence.repository import PipelineRepo
    conn = await get_connection()
    if conn is None:
        return _load_pipelines_from_files()
    try:
        repo = PipelineRepo()
        rows = await repo.list_all(conn)
        results = []
        for row in rows:
            cfg = row.get("config")
            if isinstance(cfg, str):
                try:
                    cfg = json.loads(cfg)
                except Exception:
                    cfg = {}
            elif not isinstance(cfg, dict):
                cfg = {}
            api_id = cfg.pop("_api_id", row.get("name", str(row["id"])))
            display_name = cfg.pop("_display_name", row.get("name", api_id))
            results.append({
                "id": api_id,
                "name": display_name,
                "description": row.get("description", ""),
                "yaml_config": cfg,
            })
        return results
    finally:
        await release_connection(conn)


def _builtin_by_id(template_id: str) -> Optional[Dict[str, Any]]:
    for template in BUILTIN_TEMPLATES:
        if template.get("id") == template_id:
            return copy.deepcopy(template)
    return None


def _pipeline_by_id_or_name(pipeline_id: str) -> Optional[Dict[str, Any]]:
    for pipeline in _load_pipelines():
        if pipeline.get("id") == pipeline_id or pipeline.get("name") == pipeline_id:
            data = copy.deepcopy(pipeline)
            data["source"] = "custom"
            data["is_builtin"] = False
            return data
    return None


def resolve_pipeline_reference(pipeline_ref: str) -> Dict[str, Any]:
    """Resolve a run-time pipeline reference to either a builtin template or custom pipeline."""
    if not pipeline_ref:
        raise ValueError("pipeline_id is required")
    if ":" in pipeline_ref:
        source, value = pipeline_ref.split(":", 1)
        if source == "template":
            template = _builtin_by_id(value)
            if template:
                return template
            raise KeyError(f"Unknown builtin pipeline template: {value}")
        if source == "pipeline":
            pipeline = _pipeline_by_id_or_name(value)
            if pipeline:
                return pipeline
            raise KeyError(f"Unknown custom pipeline: {value}")
        raise ValueError(f"Unsupported pipeline reference prefix: {source}")

    template = _builtin_by_id(pipeline_ref)
    if template:
        return template
    pipeline = _pipeline_by_id_or_name(pipeline_ref)
    if pipeline:
        return pipeline
    raise KeyError(f"Unknown pipeline: {pipeline_ref}")


def _dump_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
    except ImportError:  # pragma: no cover
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def materialize_pipeline_config(project_root: Path, pipeline_ref: str, run_id: str) -> Path:
    """Write a run-specific executable team config for the selected pipeline."""
    pipeline = resolve_pipeline_reference(pipeline_ref)
    template_config = _hydrate_yaml_config(pipeline.get("yaml_config") or {})
    stages = template_config.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError(f"Pipeline {pipeline.get('id')} has no executable stages")

    loaded = load_config(project_root)
    config = copy.deepcopy(loaded.config)
    execution_mode = template_config.get("execution_mode") or config.get("pipeline_settings", {}).get("execution_mode", "parallel")
    config["pipeline"] = {"execution_mode": execution_mode, "stages": stages}
    config.pop("pipeline_settings", None)
    metadata = dict(config.get("metadata") or {})
    metadata.update(
        {
            "name": pipeline.get("name"),
            "pipeline_id": pipeline.get("id"),
            "pipeline_ref": pipeline_ref,
            "pipeline_source": pipeline.get("source", "custom"),
            "pipeline_category": pipeline.get("category"),
        }
    )
    config["metadata"] = metadata

    path = project_root / ".ai" / "pipeline-configs" / f"{run_id}.yaml"
    _dump_yaml(path, config)
    return path


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
    def list_pipelines(auth: dict = _get_auth()):
        return _load_pipelines()

    @router.get("/pipelines/templates")
    def list_templates(auth: dict = _get_auth()):
        return BUILTIN_TEMPLATES

    @router.get("/pipelines/{pipeline_id}")
    def get_pipeline(pipeline_id: str, auth: dict = _get_auth()):
        pipeline = _find_pipeline(pipeline_id)
        if not pipeline:
            raise HTTPException(status_code=404, detail="Pipeline not found")
        return pipeline

    @router.post("/pipelines")
    async def create_pipeline(body: PipelineCreate, auth: dict = _get_auth()):
        if _find_pipeline(body.id):
            raise HTTPException(status_code=409, detail="Pipeline with this id already exists")

        data = {
            "id": body.id,
            "name": body.name,
            "description": body.description or "",
            "yaml_config": _hydrate_yaml_config(body.yaml_config),
        }

        from persistence.connection import get_connection, release_connection, is_available
        if not is_available():
            _save_pipeline_to_file(body.id, data)
            return data

        conn = await get_connection()
        if conn is None:
            raise HTTPException(status_code=503, detail="Database not available")
        try:
            from persistence.repository import PipelineRepo
            repo = PipelineRepo()
            cfg = dict(data["yaml_config"])
            cfg["_api_id"] = body.id
            cfg["_display_name"] = data["name"]
            await repo.upsert(
                conn,
                id=_pipeline_db_id(body.id),
                name=body.id,
                description=data["description"],
                project_path="/",
                config=cfg,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"DB error: {exc}")
        finally:
            await release_connection(conn)

        return data

    @router.put("/pipelines/{pipeline_id}")
    async def update_pipeline(pipeline_id: str, body: PipelineUpdate, auth: dict = _get_auth()):
        existing = _find_pipeline(pipeline_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Pipeline not found")

        updates = body.model_dump(exclude_none=True)
        for key, value in updates.items():
            if value is not None:
                existing[key] = _hydrate_yaml_config(value) if key == "yaml_config" else value

        from persistence.connection import get_connection, release_connection, is_available
        if not is_available():
            _save_pipeline_to_file(pipeline_id, existing)
            return existing

        conn = await get_connection()
        if conn is None:
            raise HTTPException(status_code=503, detail="Database not available")
        try:
            from persistence.repository import PipelineRepo
            repo = PipelineRepo()
            cfg = dict(existing.get("yaml_config", {}))
            cfg["_api_id"] = pipeline_id
            cfg["_display_name"] = existing["name"]
            await repo.upsert(
                conn,
                id=_pipeline_db_id(pipeline_id),
                name=pipeline_id,
                description=existing.get("description", ""),
                project_path="/",
                config=cfg,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"DB error: {exc}")
        finally:
            await release_connection(conn)

        return existing

    @router.delete("/pipelines/{pipeline_id}")
    async def delete_pipeline(pipeline_id: str, auth: dict = _get_auth()):
        if not _find_pipeline(pipeline_id):
            raise HTTPException(status_code=404, detail="Pipeline not found")

        from persistence.connection import get_connection, release_connection, is_available
        if not is_available():
            if not _delete_pipeline_file(pipeline_id):
                raise HTTPException(status_code=500, detail="Failed to delete pipeline file")
            return {"status": "deleted", "id": pipeline_id}

        conn = await get_connection()
        if conn is None:
            raise HTTPException(status_code=503, detail="Database not available")
        try:
            result = await conn.execute(
                "DELETE FROM pipeline WHERE id = $1",
                _pipeline_db_id(pipeline_id),
            )
            if not result.endswith("1"):
                raise HTTPException(status_code=404, detail="Pipeline not found in DB")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"DB error: {exc}")
        finally:
            await release_connection(conn)

        return {"status": "deleted", "id": pipeline_id}
