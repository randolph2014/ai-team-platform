from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.config import (
    ConfigError,
    DEFAULT_TEAM_FILE,
    LoadedConfig,
    _read_yaml,
    agent_map,
    executable_exists,
    expand_env,
    find_project_root,
    load_config,
    load_json_file,
    normalize_config,
    read_prompt,
    resolve_prompt_path,
    resolve_prompt_write_path,
    validate_production_config,
)
from engine.models import AgentDefinition


class TestProjectPromptOverride(unittest.TestCase):
    def test_project_agents_override_platform(self) -> None:
        """项目级 .ai/agents/ 优先于平台模板 prompt"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "tech-lead.md").write_text("Project-level prompt", encoding="utf-8")
            loaded = load_config(root)
            agents = agent_map(loaded.config)
            prompt_path = resolve_prompt_path(root, loaded.path, agents["tech-lead"])
            self.assertEqual(prompt_path, (root / ".ai" / "agents" / "tech-lead.md").resolve(strict=False))

    def test_read_prompt_returns_content(self) -> None:
        """read_prompt 返回文件内容"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "tech-lead.md").write_text("Hello from project", encoding="utf-8")
            loaded = load_config(root)
            agents = agent_map(loaded.config)
            content = read_prompt(root, loaded.path, agents["tech-lead"])
            self.assertEqual(content, "Hello from project")

    def test_template_prompt_writes_to_project_override(self) -> None:
        """平台模板 prompt 只作为读取来源，保存时写入项目级覆盖文件"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            loaded = load_config(root)
            agents = agent_map(loaded.config)

            write_path = resolve_prompt_write_path(root, loaded.path or str(DEFAULT_TEAM_FILE), agents["tech-lead"])

            self.assertEqual(write_path, (root / ".ai" / "agents" / "tech-lead.md").resolve(strict=False))

    def test_prompt_write_path_rejects_project_escape(self) -> None:
        """prompt 写路径不能通过绝对路径或 .. 逃逸项目目录"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = AgentDefinition(name="dev", runtime_id="mock", prompt="../outside.md")
            with self.assertRaises(ConfigError):
                resolve_prompt_write_path(root, str(root / ".ai" / "team.yaml"), agent)

            agent = AgentDefinition(name="dev", runtime_id="mock", prompt="/tmp/outside.md")
            with self.assertRaises(ConfigError):
                resolve_prompt_write_path(root, str(root / ".ai" / "team.yaml"), agent)


class TestNormalizeConfig(unittest.TestCase):
    def test_runtime_mapping_is_first_class(self) -> None:
        """runtimes 是新的 CLI 执行器配置入口，agent 通过 runtime_id 引用"""
        config = {
            "runtimes": {"codex": {"name": "Codex", "cli": "codex"}},
            "agents": [{"name": "dev", "runtime_id": "codex", "role": "developer"}],
            "pipeline": [],
        }
        result = normalize_config(config)
        self.assertNotIn("providers", result)
        self.assertEqual(result["runtimes"]["codex"]["cli"], "codex")
        self.assertEqual(result["agents"][0]["runtime_id"], "codex")
        self.assertEqual(agent_map(result)["dev"].runtime_id, "codex")

    def test_legacy_providers_migrate_to_runtimes(self) -> None:
        """旧 providers/agent.provider 只作为读取期迁移输入，不保留为新结构"""
        config = {
            "providers": {"Mock": {"cli": "mock", "response": "done"}},
            "agents": [{"name": "dev", "provider": "Mock", "role": "developer"}],
            "pipeline": [],
        }
        result = normalize_config(config)
        self.assertNotIn("providers", result)
        self.assertEqual(result["runtimes"]["Mock"]["cli"], "mock")
        self.assertEqual(result["agents"][0]["runtime_id"], "Mock")
        self.assertNotIn("provider", result["agents"][0])

    def test_agent_runtime_reference_must_exist(self) -> None:
        """agent.runtime_id 必须指向已配置 runtime，避免运行期才失败"""
        with self.assertRaises(ConfigError):
            normalize_config(
                {
                    "runtimes": {"codex": {"cli": "codex"}},
                    "agents": [{"name": "dev", "runtime_id": "missing"}],
                    "pipeline": [],
                }
            )

    def test_agent_model_fields_are_not_allowed(self) -> None:
        """model/fallback_models 属于 runtime 配置，agent 配置中不允许再出现"""
        with self.assertRaises(ConfigError):
            normalize_config(
                {
                    "runtimes": {"mock": {"cli": "mock"}},
                    "agents": [{"name": "dev", "runtime_id": "mock", "model": "agent-model"}],
                    "pipeline": [],
                }
            )
        with self.assertRaises(ConfigError):
            normalize_config(
                {
                    "runtimes": {"mock": {"cli": "mock"}},
                    "agents": [{"name": "dev", "runtime_id": "mock", "fallback_models": ["fallback"]}],
                    "pipeline": [],
                }
            )

    def test_string_provider_normalized(self) -> None:
        """字符串 legacy provider 自动迁移为 runtime dict"""
        config = {"providers": {"Test": "test-cli"}}
        result = normalize_config(config)
        self.assertEqual(result["runtimes"]["Test"]["cli"], "test-cli")

    def test_worktree_default_enabled(self) -> None:
        """normalize_config 默认 worktree.enabled=True"""
        config = {"providers": {}}
        result = normalize_config(config)
        self.assertTrue(result["worktree"]["enabled"])

    def test_quality_gates_default_empty(self) -> None:
        """normalize_config 默认 quality_gates=[]"""
        config = {"providers": {}}
        result = normalize_config(config)
        self.assertEqual(result["quality_gates"], [])

    def test_invalid_provider_raises(self) -> None:
        """无效 legacy provider 类型抛出 ConfigError"""
        with self.assertRaises(ConfigError):
            normalize_config({"providers": {"Bad": 123}})

    def test_auto_provider_added_when_missing(self) -> None:
        """无 runtime 时自动添加 auto runtime"""
        result = normalize_config({})
        self.assertIn("auto", result["runtimes"])

    def test_runners_default_empty(self) -> None:
        """normalize_config 会补齐 runner 默认值"""
        config = {"providers": {}}
        result = normalize_config(config)
        self.assertIn("context_threshold_chars", result["runner"])

    def test_pipeline_mapping_normalized_to_stages_and_settings(self) -> None:
        """pipeline 支持 execution_mode + stages 写法，运行期仍拿到 stage list"""
        config = {
            "runtimes": {"mock": {"cli": "mock"}},
            "agents": [],
            "pipeline": {
                "execution_mode": "serial",
                "stages": [{"id": "develop", "agents": []}],
            },
        }
        result = normalize_config(config)
        self.assertEqual(result["pipeline_settings"]["execution_mode"], "serial")
        self.assertEqual(result["pipeline"], [{"id": "develop", "agents": []}])

    def test_pipeline_execution_mode_rejects_invalid_value(self) -> None:
        """execution_mode 只允许 serial/parallel/auto，避免运行期才发现配置错"""
        with self.assertRaises(ConfigError):
            normalize_config({"pipeline": {"execution_mode": "fast", "stages": []}})

    def test_runner_split_defaults_are_normalized(self) -> None:
        """需求拆分相关 runner 默认值在 normalize_config 阶段补齐"""
        result = normalize_config({"providers": {}})
        self.assertEqual(result["runner"]["context_threshold_chars"], 100000)
        self.assertTrue(result["runner"]["auto_split_requirements"])


class TestRuntimeConfig(unittest.TestCase):
    def test_get_existing_runtime(self) -> None:
        """runtime_config 返回已存在的 runtime"""
        from engine.runtimes import runtime_config

        config = {"runtimes": {"Test": {"cli": "test-cli", "timeout": 30}}}
        result = runtime_config(config, "Test")
        self.assertEqual(result["cli"], "test-cli")

    def test_unknown_runtime_raises(self) -> None:
        """查询不存在的 runtime 抛出 ConfigError"""
        from engine.runtimes import runtime_config

        with self.assertRaises(ConfigError):
            runtime_config({"runtimes": {}}, "Nonexistent")


class TestCliParser(unittest.TestCase):
    def test_run_accepts_execution_mode_override(self) -> None:
        """CLI run 支持 --execution-mode 覆盖配置"""
        from cli.main import build_parser

        args = build_parser().parse_args(["run", "需求", "--execution-mode", "serial"])

        self.assertEqual(args.execution_mode, "serial")

    def test_resume_command_accepts_run_id(self) -> None:
        """CLI 提供 ai-team resume <run-id> 入口"""
        from cli.main import build_parser

        args = build_parser().parse_args(["resume", "run-123", "--execution-mode", "auto"])

        self.assertEqual(args.run_id, "run-123")
        self.assertEqual(args.execution_mode, "auto")


class TestLoadConfig(unittest.TestCase):
    def test_load_from_project_config(self) -> None:
        """项目级 .ai/team.yaml 不再自动加载，始终返回平台模板配置"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / ".ai" / "team.yaml").write_text(
                "providers:\n  Mock:\n    cli: mock\nagents: []\npipeline: []\n",
                encoding="utf-8",
            )
            loaded = load_config(root)
            self.assertNotEqual(loaded.source, "project")

    def test_load_with_explicit_config(self) -> None:
        """使用显式配置路径加载"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "custom.yaml"
            config_path.write_text("providers:\n  Mock:\n    cli: mock\nagents: []\npipeline: []\n", encoding="utf-8")
            loaded = load_config(root, explicit_config=str(config_path))
            self.assertIn("Mock", loaded.config["runtimes"])

    def test_load_config_invalid_yaml(self) -> None:
        """加载无效 YAML 抛出 ConfigError"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_yaml = root / "bad.yaml"
            bad_yaml.write_text("{{invalid yaml", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(root, explicit_config=str(bad_yaml))

    def test_load_config_non_dict_yaml(self) -> None:
        """YAML 内容不是 dict 时抛出 ConfigError"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_yaml = root / "list.yaml"
            bad_yaml.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(root, explicit_config=str(bad_yaml))


class TestReadYaml(unittest.TestCase):
    def test_read_valid_yaml(self) -> None:
        """读取有效 YAML 文件"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.yaml"
            path.write_text("key: value\n", encoding="utf-8")
            result = _read_yaml(path)
            self.assertEqual(result, {"key": "value"})

    def test_read_empty_yaml(self) -> None:
        """读取空 YAML 文件返回空 dict"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.yaml"
            path.write_text("", encoding="utf-8")
            result = _read_yaml(path)
            self.assertEqual(result, {})


class TestFindProjectRoot(unittest.TestCase):
    def test_finds_git_root(self) -> None:
        """从子目录找到 git 根"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            sub = root / "src" / "pkg"
            sub.mkdir(parents=True)
            result = find_project_root(str(sub))
            self.assertEqual(result, root)

    def test_file_input_returns_parent(self) -> None:
        """传入文件路径时返回其父目录"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            file = root / "README.md"
            file.write_text("test", encoding="utf-8")
            result = find_project_root(str(file))
            self.assertEqual(result, root)

    def test_finds_ai_dir_root(self) -> None:
        """从子目录找到 .ai 目录所在根（无 .git）"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".ai").mkdir()
            sub = root / "src" / "pkg"
            sub.mkdir(parents=True)
            result = find_project_root(str(sub))
            self.assertEqual(result, root)


class TestUtilityFunctions(unittest.TestCase):
    def test_executable_exists(self) -> None:
        """executable_exists 对存在的命令返回 True"""
        self.assertTrue(executable_exists("python3"))

    def test_executable_not_exists(self) -> None:
        """executable_exists 对不存在的命令返回 False"""
        self.assertFalse(executable_exists("nonexistent_binary_12345"))

    def test_expand_env(self) -> None:
        """expand_env 展开环境变量"""
        with patch.dict(os.environ, {"TEST_AI_TEAM_VAR": "hello"}):
            self.assertEqual(expand_env("$TEST_AI_TEAM_VAR"), "hello")

    def test_load_json_file(self) -> None:
        """load_json_file 读取 JSON 文件"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.json"
            path.write_text('{"key": "value"}', encoding="utf-8")
            result = load_json_file(path)
            self.assertEqual(result["key"], "value")


class TestValidateProductionConfig(unittest.TestCase):
    def test_require_worktree_without_enabled_raises(self) -> None:
        with self.assertRaises(ConfigError):
            validate_production_config({
                "runner": {"production_mode": True, "require_worktree": True},
                "worktree": {"enabled": False},
            })

    def test_require_verify_cmd_without_gates_raises(self) -> None:
        with self.assertRaises(ConfigError):
            validate_production_config({
                "runner": {"production_mode": True, "require_verify_cmd": True},
                "worktree": {"enabled": True},
                "quality_gates": [],
            })

    def test_all_conditions_met_no_error(self) -> None:
        validate_production_config({
            "runner": {"production_mode": True, "require_worktree": True, "require_verify_cmd": True},
            "worktree": {"enabled": True},
            "quality_gates": [{"name": "test", "command": "echo ok"}],
        })


class TestDefaultAgentCollaborationWorkflow(unittest.TestCase):
    def test_default_pipeline_is_context_first_and_has_hard_human_gates(self) -> None:
        from engine.config import load_config

        loaded = load_config(Path.cwd())
        stages = loaded.config["pipeline"]
        stage_ids = [stage["id"] for stage in stages]

        self.assertEqual(
            stage_ids,
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
        )
        self.assertLess(stage_ids.index("context_scan"), stage_ids.index("requirement_synthesis"))
        self.assertLess(stage_ids.index("context_scan"), stage_ids.index("planning"))

        gates = {stage["id"]: stage for stage in stages if stage.get("type") == "human_review"}
        self.assertEqual(set(gates), {"requirement_confirm", "task_plan_confirm", "acceptance_confirm"})
        for gate in gates.values():
            self.assertFalse(gate.get("allow_auto_approve"))
            self.assertTrue(gate.get("requires_reason_on_reject"))
            self.assertNotIn("skip_if_no_blocker", gate)

    def test_default_pipeline_removes_ambiguous_or_duplicate_stages(self) -> None:
        from engine.config import load_config

        loaded = load_config(Path.cwd())
        stage_ids = [stage["id"] for stage in loaded.config["pipeline"]]

        self.assertNotIn("plan_confirm", stage_ids)
        self.assertNotIn("architect", stage_ids)
        self.assertNotIn("code_apply", stage_ids)
        self.assertNotIn("risk_analysis", stage_ids)
        self.assertNotIn("doc", stage_ids)


if __name__ == "__main__":
    unittest.main()
