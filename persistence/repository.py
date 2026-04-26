from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from engine.models import AgentRun, QualityGateRun, RunReport, StageRun

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
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {self.TABLE} (id, pipeline_run_id, stage_id, stage_name, iteration,
                                       status, is_parallel, error_message, started_at,
                                       completed_at, duration_seconds, output_dir)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                error_message = EXCLUDED.error_message,
                completed_at = COALESCE(EXCLUDED.completed_at, {self.TABLE}.completed_at),
                duration_seconds = EXCLUDED.duration_seconds,
                output_dir = COALESCE(EXCLUDED.output_dir, {self.TABLE}.output_dir)
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
        provider: str,
        role: Optional[str],
        status: str,
        output_file: Optional[str],
        raw_log_file: Optional[str],
        exit_code: Optional[int],
        error_message: Optional[str],
        started_at: Optional[str],
        completed_at: Optional[str],
        duration_seconds: Optional[float],
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {self.TABLE} (id, stage_run_id, agent_name, provider, role,
                                       status, output_file, raw_log_file, exit_code,
                                       error_message, started_at, completed_at, duration_seconds)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                exit_code = EXCLUDED.exit_code,
                error_message = EXCLUDED.error_message,
                completed_at = COALESCE(EXCLUDED.completed_at, {self.TABLE}.completed_at),
                duration_seconds = EXCLUDED.duration_seconds,
                output_file = COALESCE(EXCLUDED.output_file, {self.TABLE}.output_file),
                raw_log_file = COALESCE(EXCLUDED.raw_log_file, {self.TABLE}.raw_log_file)
            """,
            id,
            stage_run_id,
            agent_name,
            provider,
            role,
            status,
            output_file,
            raw_log_file,
            exit_code,
            error_message,
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
                "config_source": report.config_source,
                "config_path": report.config_path,
                "artifacts": report.artifacts,
            }
            if report.merge_result:
                ctx["merge_result"] = report.merge_result

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
                )

                for agent in stage.agents:
                    agent_db_id = _agent_db_id(stage_db_id, agent.agent_name)
                    await agent_repo.upsert(
                        conn,
                        id=agent_db_id,
                        stage_run_id=stage_db_id,
                        agent_name=agent.agent_name,
                        provider=agent.provider,
                        role=agent.role,
                        status=agent.status,
                        output_file=agent.output_file,
                        raw_log_file=agent.raw_log_file,
                        exit_code=agent.exit_code,
                        error_message=agent.error_message,
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
