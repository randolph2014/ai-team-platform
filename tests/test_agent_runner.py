from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from engine.agent_runner import AgentRunner, build_command, _decode_claude_stream_line, resolve_auto_cli
from engine.config import ConfigError
from engine.cost_tracker import CostTracker
from engine.models import AgentDefinition


class TestBuildCommand(unittest.TestCase):
    def test_mock_provider(self) -> None:
        """mock provider 返回 mock 命令"""
        cmd, cli, mode = build_command({"cli": "mock"}, "test prompt")
        self.assertEqual(cmd, ["mock"])
        self.assertEqual(cli, "mock")

    def test_claude_provider(self) -> None:
        """claude provider 构建 claude 命令"""
        cmd, cli, mode = build_command({"cli": "claude"}, "do something")
        self.assertEqual(cmd[0], "claude")
        self.assertIn("do something", cmd)
        self.assertEqual(mode, "arg")

    def test_codex_provider(self) -> None:
        """codex provider 构建 codex exec 命令"""
        cmd, cli, mode = build_command({"cli": "codex"}, "do something")
        self.assertEqual(cmd[0], "codex")
        self.assertIn("exec", cmd)
        self.assertEqual(mode, "arg")

    def test_opencode_provider(self) -> None:
        """opencode provider 构建 opencode run 命令"""
        cmd, cli, mode = build_command({"cli": "opencode"}, "do something")
        self.assertEqual(cmd[0], "opencode")
        self.assertIn("run", cmd)

    def test_claude_with_model(self) -> None:
        """claude 带 model 参数"""
        cmd, _, _ = build_command({"cli": "claude"}, "prompt", model="claude-opus-4-7")
        self.assertIn("--model", cmd)
        self.assertIn("claude-opus-4-7", cmd)

    def test_codex_with_model(self) -> None:
        """codex 带 model 参数"""
        cmd, _, _ = build_command({"cli": "codex"}, "prompt", model="gpt-4")
        self.assertIn("-m", cmd)
        self.assertIn("gpt-4", cmd)

    @patch("engine.agent_runner.resolve_auto_cli", return_value=None)
    def test_auto_no_cli_raises(self, mock_resolve) -> None:
        """auto 但无可用 CLI 时抛出 ConfigError"""
        with self.assertRaises(ConfigError):
            build_command({"cli": "auto"}, "prompt")

    def test_custom_args_override(self) -> None:
        """自定义 args 覆盖默认"""
        cmd, _, _ = build_command({"cli": "claude", "args": ["--custom"]}, "prompt")
        self.assertIn("--custom", cmd)
        self.assertNotIn("--output-format", " ".join(cmd))


class TestDecodeClaudeStreamLine(unittest.TestCase):
    def test_json_assistant_type(self) -> None:
        """解码 assistant 类型的 JSON 流行"""
        payload = json.dumps({"type": "assistant", "message": {"content": [{"text": "hello"}]}})
        self.assertEqual(_decode_claude_stream_line(payload), "hello")

    def test_json_with_content_field(self) -> None:
        """解码含 content 字段的 JSON"""
        payload = json.dumps({"content": "direct text"})
        self.assertEqual(_decode_claude_stream_line(payload), "direct text")

    def test_non_json_passthrough(self) -> None:
        """非 JSON 文本直接返回"""
        self.assertEqual(_decode_claude_stream_line("plain text"), "plain text")

    def test_invalid_json_passthrough(self) -> None:
        """无效 JSON 直接返回原文"""
        self.assertEqual(_decode_claude_stream_line("{invalid"), "{invalid")


class TestResolveAutoCli(unittest.TestCase):
    @patch("shutil.which", return_value="/usr/local/bin/claude")
    def test_finds_claude_first(self, mock_which) -> None:
        """优先找到 claude"""
        self.assertEqual(resolve_auto_cli(), "claude")

    @patch("shutil.which", return_value=None)
    def test_returns_none_when_nothing_found(self, mock_which) -> None:
        """无可用 CLI 返回 None"""
        self.assertIsNone(resolve_auto_cli())


class TestAgentRunnerMock(unittest.TestCase):
    def test_mock_agent_with_fallback_models(self) -> None:
        """mock agent 带 fallback_models 字段时，主模型 mock 成功直接返回"""
        config = {
            "providers": {"Mock": {"cli": "mock", "response": "done"}},
            "runner": {},
        }
        runner = AgentRunner(config)
        agent = AgentDefinition(
            name="test-agent", provider="Mock", role="tester",
            model="primary-model", fallback_models=["fallback-1"],
        )
        provider = {"cli": "mock", "response": "mock output success"}
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            output_file = cwd / "output.md"
            raw_log = cwd / "raw.log"
            result = runner.run("run-1", "stage-1", agent, provider, "do something", cwd, output_file, raw_log)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.model_used, "primary-model")


class TestAgentRunnerCostTracking(unittest.TestCase):
    def test_cost_tracker_records_usage(self) -> None:
        """agent 运行后 cost_tracker 记录 token 使用"""
        with tempfile.TemporaryDirectory() as tmp:
            cost_tracker = CostTracker(Path(tmp))
            config = {
                "providers": {"Mock": {"cli": "mock", "response": "test output"}},
                "runner": {},
            }
            runner = AgentRunner(config, cost_tracker=cost_tracker)
            agent = AgentDefinition(name="dev", provider="Mock")
            provider = {"cli": "mock", "response": "hello world"}
            cwd = Path(tmp)
            output_file = cwd / "out.md"
            raw_log = cwd / "raw.log"
            result = runner.run("r1", "s1", agent, provider, "do something", cwd, output_file, raw_log)
            self.assertEqual(result.status, "completed")
            # cost_tracker should have tracked usage
            costs = cost_tracker.get_run_costs("r1")
            self.assertIsInstance(costs, dict)


if __name__ == "__main__":
    unittest.main()
