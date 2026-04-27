from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.config import (
    ConfigError,
    LoadedConfig,
    _read_yaml,
    agent_map,
    executable_exists,
    expand_env,
    find_project_root,
    load_config,
    load_json_file,
    normalize_config,
    provider_config,
    read_prompt,
    resolve_prompt_path,
    validate_production_config,
)


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
            self.assertEqual(prompt_path, root / ".ai" / "agents" / "tech-lead.md")

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


class TestNormalizeConfig(unittest.TestCase):
    def test_string_provider_normalized(self) -> None:
        """字符串 provider 自动转为 dict 形式"""
        config = {"providers": {"Test": "test-cli"}}
        result = normalize_config(config)
        self.assertEqual(result["providers"]["Test"], {"cli": "test-cli"})

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
        """无效 provider 类型抛出 ConfigError"""
        with self.assertRaises(ConfigError):
            normalize_config({"providers": {"Bad": 123}})

    def test_auto_provider_added_when_missing(self) -> None:
        """无 Auto provider 时自动添加"""
        result = normalize_config({"providers": {"Custom": {"cli": "custom"}}})
        self.assertIn("Auto", result["providers"])

    def test_runners_default_empty(self) -> None:
        """normalize_config 默认 runner={}"""
        config = {"providers": {}}
        result = normalize_config(config)
        self.assertEqual(result["runner"], {})


class TestProviderConfig(unittest.TestCase):
    def test_get_existing_provider(self) -> None:
        """provider_config 返回已存在的 provider"""
        config = {"providers": {"Test": {"cli": "test-cli", "timeout": 30}}}
        result = provider_config(config, "Test")
        self.assertEqual(result["cli"], "test-cli")

    def test_unknown_provider_raises(self) -> None:
        """查询不存在的 provider 抛出 ConfigError"""
        with self.assertRaises(ConfigError):
            provider_config({"providers": {}}, "Nonexistent")


class TestLoadConfig(unittest.TestCase):
    def test_load_from_project_config(self) -> None:
        """从项目级 .ai/team.yaml 加载配置"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / ".ai" / "team.yaml").write_text(
                "providers:\n  Mock:\n    cli: mock\nagents: []\npipeline: []\n",
                encoding="utf-8",
            )
            loaded = load_config(root)
            self.assertEqual(loaded.source, "project")

    def test_load_with_explicit_config(self) -> None:
        """使用显式配置路径加载"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "custom.yaml"
            config_path.write_text("providers:\n  Mock:\n    cli: mock\nagents: []\npipeline: []\n", encoding="utf-8")
            loaded = load_config(root, explicit_config=str(config_path))
            self.assertIn("Mock", loaded.config["providers"])

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


if __name__ == "__main__":
    unittest.main()
