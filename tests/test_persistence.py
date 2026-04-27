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
                    provider="claude",
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


class TestAgentRunRecord:
    """测试 AgentRunRecord"""

    def test_from_row_basic(self) -> None:
        from persistence.models import AgentRunRecord
        row = _make_row(
            id="a1", stage_run_id="s1", agent_name="dev",
            provider="claude", role="developer", status="completed",
            output_file=None, raw_log_file=None, exit_code=0,
            error_message=None, started_at=None, completed_at=None,
            duration_seconds=3.0,
        )
        record = AgentRunRecord.from_row(row)
        assert record.agent_name == "dev"
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
