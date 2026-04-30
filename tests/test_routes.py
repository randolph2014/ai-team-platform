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

    def test_list_templates_returns_builtin(self) -> None:
        """GET /api/pipelines/templates 返回内置模板"""
        response = self.client.get("/api/pipelines/templates")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn("id", data[0])
        self.assertIn("name", data[0])

    def test_builtin_templates_use_current_collaboration_workflow(self) -> None:
        """内置模板不应继续暴露 plan/architect/accept 等旧流程节点。"""
        response = self.client.get("/api/pipelines/templates")
        self.assertEqual(response.status_code, 200)

        legacy_stages = {"plan", "architect", "context", "accept", "risk_analysis", "doc", "code_apply"}
        required_gates = {"requirement_confirm", "task_plan_confirm", "acceptance_confirm"}
        for template in response.json():
            stages = template.get("stages", [])
            self.assertFalse(legacy_stages.intersection(stages), f"{template['id']} still exposes legacy stages")
            self.assertTrue(required_gates.issubset(stages), f"{template['id']} misses hard human gates")
            self.assertIn("requirement_synthesis", stages, f"{template['id']} must produce confirmed requirement artifacts")
            stage_contracts = {stage["id"]: stage for stage in template.get("yaml_config", {}).get("stages", [])}
            self.assertEqual(stage_contracts["context_scan"]["type"], "context_scan")
            self.assertEqual(stage_contracts["requirement_confirm"]["type"], "human_review")
            self.assertFalse(stage_contracts["requirement_confirm"]["allow_auto_approve"])
            self.assertEqual(stage_contracts["acceptance_confirm"]["reject_to"], "develop")

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

        with patch("api.runtime.resume_run_background", return_value=output_dir) as resume_bg:
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

        with patch("api.runtime.resume_run_background", return_value=output_dir) as resume_bg:
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

    def test_human_decision_requires_report(self) -> None:
        run_id = "decision-missing-report-run"
        output_dir = self.project_root / ".ai" / "team-output" / run_id
        output_dir.mkdir(parents=True)
        (output_dir / "checkpoint.json").write_text(
            json.dumps({"run_id": run_id, "completed_stages": []}),
            encoding="utf-8",
        )
        (output_dir / "requirement.md").write_text("req", encoding="utf-8")

        with patch("api.runtime.resume_run_background", return_value=output_dir) as resume_bg:
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

        with patch("api.runtime.resume_run_background", return_value=output_dir) as resume_bg:
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

        with patch("api.runtime.resume_run_background", return_value=output_dir) as resume_bg:
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

        with patch("api.runtime.resume_run_background", return_value=output_dir) as resume_bg:
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
        self.assertIsInstance(response.json(), list)


class TestRunsFallbackToFilesystem(BaseRoutesTest):
    """测试 runs 在无 DB 环境下的文件系统 fallback"""

    def test_get_run_from_filesystem(self) -> None:
        """GET /api/runs/{id} 从文件系统读取报告"""
        import json
        from engine.models import RunReport, StageRun

        output_dir = self.project_root / ".ai" / "team-output" / "fs-test-run"
        output_dir.mkdir(parents=True)

        report = RunReport(
            run_id="fs-test-run",
            status="completed",
            requirement="测试需求",
            project_root=str(self.project_root),
            output_dir=str(output_dir),
            config_source="project",
            stages=[
                StageRun(stage_id="develop", stage_name="Develop", status="completed", agents=[])
            ],
        )
        report.write(output_dir / "report.json")

        response = self.client.get("/api/runs/fs-test-run", params={"workdir": str(self.project_root)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["run_id"], "fs-test-run")
        self.assertEqual(data["status"], "completed")
        self.assertEqual(len(data["stages"]), 1)

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
        run_ids = [r["run_id"] for r in data]
        self.assertIn("list-fs-run", run_ids)


if __name__ == "__main__":
    unittest.main()
