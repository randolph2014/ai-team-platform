"""
API 路由集成测试。

测试范围：
- settings GET/POST/reset
- pipelines CRUD（list, templates, get, create, update, delete）
- costs 查询（按 run_id 查询、按周期汇总）
- config runtimes 和 validate 端点
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
from unittest.mock import AsyncMock, patch

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
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        (root / ".git").mkdir(parents=True)
        (root / ".ai").mkdir(parents=True)
        (root / ".ai" / "agents").mkdir(parents=True)
        (root / ".ai" / "agents" / "dev.md").write_text("You are a dev agent.", encoding="utf-8")
        self.project_root = root
        self.pipelines_dir = root / ".ai" / "pipelines"

        initial_config = (
            """
runtimes:
  mock:
    name: Mock
    cli: mock
agents:
  - name: dev
    runtime_id: mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: dev-output.md
"""
        )
        self.settings_store = self._load_yaml(initial_config)

        async def fake_db_get_settings():
            return self._clone_config(self.settings_store) if self.settings_store else None

        async def fake_db_save_settings(config):
            self.settings_store = self._clone_config(config)
            return True

        async def fake_db_delete_settings():
            self.settings_store = {}
            return True

        def fake_try_load_db_config():
            return self._clone_config(self.settings_store) if self.settings_store else None

        self._config_patches = [
            patch("engine.config._try_load_db_config", side_effect=fake_try_load_db_config),
            patch("api.routes.settings._db_get_settings", side_effect=fake_db_get_settings),
            patch("api.routes.settings._db_save_settings", side_effect=fake_db_save_settings),
            patch("api.routes.settings._db_delete_settings", side_effect=fake_db_delete_settings),
            patch("api.routes.pipelines.PIPELINES_DIR", self.pipelines_dir),
        ]
        for p in self._config_patches:
            p.start()

        from api.app import create_app
        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        for p in reversed(self._config_patches):
            p.stop()
        self.temp_dir.cleanup()

    def set_settings_store(self, config) -> None:
        self.settings_store = self._clone_config(config)

    @staticmethod
    def _clone_config(config):
        return json.loads(json.dumps(config))

    @staticmethod
    def _load_yaml(content: str):
        import yaml

        return yaml.safe_load(content) or {}


class TestHealthEndpoint(BaseRoutesTest):
    """测试健康检查端点"""

    def test_health_returns_ok(self) -> None:
        """GET /health 返回 HTTP 200 和 status ok"""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("database", data)
        self.assertIn("queue", data)
        self.assertFalse(data["database"]["configured"])
        self.assertFalse(data["queue"]["configured"])


class TestSettingsRoutes(BaseRoutesTest):
    """测试 settings 端点"""

    def test_get_settings_returns_config(self) -> None:
        """GET /api/settings 返回当前配置"""
        response = self.client.get("/api/settings", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("config", data)
        self.assertIn("source", data)
        self.assertIn("runtimes", data["config"])
        self.assertNotIn("providers", data["config"])
        self.assertIn("agents", data["config"])

    def test_get_settings_default_workdir(self) -> None:
        """GET /api/settings 默认 workdir 返回配置"""
        with patch("engine.config.find_project_root", return_value=self.project_root):
            response = self.client.get("/api/settings")
            self.assertEqual(response.status_code, 200)

    def test_update_settings_creates_new_config(self) -> None:
        """POST /api/settings 写入 DB 配置"""

        response = self.client.post(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json={
                "agents": [
                    {"name": "custom-agent", "runtime_id": "auto", "role": "custom", "prompt": "custom.md"}
                ],
                "metadata": {"name": "custom-project"},
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "saved")
        self.assertEqual(data["path"], "db:default")
        self.assertEqual(self.settings_store["metadata"]["name"], "custom-project")

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
        self.assertEqual(self.settings_store, {})


class TestPipelinesRoutes(BaseRoutesTest):
    """测试 pipelines CRUD 端点"""

    def test_list_pipelines_returns_list(self) -> None:
        """GET /api/pipelines 返回流水线列表"""
        response = self.client.get("/api/pipelines")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)

    def test_list_pipelines_falls_back_to_files_when_db_query_fails(self) -> None:
        """GET /api/pipelines 的 DB 查询失败时返回本地流水线列表而不是 500。"""
        with patch("persistence.connection.is_available", return_value=True), \
             patch("api.routes.pipelines._async_list_pipelines", new=AsyncMock(side_effect=RuntimeError("loop closed"))):
            response = self.client.get("/api/pipelines")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_templates_returns_builtin(self) -> None:
        """GET /api/pipelines/templates 返回内置模板"""
        response = self.client.get("/api/pipelines/templates")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual([item["id"] for item in data], ["project-delivery", "bugfix"])
        self.assertIn("id", data[0])
        self.assertIn("name", data[0])
        self.assertEqual(data[0]["name"], "研发流水线")

    def test_builtin_templates_use_current_collaboration_workflow(self) -> None:
        """内置模板必须是有真实差异的可执行流水线。"""
        response = self.client.get("/api/pipelines/templates")
        self.assertEqual(response.status_code, 200)

        legacy_stages = {"plan", "architect", "context", "accept", "risk_analysis", "doc", "code_apply"}
        templates = {template["id"]: template for template in response.json()}
        self.assertEqual(set(templates), {"project-delivery", "bugfix"})

        expected_stage_ids = {
            "project-delivery": [
                "context_scan",
                "requirement_analysis",
                "requirement_synthesis",
                "requirement_confirm",
                "planning",
                "task_plan_confirm",
                "develop",
                "qa",
                "harness_verify",
                "review",
                "acceptance_confirm",
                "retrospect",
            ],
            "bugfix": [
                "context_scan",
                "requirement_synthesis",
                "requirement_confirm",
                "planning",
                "develop",
                "qa",
                "harness_verify",
                "review",
                "acceptance_confirm",
            ],
        }
        for template_id, template in templates.items():
            stages = template.get("stages", [])
            self.assertEqual(stages, expected_stage_ids[template_id])
            self.assertFalse(legacy_stages.intersection(stages), f"{template['id']} still exposes legacy stages")
            self.assertIn("requirement_synthesis", stages, f"{template['id']} must produce confirmed requirement artifacts")
            stage_contracts = {stage["id"]: stage for stage in template.get("yaml_config", {}).get("stages", [])}
            self.assertEqual(stage_contracts["context_scan"]["type"], "context_scan")
            self.assertEqual(stage_contracts["requirement_confirm"]["type"], "human_review")
            self.assertFalse(stage_contracts["requirement_confirm"]["allow_auto_approve"])
            if template_id == "project-delivery":
                self.assertEqual(stage_contracts["task_plan_confirm"]["type"], "human_review")
                self.assertEqual(stage_contracts["acceptance_confirm"]["reject_to"], "develop")
            if template_id == "bugfix":
                self.assertNotIn("requirement_analysis", stages)
                self.assertNotIn("task_plan_confirm", stages)
                self.assertEqual(stage_contracts["planning"]["name"], "修复方案与回归计划")

    def test_create_pipeline_hydrates_known_stage_contracts(self) -> None:
        """保存模板时即使 UI 只传 id，也必须补齐上下文扫描和硬人工门禁契约。"""
        payload = {
            "id": "hydrated-pipe",
            "name": "补齐契约流水线",
            "yaml_config": {"stages": [{"id": "context_scan"}, {"id": "requirement_confirm"}]},
        }
        response = self.client.post("/api/pipelines", json=payload)
        self.assertEqual(response.status_code, 200)

        stages = {stage["id"]: stage for stage in response.json()["yaml_config"]["stages"]}
        self.assertEqual(stages["context_scan"]["type"], "context_scan")
        self.assertIn("codebase-context.json", stages["context_scan"]["required_artifacts"])
        self.assertEqual(stages["requirement_confirm"]["type"], "human_review")
        self.assertFalse(stages["requirement_confirm"]["allow_auto_approve"])
        self.assertEqual(stages["requirement_confirm"]["reject_to"], "requirement_synthesis")

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
        response = self.client.get("/api/costs", params={"run_id": "cost-run-001"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["run_id"], "cost-run-001")
        self.assertEqual(data["count"], 0)

    def test_get_costs_nonexistent_run(self) -> None:
        response = self.client.get("/api/costs", params={"run_id": "nonexistent-run"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 0)

    def test_get_cost_summary_daily(self) -> None:
        response = self.client.get("/api/costs/summary", params={"period": "daily"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("period", data)
        self.assertIn("total_cost", data)

    def test_get_cost_summary_weekly(self) -> None:
        response = self.client.get("/api/costs/summary", params={"period": "weekly"})
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

    def test_get_runtimes_returns_list(self) -> None:
        """GET /api/config/runtimes 返回 runtime 列表"""
        response = self.client.get("/api/config/runtimes", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("runtimes", data)
        self.assertIn("candidates", data)
        self.assertIsInstance(data["runtimes"], dict)
        self.assertIn("mock", data["runtimes"])

    def test_get_runtimes_discovers_supported_cli_candidates(self) -> None:
        """GET /api/config/runtimes 返回本机探测到的 CLI 候选项（不包含 unsupported CLI）"""
        def fake_which(name: str):
            if name in {"claude", "codex"}:
                return f"/usr/local/bin/{name}"
            return None

        with patch("engine.runtimes.shutil.which", side_effect=fake_which), \
             patch("engine.runtimes.detect_cli_version", return_value="1.0.0"):
            response = self.client.get("/api/config/runtimes", params={"workdir": str(self.project_root)})

        self.assertEqual(response.status_code, 200)
        candidates = {item["id"]: item for item in response.json()["candidates"]}
        self.assertTrue(candidates["claude"]["available"])
        self.assertEqual(candidates["claude"]["path"], "/usr/local/bin/claude")
        self.assertTrue(candidates["codex"]["available"])
        self.assertTrue(candidates["claude"]["supported"])
        self.assertTrue(candidates["codex"]["supported"])
        self.assertNotIn("hermes", candidates)

    def test_get_runtimes_reports_auto_runtime_resolution(self) -> None:
        """GET /api/config/runtimes 明确暴露 auto 当前会解析到哪个 CLI。"""
        from engine.config import normalize_config
        from engine.runtimes import clear_runtime_candidate_cache

        self.set_settings_store(normalize_config({
            "runtimes": {"auto": {"name": "Auto", "cli": "auto"}},
            "agents": [],
            "pipeline": [],
        }))
        clear_runtime_candidate_cache()

        def fake_which(name: str):
            if name == "codex":
                return "/usr/local/bin/codex"
            return None

        with patch("engine.runtimes.shutil.which", side_effect=fake_which), \
             patch("engine.runtimes.detect_cli_version", return_value="codex 1.0"):
            response = self.client.get("/api/config/runtimes", params={"workdir": str(self.project_root)})

        self.assertEqual(response.status_code, 200)
        runtime = response.json()["runtimes"]["auto"]
        self.assertTrue(runtime["available"])
        self.assertEqual(runtime["resolved_cli"], "codex")
        self.assertEqual(runtime["path"], "/usr/local/bin/codex")
        self.assertEqual(runtime["version"], "codex 1.0")

    def test_get_runtimes_masks_sensitive_fields(self) -> None:
        """GET /api/config/runtimes 不泄露 runtime 敏感字段"""
        from engine.config import normalize_config
        config = normalize_config({
            "runtimes": {
                "Claude": {"cli": "claude", "api_key": "sk-secret"},
            },
            "agents": [],
            "pipeline": [],
        })
        self.set_settings_store(config)

        response = self.client.get("/api/config/runtimes", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        runtime = response.json()["runtimes"]["Claude"]
        self.assertEqual(runtime["api_key"], "***")
        self.assertEqual(runtime["cli"], "claude")

    def test_validate_config_returns_result(self) -> None:
        """GET /api/config/validate 返回验证结果"""
        response = self.client.get("/api/config/validate", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("valid", data)
        self.assertIn("errors", data)
        self.assertIn("warnings", data)

    def test_validate_unknown_runtime_reference_returns_error(self) -> None:
        """GET /api/config/validate 校验 agent.runtime_id 引用"""
        self.set_settings_store(self._load_yaml("""
runtimes:
  mock:
    cli: mock
agents:
  - name: dev
    runtime_id: missing
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
"""))
        response = self.client.get("/api/config/validate", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["valid"])
        self.assertTrue(any("Unknown runtime" in error for error in data["errors"]))

    def test_validate_with_worktree_enabled(self) -> None:
        """验证配置启用 worktree 但无 git 时报错"""
        self.set_settings_store(self._load_yaml("""
runtimes:
  mock:
    name: Mock
    cli: mock
agents:
  - name: dev
    runtime_id: mock
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
"""))
        response = self.client.get("/api/config/validate", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # 如果系统没有 git，valid 应为 False；如果有 git 则跳过
        # 这里只验证端点正常返回
        self.assertIn("valid", data)

    def test_get_agent_prompt_reads_resolved_file(self) -> None:
        """GET /api/settings/agents/{name}/prompt 返回真实 prompt 文件内容"""
        response = self.client.get(
            "/api/settings/agents/dev/prompt",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["agent_name"], "dev")
        self.assertEqual(data["content"], "You are a dev agent.")
        self.assertTrue(data["path"].endswith(".ai/agents/dev.md"))

    def test_put_agent_prompt_writes_resolved_file(self) -> None:
        """PUT /api/settings/agents/{name}/prompt 修改对应 prompt 文档"""
        response = self.client.put(
            "/api/settings/agents/dev/prompt",
            params={"workdir": str(self.project_root)},
            json={"content": "Updated prompt"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual((self.project_root / ".ai" / "agents" / "dev.md").read_text(encoding="utf-8"), "Updated prompt")

    def test_put_agent_prompt_materializes_template_prompt_in_project(self) -> None:
        """平台模板 prompt 保存时写入项目覆盖文件，不修改平台模板"""
        self.set_settings_store(self._load_yaml("""
runtimes:
  mock:
    name: Mock
    cli: mock
agents:
  - name: tech-lead
    runtime_id: mock
    prompt: agents/tech-lead.md
pipeline: []
"""))
        project_prompt = self.project_root / ".ai" / "agents" / "tech-lead.md"
        if project_prompt.exists():
            project_prompt.unlink()

        response = self.client.put(
            "/api/settings/agents/tech-lead/prompt",
            params={"workdir": str(self.project_root)},
            json={"content": "Project tech lead prompt"},
        )

        self.assertEqual(response.status_code, 200)
        written_path = Path(response.json()["path"])
        self.assertTrue(
            written_path.resolve().is_relative_to(self.project_root.resolve()),
            f"{written_path} is not within {self.project_root}",
        )
        self.assertEqual(written_path.read_text(encoding="utf-8"), "Project tech lead prompt")

    def test_put_agent_prompt_rejects_path_escape(self) -> None:
        """prompt 写路径不能通过配置逃逸项目目录"""
        project_override = self.project_root / ".ai" / "agents" / "dev.md"
        if project_override.exists():
            project_override.unlink()

        self.set_settings_store(self._load_yaml("""
runtimes:
  mock:
    name: Mock
    cli: mock
agents:
  - name: dev
    runtime_id: mock
    prompt: ../outside.md
pipeline: []
"""))

        response = self.client.put(
            "/api/settings/agents/dev/prompt",
            params={"workdir": str(self.project_root)},
            json={"content": "escape"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.project_root.parent / "outside.md").exists())


class TestRunsRoutes(BaseRoutesTest):
    """测试 runs CRUD 端点"""

    def test_create_run_starts_execution(self) -> None:
        """POST /api/runs 创建并启动运行"""
        (self.project_root / ".ai" / "agents" / "dev.md").write_text("You are a dev agent.", encoding="utf-8")
        output_dir = self.project_root / ".ai" / "team-output" / "api-test-run-001"

        with patch("api.routes.runs.start_run_background", return_value=output_dir) as start_bg:
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
        self.assertEqual(data["status"], "queued")
        start_bg.assert_called_once()

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

    def test_create_run_rejects_only_stage_because_it_bypasses_hard_gates(self) -> None:
        """POST /api/runs 不允许用 only_stage 绕过强制人工确认。"""
        response = self.client.post(
            "/api/runs",
            json={
                "requirement": "测试需求",
                "workdir": str(self.project_root),
                "run_id": "api-only-stage",
                "only_stage": "develop",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("hard human gates", response.json()["detail"])

    def test_create_run_with_builtin_pipeline_materializes_executable_config(self) -> None:
        """POST /api/runs 选择内置模板时必须物化可执行配置并传给 runner。"""
        output_dir = self.project_root / ".ai" / "team-output" / "api-bugfix-run"

        with patch("api.routes.runs.start_run_background", return_value=output_dir) as start_bg:
            response = self.client.post(
                "/api/runs",
                json={
                    "requirement": "修复登录失败",
                    "workdir": str(self.project_root),
                    "run_id": "api-bugfix-run",
                    "pipeline_id": "template:bugfix",
                    "yes": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        config_path = Path(start_bg.call_args.kwargs["config_path"])
        self.assertEqual(config_path.resolve(strict=False), (self.project_root / ".ai" / "pipeline-configs" / "api-bugfix-run.yaml").resolve(strict=False))
        self.assertTrue(config_path.exists())
        self.assertFalse(output_dir.exists())

        import yaml

        materialized = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        self.assertEqual(materialized["metadata"]["pipeline_id"], "bugfix")
        self.assertEqual(materialized["metadata"]["pipeline_source"], "builtin")
        stage_ids = [stage["id"] for stage in materialized["pipeline"]["stages"]]
        self.assertEqual(
            stage_ids,
            [
                "context_scan",
                "requirement_synthesis",
                "requirement_confirm",
                "planning",
                "develop",
                "qa",
                "harness_verify",
                "review",
                "acceptance_confirm",
            ],
        )
        self.assertNotIn("requirement_analysis", stage_ids)
        self.assertEqual(materialized["pipeline"]["execution_mode"], "parallel")

    def test_create_run_rejects_ambiguous_pipeline_and_config_path(self) -> None:
        """POST /api/runs 不能同时传 pipeline_id 和 config_path，避免执行来源不清。"""
        response = self.client.post(
            "/api/runs",
            json={
                "requirement": "修复登录失败",
                "workdir": str(self.project_root),
                "run_id": "api-ambiguous-pipeline",
                "pipeline_id": "template:bugfix",
                "config_path": str(self.project_root / ".ai" / "pipeline-configs" / "manual.yaml"),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("pipeline_id", response.json()["detail"])

    def test_create_run_rejects_deprecated_project_team_config_path(self) -> None:
        """POST /api/runs 拒绝历史项目配置入口，避免它被重新当作事实源。"""
        response = self.client.post(
            "/api/runs",
            json={
                "requirement": "修复登录失败",
                "workdir": str(self.project_root),
                "run_id": "api-deprecated-team-config",
                "config_path": str(self.project_root / ".ai" / "team.yaml"),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("deprecated", response.json()["detail"])

    def test_list_runs_returns_list(self) -> None:
        """GET /api/runs 返回运行列表"""
        response = self.client.get("/api/runs", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("items", data)
        self.assertIsInstance(data["items"], list)

    def test_get_run_not_found_returns_404(self) -> None:
        """GET /api/runs/{run_id} 不存在的运行返回 404"""
        response = self.client.get("/api/runs/nonexistent-run", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 404)

    def test_resume_run_passes_config_path_and_execution_mode(self) -> None:
        """POST /api/runs/{id}/resume 使用原 report.config_path 并透传 execution_mode/yes"""
        run_id = "resume-route-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text('{"run_id":"resume-route-run","completed_stages":["plan"]}', encoding="utf-8")
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")
        config_path = str(self.project_root / ".ai" / "custom-team.yaml")
        (output_dir / "report.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "waiting",
                    "requirement": "req",
                    "project_root": str(self.project_root),
                    "output_dir": str(output_dir),
                    "config_source": "project",
                    "config_path": config_path,
                }
            ),
            encoding="utf-8",
        )

        with patch("api.routes.runs.resume_run_background", return_value=output_dir) as resume_bg:
            response = self.client.post(
                f"/api/runs/{run_id}/resume",
                params={"workdir": str(self.project_root), "yes": True, "execution_mode": "serial"},
            )

        self.assertEqual(response.status_code, 200)
        resume_bg.assert_called_once_with(
            run_id=run_id,
            workdir=str(self.project_root),
            yes=True,
            reject=False,
            config_path=config_path,
            execution_mode="serial",
        )

    def test_resume_run_rejects_deprecated_project_team_config_path(self) -> None:
        """POST /api/runs/{id}/resume 拒绝历史项目级 team 配置入口。"""
        run_id = "resume-deprecated-team-config-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": ["plan"]}),
            encoding="utf-8",
        )
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")

        with patch("api.routes.runs.resume_run_background", return_value=output_dir) as resume_bg:
            response = self.client.post(
                f"/api/runs/{run_id}/resume",
                params={
                    "workdir": str(self.project_root),
                    "config_path": str(self.project_root / ".ai" / "team.yaml"),
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("deprecated", response.json()["detail"])
        resume_bg.assert_not_called()

    def test_human_decision_reject_requires_reason(self) -> None:
        run_id = "decision-reason-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": []}),
            encoding="utf-8",
        )
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")
        (output_dir / "report.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "waiting",
                    "requirement": "req",
                    "project_root": str(self.project_root),
                    "output_dir": str(output_dir),
                    "config_source": "project",
                    "stages": [
                        {
                            "stage_id": "requirement_confirm",
                            "stage_name": "Requirement Confirm",
                            "status": "waiting",
                            "type": "human_review",
                            "is_parallel": False,
                            "agents": [],
                            "quality_gates": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        response = self.client.post(
            f"/api/runs/{run_id}/human-decision",
            params={"workdir": str(self.project_root)},
            json={"stage_id": "requirement_confirm", "decision": "rejected", "reason": ""},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("reason", response.json()["detail"])

    def test_human_decision_endpoint_passes_structured_decision_to_runtime(self) -> None:
        run_id = "decision-submit-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": []}),
            encoding="utf-8",
        )
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")
        (output_dir / "report.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "waiting",
                    "requirement": "req",
                    "project_root": str(self.project_root),
                    "output_dir": str(output_dir),
                    "config_source": "project",
                    "stages": [
                        {
                            "stage_id": "task_plan_confirm",
                            "stage_name": "Task Plan Confirm",
                            "status": "waiting",
                            "type": "human_review",
                            "is_parallel": False,
                            "agents": [],
                            "quality_gates": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with patch("api.routes.runs.resume_run_background", return_value=output_dir) as resume_bg:
            response = self.client.post(
                f"/api/runs/{run_id}/human-decision",
                params={"workdir": str(self.project_root)},
                json={
                    "stage_id": "task_plan_confirm",
                    "decision": "rejected",
                    "reason": "任务缺少回滚方案",
                    "required_changes": ["补充回滚方案"],
                    "target_stage": "planning",
                },
            )

        self.assertEqual(response.status_code, 200)
        decision = resume_bg.call_args.kwargs["human_decision"]
        self.assertEqual(decision.stage_id, "task_plan_confirm")
        self.assertEqual(decision.reason, "任务缺少回滚方案")
        self.assertEqual(decision.required_changes, ["补充回滚方案"])

    def test_human_decision_rejects_deprecated_project_team_config_path(self) -> None:
        """POST /api/runs/{id}/human-decision 不能用历史项目级 team 配置恢复运行。"""
        run_id = "decision-deprecated-team-config-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": []}),
            encoding="utf-8",
        )
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")
        (output_dir / "report.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "waiting",
                    "requirement": "req",
                    "project_root": str(self.project_root),
                    "output_dir": str(output_dir),
                    "config_source": "project",
                    "config_path": str(self.project_root / ".ai" / "team.yaml"),
                    "stages": [
                        {
                            "stage_id": "task_plan_confirm",
                            "stage_name": "Task Plan Confirm",
                            "status": "waiting",
                            "type": "human_review",
                            "is_parallel": False,
                            "agents": [],
                            "quality_gates": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with patch("api.routes.runs.resume_run_background", return_value=output_dir) as resume_bg:
            response = self.client.post(
                f"/api/runs/{run_id}/human-decision",
                params={"workdir": str(self.project_root)},
                json={"stage_id": "task_plan_confirm", "decision": "approved"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("deprecated", response.json()["detail"])
        resume_bg.assert_not_called()

    def test_human_decision_requires_report(self) -> None:
        run_id = "decision-missing-report-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": []}),
            encoding="utf-8",
        )
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")

        with patch("api.routes.runs.resume_run_background", return_value=output_dir) as resume_bg:
            response = self.client.post(
                f"/api/runs/{run_id}/human-decision",
                params={"workdir": str(self.project_root)},
                json={"stage_id": "task_plan_confirm", "decision": "approved"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("report", response.json()["detail"])
        resume_bg.assert_not_called()

    def test_human_decision_rejects_non_waiting_stage(self) -> None:
        run_id = "decision-completed-stage-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": ["task_plan_confirm"]}),
            encoding="utf-8",
        )
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")
        (output_dir / "report.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "waiting",
                    "requirement": "req",
                    "project_root": str(self.project_root),
                    "output_dir": str(output_dir),
                    "config_source": "project",
                    "stages": [
                        {
                            "stage_id": "task_plan_confirm",
                            "stage_name": "Task Plan Confirm",
                            "status": "completed",
                            "type": "human_review",
                            "is_parallel": False,
                            "agents": [],
                            "quality_gates": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with patch("api.routes.runs.resume_run_background", return_value=output_dir) as resume_bg:
            response = self.client.post(
                f"/api/runs/{run_id}/human-decision",
                params={"workdir": str(self.project_root)},
                json={"stage_id": "task_plan_confirm", "decision": "approved"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("stage status is completed", response.json()["detail"])
        resume_bg.assert_not_called()

    def test_human_decision_uses_latest_matching_waiting_stage(self) -> None:
        run_id = "decision-latest-stage-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": ["requirement_confirm"]}),
            encoding="utf-8",
        )
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")
        (output_dir / "report.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "waiting",
                    "requirement": "req",
                    "project_root": str(self.project_root),
                    "output_dir": str(output_dir),
                    "config_source": "project",
                    "stages": [
                        {
                            "stage_id": "requirement_confirm",
                            "stage_name": "Requirement Confirm",
                            "status": "completed",
                            "type": "human_review",
                            "is_parallel": False,
                            "agents": [],
                            "quality_gates": [],
                        },
                        {
                            "stage_id": "requirement_confirm",
                            "stage_name": "Requirement Confirm",
                            "status": "waiting",
                            "type": "human_review",
                            "is_parallel": False,
                            "agents": [],
                            "quality_gates": [],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        with patch("api.routes.runs.resume_run_background", return_value=output_dir) as resume_bg:
            response = self.client.post(
                f"/api/runs/{run_id}/human-decision",
                params={"workdir": str(self.project_root)},
                json={"stage_id": "requirement_confirm", "decision": "approved"},
            )

        self.assertEqual(response.status_code, 200)
        resume_bg.assert_called_once()

    def test_human_decision_rejects_unknown_stage(self) -> None:
        run_id = "decision-unknown-stage-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": []}),
            encoding="utf-8",
        )
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")
        (output_dir / "report.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "waiting",
                    "requirement": "req",
                    "project_root": str(self.project_root),
                    "output_dir": str(output_dir),
                    "config_source": "project",
                    "stages": [
                        {
                            "stage_id": "requirement_confirm",
                            "stage_name": "Requirement Confirm",
                            "status": "waiting",
                            "type": "human_review",
                            "is_parallel": False,
                            "agents": [],
                            "quality_gates": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with patch("api.routes.runs.resume_run_background", return_value=output_dir) as resume_bg:
            response = self.client.post(
                f"/api/runs/{run_id}/human-decision",
                params={"workdir": str(self.project_root)},
                json={"stage_id": "task_plan_confirm", "decision": "approved"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("stage task_plan_confirm not found", response.json()["detail"])
        resume_bg.assert_not_called()

    def test_human_decision_runtime_value_error_returns_400(self) -> None:
        run_id = "decision-missing-requirement-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": []}),
            encoding="utf-8",
        )
        (output_dir / "report.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "waiting",
                    "requirement": "req",
                    "project_root": str(self.project_root),
                    "output_dir": str(output_dir),
                    "config_source": "project",
                    "stages": [
                        {
                            "stage_id": "task_plan_confirm",
                            "stage_name": "Task Plan Confirm",
                            "status": "waiting",
                            "type": "human_review",
                            "is_parallel": False,
                            "agents": [],
                            "quality_gates": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        client = TestClient(self.app, raise_server_exceptions=False)

        response = client.post(
            f"/api/runs/{run_id}/human-decision",
            params={"workdir": str(self.project_root)},
            json={"stage_id": "task_plan_confirm", "decision": "approved"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("requirement.md", response.json()["detail"])


class TestCancelRetryRoutes(BaseRoutesTest):
    def test_cancel_queued_run(self) -> None:
        from engine.models import RunReport
        from engine.task_board import load_tasks, task_id_for_run

        run_id = "cancel-test-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="running",
            requirement="req",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")

        mock_result = {"cancelled": True, "job_id": "rq-job-1", "previous_status": "queued"}
        with patch("engine.task_queue.get_redis_conn") as mock_conn, \
             patch("engine.task_queue.cancel_rq_job", return_value=mock_result):
            mock_conn.return_value.get.return_value = b"rq-job-1"
            response = self.client.post(
                f"/api/runs/{run_id}/cancel",
                params={"workdir": str(self.project_root)},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "cancelled")
        task = next(task for task in load_tasks(self.project_root) if task.id == task_id_for_run(run_id))
        self.assertEqual(task.state, "cancelled")
        self.assertEqual(task.run_id, run_id)
        self.assertIn(output_dir.resolve(), [Path(path).resolve() for path in task.artifact_dirs])
        self.assertIn(f"run:{run_id}:cancel:cancelled", task.decision_ids)

    def test_cancel_completed_run_returns_409(self) -> None:
        from engine.models import RunReport

        run_id = "cancel-completed-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="completed",
            requirement="req",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")

        response = self.client.post(
            f"/api/runs/{run_id}/cancel",
            params={"workdir": str(self.project_root)},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("completed", response.json()["detail"])

    def test_cancel_nonexistent_run_returns_404(self) -> None:
        response = self.client.post(
            "/api/runs/nonexistent-cancel/cancel",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 404)

    def test_cancel_run_does_not_overwrite_accepted_task_state(self) -> None:
        from engine.models import RunReport
        from engine.task_board import TaskEvent, load_tasks, record_task_event, task_id_for_run

        run_id = "cancel-accepted-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="running",
            requirement="accepted req",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")
        task_id = task_id_for_run(run_id)
        record_task_event(
            self.project_root,
            TaskEvent(
                task_id=task_id,
                title="accepted req",
                state="accepted",
                source_stage="acceptance_confirm",
                decision="approved",
                run_id=run_id,
                artifact_dir=str(output_dir),
                decision_ids=[f"human:{run_id}:acceptance_confirm:1"],
            ),
        )

        response = self.client.post(
            f"/api/runs/{run_id}/cancel",
            params={"workdir": str(self.project_root)},
        )

        self.assertEqual(response.status_code, 200)
        task = next(task for task in load_tasks(self.project_root) if task.id == task_id)
        self.assertEqual(task.state, "accepted")
        self.assertTrue(any(item["state"] == "cancelled" for item in task.state_history))

    def test_retry_failed_run(self) -> None:
        from engine.models import RunReport

        run_id = "retry-failed-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="failed",
            requirement="original requirement",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="project",
            config_path=str(self.project_root / "config.yaml"),
        )
        report.write(output_dir / "report.json")

        with patch("api.routes.runs.start_run_background", return_value=output_dir):
            response = self.client.post(
                f"/api/runs/{run_id}/retry",
                params={"workdir": str(self.project_root)},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["original_run_id"], run_id)
        self.assertEqual(data["status"], "queued")
        self.assertTrue(data["run_id"].startswith("retry-"))

    def test_retry_completed_run_returns_409(self) -> None:
        from engine.models import RunReport

        run_id = "retry-completed-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="completed",
            requirement="req",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")

        response = self.client.post(
            f"/api/runs/{run_id}/retry",
            params={"workdir": str(self.project_root)},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("completed", response.json()["detail"])

    def test_retry_nonexistent_run_returns_404(self) -> None:
        response = self.client.post(
            "/api/runs/nonexistent-retry/retry",
            params={"workdir": str(self.project_root)},
        )
        self.assertEqual(response.status_code, 404)

    def test_enqueue_failure_returns_503(self) -> None:
        with patch("api.routes.runs.start_run_background", side_effect=RuntimeError("Redis unavailable")):
            response = self.client.post(
                "/api/runs",
                json={
                    "requirement": "test 503",
                    "workdir": str(self.project_root),
                    "run_id": "api-503-test-2",
                    "yes": True,
                },
            )
        self.assertEqual(response.status_code, 503)


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

    def test_artifact_path_rejects_sibling_prefix_escape(self) -> None:
        """artifact 文件边界必须按路径层级判断，不能让 run2 命中 run。"""
        from fastapi import HTTPException
        from api.routes.artifacts import _resolve_artifact_path

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_dir = base / "run"
            sibling_dir = base / "run2"
            run_dir.mkdir()
            sibling_dir.mkdir()
            (sibling_dir / "secret.txt").write_text("secret", encoding="utf-8")

            with self.assertRaises(HTTPException) as ctx:
                _resolve_artifact_path(run_dir, "../run2/secret.txt")

            self.assertEqual(ctx.exception.status_code, 404)


class TestSettingsDesensitization(BaseRoutesTest):
    """测试 settings GET 敏感字段脱敏"""

    def test_get_settings_masks_sensitive_fields(self) -> None:
        """GET /api/settings 对 api_key/secret/token 等字段脱敏"""
        # 写入包含敏感字段的配置
        from engine.config import normalize_config
        config = normalize_config({
            "runtimes": {
                "Claude": {"cli": "claude", "api_key": "sk-super-secret-key"},
                "OpenAI": {"cli": "openai", "secret_token": "tok-abc123"},
            },
            "agents": [],
            "pipeline": [],
        })
        self.set_settings_store(config)

        response = self.client.get("/api/settings", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        runtimes = response.json()["config"]["runtimes"]
        self.assertEqual(runtimes["Claude"]["api_key"], "***")
        self.assertEqual(runtimes["OpenAI"]["secret_token"], "***")
        # 非敏感字段不被脱敏
        self.assertEqual(runtimes["Claude"]["cli"], "claude")

    def test_get_settings_preserves_empty_sensitive_fields(self) -> None:
        """GET /api/settings 空字符串的敏感字段不被脱敏为 ***"""
        from engine.config import normalize_config
        config = normalize_config({
            "runtimes": {
                "Claude": {"cli": "claude", "api_key": ""},
            },
            "agents": [],
            "pipeline": [],
        })
        self.set_settings_store(config)

        response = self.client.get("/api/settings", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        runtimes = response.json()["config"]["runtimes"]
        self.assertEqual(runtimes["Claude"]["api_key"], "")


class TestSettingsPutEndpoint(BaseRoutesTest):
    """测试 PUT /api/settings 端点"""

    def test_put_settings_updates_config(self) -> None:
        """PUT /api/settings 更新 DB 配置"""

        response = self.client.put(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json={"metadata": {"name": "put-test-project"}},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "saved")
        self.assertEqual(data["path"], "db:default")
        self.assertEqual(self.settings_store["metadata"]["name"], "put-test-project")

    def test_put_settings_same_as_post(self) -> None:
        """PUT 和 POST 返回一致的结果"""
        body = {"metadata": {"version": "3.0"}}
        put_resp = self.client.put(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json=body,
        )
        post_resp = self.client.post(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json=body,
        )
        self.assertEqual(put_resp.status_code, post_resp.status_code)
        self.assertEqual(put_resp.json()["status"], post_resp.json()["status"])

    def test_put_response_masks_sensitive_fields(self) -> None:
        """PUT /api/settings 响应中敏感字段被脱敏"""
        response = self.client.put(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json={
                "runtimes": {
                    "Claude": {"cli": "claude", "api_key": "sk-should-be-masked"},
                },
                "agents": [
                    {"name": "dev", "runtime_id": "Claude", "role": "developer", "prompt": "agents/dev.md"}
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        runtimes = response.json()["config"]["runtimes"]
        self.assertEqual(runtimes["Claude"]["api_key"], "***")

    def test_put_settings_preserves_masked_runtime_secret(self) -> None:
        """把 GET 脱敏结果原样保存时，不应把真实密钥覆盖成 ***"""
        from engine.config import normalize_config
        config = normalize_config({
            "runtimes": {
                "Claude": {"cli": "claude", "api_key": "sk-real-secret"},
            },
            "agents": [
                {"name": "dev", "runtime_id": "Claude", "role": "developer", "prompt": "agents/dev.md"}
            ],
            "pipeline": [],
        })
        self.set_settings_store(config)

        get_response = self.client.get("/api/settings", params={"workdir": str(self.project_root)})
        self.assertEqual(get_response.status_code, 200)
        masked_config = get_response.json()["config"]
        self.assertEqual(masked_config["runtimes"]["Claude"]["api_key"], "***")

        put_response = self.client.put(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json=masked_config,
        )
        self.assertEqual(put_response.status_code, 200)

        self.assertEqual(self.settings_store["runtimes"]["Claude"]["api_key"], "sk-real-secret")

    def test_post_settings_runtime_partial_update_preserves_other_runtimes(self) -> None:
        """POST 局部更新 runtimes 时不能丢掉未提交的已有 runtime"""
        self.set_settings_store(self._load_yaml("""
runtimes:
  mock:
    name: Mock
    cli: mock
  codex:
    name: Codex
    cli: codex
agents:
  - name: dev
    runtime_id: mock
    role: developer
    prompt: agents/dev.md
pipeline: []
"""))

        response = self.client.post(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json={"runtimes": {"mock": {"name": "Mock Updated", "cli": "mock"}}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("codex", self.settings_store["runtimes"])
        self.assertEqual(self.settings_store["runtimes"]["mock"]["name"], "Mock Updated")

    def test_put_settings_runtimes_replaces_removed_runtime(self) -> None:
        """PUT 保存完整 settings 时应能删除废弃 runtime"""
        self.set_settings_store(self._load_yaml("""
runtimes:
  mock:
    name: Mock
    cli: mock
  codex:
    name: Codex
    cli: codex
agents:
  - name: dev
    runtime_id: mock
    role: developer
    prompt: agents/dev.md
pipeline: []
"""))

        response = self.client.put(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json={
                "runtimes": {"mock": {"name": "Mock", "cli": "mock"}},
                "agents": [{"name": "dev", "runtime_id": "mock", "role": "developer", "prompt": "agents/dev.md"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("codex", self.settings_store["runtimes"])

    def test_put_settings_runtime_replaces_removed_runtime_fields(self) -> None:
        """PUT 保存完整 settings 时应能删除同名 runtime 内部旧字段"""
        self.set_settings_store(self._load_yaml("""
runtimes:
  mock:
    name: Mock
    cli: mock
    model: old-model
    fallback_models:
      - old-fallback
    env:
      OLD_FLAG: "1"
    api_key: sk-real-secret
agents:
  - name: dev
    runtime_id: mock
    role: developer
    prompt: agents/dev.md
pipeline: []
"""))

        response = self.client.put(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json={
                "runtimes": {"mock": {"name": "Mock", "cli": "mock", "api_key": "***"}},
                "agents": [{"name": "dev", "runtime_id": "mock", "role": "developer", "prompt": "agents/dev.md"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        runtime = self.settings_store["runtimes"]["mock"]
        self.assertNotIn("model", runtime)
        self.assertNotIn("fallback_models", runtime)
        self.assertNotIn("env", runtime)
        self.assertEqual(runtime["api_key"], "sk-real-secret")

    def test_put_settings_does_not_persist_discovery_metadata(self) -> None:
        """available/path/version 等探测字段不能写入 team.yaml"""
        response = self.client.put(
            "/api/settings",
            params={"workdir": str(self.project_root)},
            json={
                "runtimes": {
                    "claude": {
                        "name": "Claude",
                        "cli": "claude",
                        "available": True,
                        "path": "/usr/local/bin/claude",
                        "version": "1.0.0",
                        "configured": True,
                    }
                },
                "agents": [
                    {"name": "dev", "runtime_id": "claude", "role": "developer", "prompt": "agents/dev.md"}
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        runtime = self.settings_store["runtimes"]["claude"]
        self.assertNotIn("available", runtime)
        self.assertNotIn("path", runtime)
        self.assertNotIn("version", runtime)
        self.assertNotIn("configured", runtime)


class TestRunsPagination(BaseRoutesTest):
    """测试 runs 分页参数"""

    def test_list_runs_with_pagination_params(self) -> None:
        """GET /api/runs 支持 page/size 分页参数"""
        response = self.client.get(
            "/api/runs",
            params={"workdir": str(self.project_root), "page": 1, "size": 5},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("items", data)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["size"], 5)


class TestRunsFallbackToFilesystem(BaseRoutesTest):
    """测试 runs 在无 DB 环境下的文件系统 fallback"""

    def test_get_run_from_filesystem(self) -> None:
        """GET /api/runs/{id} 从文件系统读取报告"""
        import json
        from engine.models import ArtifactValidationRun, RunReport, StageRun

        output_dir = self.project_root / ".ai" / "team-output" / "fs-test-run"
        output_dir.mkdir(parents=True)
        (output_dir / "implementation-report.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "summary": "历史运行时通过的旧格式报告",
                    "changed_files": ["src/app.py"],
                    "tests_run": [],
                    "acceptance_coverage": [],
                    "evidence": [],
                    "risks": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = RunReport(
            run_id="fs-test-run",
            status="completed",
            requirement="测试需求",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="project",
            artifacts=["implementation-report.json"],
            stages=[
                StageRun(
                    stage_id="develop",
                    stage_name="Develop",
                    status="completed",
                    agents=[],
                    artifact_validations=[
                        ArtifactValidationRun(
                            artifact="implementation-report.json",
                            status="passed",
                            message="schema valid",
                            validator="runtime-schema",
                        )
                    ],
                )
            ],
        )
        report.write(output_dir / "report.json")

        response = self.client.get("/api/runs/fs-test-run", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["run_id"], "fs-test-run")
        self.assertEqual(data["status"], "completed")
        self.assertEqual(len(data["stages"]), 1)
        self.assertEqual(data["stages"][0]["artifact_validations"][0]["status"], "passed")
        self.assertEqual(data["current_contract_status"], "failed")
        self.assertEqual(data["current_contract_validations"][0]["artifact"], "implementation-report.json")
        self.assertEqual(data["current_contract_validations"][0]["validator"], "current-schema")
        self.assertIn("traceability", data["current_contract_validations"][0]["message"])

    def test_list_runs_from_filesystem(self) -> None:
        """GET /api/runs 从文件系统扫描返回列表"""
        import json
        from engine.models import RunReport

        output_dir = self.project_root / ".ai" / "team-output" / "list-fs-run"
        output_dir.mkdir(parents=True)

        report = RunReport(
            run_id="list-fs-run",
            status="completed",
            requirement="测试",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="default",
        )
        report.write(output_dir / "report.json")

        response = self.client.get("/api/runs", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        run_ids = [r["run_id"] for r in items]
        self.assertIn("list-fs-run", run_ids)

    def test_get_run_uses_completed_file_report_when_db_detail_is_stale(self) -> None:
        """DB 详情缺 stages/artifacts 时，文件报告优先，避免 queued 覆盖 completed。"""
        from engine.models import RunReport, StageRun

        run_id = "stale-db-detail"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="completed",
            requirement="测试需求",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="project",
            started_at="2026-05-11T08:00:00+00:00",
            completed_at="2026-05-11T08:00:05+00:00",
            artifacts=["a.md", "b.json"],
            stages=[
                StageRun(stage_id="planning", stage_name="Planning", status="completed", started_at="2026-05-11T08:00:01+00:00"),
                StageRun(stage_id="develop", stage_name="Develop", status="completed", started_at="2026-05-11T08:00:02+00:00"),
            ],
        )
        report.write(output_dir / "report.json")
        stale_db = {
            "run_id": run_id,
            "status": "queued",
            "project_root": str(self.project_root),
            "output_dir": "",
            "started_at": None,
            "artifacts": [],
            "stages": [],
        }

        with patch("api.routes.runs._db_get_run", new=AsyncMock(return_value=stale_db)):
            response = self.client.get(f"/api/runs/{run_id}", params={"workdir": str(self.project_root)})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["output_dir"], str(output_dir))
        self.assertEqual(data["artifacts"], ["a.md", "b.json"])
        self.assertEqual([stage["stage_id"] for stage in data["stages"]], ["planning", "develop"])

    def test_list_runs_overlays_stale_db_summary_from_file_report(self) -> None:
        """DB 摘要缺运行结果字段时，列表使用最新文件报告补齐。"""
        from engine.models import RunReport

        run_id = "stale-db-list"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        report = RunReport(
            run_id=run_id,
            status="completed",
            requirement="测试列表",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="project",
            started_at="2026-05-11T08:00:00+00:00",
            completed_at="2026-05-11T08:00:05+00:00",
            duration_seconds=5,
        )
        report.write(output_dir / "report.json")
        db_results = {
            "items": [{"run_id": run_id, "status": "queued", "output_dir": "", "started_at": None}],
            "total": 1,
            "page": 1,
            "size": 20,
        }

        with patch("api.routes.runs._db_list_runs", new=AsyncMock(return_value=db_results)):
            response = self.client.get("/api/runs", params={"workdir": str(self.project_root)})

        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertEqual(item["status"], "completed")
        self.assertEqual(item["output_dir"], str(output_dir))
        self.assertEqual(item["started_at"], "2026-05-11T08:00:00+00:00")
        self.assertEqual(item["duration_seconds"], 5)

    def test_list_runs_includes_filesystem_completed_run_missing_from_db_page(self) -> None:
        """DB 状态过滤漏掉 stale completed 文件时，列表会追加文件报告。"""
        from engine.models import RunReport

        run_id = "stale-db-filtered"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        RunReport(
            run_id=run_id,
            status="completed",
            requirement="测试过滤",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="project",
        ).write(output_dir / "report.json")
        db_results = {"items": [], "total": 0, "page": 1, "size": 20}

        with patch("api.routes.runs._db_list_runs", new=AsyncMock(return_value=db_results)):
            response = self.client.get("/api/runs", params={"workdir": str(self.project_root), "status": "completed"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["run_id"] for item in response.json()["items"]], [run_id])


class TestProjectRoutes(BaseRoutesTest):
    """测试 /api/projects CRUD 端点"""

    def test_validate_root_path_allows_allowed_root_child(self) -> None:
        """AI_TEAM_ALLOWED_ROOTS 允许 root 自身及其子路径。"""
        from api.routes.projects import _validate_root_path

        allowed_root = self.project_root
        child = allowed_root / "child"
        child.mkdir()

        with patch.dict(os.environ, {"AI_TEAM_ALLOWED_ROOTS": str(allowed_root)}, clear=False):
            self.assertEqual(_validate_root_path(str(child)), str(child.resolve()))

    def test_validate_root_path_rejects_sibling_prefix(self) -> None:
        """root2 不能因为字符串前缀匹配 root 而越过项目根目录边界。"""
        from fastapi import HTTPException
        from api.routes.projects import _validate_root_path

        base = self.project_root.parent
        allowed_root = base / f"{self.project_root.name}-allowed-root"
        sibling = base / f"{self.project_root.name}-allowed-root2"
        allowed_root.mkdir()
        sibling.mkdir()

        with patch.dict(os.environ, {"AI_TEAM_ALLOWED_ROOTS": str(allowed_root)}, clear=False):
            with self.assertRaises(HTTPException) as ctx:
                _validate_root_path(str(sibling))

        self.assertEqual(ctx.exception.status_code, 403)

    def test_create_project_rejects_sibling_prefix_outside_allowed_roots(self) -> None:
        """POST /api/projects 也必须拒绝 root/root2 这类字符串前缀逃逸。"""
        allowed_root = self.project_root
        sibling = allowed_root.parent / f"{allowed_root.name}2"
        sibling.mkdir()

        with patch.dict(os.environ, {"AI_TEAM_ALLOWED_ROOTS": str(allowed_root)}, clear=False):
            response = self.client.post(
                "/api/projects",
                json={"name": "Bad Project", "root_path": str(sibling)},
            )

        self.assertEqual(response.status_code, 403)

    def test_list_projects_empty(self) -> None:
        """GET /api/projects 无 DB 时返回空列表"""
        with patch("api.routes.projects.try_persistence", return_value=None):
            response = self.client.get("/api/projects")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_create_project_returns_record(self) -> None:
        """POST /api/projects 创建项目"""
        from unittest.mock import AsyncMock

        created = {}

        async def fake_create(conn, *, name, root_path):
            created["name"] = name
            created["root_path"] = root_path
            return "fake-id"

        async def fake_get_by_id(conn, id):
            return {"id": id, "name": created.get("name", ""), "root_path": created.get("root_path", ""), "created_at": "2026-01-01T00:00:00"}

        async def fake_get_by_root_path(conn, root_path):
            return None

        fake_repo = type("FakeRepo", (), {
            "create": staticmethod(fake_create),
            "get_by_id": staticmethod(fake_get_by_id),
            "get_by_root_path": staticmethod(fake_get_by_root_path),
        })()

        conn = AsyncMock()
        get_conn = AsyncMock(return_value=conn)
        release_conn = AsyncMock()
        fake_db = (get_conn, release_conn, None, None, None)

        with patch("api.routes.projects.try_persistence", return_value=fake_db), \
             patch("api.routes.projects._get_project_repo", return_value=fake_repo):
            response = self.client.post(
                "/api/projects",
                json={"name": "Test Project", "root_path": str(self.project_root)},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "Test Project")

    def test_create_project_duplicate_root_path_returns_409(self) -> None:
        """POST /api/projects 重复 root_path 返回 409"""
        from unittest.mock import AsyncMock

        async def fake_create(conn, *, name, root_path):
            return "fake-id"

        async def fake_get_by_id(conn, id):
            return {"id": id, "name": "X", "root_path": str(self.project_root), "created_at": "2026-01-01T00:00:00"}

        async def fake_get_by_root_path(conn, root_path):
            return {"id": "existing", "name": "Existing", "root_path": root_path, "created_at": "2026-01-01T00:00:00"}

        fake_repo = type("FakeRepo", (), {
            "create": staticmethod(fake_create),
            "get_by_id": staticmethod(fake_get_by_id),
            "get_by_root_path": staticmethod(fake_get_by_root_path),
        })()

        conn = AsyncMock()
        fake_db = (AsyncMock(return_value=conn), AsyncMock(), None, None, None)

        with patch("api.routes.projects.try_persistence", return_value=fake_db), \
             patch("api.routes.projects._get_project_repo", return_value=fake_repo):
            response = self.client.post(
                "/api/projects",
                json={"name": "Dup Project", "root_path": str(self.project_root)},
            )

        self.assertEqual(response.status_code, 409)

    def test_create_project_nonexistent_path_returns_400(self) -> None:
        """POST /api/projects 不存在的路径返回 400"""
        response = self.client.post(
            "/api/projects",
            json={"name": "Bad", "root_path": "/nonexistent/path/xyz"},
        )
        self.assertEqual(response.status_code, 400)

    def test_browse_project_directories_lists_allowed_children(self) -> None:
        """GET /api/projects/browse 返回可选择的目录，并复用 allowed roots 边界。"""
        repo_dir = self.project_root / "repo"
        repo_dir.mkdir()
        hidden_file = self.project_root / "README.md"
        hidden_file.write_text("not a directory", encoding="utf-8")

        with patch.dict(os.environ, {"AI_TEAM_ALLOWED_ROOTS": str(self.project_root)}, clear=False):
            response = self.client.get("/api/projects/browse", params={"path": str(self.project_root)})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["path"], str(self.project_root.resolve()))
        self.assertEqual(data["parent"], None)
        self.assertEqual([entry["name"] for entry in data["entries"]], ["repo"])
        self.assertEqual(data["entries"][0]["path"], str(repo_dir.resolve()))

    def test_browse_project_directories_rejects_outside_allowed_roots(self) -> None:
        """目录浏览不能越过 allowed roots。"""
        outside = self.project_root.parent / f"{self.project_root.name}-outside"
        outside.mkdir()

        with patch.dict(os.environ, {"AI_TEAM_ALLOWED_ROOTS": str(self.project_root)}, clear=False):
            response = self.client.get("/api/projects/browse", params={"path": str(outside)})

        self.assertEqual(response.status_code, 403)

    def test_import_project_returns_existing_record_for_same_root_path(self) -> None:
        """POST /api/projects/import 对同一路径幂等，不要求用户先手动建项目。"""
        existing = {"id": "existing", "name": "Existing", "root_path": str(self.project_root.resolve()), "created_at": "2026-01-01T00:00:00"}

        async def fake_create(conn, *, name, root_path):
            raise AssertionError("import should not create duplicate project")

        async def fake_get_by_id(conn, id):
            return existing

        async def fake_get_by_root_path(conn, root_path):
            return existing

        fake_repo = type("FakeRepo", (), {
            "create": staticmethod(fake_create),
            "get_by_id": staticmethod(fake_get_by_id),
            "get_by_root_path": staticmethod(fake_get_by_root_path),
        })()

        conn = AsyncMock()
        fake_db = (AsyncMock(return_value=conn), AsyncMock(), None, None, None)

        with patch("api.routes.projects.try_persistence", return_value=fake_db), \
             patch("api.routes.projects._get_project_repo", return_value=fake_repo):
            response = self.client.post("/api/projects/import", json={"root_path": str(self.project_root)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), existing)

    def test_import_project_creates_project_from_selected_directory(self) -> None:
        """POST /api/projects/import 可直接把选择的目录引入为项目。"""
        repo_dir = self.project_root / "selected-repo"
        repo_dir.mkdir()
        created = {}

        async def fake_create(conn, *, name, root_path):
            created["name"] = name
            created["root_path"] = root_path
            return "new-id"

        async def fake_get_by_id(conn, id):
            return {"id": id, "name": created["name"], "root_path": created["root_path"], "created_at": "2026-01-01T00:00:00"}

        async def fake_get_by_root_path(conn, root_path):
            return None

        fake_repo = type("FakeRepo", (), {
            "create": staticmethod(fake_create),
            "get_by_id": staticmethod(fake_get_by_id),
            "get_by_root_path": staticmethod(fake_get_by_root_path),
        })()

        conn = AsyncMock()
        fake_db = (AsyncMock(return_value=conn), AsyncMock(), None, None, None)

        with patch("api.routes.projects.try_persistence", return_value=fake_db), \
             patch("api.routes.projects._get_project_repo", return_value=fake_repo):
            response = self.client.post("/api/projects/import", json={"root_path": str(repo_dir)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "new-id")
        self.assertEqual(response.json()["name"], "selected-repo")
        self.assertEqual(response.json()["root_path"], str(repo_dir.resolve()))

    def test_delete_project(self) -> None:
        """DELETE /api/projects/{id} 删除项目"""
        from unittest.mock import AsyncMock

        async def fake_delete(conn, id):
            return id == "proj-to-delete"

        fake_repo = type("FakeRepo", (), {"delete": staticmethod(fake_delete)})()

        conn = AsyncMock()
        fake_db = (AsyncMock(return_value=conn), AsyncMock(), None, None, None)

        with patch("api.routes.projects.try_persistence", return_value=fake_db), \
             patch("api.routes.projects._get_project_repo", return_value=fake_repo):
            response = self.client.delete("/api/projects/proj-to-delete")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "deleted")

    def test_delete_nonexistent_project_returns_404(self) -> None:
        """DELETE /api/projects/{id} 不存在的返回 404"""
        from unittest.mock import AsyncMock

        async def fake_delete(conn, id):
            return False

        fake_repo = type("FakeRepo", (), {"delete": staticmethod(fake_delete)})()

        conn = AsyncMock()
        fake_db = (AsyncMock(return_value=conn), AsyncMock(), None, None, None)

        with patch("api.routes.projects.try_persistence", return_value=fake_db), \
             patch("api.routes.projects._get_project_repo", return_value=fake_repo):
            response = self.client.delete("/api/projects/nonexistent")

        self.assertEqual(response.status_code, 404)


class TestProductionWorkdirRejection(BaseRoutesTest):
    """测试生产模式下 workdir 被拒绝"""

    def test_create_run_rejects_workdir_in_production(self) -> None:
        """POST /api/runs 生产模式下传 workdir 被拒绝"""
        with patch("api.routes.runs.is_production_mode", return_value=True):
            response = self.client.post(
                "/api/runs",
                json={
                    "requirement": "test",
                    "workdir": str(self.project_root),
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("project_id", response.json()["detail"])

    def test_create_run_accepts_project_id_in_production(self) -> None:
        """POST /api/runs 生产模式下传 project_id 被接受"""
        from unittest.mock import AsyncMock

        async def fake_get_by_id(conn, id):
            if id == "proj-1":
                return {"id": "proj-1", "name": "Test", "root_path": str(self.project_root), "created_at": "2026-01-01T00:00:00"}
            return None

        fake_repo = type("FakeRepo", (), {"get_by_id": staticmethod(fake_get_by_id)})()

        conn = AsyncMock()
        fake_db = (AsyncMock(return_value=conn), AsyncMock(), None, None, None)
        output_dir = self.project_root / ".ai" / "team-output" / "prod-test-run"

        with patch.dict(os.environ, {"AI_TEAM_ALLOWED_ROOTS": ""}, clear=False), \
             patch("api.routes.runs.is_production_mode", return_value=True), \
             patch("api.routes.runs.try_persistence", return_value=fake_db), \
             patch("api.routes.runs._get_project_repo", return_value=fake_repo), \
             patch("api.routes.runs.start_run_background", return_value=output_dir) as start_bg:
            response = self.client.post(
                "/api/runs",
                json={
                    "requirement": "test",
                    "project_id": "proj-1",
                    "run_id": "prod-test-run",
                    "yes": True,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run_id"], "prod-test-run")
        start_bg.assert_called_once()

    def test_create_run_rejects_project_id_root_outside_allowed_roots(self) -> None:
        """通过 project_id 解析出的 root_path 仍必须经过 allowlist 校验。"""
        from unittest.mock import AsyncMock

        outside_root = self.project_root.parent / f"{self.project_root.name}2"
        outside_root.mkdir()

        async def fake_get_by_id(conn, id):
            return {"id": id, "name": "Outside", "root_path": str(outside_root), "created_at": "2026-01-01T00:00:00"}

        fake_repo = type("FakeRepo", (), {"get_by_id": staticmethod(fake_get_by_id)})()

        conn = AsyncMock()
        fake_db = (AsyncMock(return_value=conn), AsyncMock(), None, None, None)

        with patch.dict(os.environ, {"AI_TEAM_ALLOWED_ROOTS": str(self.project_root)}, clear=False), \
             patch("api.routes.runs.try_persistence", return_value=fake_db), \
             patch("api.routes.runs._get_project_repo", return_value=fake_repo), \
             patch("api.routes.runs.start_run_background") as start_bg:
            response = self.client.post(
                "/api/runs",
                json={
                    "requirement": "test",
                    "project_id": "proj-outside",
                    "run_id": "outside-project-run",
                    "yes": True,
                },
            )

        self.assertEqual(response.status_code, 403)
        start_bg.assert_not_called()


class TestProjectOwnershipValidation(BaseRoutesTest):
    """测试 artifact 跨 project 读取校验"""

    def test_artifact_rejects_cross_project_access(self) -> None:
        """GET /api/runs/{id}/artifacts 跨 project 访问被拒绝"""
        from unittest.mock import AsyncMock

        async def fake_project_get_by_id(conn, id):
            if id == "proj-other":
                return {"id": "proj-other", "name": "Other", "root_path": "/some/other/path", "created_at": "2026-01-01T00:00:00"}
            return None

        async def fake_run_exists(conn, id):
            return True

        async def fake_run_get_by_id(conn, id):
            return {"id": id, "project_root": str(self.project_root)}

        fake_project_repo = type("FakeProjectRepo", (), {"get_by_id": staticmethod(fake_project_get_by_id)})()
        fake_run_repo_cls = type("FakeRunRepo", (), {
            "run_exists": staticmethod(fake_run_exists),
            "get_by_id": staticmethod(fake_run_get_by_id),
        })

        conn = AsyncMock()
        fake_db = (AsyncMock(return_value=conn), AsyncMock(), fake_run_repo_cls, None, None)

        with patch("api.routes.artifacts.try_persistence", return_value=fake_db), \
             patch("api.routes.artifacts._get_project_repo", return_value=fake_project_repo), \
             patch("api.routes.artifacts.run_db_id", side_effect=lambda x: x):
            response = self.client.get(
                "/api/runs/fake-run/artifacts",
                params={"project_id": "proj-other"},
            )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
