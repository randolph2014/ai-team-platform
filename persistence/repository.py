from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from engine.models import AgentRun, QualityGateRun, RunReport, StageRun, model_to_dict

logger = logging.getLogger(__name__)

# ——————————————————————————————————————————————————————————————————————————————
# 工具函数
# ——————————————————————————————————————————————————————————————————————————————


def _to_dt(value: Optional[str]) -> Optional[datetime]:
    """将 ISO-8601 字符串转为 datetime，兼容 Z/+00:00 后缀"""
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _run_db_id(run_id: str) -> str:
    """将应用的 run_id 转换为数据库 pipeline_run.id（UUID v5）"""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"ai-team:pipeline_run:{run_id}"))


def _stage_db_id(run_db_id: str, stage_id: str, iteration: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{run_db_id}:stage:{stage_id}:{iteration}"))


def _agent_db_id(stage_db_id: str, agent_name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{stage_db_id}:agent:{agent_name}"))


def _gate_db_id(stage_db_id: str, gate_name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{stage_db_id}:gate:{gate_name}"))


def _jsonb(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False) if value is not None else "{}"


def _json_or_default(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


# ——————————————————————————————————————————————————————————————————————————————
# Repository 类
# ——————————————————————————————————————————————————————————————————————————————


class PipelineRepo:
    """pipeline 表 CRUD 操作"""

    TABLE = "pipeline"

    async def upsert(
        self,
        conn,
        *,
        id: Optional[str] = None,
        name: str,
        description: Optional[str] = None,
        project_path: str,
        config: Dict[str, Any],
        version: int = 1,
    ) -> str:
        rows = await conn.fetch(
            f"""
            INSERT INTO {self.TABLE} (id, name, description, project_path, config, version)
            VALUES (COALESCE($1, gen_random_uuid()), $2, $3, $4, $5::jsonb, $6)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                config = EXCLUDED.config,
                version = EXCLUDED.version,
                updated_at = now()
            RETURNING id
            """,
            id,
            name,
            description,
            project_path,
            _jsonb(config),
            version,
        )
        return rows[0]["id"]

    async def get_by_id(self, conn, id: str) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(f"SELECT * FROM {self.TABLE} WHERE id = $1", id)
        return dict(row) if row else None

    async def list_all(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch(f"SELECT * FROM {self.TABLE} ORDER BY created_at DESC")
        return [dict(row) for row in rows]

    async def get_by_name(self, conn, name: str) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(f"SELECT * FROM {self.TABLE} WHERE name = $1", name)
        return dict(row) if row else None


class PipelineVersionRepo:
    """pipeline_version 表 CRUD 操作"""

    TABLE = "pipeline_version"

    async def upsert(
        self,
        conn,
        *,
        pipeline_id: str,
        version: int,
        config: Dict[str, Any],
    ) -> str:
        rows = await conn.fetch(
            f"""
            INSERT INTO {self.TABLE} (id, pipeline_id, version, config)
            VALUES (gen_random_uuid(), $1, $2, $3::jsonb)
            ON CONFLICT (pipeline_id, version) DO UPDATE SET
                config = EXCLUDED.config
            RETURNING id
            """,
            pipeline_id,
            version,
            _jsonb(config),
        )
        return rows[0]["id"]

    async def list_by_pipeline(self, conn, pipeline_id: str) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            f"SELECT * FROM {self.TABLE} WHERE pipeline_id = $1 ORDER BY version DESC",
            pipeline_id,
        )
        return [dict(row) for row in rows]


class PipelineRunRepo:
    """pipeline_run 表 CRUD 操作"""

    TABLE = "pipeline_run"

    async def upsert(
        self,
        conn,
        *,
        id: str,
        pipeline_id: Optional[str],
        status: str,
        project_root: str,
        main_branch: str,
        requirement: str,
        trigger_source: str,
        worktree_path: Optional[str],
        context: Dict[str, Any],
        error_message: Optional[str],
        started_at: Optional[str],
        completed_at: Optional[str],
        duration_seconds: Optional[float],
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {self.TABLE} (id, pipeline_id, status, project_root, main_branch,
                                       requirement, trigger_source, worktree_path, context,
                                       error_message, started_at, completed_at, duration_seconds)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                error_message = EXCLUDED.error_message,
                completed_at = COALESCE(EXCLUDED.completed_at, {self.TABLE}.completed_at),
                duration_seconds = EXCLUDED.duration_seconds,
                worktree_path = COALESCE(EXCLUDED.worktree_path, {self.TABLE}.worktree_path),
                context = {self.TABLE}.context || EXCLUDED.context
            """,
            id,
            pipeline_id,
            status,
            project_root,
            main_branch,
            requirement,
            trigger_source,
            worktree_path,
            _jsonb(context),
            error_message,
            _to_dt(started_at),
            _to_dt(completed_at),
            duration_seconds,
        )

    async def get_by_id(self, conn, id: str) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(f"SELECT * FROM {self.TABLE} WHERE id = $1", id)
        return dict(row) if row else None

    async def list_recent(self, conn, *, limit: int = 50) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            f"SELECT * FROM {self.TABLE} ORDER BY created_at DESC LIMIT $1",
            limit,
        )
        return [dict(row) for row in rows]

    async def list_by_status(self, conn, status: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            f"SELECT * FROM {self.TABLE} WHERE status = $1 ORDER BY created_at DESC LIMIT $2",
            status,
            limit,
        )
        return [dict(row) for row in rows]

    async def list_paginated(
        self, conn, *, page: int = 1, size: int = 20, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        offset = (page - 1) * size
        if status:
            rows = await conn.fetch(
                f"SELECT * FROM {self.TABLE} WHERE status = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                status,
                size,
                offset,
            )
        else:
            rows = await conn.fetch(
                f"SELECT * FROM {self.TABLE} ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                size,
                offset,
            )
        return [dict(row) for row in rows]

    async def count(self, conn, status: Optional[str] = None) -> int:
        if status:
            row = await conn.fetchrow(
                f"SELECT COUNT(*) as cnt FROM {self.TABLE} WHERE status = $1",
                status,
            )
        else:
            row = await conn.fetchrow(f"SELECT COUNT(*) as cnt FROM {self.TABLE}")
        return row["cnt"] if row else 0

    async def update_status(
        self,
        conn,
        run_id: str,
        status: str,
        error_message: Optional[str] = None,
        completed_at: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ) -> bool:
        parts = ["status = $2"]
        params: list = [run_id, status]
        idx = 3
        if error_message is not None:
            parts.append(f"error_message = ${idx}")
            params.append(error_message)
            idx += 1
        if completed_at is not None:
            parts.append(f"completed_at = ${idx}")
            params.append(_to_dt(completed_at))
            idx += 1
        if duration_seconds is not None:
            parts.append(f"duration_seconds = ${idx}")
            params.append(duration_seconds)
            idx += 1
        result = await conn.execute(
            f"UPDATE {self.TABLE} SET {', '.join(parts)} WHERE id = $1",
            *params,
        )
        return result.endswith("1")

    async def create_pending(
        self,
        conn,
        *,
        id: str,
        pipeline_id: Optional[str],
        project_root: str,
        main_branch: str,
        requirement: str,
        trigger_source: str = "manual",
        worktree_path: Optional[str] = None,
        app_run_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        ctx = {key: value for key, value in (context or {}).items() if value is not None}
        if app_run_id:
            ctx["app_run_id"] = app_run_id
        await conn.execute(
            f"""
            INSERT INTO {self.TABLE} (id, pipeline_id, status, project_root, main_branch,
                                       requirement, trigger_source, worktree_path, context)
            VALUES ($1, $2, 'pending', $3, $4, $5, $6, $7, $8::jsonb)
            ON CONFLICT (id) DO NOTHING
            """,
            id,
            pipeline_id,
            project_root,
            main_branch,
            requirement,
            trigger_source,
            worktree_path,
            _jsonb(ctx),
        )

    async def get_run_with_details(self, conn, run_id: str) -> Optional[Dict[str, Any]]:
        run = await self.get_by_id(conn, run_id)
        if run is None:
            return None
        stage_repo = StageRunRepo()
        agent_repo = AgentRunRepo()
        gate_repo = QualityGateRunRepo()
        stages = await stage_repo.list_by_run(conn, run_id)
        for stage in stages:
            stage["agents"] = await agent_repo.list_by_stage(conn, stage["id"])
            stage["quality_gates"] = await gate_repo.list_by_stage(conn, stage["id"])
        run["stages"] = stages
        return run

    async def run_exists(self, conn, run_id: str) -> bool:
        row = await conn.fetchrow(
            f"SELECT 1 FROM {self.TABLE} WHERE id = $1", run_id
        )
        return row is not None


class StageRunRepo:
    """stage_run 表 CRUD 操作"""

    TABLE = "stage_run"

    async def upsert(
        self,
        conn,
        *,
        id: str,
        pipeline_run_id: str,
        stage_id: str,
        stage_name: str,
        iteration: int,
        status: str,
        is_parallel: bool,
        error_message: Optional[str],
        started_at: Optional[str],
        completed_at: Optional[str],
        duration_seconds: Optional[float],
        output_dir: Optional[str],
        stage_type: str = "agent",
        artifact_validations: Optional[List[Dict[str, Any]]] = None,
        human_decision: Optional[Dict[str, Any]] = None,
        loopback_to: Optional[str] = None,
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {self.TABLE} (id, pipeline_run_id, stage_id, stage_name, iteration,
                                       status, is_parallel, error_message, started_at,
                                       completed_at, duration_seconds, output_dir, stage_type,
                                       artifact_validations, human_decision, loopback_to)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb, $15::jsonb, $16)
            ON CONFLICT (id) DO UPDATE SET
                stage_type = EXCLUDED.stage_type,
                status = EXCLUDED.status,
                is_parallel = EXCLUDED.is_parallel,
                error_message = EXCLUDED.error_message,
                completed_at = COALESCE(EXCLUDED.completed_at, {self.TABLE}.completed_at),
                duration_seconds = EXCLUDED.duration_seconds,
                output_dir = COALESCE(EXCLUDED.output_dir, {self.TABLE}.output_dir),
                artifact_validations = EXCLUDED.artifact_validations,
                human_decision = EXCLUDED.human_decision,
                loopback_to = EXCLUDED.loopback_to
            """,
            id,
            pipeline_run_id,
            stage_id,
            stage_name,
            iteration,
            status,
            is_parallel,
            error_message,
            _to_dt(started_at),
            _to_dt(completed_at),
            duration_seconds,
            output_dir,
            stage_type,
            _jsonb(artifact_validations or []),
            _jsonb(human_decision) if human_decision is not None else None,
            loopback_to,
        )

    async def list_by_run(self, conn, pipeline_run_id: str) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            f"SELECT * FROM {self.TABLE} WHERE pipeline_run_id = $1 ORDER BY iteration, stage_id",
            pipeline_run_id,
        )
        return [dict(row) for row in rows]

    async def get_by_id(self, conn, id: str) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(f"SELECT * FROM {self.TABLE} WHERE id = $1", id)
        return dict(row) if row else None


class AgentRunRepo:
    """agent_run 表 CRUD 操作"""

    TABLE = "agent_run"

    async def upsert(
        self,
        conn,
        *,
        id: str,
        stage_run_id: str,
        agent_name: str,
        runtime_id: str,
        runtime_cli: Optional[str],
        role: Optional[str],
        status: str,
        output_file: Optional[str],
        raw_log_file: Optional[str],
        exit_code: Optional[int],
        error_message: Optional[str],
        model_requested: Optional[str] = None,
        model_used: Optional[str] = None,
        started_at: Optional[str],
        completed_at: Optional[str],
        duration_seconds: Optional[float],
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {self.TABLE} (id, stage_run_id, agent_name, runtime_id, runtime_cli, role,
                                        status, output_file, raw_log_file, exit_code,
                                        error_message, model_requested, model_used,
                                        started_at, completed_at, duration_seconds)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            ON CONFLICT (id) DO UPDATE SET
                runtime_id = EXCLUDED.runtime_id,
                runtime_cli = EXCLUDED.runtime_cli,
                status = EXCLUDED.status,
                exit_code = EXCLUDED.exit_code,
                error_message = EXCLUDED.error_message,
                model_requested = COALESCE(EXCLUDED.model_requested, {self.TABLE}.model_requested),
                model_used = EXCLUDED.model_used,
                completed_at = COALESCE(EXCLUDED.completed_at, {self.TABLE}.completed_at),
                duration_seconds = EXCLUDED.duration_seconds,
                output_file = COALESCE(EXCLUDED.output_file, {self.TABLE}.output_file),
                raw_log_file = COALESCE(EXCLUDED.raw_log_file, {self.TABLE}.raw_log_file)
            """,
            id,
            stage_run_id,
            agent_name,
            runtime_id,
            runtime_cli,
            role,
            status,
            output_file,
            raw_log_file,
            exit_code,
            error_message,
            model_requested,
            model_used,
            _to_dt(started_at),
            _to_dt(completed_at),
            duration_seconds,
        )

    async def list_by_stage(self, conn, stage_run_id: str) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            f"SELECT * FROM {self.TABLE} WHERE stage_run_id = $1 ORDER BY agent_name",
            stage_run_id,
        )
        return [dict(row) for row in rows]

    async def get_by_id(self, conn, id: str) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(f"SELECT * FROM {self.TABLE} WHERE id = $1", id)
        return dict(row) if row else None


class QualityGateRunRepo:
    """quality_gate_run 表 CRUD 操作"""

    TABLE = "quality_gate_run"

    async def upsert(
        self,
        conn,
        *,
        id: str,
        stage_run_id: str,
        gate_name: str,
        gate_type: str,
        status: str,
        command: Optional[str],
        exit_code: Optional[int],
        output: Optional[str],
        required: bool,
        retry_count: int,
        started_at: Optional[str],
        completed_at: Optional[str],
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {self.TABLE} (id, stage_run_id, gate_name, gate_type, status,
                                       command, exit_code, output, required, retry_count,
                                       started_at, completed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                exit_code = EXCLUDED.exit_code,
                output = COALESCE(EXCLUDED.output, {self.TABLE}.output),
                retry_count = EXCLUDED.retry_count,
                completed_at = COALESCE(EXCLUDED.completed_at, {self.TABLE}.completed_at)
            """,
            id,
            stage_run_id,
            gate_name,
            gate_type,
            status,
            command,
            exit_code,
            output,
            required,
            retry_count,
            _to_dt(started_at),
            _to_dt(completed_at),
        )

    async def list_by_stage(self, conn, stage_run_id: str) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            f"SELECT * FROM {self.TABLE} WHERE stage_run_id = $1 ORDER BY gate_name",
            stage_run_id,
        )
        return [dict(row) for row in rows]

    async def get_by_id(self, conn, id: str) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(f"SELECT * FROM {self.TABLE} WHERE id = $1", id)
        return dict(row) if row else None


# ——————————————————————————————————————————————————————————————————————————————
# 全局持久化入口
# ——————————————————————————————————————————————————————————————————————————————


async def save_report(report: RunReport, config: Optional[Dict[str, Any]] = None) -> None:
    """将 RunReport 完整写入数据库（pipeline_run → stage_run → agent_run → quality_gate_run）。

    若 DATABASE_URL 未配置则静默跳过；任何 DB 异常均在此层捕获，不向上抛出。
    """
    from .connection import get_connection, release_connection

    conn = await get_connection()
    if conn is None:
        return

    run_repo = PipelineRunRepo()
    stage_repo = StageRunRepo()
    agent_repo = AgentRunRepo()
    gate_repo = QualityGateRunRepo()

    try:
        async with conn.transaction():
            run_db_id = _run_db_id(report.run_id)

            ctx: Dict[str, Any] = {
                "app_run_id": report.run_id,
                "config_source": report.config_source,
                "config_path": report.config_path,
                "artifacts": report.artifacts,
                "human_decisions": [model_to_dict(item) for item in report.human_decisions],
                "changed_files": report.changed_files,
                "diff_stat": report.diff_stat,
            }
            if report.merge_result:
                ctx["merge_result"] = report.merge_result
            if report.error_detail:
                ctx["error_detail"] = model_to_dict(report.error_detail)
            if report.status_timeline:
                ctx["status_timeline"] = [model_to_dict(item) for item in report.status_timeline]

            await run_repo.upsert(
                conn,
                id=run_db_id,
                pipeline_id=None,
                status=report.status,
                project_root=report.project_root,
                main_branch="main",
                requirement=report.requirement,
                trigger_source="manual",
                worktree_path=report.worktree_path,
                context=ctx,
                error_message=report.error_message,
                started_at=report.started_at,
                completed_at=report.completed_at,
                duration_seconds=report.duration_seconds,
            )

            for stage in report.stages:
                stage_db_id = _stage_db_id(run_db_id, stage.stage_id, stage.iteration)

                await stage_repo.upsert(
                    conn,
                    id=stage_db_id,
                    pipeline_run_id=run_db_id,
                    stage_id=stage.stage_id,
                    stage_name=stage.stage_name,
                    iteration=stage.iteration,
                    status=stage.status,
                    is_parallel=stage.is_parallel,
                    error_message=stage.error_message,
                    started_at=stage.started_at,
                    completed_at=stage.completed_at,
                    duration_seconds=stage.duration_seconds,
                    output_dir=stage.output_dir,
                    stage_type=stage.type,
                    artifact_validations=[model_to_dict(item) for item in stage.artifact_validations],
                    human_decision=model_to_dict(stage.human_decision) if stage.human_decision else None,
                    loopback_to=stage.loopback_to,
                )

                for agent in stage.agents:
                    agent_db_id = _agent_db_id(stage_db_id, agent.agent_name)
                    await agent_repo.upsert(
                        conn,
                        id=agent_db_id,
                        stage_run_id=stage_db_id,
                        agent_name=agent.agent_name,
                        runtime_id=agent.runtime_id,
                        runtime_cli=agent.runtime_cli,
                        role=agent.role,
                        status=agent.status,
                        output_file=agent.output_file,
                        raw_log_file=agent.raw_log_file,
                        exit_code=agent.exit_code,
                        error_message=agent.error_message,
                        model_requested=getattr(agent, "model_requested", None),
                        model_used=agent.model_used,
                        started_at=agent.started_at,
                        completed_at=agent.completed_at,
                        duration_seconds=agent.duration_seconds,
                    )

                for gate in stage.quality_gates:
                    gate_db_id = _gate_db_id(stage_db_id, gate.name)
                    await gate_repo.upsert(
                        conn,
                        id=gate_db_id,
                        stage_run_id=stage_db_id,
                        gate_name=gate.name,
                        gate_type=gate.type,
                        status=gate.status,
                        command=gate.command,
                        exit_code=gate.exit_code,
                        output=gate.output,
                        required=gate.required,
                        retry_count=gate.retry_count,
                        started_at=gate.started_at,
                        completed_at=gate.completed_at,
                    )
    except Exception:
        logger.exception("Failed to persist report %s to database", report.run_id)
    finally:
        await release_connection(conn)


def save_report_sync(report: RunReport, config: Optional[Dict[str, Any]] = None) -> None:
    """同步包装器，供 Orchestrator 等非异步上下文调用。

    所有异常均被静默捕获，确保 DB 故障不影响主流程。
    """
    try:
        from .connection import is_available

        if not is_available():
            return

        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(save_report(report, config))
        else:
            # 已有运行中的事件循环（如 FastAPI handler 直接调用时），在独立线程中执行
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda: asyncio.run(save_report(report, config))).result(timeout=30)
    except Exception:
        pass


class WebhookRepo:
    """webhook 表 CRUD 操作"""

    TABLE = "webhook"

    async def create(
        self,
        conn,
        *,
        id: str,
        url: str,
        secret: str,
        events: List[str],
        pipeline_id: Optional[str] = None,
        enabled: bool = True,
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {self.TABLE} (id, url, secret, events, pipeline_id, enabled)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            ON CONFLICT (id) DO UPDATE SET
                url = EXCLUDED.url,
                secret = EXCLUDED.secret,
                events = EXCLUDED.events,
                pipeline_id = EXCLUDED.pipeline_id,
                enabled = EXCLUDED.enabled
            """,
            id,
            url,
            secret,
            _jsonb(events),
            pipeline_id,
            enabled,
        )

    async def get_by_id(self, conn, id: str, mask_secret: bool = True) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(f"SELECT * FROM {self.TABLE} WHERE id = $1", id)
        if row is None:
            return None
        result = dict(row)
        result["id"] = str(result["id"])
        if result.get("pipeline_id"):
            result["pipeline_id"] = str(result["pipeline_id"])
        if result.get("events") and isinstance(result["events"], str):
            try:
                result["events"] = json.loads(result["events"])
            except Exception:
                pass
        result["created_at"] = _dt_to_str(result.get("created_at"))
        if mask_secret and result.get("secret"):
            result["secret"] = _mask_webhook_secret(result["secret"])
        return result

    async def list_all(self, conn, mask_secret: bool = True) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            f"SELECT * FROM {self.TABLE} ORDER BY created_at DESC"
        )
        results = []
        for row in rows:
            r = dict(row)
            r["id"] = str(r["id"])
            if r.get("pipeline_id"):
                r["pipeline_id"] = str(r["pipeline_id"])
            if r.get("events") and isinstance(r["events"], str):
                try:
                    r["events"] = json.loads(r["events"])
                except Exception:
                    pass
            r["created_at"] = _dt_to_str(r.get("created_at"))
            if mask_secret and r.get("secret"):
                r["secret"] = _mask_webhook_secret(r["secret"])
            results.append(r)
        return results

    async def delete(self, conn, id: str) -> bool:
        result = await conn.execute(
            f"DELETE FROM {self.TABLE} WHERE id = $1", id
        )
        return result.endswith("1")

    async def list_by_pipeline(self, conn, pipeline_id: str) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            f"SELECT * FROM {self.TABLE} WHERE pipeline_id = $1 ORDER BY created_at DESC",
            pipeline_id,
        )
        results = []
        for row in rows:
            r = dict(row)
            r["id"] = str(r["id"])
            r["pipeline_id"] = str(r["pipeline_id"]) if r.get("pipeline_id") else None
            if r.get("events") and isinstance(r["events"], str):
                try:
                    r["events"] = json.loads(r["events"])
                except Exception:
                    pass
            r["created_at"] = _dt_to_str(r.get("created_at"))
            if r.get("secret"):
                r["secret"] = _mask_webhook_secret(r["secret"])
            results.append(r)
        return results

    async def update_enabled(self, conn, id: str, enabled: bool) -> bool:
        result = await conn.execute(
            f"UPDATE {self.TABLE} SET enabled = $2 WHERE id = $1", id, enabled
        )
        return result.endswith("1")

    async def rotate_secret(self, conn, id: str, new_secret: str) -> bool:
        result = await conn.execute(
            f"UPDATE {self.TABLE} SET secret = $2 WHERE id = $1", id, new_secret
        )
        return result.endswith("1")


class WebhookDeliveryRepo:
    TABLE = "webhook_delivery"

    async def create(
        self,
        conn,
        *,
        webhook_id: str,
        event_type: str,
        status: str = "pending",
        request_url: Optional[str] = None,
        request_headers: Optional[Dict[str, Any]] = None,
        request_body: Optional[Dict[str, Any]] = None,
        response_status: Optional[int] = None,
        response_body: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> str:
        rows = await conn.fetch(
            f"""
            INSERT INTO {self.TABLE} (webhook_id, event_type, status, request_url, request_headers, request_body,
                                       response_status, response_body, attempts, last_attempt_at, error_message)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, 1, now(), $9)
            RETURNING id
            """,
            webhook_id,
            event_type,
            status,
            request_url,
            _jsonb(request_headers or {}),
            _jsonb(request_body or {}),
            response_status,
            response_body,
            error_message,
        )
        return str(rows[0]["id"])

    async def get_by_webhook(self, conn, webhook_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            f"SELECT * FROM {self.TABLE} WHERE webhook_id = $1 ORDER BY created_at DESC LIMIT $2",
            webhook_id,
            limit,
        )
        results = []
        for row in rows:
            r = dict(row)
            r["id"] = str(r["id"])
            r["webhook_id"] = str(r["webhook_id"])
            r["created_at"] = _dt_to_str(r.get("created_at"))
            r["last_attempt_at"] = _dt_to_str(r.get("last_attempt_at"))
            r["next_retry_at"] = _dt_to_str(r.get("next_retry_at"))
            results.append(r)
        return results

    async def mark_status(self, conn, id: str, status: str, response_status: Optional[int] = None, error_message: Optional[str] = None) -> bool:
        parts = ["status = $2", "attempts = attempts + 1", "last_attempt_at = now()"]
        params: list = [id, status]
        idx = 3
        if response_status is not None:
            parts.append(f"response_status = ${idx}")
            params.append(response_status)
            idx += 1
        if error_message is not None:
            parts.append(f"error_message = ${idx}")
            params.append(error_message)
            idx += 1
        result = await conn.execute(
            f"UPDATE {self.TABLE} SET {', '.join(parts)} WHERE id = $1",
            *params,
        )
        return result.endswith("1")

    async def list_pending_retries(self, conn, *, limit: int = 100) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            f"SELECT * FROM {self.TABLE} WHERE status IN ('failed', 'pending') AND next_retry_at <= now() ORDER BY created_at ASC LIMIT $1",
            limit,
        )
        return [dict(row) for row in rows]


class EvalSuiteRepo:
    """eval_suite 表 CRUD 操作"""

    TABLE = "eval_suite"

    async def create(self, conn, *, name: str, tasks: List[Dict[str, Any]]) -> str:
        rows = await conn.fetch(
            f"""
            INSERT INTO {self.TABLE} (id, name, tasks)
            VALUES (gen_random_uuid(), $1, $2::jsonb)
            RETURNING id
            """,
            name,
            _jsonb(tasks),
        )
        return str(rows[0]["id"])

    async def get_by_id(self, conn, id: str) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(f"SELECT * FROM {self.TABLE} WHERE id = $1", id)
        return dict(row) if row else None

    async def list_all(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch(f"SELECT * FROM {self.TABLE} ORDER BY created_at DESC")
        return [dict(row) for row in rows]


class EvalResultRepo:
    """eval_result 表 CRUD 操作"""

    TABLE = "eval_result"

    async def create(
        self,
        conn,
        *,
        suite_name: str,
        agent_name: str,
        model: Optional[str] = None,
        scores: Dict[str, Any],
        suite_id: Optional[str] = None,
    ) -> str:
        rows = await conn.fetch(
            f"""
            INSERT INTO {self.TABLE} (id, suite_id, agent_name, model, scores)
            VALUES (gen_random_uuid(), $1, $2, $3, $4::jsonb)
            RETURNING id
            """,
            suite_id,
            agent_name,
            model,
            _jsonb(scores),
        )
        return str(rows[0]["id"])

    async def get_by_id(self, conn, id: str) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(f"SELECT * FROM {self.TABLE} WHERE id = $1", id)
        return dict(row) if row else None

    async def list_all(
        self,
        conn,
        *,
        agent_name: Optional[str] = None,
        suite_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query = f"SELECT * FROM {self.TABLE} WHERE 1=1"
        params: list = []
        idx = 1

        if agent_name:
            query += f" AND agent_name = ${idx}"
            params.append(agent_name)
            idx += 1

        if suite_name:
            query += f" AND scores->>'suite_name' = ${idx}"
            params.append(suite_name)
            idx += 1

        query += f" ORDER BY created_at DESC LIMIT ${idx}"
        params.append(limit)

        rows = await conn.fetch(query, *params)
        results = []
        for row in rows:
            r = dict(row)
            r["id"] = str(r["id"])
            if r.get("suite_id"):
                r["suite_id"] = str(r["suite_id"])
            r["created_at"] = _dt_to_str(r.get("created_at"))
            results.append(r)
        return results


# ——————————————————————————————————————————————————————————————————————————————
# API 层辅助：从 asyncpg 行记录转为 API 响应格式
# ——————————————————————————————————————————————————————————————————————————————


def _dt_to_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _mask_webhook_secret(secret: str) -> str:
    if not secret or len(secret) <= 8:
        return "********"
    return secret[:4] + "****" + secret[-4:]


def run_row_to_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    """将 pipeline_run 行转为 list_runs 的摘要格式。"""
    ctx = row.get("context") or {}
    if isinstance(ctx, str):
        try:
            import json
            ctx = json.loads(ctx)
        except Exception:
            ctx = {}
    return {
        "run_id": ctx.get("app_run_id") or row.get("id"),
        "status": row.get("status"),
        "pipeline": ctx.get("pipeline_ref") or ctx.get("config_path"),
        "output_dir": ctx.get("output_dir"),
        "started_at": _dt_to_str(row.get("started_at")),
        "completed_at": _dt_to_str(row.get("completed_at")),
        "duration_seconds": row.get("duration_seconds"),
        "requirement": row.get("requirement"),
    }


def run_detail_to_response(detail: Dict[str, Any]) -> Dict[str, Any]:
    """将 get_run_with_details 的结果转为 API 响应格式。"""
    ctx = detail.get("context") or {}
    if isinstance(ctx, str):
        try:
            import json
            ctx = json.loads(ctx)
        except Exception:
            ctx = {}
    stages = []
    for stage in detail.get("stages", []):
        artifact_validations = _json_or_default(stage.get("artifact_validations"), [])
        human_decision = _json_or_default(stage.get("human_decision"), None)
        agents = []
        for agent in stage.get("agents", []):
            agents.append({
                "agent_name": agent.get("agent_name"),
                "runtime_id": agent.get("runtime_id"),
                "runtime_cli": agent.get("runtime_cli"),
                "role": agent.get("role"),
                "model_requested": agent.get("model_requested"),
                "model_used": agent.get("model_used"),
                "status": agent.get("status"),
                "started_at": _dt_to_str(agent.get("started_at")),
                "completed_at": _dt_to_str(agent.get("completed_at")),
                "duration_seconds": agent.get("duration_seconds"),
                "output_file": agent.get("output_file"),
                "exit_code": agent.get("exit_code"),
                "error_message": agent.get("error_message"),
            })
        gates = []
        for gate in stage.get("quality_gates", []):
            gates.append({
                "name": gate.get("gate_name"),
                "type": gate.get("gate_type"),
                "status": gate.get("status"),
                "command": gate.get("command"),
                "exit_code": gate.get("exit_code"),
                "output": gate.get("output"),
                "required": gate.get("required"),
            })
        stages.append({
            "stage_id": stage.get("stage_id"),
            "stage_name": stage.get("stage_name"),
            "iteration": stage.get("iteration"),
            "type": stage.get("stage_type") or stage.get("type") or "agent",
            "status": stage.get("status"),
            "is_parallel": stage.get("is_parallel"),
            "started_at": _dt_to_str(stage.get("started_at")),
            "completed_at": _dt_to_str(stage.get("completed_at")),
            "duration_seconds": stage.get("duration_seconds"),
            "output_dir": stage.get("output_dir"),
            "error_message": stage.get("error_message"),
            "artifact_validations": artifact_validations,
            "human_decision": human_decision,
            "loopback_to": stage.get("loopback_to") or stage.get("loopback_from"),
            "agents": agents,
            "quality_gates": gates,
        })
    return {
        "run_id": ctx.get("app_run_id") or detail.get("id"),
        "status": detail.get("status"),
        "mode": "single",
        "project_root": detail.get("project_root"),
        "output_dir": detail.get("output_dir") or "",
        "requirement": detail.get("requirement"),
        "worktree_path": detail.get("worktree_path"),
        "merge_result": ctx.get("merge_result"),
        "changed_files": ctx.get("changed_files", []),
        "diff_stat": ctx.get("diff_stat", ""),
        "config_source": ctx.get("config_source"),
        "config_path": ctx.get("config_path"),
        "started_at": _dt_to_str(detail.get("started_at")),
        "completed_at": _dt_to_str(detail.get("completed_at")),
        "duration_seconds": detail.get("duration_seconds"),
        "error_message": detail.get("error_message"),
        "error_detail": _json_or_default(ctx.get("error_detail"), None),
        "artifacts": ctx.get("artifacts", []),
        "human_decisions": _json_or_default(ctx.get("human_decisions"), []),
        "status_timeline": _json_or_default(ctx.get("status_timeline"), []),
        "stages": stages,
    }


class ProjectRepo:
    TABLE = "project"

    async def create(self, conn, *, name: str, root_path: str) -> str:
        rows = await conn.fetch(
            f"""
            INSERT INTO {self.TABLE} (id, name, root_path)
            VALUES (gen_random_uuid(), $1, $2)
            RETURNING id
            """,
            name,
            root_path,
        )
        return str(rows[0]["id"])

    async def get_by_id(self, conn, id: str) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(f"SELECT * FROM {self.TABLE} WHERE id = $1", id)
        if row is None:
            return None
        r = dict(row)
        r["id"] = str(r["id"])
        r["created_at"] = _dt_to_str(r.get("created_at"))
        return r

    async def get_by_root_path(self, conn, root_path: str) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(f"SELECT * FROM {self.TABLE} WHERE root_path = $1", root_path)
        if row is None:
            return None
        r = dict(row)
        r["id"] = str(r["id"])
        r["created_at"] = _dt_to_str(r.get("created_at"))
        return r

    async def list_all(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch(f"SELECT * FROM {self.TABLE} ORDER BY created_at DESC")
        results = []
        for row in rows:
            r = dict(row)
            r["id"] = str(r["id"])
            r["created_at"] = _dt_to_str(r.get("created_at"))
            results.append(r)
        return results

    async def delete(self, conn, id: str) -> bool:
        result = await conn.execute(f"DELETE FROM {self.TABLE} WHERE id = $1", id)
        return result.endswith("1")


class SettingsRepo:
    """settings 表 CRUD 操作 — 存储平台级配置（runtimes/agents/pipeline 等）。"""

    async def get(self, conn, key: str = "default") -> Optional[Dict[str, Any]]:
        """读取配置，返回 dict 或 None。"""
        row = await conn.fetchrow("SELECT config FROM settings WHERE key = $1", key)
        if row is None:
            return None
        config = row["config"]
        return json.loads(config) if isinstance(config, str) else dict(config)

    async def upsert(self, conn, key: str, config: Dict[str, Any]) -> None:
        """写入或更新配置（UPSERT）。"""
        await conn.execute(
            """
            INSERT INTO settings (key, config, created_at, updated_at)
            VALUES ($1, $2::jsonb, now(), now())
            ON CONFLICT (key) DO UPDATE SET
                config = EXCLUDED.config,
                updated_at = now()
            """,
            key,
            _jsonb(config),
        )

    async def delete(self, conn, key: str = "default") -> bool:
        """删除配置，返回是否确实删除了一行。"""
        result = await conn.execute("DELETE FROM settings WHERE key = $1", key)
        return result != "DELETE 0"


def settings_sync(method):
    """装饰器：将 async SettingsRepo 方法包装为同步调用，DB 不可用时静默跳过。"""
    import asyncio
    import functools

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            from .connection import is_available
            if not is_available():
                return None
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(method(*args, **kwargs))
            else:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(lambda: asyncio.run(method(*args, **kwargs))).result(timeout=10)
        except Exception:
            logger.debug("Settings DB operation failed, falling back to file", exc_info=True)
            return None
    return wrapper
