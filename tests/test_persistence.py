"""
Persistence 层单元测试。

测试范围：
- connection.py: 连接池创建/关闭、数据库不可用时的优雅降级
- repository.py: 各 Repository 的 CRUD 操作（使用 mock 连接）
- migration.py: 迁移执行逻辑（使用 mock 连接）

所有数据库操作均通过 mock 实现，无需真实 PostgreSQL。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 在导入 persistence 模块前 mock asyncpg，避免环境缺少该包时导入失败
_mock_asyncpg = MagicMock()
_mock_asyncpg.Connection = MagicMock
_mock_asyncpg.Pool = MagicMock
_mock_asyncpg.create_pool = AsyncMock()
sys.modules.setdefault("asyncpg", _mock_asyncpg)

from persistence.migration import _ensure_tracking_table, _execute_pending, _load_executed_names
from persistence.repository import (
    AgentRunRepo,
    PipelineRepo,
    PipelineRunRepo,
    PipelineVersionRepo,
    QualityGateRunRepo,
    StageRunRepo,
    _agent_db_id,
    _gate_db_id,
    _run_db_id,
    _stage_db_id,
    save_report,
)


# ══════════════════════════════════════════════════════════════════════
# 工具函数测试
# ══════════════════════════════════════════════════════════════════════


class TestUtils:
    """测试 repository.py 中的工具函数"""

    def test_run_db_id_is_deterministic(self) -> None:
        """_run_db_id 对相同输入产生相同的 UUID"""
        id1 = _run_db_id("run-123")
        id2 = _run_db_id("run-123")
        assert id1 == id2

    def test_run_db_id_different_for_different_inputs(self) -> None:
        """不同输入产生不同的 UUID"""
        id1 = _run_db_id("run-123")
        id2 = _run_db_id("run-456")
        assert id1 != id2

    def test_stage_db_id_includes_iteration(self) -> None:
        """_stage_db_id 包含 iteration 信息，不同 iteration 产生不同 ID"""
        run_db_id = _run_db_id("run-abc")
        id_v1 = _stage_db_id(run_db_id, "develop", 1)
        id_v2 = _stage_db_id(run_db_id, "develop", 2)
        assert id_v1 != id_v2

    def test_agent_db_id_is_deterministic(self) -> None:
        """_agent_db_id 对相同输入产生相同的 UUID"""
        stage_id = _stage_db_id(_run_db_id("run-1"), "develop", 1)
        id1 = _agent_db_id(stage_id, "tech-lead")
        id2 = _agent_db_id(stage_id, "tech-lead")
        assert id1 == id2


# ══════════════════════════════════════════════════════════════════════
# Connection 测试
# ══════════════════════════════════════════════════════════════════════


class TestConnection:
    """测试 persistence/connection.py"""

    def test_connection_returns_none_when_no_url(self) -> None:
        """未设置 DATABASE_URL 时 get_connection 返回 None"""
        from persistence.connection import get_connection as async_get_connection

        with patch.dict(os.environ, {}, clear=True):
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(async_get_connection())
                assert result is None
            finally:
                loop.close()

    def test_is_available_returns_false_when_no_url(self) -> None:
        """未设置数据库 URL 时 is_available 返回 False"""
        from persistence.connection import is_available

        with patch.dict(os.environ, {}, clear=True):
            assert is_available() is False

    def test_is_available_returns_true_when_url_set(self) -> None:
        """设置数据库 URL 时 is_available 返回 True"""
        from persistence.connection import is_available

        with patch.dict(os.environ, {"DATABASE_URL": "postgres://localhost/test"}, clear=True):
            assert is_available() is True

    def test_close_pool_sets_pool_to_none(self) -> None:
        """close_pool 将连接池变量重置为 None"""
        from persistence import connection

        connection._pool = AsyncMock()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(connection.close_pool())
            assert connection._pool is None
        finally:
            loop.close()


# ══════════════════════════════════════════════════════════════════════
# Repository 测试（使用 mock 连接）
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_conn() -> MagicMock:
    """创建一个 mock 数据库连接"""
    conn = MagicMock()
    conn.fetch = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.execute = AsyncMock()
    conn.transaction = MagicMock()
    return conn


class TestPipelineRepo:
    """测试 PipelineRepo CRUD"""

    def test_upsert_inserts_and_returns_id(self, mock_conn: MagicMock) -> None:
        """upsert 插入新记录并返回 ID"""
        repo = PipelineRepo()
        mock_conn.fetch.return_value = [{"id": "pipe-001"}]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                repo.upsert(
                    mock_conn,
                    name="test-pipeline",
                    description="A test pipeline",
                    project_path="/tmp/proj",
                    config={"agents": []},
                )
            )
            assert result == "pipe-001"
            assert mock_conn.fetch.called
        finally:
            loop.close()

    def test_get_by_id_returns_record(self, mock_conn: MagicMock) -> None:
        """get_by_id 返回匹配的记录"""
        repo = PipelineRepo()
        mock_conn.fetchrow.return_value = {"id": "pipe-001", "name": "test"}

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.get_by_id(mock_conn, "pipe-001"))
            assert result == {"id": "pipe-001", "name": "test"}
        finally:
            loop.close()

    def test_get_by_id_returns_none_when_not_found(self, mock_conn: MagicMock) -> None:
        """get_by_id 无匹配时返回 None"""
        repo = PipelineRepo()
        mock_conn.fetchrow.return_value = None

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.get_by_id(mock_conn, "nonexistent"))
            assert result is None
        finally:
            loop.close()

    def test_list_all_returns_records(self, mock_conn: MagicMock) -> None:
        """list_all 返回所有记录"""
        repo = PipelineRepo()
        mock_conn.fetch.return_value = [{"id": "a"}, {"id": "b"}]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.list_all(mock_conn))
            assert len(result) == 2
        finally:
            loop.close()

    def test_get_by_name_finds_record(self, mock_conn: MagicMock) -> None:
        """get_by_name 按名称查找记录"""
        repo = PipelineRepo()
        mock_conn.fetchrow.return_value = {"id": "pipe-x", "name": "my-pipe"}

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.get_by_name(mock_conn, "my-pipe"))
            assert result["name"] == "my-pipe"
        finally:
            loop.close()


class TestPipelineRunRepo:
    """测试 PipelineRunRepo CRUD"""

    def test_upsert_executes_without_error(self, mock_conn: MagicMock) -> None:
        """upsert 正常执行"""
        repo = PipelineRunRepo()
        mock_conn.execute = AsyncMock(return_value=None)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                repo.upsert(
                    mock_conn,
                    id="run-001",
                    pipeline_id=None,
                    status="running",
                    project_root="/tmp",
                    main_branch="main",
                    requirement="test",
                    trigger_source="manual",
                    worktree_path=None,
                    context={},
                    error_message=None,
                    started_at=None,
                    completed_at=None,
                    duration_seconds=None,
                )
            )
            assert mock_conn.execute.called
        finally:
            loop.close()

    def test_get_by_id_returns_record(self, mock_conn: MagicMock) -> None:
        """get_by_id 返回运行记录"""
        repo = PipelineRunRepo()
        mock_conn.fetchrow.return_value = {"id": "run-001", "status": "completed"}

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.get_by_id(mock_conn, "run-001"))
            assert result["status"] == "completed"
        finally:
            loop.close()

    def test_list_recent_returns_limited(self, mock_conn: MagicMock) -> None:
        """list_recent 正确限制数量"""
        repo = PipelineRunRepo()
        mock_conn.fetch.return_value = [{"id": f"run-{i}"} for i in range(5)]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.list_recent(mock_conn, limit=5))
            assert len(result) == 5
        finally:
            loop.close()

    def test_list_by_status_filters_correctly(self, mock_conn: MagicMock) -> None:
        """list_by_status 按状态过滤"""
        repo = PipelineRunRepo()
        mock_conn.fetch.return_value = [{"id": "run-x", "status": "failed"}]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.list_by_status(mock_conn, "failed"))
            assert result[0]["status"] == "failed"
        finally:
            loop.close()


class TestAgentRunRepo:
    """测试 AgentRunRepo CRUD"""

    def test_upsert_executes(self, mock_conn: MagicMock) -> None:
        """AgentRun upsert 正常执行"""
        repo = AgentRunRepo()
        mock_conn.execute = AsyncMock(return_value=None)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                repo.upsert(
                    mock_conn,
                    id="agent-001",
                    stage_run_id="stage-001",
                    agent_name="dev",
                    runtime_id="codex-runtime",
                    runtime_cli="codex",
                    role="developer",
                    status="completed",
                    output_file=None,
                    raw_log_file=None,
                    exit_code=0,
                    error_message=None,
                    started_at=None,
                    completed_at=None,
                    duration_seconds=10.0,
                )
            )
            assert mock_conn.execute.called
        finally:
            loop.close()

    def test_get_by_id_returns_agent(self, mock_conn: MagicMock) -> None:
        """get_by_id 返回 Agent 记录"""
        repo = AgentRunRepo()
        mock_conn.fetchrow.return_value = {"id": "agent-001", "agent_name": "dev"}

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.get_by_id(mock_conn, "agent-001"))
            assert result["agent_name"] == "dev"
        finally:
            loop.close()

    def test_list_by_stage_returns_agents(self, mock_conn: MagicMock) -> None:
        """list_by_stage 返回 stage 下所有 agent"""
        repo = AgentRunRepo()
        mock_conn.fetch.return_value = [
            {"id": "a1", "agent_name": "dev"},
            {"id": "a2", "agent_name": "qa"},
        ]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.list_by_stage(mock_conn, "stage-001"))
            assert len(result) == 2
        finally:
            loop.close()


class TestQualityGateRunRepo:
    """测试 QualityGateRunRepo CRUD"""

    def test_upsert_executes(self, mock_conn: MagicMock) -> None:
        """QualityGateRun upsert 正常执行"""
        repo = QualityGateRunRepo()
        mock_conn.execute = AsyncMock(return_value=None)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                repo.upsert(
                    mock_conn,
                    id="gate-001",
                    stage_run_id="stage-001",
                    gate_name="smoke",
                    gate_type="command",
                    status="passed",
                    command="echo ok",
                    exit_code=0,
                    output="ok",
                    required=True,
                    retry_count=0,
                    started_at=None,
                    completed_at=None,
                )
            )
            assert mock_conn.execute.called
        finally:
            loop.close()

    def test_get_by_id_returns_gate(self, mock_conn: MagicMock) -> None:
        """get_by_id 返回质量门禁记录"""
        repo = QualityGateRunRepo()
        mock_conn.fetchrow.return_value = {"id": "gate-001", "gate_name": "smoke", "status": "passed"}

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.get_by_id(mock_conn, "gate-001"))
            assert result["gate_name"] == "smoke"
            assert result["status"] == "passed"
        finally:
            loop.close()

    def test_list_by_stage_returns_gates(self, mock_conn: MagicMock) -> None:
        """list_by_stage 返回 stage 下所有门禁"""
        repo = QualityGateRunRepo()
        mock_conn.fetch.return_value = [
            {"id": "g1", "gate_name": "lint", "status": "passed"},
            {"id": "g2", "gate_name": "test", "status": "failed"},
        ]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.list_by_stage(mock_conn, "stage-001"))
            assert len(result) == 2
        finally:
            loop.close()


class TestStageRunRepo:
    """测试 StageRunRepo CRUD"""

    def test_upsert_executes(self, mock_conn: MagicMock) -> None:
        """StageRun upsert 正常执行"""
        repo = StageRunRepo()
        mock_conn.execute = AsyncMock(return_value=None)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                repo.upsert(
                    mock_conn,
                    id="stage-001",
                    pipeline_run_id="run-001",
                    stage_id="develop",
                    stage_name="开发",
                    iteration=1,
                    status="running",
                    is_parallel=False,
                    error_message=None,
                    started_at=None,
                    completed_at=None,
                    duration_seconds=None,
                    output_dir=None,
                )
            )
            assert mock_conn.execute.called
        finally:
            loop.close()

    def test_upsert_persists_runtime_contract_fields(self, mock_conn: MagicMock) -> None:
        """StageRun upsert writes fields required by run detail API/UI contract."""
        repo = StageRunRepo()
        mock_conn.execute = AsyncMock(return_value=None)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                repo.upsert(
                    mock_conn,
                    id="stage-001",
                    pipeline_run_id="run-001",
                    stage_id="task_plan_confirm",
                    stage_name="任务计划确认",
                    iteration=1,
                    status="waiting",
                    is_parallel=False,
                    error_message=None,
                    started_at=None,
                    completed_at=None,
                    duration_seconds=None,
                    output_dir="/tmp/out",
                    stage_type="human_review",
                    artifact_validations=[
                        {"artifact": "task-plan.json", "status": "failed", "message": "缺少回滚方案"}
                    ],
                    human_decision={
                        "stage_id": "task_plan_confirm",
                        "decision": "rejected",
                        "reason": "任务缺少回滚方案",
                        "required_changes": ["补充回滚方案"],
                    },
                    loopback_to="planning",
                )
            )
            sql = mock_conn.execute.call_args.args[0]
            params = mock_conn.execute.call_args.args[1:]
            assert "stage_type" in sql
            assert "artifact_validations" in sql
            assert "human_decision" in sql
            assert "loopback_to" in sql
            assert "human_review" in params
            assert "planning" in params
            assert any(isinstance(item, str) and "task-plan.json" in item for item in params)
            assert any(isinstance(item, str) and "任务缺少回滚方案" in item for item in params)
        finally:
            loop.close()


class TestPipelineVersionRepo:
    """测试 PipelineVersionRepo CRUD"""

    def test_upsert_executes(self, mock_conn: MagicMock) -> None:
        """PipelineVersion upsert 正常执行"""
        repo = PipelineVersionRepo()
        mock_conn.fetch.return_value = [{"id": "ver-001"}]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                repo.upsert(
                    mock_conn,
                    pipeline_id="pipe-001",
                    version=1,
                    config={"agents": []},
                )
            )
            assert result == "ver-001"
        finally:
            loop.close()

    def test_list_by_pipeline_returns_versions(self, mock_conn: MagicMock) -> None:
        """list_by_pipeline 返回版本列表"""
        repo = PipelineVersionRepo()
        mock_conn.fetch.return_value = [
            {"id": "v2", "version": 2},
            {"id": "v1", "version": 1},
        ]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.list_by_pipeline(mock_conn, "pipe-001"))
            assert len(result) == 2
            assert result[0]["version"] == 2
        finally:
            loop.close()


# ══════════════════════════════════════════════════════════════════════
# Migration 测试
# ══════════════════════════════════════════════════════════════════════


class TestMigration:
    """测试 persistence/migration.py"""

    def test_ensure_tracking_table_executes(self, mock_conn: MagicMock) -> None:
        """_ensure_tracking_table 执行 CREATE TABLE IF NOT EXISTS"""
        mock_conn.execute = AsyncMock(return_value=None)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_ensure_tracking_table(mock_conn))
            assert mock_conn.execute.called
        finally:
            loop.close()

    def test_load_executed_names_returns_empty_set(self, mock_conn: MagicMock) -> None:
        """无已执行迁移时返回空集合"""
        mock_conn.fetch.return_value = []

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_load_executed_names(mock_conn))
            assert result == set()
        finally:
            loop.close()

    def test_load_executed_names_returns_migration_names(self, mock_conn: MagicMock) -> None:
        """返回已执行的迁移名称集合"""
        mock_conn.fetch.return_value = [
            {"name": "001_initial.up.sql"},
            {"name": "002_add_user.up.sql"},
        ]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_load_executed_names(mock_conn))
            assert result == {"001_initial.up.sql", "002_add_user.up.sql"}
        finally:
            loop.close()

    def test_execute_pending_with_no_pending_migrations(self, mock_conn: MagicMock) -> None:
        """无待执行迁移时跳过"""
        from persistence.migration import MIGRATIONS_DIR

        mock_conn.fetch = AsyncMock(return_value=[])
        with patch.object(pytest.importorskip("persistence.migration"), "MIGRATIONS_DIR") as mock_dir:
            mock_dir.glob.return_value = []
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_execute_pending(mock_conn))
                # 不应再执行 execute（除了 _ensure_tracking_table 和 _load_executed_names 的 fetch）
            finally:
                loop.close()

    def test_run_migrations_skips_when_no_connection(self) -> None:
        """未配置数据库时 run_migrations 静默跳过"""
        from persistence.migration import run_migrations

        with patch("persistence.connection.get_connection", AsyncMock(return_value=None)):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(run_migrations())
            finally:
                loop.close()

    def test_runtime_migration_does_not_unconditionally_read_provider(self) -> None:
        """006 需要兼容新库：001 已无 provider 列，不能直接引用 provider"""
        sql = (Path(__file__).resolve().parents[1] / "persistence" / "migrations" / "006_agent_runtime_fields.up.sql").read_text(encoding="utf-8")
        assert "information_schema.columns" in sql
        assert "column_name = 'provider'" in sql
        assert "EXECUTE" in sql


# ══════════════════════════════════════════════════════════════════════
# save_report 测试
# ══════════════════════════════════════════════════════════════════════


class TestSaveReport:
    """测试 save_report 持久化功能"""

    def test_save_report_skips_when_no_connection(self) -> None:
        """未配置数据库时 save_report 静默跳过"""
        from engine.models import RunReport

        report = RunReport(
            run_id="test-run",
            status="completed",
            requirement="test",
            project_root="/tmp",
            output_dir="/tmp",
            config_source="default",
        )

        with patch("persistence.connection.get_connection", AsyncMock(return_value=None)):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(save_report(report))
            finally:
                loop.close()

    def test_save_report_sync_skips_when_no_url(self) -> None:
        """save_report_sync 未配置 URL 时静默跳过"""
        from engine.models import RunReport
        from persistence.repository import save_report_sync

        with patch("persistence.connection.is_available", return_value=False):
            report = RunReport(
                run_id="test-run",
                status="completed",
                requirement="test",
                project_root="/tmp",
                output_dir="/tmp",
                config_source="default",
            )
            # 不应抛出异常
            save_report_sync(report)

    def test_save_report_passes_stage_contract_fields(self) -> None:
        """save_report must persist fields required by DB-backed run detail UI."""
        from engine.models import ArtifactValidationRun, HumanDecision, RunReport, StageRun

        class _Tx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _Conn:
            def transaction(self):
                return _Tx()

        run_repo = MagicMock()
        run_repo.upsert = AsyncMock(return_value=None)
        stage_repo = MagicMock()
        stage_repo.upsert = AsyncMock(return_value=None)
        agent_repo = MagicMock()
        agent_repo.upsert = AsyncMock(return_value=None)
        gate_repo = MagicMock()
        gate_repo.upsert = AsyncMock(return_value=None)

        stage = StageRun(
            stage_id="task_plan_confirm",
            stage_name="任务计划确认",
            status="waiting",
            type="human_review",
            artifact_validations=[
                ArtifactValidationRun(artifact="task-plan.json", status="failed", message="缺少回滚方案")
            ],
            human_decision=HumanDecision(
                stage_id="task_plan_confirm",
                decision="rejected",
                reason="任务缺少回滚方案",
                required_changes=["补充回滚方案"],
                target_stage="planning",
            ),
            loopback_to="planning",
        )
        report = RunReport(
            run_id="test-run",
            status="waiting",
            requirement="test",
            project_root="/tmp",
            output_dir="/tmp/out",
            config_source="default",
            stages=[stage],
            human_decisions=[stage.human_decision],
        )

        with (
            patch("persistence.connection.get_connection", AsyncMock(return_value=_Conn())),
            patch("persistence.connection.release_connection", AsyncMock(return_value=None)),
            patch("persistence.repository.PipelineRunRepo", return_value=run_repo),
            patch("persistence.repository.StageRunRepo", return_value=stage_repo),
            patch("persistence.repository.AgentRunRepo", return_value=agent_repo),
            patch("persistence.repository.QualityGateRunRepo", return_value=gate_repo),
        ):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(save_report(report))
            finally:
                loop.close()

        run_kwargs = run_repo.upsert.await_args.kwargs
        assert run_kwargs["context"]["human_decisions"][0]["reason"] == "任务缺少回滚方案"
        stage_kwargs = stage_repo.upsert.await_args.kwargs
        assert stage_kwargs["stage_type"] == "human_review"
        assert stage_kwargs["artifact_validations"][0]["artifact"] == "task-plan.json"
        assert stage_kwargs["human_decision"]["decision"] == "rejected"
        assert stage_kwargs["loopback_to"] == "planning"


# ══════════════════════════════════════════════════════════════════════
# ORM Models 测试
# ══════════════════════════════════════════════════════════════════════


def _make_row(**kwargs):
    """Create a mapping object mimicking an asyncpg Record (supports dict())."""

    class _FakeRecord(dict):
        """Dict subclass that also supports attribute access (like asyncpg Record)."""
        def __getattr__(self, key):
            try:
                return self[key]
            except KeyError:
                raise AttributeError(key)

    return _FakeRecord(kwargs)


class TestPipelineRecord:
    """测试 PipelineRecord ORM 模型"""

    def test_from_row_basic(self) -> None:
        """from_row 正确转换 asyncpg Record"""
        from persistence.models import PipelineRecord
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        row = _make_row(
            id="550e8400-e29b-41d4-a716-446655440000",
            name="test-pipeline",
            description="A test",
            project_path="/tmp/proj",
            config='{"agents": []}',
            version=2,
            created_at=now,
            updated_at=now,
        )
        record = PipelineRecord.from_row(row)
        assert record.name == "test-pipeline"
        assert record.version == 2
        assert isinstance(record.config, dict)

    def test_to_dict(self) -> None:
        """to_dict 返回可序列化字典"""
        from persistence.models import PipelineRecord
        record = PipelineRecord(id="abc", name="test", project_path="/tmp")
        d = record.to_dict()
        assert isinstance(d, dict)
        assert d["name"] == "test"

    def test_from_row_with_uuid_object(self) -> None:
        """from_row 处理 UUID 对象"""
        from persistence.models import PipelineRecord
        import uuid
        uid = uuid.uuid4()
        row = _make_row(id=uid, name="p1", project_path="/x", config="{}", version=1, created_at=None, updated_at=None, description=None)
        record = PipelineRecord.from_row(row)
        assert record.id == str(uid)


class TestPipelineVersionRecord:
    """测试 PipelineVersionRecord"""

    def test_from_row_basic(self) -> None:
        from persistence.models import PipelineVersionRecord
        row = _make_row(id="v1", pipeline_id="p1", version=3, config='{"k": "v"}', created_at=None)
        record = PipelineVersionRecord.from_row(row)
        assert record.version == 3
        assert record.config == {"k": "v"}

    def test_to_dict(self) -> None:
        from persistence.models import PipelineVersionRecord
        record = PipelineVersionRecord(id="v1", pipeline_id="p1", version=1)
        d = record.to_dict()
        assert d["pipeline_id"] == "p1"


class TestPipelineRunRecord:
    """测试 PipelineRunRecord"""

    def test_from_row_basic(self) -> None:
        from persistence.models import PipelineRunRecord
        row = _make_row(
            id="r1", pipeline_id=None, status="completed",
            project_root="/tmp", main_branch="main",
            requirement="test", trigger_source="api",
            worktree_path=None, context="{}",
            error_message=None, started_at=None,
            completed_at=None, created_at=None, duration_seconds=10.5,
        )
        record = PipelineRunRecord.from_row(row)
        assert record.status == "completed"
        assert record.duration_seconds == 10.5

    def test_to_dict(self) -> None:
        from persistence.models import PipelineRunRecord
        record = PipelineRunRecord(id="r1")
        d = record.to_dict()
        assert d["status"] == "pending"


class TestStageRunRecord:
    """测试 StageRunRecord"""

    def test_from_row_basic(self) -> None:
        from persistence.models import StageRunRecord
        row = _make_row(
            id="s1", pipeline_run_id="r1", stage_id="develop",
            stage_name="Develop", iteration=1, status="completed",
            is_parallel=False, loopback_from=None, error_message=None,
            started_at=None, completed_at=None, duration_seconds=5.0,
            output_dir="/tmp",
        )
        record = StageRunRecord.from_row(row)
        assert record.stage_id == "develop"
        assert record.iteration == 1

    def test_from_row_parses_stage_runtime_json_fields(self) -> None:
        from persistence.models import StageRunRecord
        row = _make_row(
            id="s1", pipeline_run_id="r1", stage_id="task_plan_confirm",
            stage_name="Task Plan Confirm", iteration=1, stage_type="human_review",
            status="waiting", is_parallel=False, loopback_from=None,
            loopback_to="planning",
            artifact_validations='[{"artifact":"task-plan.json","status":"failed","message":"缺少回滚方案"}]',
            human_decision='{"stage_id":"task_plan_confirm","decision":"approved","reason":"","required_changes":[]}',
            error_message=None, started_at=None, completed_at=None,
            duration_seconds=None, output_dir="/tmp",
        )

        record = StageRunRecord.from_row(row)

        assert record.stage_type == "human_review"
        assert record.artifact_validations[0]["artifact"] == "task-plan.json"
        assert record.human_decision["decision"] == "approved"
        assert record.loopback_to == "planning"


class TestAgentRunRecord:
    """测试 AgentRunRecord"""

    def test_from_row_basic(self) -> None:
        from persistence.models import AgentRunRecord
        row = _make_row(
            id="a1", stage_run_id="s1", agent_name="dev",
            runtime_id="codex-runtime", runtime_cli="codex", role="developer", status="completed",
            output_file=None, raw_log_file=None, exit_code=0,
            error_message=None, started_at=None, completed_at=None,
            duration_seconds=3.0,
        )
        record = AgentRunRecord.from_row(row)
        assert record.agent_name == "dev"
        assert record.runtime_id == "codex-runtime"
        assert record.runtime_cli == "codex"
        assert record.exit_code == 0


class TestQualityGateRecord:
    """测试 QualityGateRecord"""

    def test_from_row_basic(self) -> None:
        from persistence.models import QualityGateRecord
        row = _make_row(
            id="g1", stage_run_id="s1", gate_name="lint",
            gate_type="command", status="passed",
            command="npm run lint", exit_code=0,
            output="OK", required=True, retry_count=0,
            started_at=None, completed_at=None,
        )
        record = QualityGateRecord.from_row(row)
        assert record.gate_name == "lint"
        assert record.status == "passed"
        assert record.required is True


class TestModelsExistInPackage:
    """测试 persistence 包正确导出模型类"""

    def test_pipeline_record_importable(self) -> None:
        from persistence import PipelineRecord
        assert PipelineRecord is not None

    def test_pipeline_run_record_importable(self) -> None:
        from persistence import PipelineRunRecord
        assert PipelineRunRecord is not None

    def test_stage_run_record_importable(self) -> None:
        from persistence import StageRunRecord
        assert StageRunRecord is not None

    def test_agent_run_record_importable(self) -> None:
        from persistence import AgentRunRecord
        assert AgentRunRecord is not None

    def test_quality_gate_record_importable(self) -> None:
        from persistence import QualityGateRecord
        assert QualityGateRecord is not None

    def test_pipeline_version_record_importable(self) -> None:
        from persistence import PipelineVersionRecord
        assert PipelineVersionRecord is not None


class TestInitDbExists:
    """验证 init_db / run_migrations / get_connection 等入口函数存在"""

    def test_run_migrations_callable(self) -> None:
        from persistence import run_migrations
        assert callable(run_migrations)

    def test_get_connection_callable(self) -> None:
        from persistence import get_connection
        assert callable(get_connection)

    def test_close_pool_callable(self) -> None:
        from persistence import close_pool
        assert callable(close_pool)


class TestRepoClassesExist:
    """验证 Repository 类可以从 persistence 包导入"""

    def test_pipeline_repo_importable(self) -> None:
        from persistence import PipelineRepo
        repo = PipelineRepo()
        assert hasattr(repo, "upsert")
        assert hasattr(repo, "get_by_id")

    def test_pipeline_run_repo_importable(self) -> None:
        from persistence import PipelineRunRepo
        repo = PipelineRunRepo()
        assert hasattr(repo, "upsert")
        assert hasattr(repo, "list_recent")

    def test_stage_run_repo_importable(self) -> None:
        from persistence import StageRunRepo
        assert StageRunRepo is not None

    def test_agent_run_repo_importable(self) -> None:
        from persistence import AgentRunRepo
        assert AgentRunRepo is not None

    def test_quality_gate_run_repo_importable(self) -> None:
        from persistence import QualityGateRunRepo
        assert QualityGateRunRepo is not None


# ══════════════════════════════════════════════════════════════════════
# 辅助函数补充测试
# ══════════════════════════════════════════════════════════════════════


class TestToDt:
    """测试 _to_dt() ISO 字符串转 datetime"""

    def test_none_returns_none(self) -> None:
        from persistence.repository import _to_dt
        assert _to_dt(None) is None

    def test_valid_iso_string(self) -> None:
        from persistence.repository import _to_dt
        result = _to_dt("2025-01-15T10:30:00+08:00")
        assert result is not None
        assert result.year == 2025
        assert result.month == 1
        assert result.hour == 10

    def test_z_suffix_converted(self) -> None:
        from persistence.repository import _to_dt
        result = _to_dt("2025-06-01T12:00:00Z")
        assert result is not None
        assert result.tzinfo is not None
        assert result.hour == 12


class TestJsonb:
    """测试 _jsonb() JSON 序列化"""

    def test_none_returns_empty_dict(self) -> None:
        from persistence.repository import _jsonb
        assert _jsonb(None) == "{}"

    def test_dict_serialized(self) -> None:
        from persistence.repository import _jsonb
        result = _jsonb({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result

    def test_list_serialized(self) -> None:
        from persistence.repository import _jsonb
        result = _jsonb([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_nested_dict(self) -> None:
        from persistence.repository import _jsonb
        result = _jsonb({"a": {"b": [1, 2]}})
        assert '"a"' in result
        assert '"b"' in result


class TestDtToStr:
    """测试 _dt_to_str() datetime 转 ISO 字符串"""

    def test_none_returns_none(self) -> None:
        from persistence.repository import _dt_to_str
        assert _dt_to_str(None) is None

    def test_datetime_returns_iso(self) -> None:
        from persistence.repository import _dt_to_str
        from datetime import datetime, timezone
        dt = datetime(2025, 3, 10, 8, 0, 0, tzinfo=timezone.utc)
        result = _dt_to_str(dt)
        assert "2025-03-10" in result
        assert "08:00:00" in result

    def test_string_passthrough(self) -> None:
        from persistence.repository import _dt_to_str
        s = "2025-03-10T08:00:00+00:00"
        assert _dt_to_str(s) == s


class TestRunRowToSummary:
    """测试 run_row_to_summary() 行转摘要"""

    def test_basic_row(self) -> None:
        from persistence.repository import run_row_to_summary
        from datetime import datetime, timezone
        row = _make_row(
            id="db-id-001",
            status="completed",
            context={"app_run_id": "app-001", "config_path": "/cfg/p.yaml"},
            started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )
        result = run_row_to_summary(row)
        assert result["run_id"] == "app-001"
        assert result["status"] == "completed"
        assert result["pipeline"] == "/cfg/p.yaml"
        assert "2025-01-01" in result["started_at"]

    def test_string_context_parsed(self) -> None:
        from persistence.repository import run_row_to_summary
        row = _make_row(
            id="db-id-002",
            status="running",
            context='{"app_run_id": "app-002", "config_path": "/x.yaml"}',
            started_at=None,
            completed_at=None,
        )
        result = run_row_to_summary(row)
        assert result["run_id"] == "app-002"
        assert result["pipeline"] == "/x.yaml"

    def test_missing_context_fallback_to_id(self) -> None:
        from persistence.repository import run_row_to_summary
        row = _make_row(
            id="db-id-003",
            status="failed",
            context=None,
            started_at=None,
            completed_at=None,
        )
        result = run_row_to_summary(row)
        assert result["run_id"] == "db-id-003"
        assert result["pipeline"] is None

    def test_invalid_string_context(self) -> None:
        from persistence.repository import run_row_to_summary
        row = _make_row(
            id="db-id-004",
            status="pending",
            context="not-json",
            started_at=None,
            completed_at=None,
        )
        result = run_row_to_summary(row)
        assert result["run_id"] == "db-id-004"

    def test_empty_dict_context(self) -> None:
        from persistence.repository import run_row_to_summary
        row = _make_row(
            id="db-id-005",
            status="completed",
            context={},
            started_at=None,
            completed_at=None,
        )
        result = run_row_to_summary(row)
        assert result["run_id"] == "db-id-005"


class TestRunDetailToResponse:
    """测试 run_detail_to_response() 详细信息转 API 响应"""

    def test_full_detail(self) -> None:
        from persistence.repository import run_detail_to_response
        from datetime import datetime, timezone
        detail = {
            "id": "db-id-001",
            "status": "completed",
            "project_root": "/tmp/proj",
            "requirement": "add feature X",
            "worktree_path": "/tmp/wt",
            "context": {
                "app_run_id": "app-001",
                "config_source": "default",
                "config_path": "/cfg/p.yaml",
                "artifacts": ["/out/a.txt"],
            },
            "started_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "completed_at": datetime(2025, 1, 2, tzinfo=timezone.utc),
            "duration_seconds": 86400.0,
            "error_message": None,
            "stages": [
                {
                    "id": "stage-db-001",
                    "stage_id": "develop",
                    "stage_name": "开发",
                    "iteration": 1,
                    "status": "completed",
                    "is_parallel": False,
                    "started_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                    "completed_at": datetime(2025, 1, 2, tzinfo=timezone.utc),
                    "duration_seconds": 3600.0,
                    "output_dir": "/tmp/out",
                    "error_message": None,
                    "agents": [
                        {
                            "agent_name": "dev",
                            "runtime_id": "codex-runtime",
                            "runtime_cli": "codex",
                            "role": "developer",
                            "model_requested": "sonnet",
                            "model_used": "sonnet-4",
                            "status": "completed",
                            "started_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                            "completed_at": datetime(2025, 1, 2, tzinfo=timezone.utc),
                            "duration_seconds": 1800.0,
                            "output_file": "/tmp/out/dev.md",
                            "exit_code": 0,
                            "error_message": None,
                        }
                    ],
                    "quality_gates": [
                        {
                            "gate_name": "lint",
                            "gate_type": "command",
                            "status": "passed",
                            "command": "npm run lint",
                            "exit_code": 0,
                            "output": "OK",
                            "required": True,
                        }
                    ],
                }
            ],
        }
        result = run_detail_to_response(detail)
        assert result["run_id"] == "app-001"
        assert result["status"] == "completed"
        assert result["config_path"] == "/cfg/p.yaml"
        assert result["artifacts"] == ["/out/a.txt"]
        assert len(result["stages"]) == 1
        stage = result["stages"][0]
        assert stage["stage_id"] == "develop"
        assert len(stage["agents"]) == 1
        assert stage["agents"][0]["agent_name"] == "dev"
        assert stage["agents"][0]["runtime_id"] == "codex-runtime"
        assert stage["agents"][0]["runtime_cli"] == "codex"
        assert stage["agents"][0]["model_used"] == "sonnet-4"
        assert len(stage["quality_gates"]) == 1
        assert stage["quality_gates"][0]["name"] == "lint"
        assert stage["quality_gates"][0]["required"] is True

    def test_includes_stage_runtime_contract_fields(self) -> None:
        from persistence.repository import run_detail_to_response
        detail = {
            "id": "db-id-005",
            "status": "waiting",
            "project_root": "/tmp",
            "requirement": "req",
            "worktree_path": None,
            "context": {
                "app_run_id": "app-005",
                "artifacts": [],
                "human_decisions": [
                    {
                        "stage_id": "task_plan_confirm",
                        "decision": "rejected",
                        "reason": "任务缺少回滚方案",
                        "required_changes": ["补充回滚方案"],
                    }
                ],
            },
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "error_message": None,
            "stages": [
                {
                    "id": "stage-db-005",
                    "stage_id": "task_plan_confirm",
                    "stage_name": "任务计划确认",
                    "iteration": 1,
                    "stage_type": "human_review",
                    "status": "waiting",
                    "is_parallel": False,
                    "artifact_validations": [
                        {"artifact": "task-plan.json", "status": "failed", "message": "缺少回滚方案"}
                    ],
                    "human_decision": {
                        "stage_id": "task_plan_confirm",
                        "decision": "rejected",
                        "reason": "任务缺少回滚方案",
                        "required_changes": ["补充回滚方案"],
                    },
                    "loopback_to": "planning",
                    "started_at": None,
                    "completed_at": None,
                    "duration_seconds": None,
                    "output_dir": "/tmp/out",
                    "error_message": None,
                    "agents": [],
                    "quality_gates": [],
                }
            ],
        }

        result = run_detail_to_response(detail)

        assert result["human_decisions"][0]["reason"] == "任务缺少回滚方案"
        stage = result["stages"][0]
        assert stage["type"] == "human_review"
        assert stage["artifact_validations"][0]["artifact"] == "task-plan.json"
        assert stage["human_decision"]["decision"] == "rejected"
        assert stage["loopback_to"] == "planning"

    def test_string_context_parsed(self) -> None:
        from persistence.repository import run_detail_to_response
        detail = {
            "id": "db-id-002",
            "status": "failed",
            "project_root": "/tmp",
            "requirement": "req",
            "worktree_path": None,
            "context": '{"app_run_id": "app-002", "artifacts": []}',
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "error_message": "timeout",
            "stages": [],
        }
        result = run_detail_to_response(detail)
        assert result["run_id"] == "app-002"
        assert result["error_message"] == "timeout"
        assert result["stages"] == []

    def test_invalid_string_context_fallback(self) -> None:
        from persistence.repository import run_detail_to_response
        detail = {
            "id": "db-id-003",
            "status": "pending",
            "project_root": "/tmp",
            "requirement": "req",
            "worktree_path": None,
            "context": "not-json",
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "error_message": None,
            "stages": [],
        }
        result = run_detail_to_response(detail)
        assert result["run_id"] == "db-id-003"
        assert result["artifacts"] == []

    def test_none_context(self) -> None:
        from persistence.repository import run_detail_to_response
        detail = {
            "id": "db-id-004",
            "status": "completed",
            "project_root": "/tmp",
            "requirement": "req",
            "worktree_path": None,
            "context": None,
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "error_message": None,
            "stages": [],
        }
        result = run_detail_to_response(detail)
        assert result["run_id"] == "db-id-004"
        assert result["config_source"] is None


# ══════════════════════════════════════════════════════════════════════
# Repository 补充测试（未覆盖的方法）
# ══════════════════════════════════════════════════════════════════════


class TestPipelineRunRepoExtra:
    """测试 PipelineRunRepo 中未覆盖的方法"""

    def test_list_paginated_default(self, mock_conn: MagicMock) -> None:
        repo = PipelineRunRepo()
        mock_conn.fetch.return_value = [{"id": "run-1"}, {"id": "run-2"}]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.list_paginated(mock_conn))
            assert len(result) == 2
            call_args = mock_conn.fetch.call_args
            assert call_args[0][1] == 20
            assert call_args[0][2] == 0
        finally:
            loop.close()

    def test_list_paginated_page_2(self, mock_conn: MagicMock) -> None:
        repo = PipelineRunRepo()
        mock_conn.fetch.return_value = [{"id": "run-3"}]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.list_paginated(mock_conn, page=2, size=10))
            assert len(result) == 1
            call_args = mock_conn.fetch.call_args
            assert call_args[0][1] == 10
            assert call_args[0][2] == 10
        finally:
            loop.close()

    def test_update_status_basic(self, mock_conn: MagicMock) -> None:
        repo = PipelineRunRepo()
        mock_conn.execute.return_value = "UPDATE 1"

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.update_status(mock_conn, "run-001", "completed"))
            assert result is True
            call_args = mock_conn.execute.call_args
            assert "status = $2" in call_args[0][0]
            assert "WHERE id = $1" in call_args[0][0]
        finally:
            loop.close()

    def test_update_status_with_all_params(self, mock_conn: MagicMock) -> None:
        repo = PipelineRunRepo()
        mock_conn.execute.return_value = "UPDATE 1"

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                repo.update_status(
                    mock_conn,
                    "run-001",
                    "failed",
                    error_message="timeout",
                    completed_at="2025-01-01T00:00:00Z",
                    duration_seconds=120.5,
                )
            )
            assert result is True
            sql = mock_conn.execute.call_args[0][0]
            assert "error_message" in sql
            assert "completed_at" in sql
            assert "duration_seconds" in sql
        finally:
            loop.close()

    def test_update_status_no_rows_affected(self, mock_conn: MagicMock) -> None:
        repo = PipelineRunRepo()
        mock_conn.execute.return_value = "UPDATE 0"

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.update_status(mock_conn, "nonexistent", "completed"))
            assert result is False
        finally:
            loop.close()

    def test_create_pending(self, mock_conn: MagicMock) -> None:
        repo = PipelineRunRepo()
        mock_conn.execute.return_value = None

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                repo.create_pending(
                    mock_conn,
                    id="run-new",
                    pipeline_id="pipe-001",
                    project_root="/tmp",
                    main_branch="main",
                    requirement="do something",
                    trigger_source="api",
                    worktree_path="/tmp/wt",
                    app_run_id="app-new",
                )
            )
            assert mock_conn.execute.called
            sql = mock_conn.execute.call_args[0][0]
            assert "'pending'" in sql
        finally:
            loop.close()

    def test_create_pending_without_app_run_id(self, mock_conn: MagicMock) -> None:
        repo = PipelineRunRepo()
        mock_conn.execute.return_value = None

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                repo.create_pending(
                    mock_conn,
                    id="run-new-2",
                    pipeline_id=None,
                    project_root="/tmp",
                    main_branch="main",
                    requirement="do something",
                )
            )
            assert mock_conn.execute.called
        finally:
            loop.close()

    def test_get_run_with_details_returns_none(self, mock_conn: MagicMock) -> None:
        repo = PipelineRunRepo()
        mock_conn.fetchrow.return_value = None

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.get_run_with_details(mock_conn, "nonexistent"))
            assert result is None
        finally:
            loop.close()

    def test_get_run_with_details_returns_full_detail(self, mock_conn: MagicMock) -> None:
        repo = PipelineRunRepo()
        run_row = {"id": "run-001", "status": "completed"}
        stage_row = {"id": "stage-001", "stage_id": "develop"}
        agent_row = {"id": "agent-001", "agent_name": "dev"}
        gate_row = {"id": "gate-001", "gate_name": "lint"}

        mock_conn.fetchrow.return_value = run_row
        mock_conn.fetch.side_effect = [
            [stage_row],
            [agent_row],
            [gate_row],
        ]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.get_run_with_details(mock_conn, "run-001"))
            assert result is not None
            assert result["id"] == "run-001"
            assert len(result["stages"]) == 1
            assert result["stages"][0]["agents"] == [agent_row]
            assert result["stages"][0]["quality_gates"] == [gate_row]
        finally:
            loop.close()

    def test_run_exists_true(self, mock_conn: MagicMock) -> None:
        repo = PipelineRunRepo()
        mock_conn.fetchrow.return_value = {"1": 1}

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.run_exists(mock_conn, "run-001"))
            assert result is True
        finally:
            loop.close()

    def test_run_exists_false(self, mock_conn: MagicMock) -> None:
        repo = PipelineRunRepo()
        mock_conn.fetchrow.return_value = None

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.run_exists(mock_conn, "nonexistent"))
            assert result is False
        finally:
            loop.close()


class TestStageRunRepoExtra:
    """测试 StageRunRepo 中未覆盖的方法"""

    def test_list_by_run(self, mock_conn: MagicMock) -> None:
        repo = StageRunRepo()
        mock_conn.fetch.return_value = [
            {"id": "s1", "stage_id": "develop", "iteration": 1},
            {"id": "s2", "stage_id": "test", "iteration": 1},
        ]

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.list_by_run(mock_conn, "run-001"))
            assert len(result) == 2
            assert result[0]["stage_id"] == "develop"
        finally:
            loop.close()

    def test_list_by_run_empty(self, mock_conn: MagicMock) -> None:
        repo = StageRunRepo()
        mock_conn.fetch.return_value = []

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.list_by_run(mock_conn, "run-empty"))
            assert result == []
        finally:
            loop.close()

    def test_get_by_id_returns_record(self, mock_conn: MagicMock) -> None:
        repo = StageRunRepo()
        mock_conn.fetchrow.return_value = {"id": "stage-001", "stage_id": "develop", "status": "completed"}

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.get_by_id(mock_conn, "stage-001"))
            assert result is not None
            assert result["stage_id"] == "develop"
            assert result["status"] == "completed"
        finally:
            loop.close()

    def test_get_by_id_returns_none(self, mock_conn: MagicMock) -> None:
        repo = StageRunRepo()
        mock_conn.fetchrow.return_value = None

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(repo.get_by_id(mock_conn, "nonexistent"))
            assert result is None
        finally:
            loop.close()
