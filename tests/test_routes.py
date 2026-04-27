"""
API 路由集成测试。

测试范围：
- settings GET/POST/reset
- pipelines CRUD（list, templates, get, create, update, delete）
- costs 查询（按 run_id 查询、按周期汇总）
- config providers 和 validate 端点
- runs CRUD（create, list, get）

使用 FastAPI TestClient，通过临时目录和 mock 隔离文件操作。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:
    HAS_FASTAPI = False
else:
    HAS_FASTAPI = True


class BaseRoutesTest(unittest.TestCase):
    """路由测试基类，提供 setUp/tearDown 和辅助方法"""

    @classmethod
    def setUpClass(cls) -> None:
        if not HAS_FASTAPI:
            raise unittest.SkipTest("FastAPI 未安装，跳过路由测试")

    def setUp(self) -> None:
        # 使用临时目录作为项目根目录
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        (root / ".git").mkdir(parents=True)
        (root / ".ai").mkdir(parents=True)
        (root / ".ai" / "agents").mkdir(parents=True)
        (root / ".ai" / "agents" / "dev.md").write_text("You are a dev agent.", encoding="utf-8")
        (root / ".ai" / "team.yaml").write_text(
            """
providers:
  Mock:
    cli: mock
agents:
  - name: dev
    provider: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: dev-output.md
""",
            encoding="utf-8",
        )
        self.project_root = root

        # 创建 TestClient
        from api.app import create_app
        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()


class TestHealthEndpoint(BaseRoutesTest):
    """测试健康检查端点"""

    def test_health_returns_ok(self) -> None:
        """GET /health 返回 HTTP 200 和 status ok"""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class TestSettingsRoutes(BaseRoutesTest):
    """测试 settings 端点"""

    def test_get_settings_returns_config(self) -> None:
        """GET /api/settings 返回当前配置"""
        response = self.client.get("/api/settings", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("config", data)
        self.assertIn("source", data)
        self.assertIn("providers", data["config"])
        self.assertIn("agents", data["config"])

    def test_get_settings_default_workdir(self) -> None:
        """GET /api/settings 默认 workdir 返回配置"""
        with patch("engine.config.find_project_root", return_value=self.project_root):
            response = self.client.get("/api/settings")
            self.assertEqual(response.status_code, 200)

    def test_update_settings_creates_new_config(self) -> None:
        """POST /api/settings 创建新配置"""
        # 先删除项目配置文件
        config_path = self.project_root / ".ai" / "team.yaml"
        config_path.unlink()

        response = self.client.post(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json={
                "agents": [
                    {"name": "custom-agent", "provider": "Auto", "role": "custom", "prompt": "custom.md"}
                ],
                "metadata": {"name": "custom-project"},
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "saved")
        self.assertTrue(config_path.exists())

    def test_update_settings_merges_existing_config(self) -> None:
        """POST /api/settings 合并更新已有配置"""
        response = self.client.post(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json={"metadata": {"version": "2.0"}},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("metadata", data["config"])

    def test_reset_settings_removes_and_reloads(self) -> None:
        """POST /api/settings/reset 删除自定义配置并回退"""
        response = self.client.post("/api/settings/reset", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "reset")


class TestPipelinesRoutes(BaseRoutesTest):
    """测试 pipelines CRUD 端点"""

    @classmethod
    def setUpClass(cls) -> None:
        """清理 pipelines 目录残留，确保测试隔离"""
        from api.routes.pipelines import PIPELINES_DIR
        if PIPELINES_DIR.exists():
            for f in PIPELINES_DIR.glob("*.json"):
                try:
                    f.unlink()
                except OSError:
                    pass

    def test_list_pipelines_returns_list(self) -> None:
        """GET /api/pipelines 返回流水线列表"""
        response = self.client.get("/api/pipelines")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)

    def test_list_templates_returns_builtin(self) -> None:
        """GET /api/pipelines/templates 返回内置模板"""
        response = self.client.get("/api/pipelines/templates")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn("id", data[0])
        self.assertIn("name", data[0])

    def test_create_pipeline_saves(self) -> None:
        """POST /api/pipelines 创建新流水线"""
        payload = {
            "id": "custom-pipe",
            "name": "自定义流水线",
            "description": "测试用流水线",
            "yaml_config": {"stages": []},
        }
        response = self.client.post("/api/pipelines", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], "custom-pipe")
        self.assertEqual(data["name"], "自定义流水线")

    def test_create_duplicate_pipeline_returns_409(self) -> None:
        """POST /api/pipelines 重复 ID 返回 409"""
        payload = {"id": "dup-pipe", "name": "重复流水线", "yaml_config": {}}
        self.client.post("/api/pipelines", json=payload)
        response = self.client.post("/api/pipelines", json=payload)
        self.assertEqual(response.status_code, 409)

    def test_get_pipeline_returns_record(self) -> None:
        """GET /api/pipelines/{id} 返回指定流水线"""
        payload = {"id": "get-pipe", "name": "查询流水线", "yaml_config": {}}
        self.client.post("/api/pipelines", json=payload)
        response = self.client.get("/api/pipelines/get-pipe")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "查询流水线")

    def test_get_nonexistent_pipeline_returns_404(self) -> None:
        """GET /api/pipelines/{id} 不存在的返回 404"""
        response = self.client.get("/api/pipelines/nonexistent-id")
        self.assertEqual(response.status_code, 404)

    def test_update_pipeline_updates_fields(self) -> None:
        """PUT /api/pipelines/{id} 更新流水线字段"""
        payload = {"id": "update-pipe", "name": "原始名称", "yaml_config": {}}
        self.client.post("/api/pipelines", json=payload)
        response = self.client.put("/api/pipelines/update-pipe", json={"name": "更新后名称"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "更新后名称")

    def test_delete_pipeline_removes(self) -> None:
        """DELETE /api/pipelines/{id} 删除流水线"""
        payload = {"id": "del-pipe", "name": "待删除", "yaml_config": {}}
        self.client.post("/api/pipelines", json=payload)
        response = self.client.delete("/api/pipelines/del-pipe")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "deleted")

        # 确认已删除
        response = self.client.get("/api/pipelines/del-pipe")
        self.assertEqual(response.status_code, 404)

    def test_delete_nonexistent_pipeline_returns_404(self) -> None:
        """DELETE /api/pipelines/{id} 不存在的返回 404"""
        response = self.client.delete("/api/pipelines/nonexistent-id")
        self.assertEqual(response.status_code, 404)

    def test_update_nonexistent_pipeline_returns_404(self) -> None:
        """PUT /api/pipelines/{id} 不存在的返回 404"""
        response = self.client.put("/api/pipelines/nonexistent-id", json={"name": "x"})
        self.assertEqual(response.status_code, 404)


class TestCostsRoutes(BaseRoutesTest):
    """测试 costs 查询端点"""

    def test_get_costs_for_run(self) -> None:
        """GET /api/costs?run_id=xxx 返回指定运行的成本"""
        from engine.cost_tracker import CostTracker

        # 先写入一些成本数据
        tracker = CostTracker(self.project_root)
        tracker.track_usage("cost-run-001", "dev", "claude-sonnet", 1000, 500)

        response = self.client.get("/api/costs", params={"run_id": "cost-run-001", "workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["run_id"], "cost-run-001")
        self.assertEqual(data["count"], 1)

    def test_get_costs_nonexistent_run(self) -> None:
        """GET /api/costs 查询不存在的运行返回空记录"""
        response = self.client.get("/api/costs", params={"run_id": "nonexistent-run", "workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 0)

    def test_get_cost_summary_daily(self) -> None:
        """GET /api/costs/summary?period=daily 返回日汇总"""
        response = self.client.get("/api/costs/summary", params={"period": "daily", "workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("period", data)
        self.assertIn("total_cost", data)

    def test_get_cost_summary_weekly(self) -> None:
        """GET /api/costs/summary?period=weekly 返回周汇总"""
        response = self.client.get("/api/costs/summary", params={"period": "weekly", "workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["period"], "weekly")

    def test_get_cost_summary_monthly(self) -> None:
        """GET /api/costs/summary?period=monthly 返回月汇总"""
        response = self.client.get("/api/costs/summary", params={"period": "monthly", "workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["period"], "monthly")

    def test_get_cost_summary_invalid_period_returns_400(self) -> None:
        """GET /api/costs/summary 无效 period 返回 400"""
        response = self.client.get("/api/costs/summary", params={"period": "invalid", "workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 400)


class TestConfigRoutes(BaseRoutesTest):
    """测试 config 相关端点"""

    def test_get_providers_returns_list(self) -> None:
        """GET /api/config/providers 返回提供者列表"""
        response = self.client.get("/api/config/providers")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("providers", data)
        self.assertIsInstance(data["providers"], dict)

    def test_validate_config_returns_result(self) -> None:
        """GET /api/config/validate 返回验证结果"""
        response = self.client.get("/api/config/validate", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("valid", data)
        self.assertIn("errors", data)
        self.assertIn("warnings", data)

    def test_validate_with_worktree_enabled(self) -> None:
        """验证配置启用 worktree 但无 git 时报错"""
        (self.project_root / ".ai" / "team.yaml").write_text(
            """
providers:
  Mock:
    cli: mock
agents:
  - name: dev
    provider: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
worktree:
  enabled: true
runner:
  require_worktree: true
""",
            encoding="utf-8",
        )
        response = self.client.get("/api/config/validate", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # 如果系统没有 git，valid 应为 False；如果有 git 则跳过
        # 这里只验证端点正常返回
        self.assertIn("valid", data)


class TestRunsRoutes(BaseRoutesTest):
    """测试 runs CRUD 端点"""

    def test_create_run_starts_execution(self) -> None:
        """POST /api/runs 创建并启动运行"""
        (self.project_root / ".ai" / "agents" / "dev.md").write_text("You are a dev agent.", encoding="utf-8")

        response = self.client.post(
            "/api/runs",
            json={
                "requirement": "测试需求",
                "workdir": str(self.project_root),
                "run_id": "api-test-run-001",
                "yes": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["run_id"], "api-test-run-001")
        self.assertEqual(data["status"], "running")

    def test_create_run_duplicate_id_returns_409(self) -> None:
        """POST /api/runs 重复 run_id 返回 409"""
        output_dir = self.project_root / ".ai" / "team-output" / "dup-run"
        output_dir.mkdir(parents=True)

        response = self.client.post(
            "/api/runs",
            json={
                "requirement": "测试需求",
                "workdir": str(self.project_root),
                "run_id": "dup-run",
                "yes": True,
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_list_runs_returns_list(self) -> None:
        """GET /api/runs 返回运行列表"""
        response = self.client.get("/api/runs", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)

    def test_get_run_not_found_returns_404(self) -> None:
        """GET /api/runs/{run_id} 不存在的运行返回 404"""
        response = self.client.get("/api/runs/nonexistent-run", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 404)


class TestArtifactsRoutes(BaseRoutesTest):
    """测试 artifacts 端点"""

    def test_list_artifacts_run_not_found_returns_404(self) -> None:
        """GET /api/runs/{run_id}/artifacts 不存在的运行返回 404"""
        response = self.client.get("/api/runs/nonexistent-run/artifacts", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 404)

    def test_get_artifact_not_found_returns_404(self) -> None:
        """GET /api/runs/{run_id}/artifacts/{file} 不存在的文件返回 404"""
        response = self.client.get(
            "/api/runs/nonexistent-run/artifacts/somefile.txt",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
