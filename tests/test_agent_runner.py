from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from engine.agent_runner import AgentRunner, _decode_claude_stream_line, resolve_auto_cli
from engine.config import ConfigError
from engine.cost_tracker import CostTracker
from engine.models import AgentDefinition


class TestBuildCommand(unittest.TestCase):
    def test_mock_runtime(self) -> None:
        """mock runtime 返回 mock 命令"""
        from engine.runtimes import build_runtime_command

        cmd, cli, mode = build_runtime_command({"cli": "mock"}, "test prompt")
        self.assertEqual(cmd, ["mock"])
        self.assertEqual(cli, "mock")

    def test_claude_runtime(self) -> None:
        """claude runtime 构建 claude 命令"""
        from engine.runtimes import build_runtime_command

        cmd, cli, mode = build_runtime_command({"cli": "claude"}, "do something")
        self.assertEqual(cmd[0], "claude")
        self.assertIn("do something", cmd)
        self.assertEqual(mode, "arg")

    def test_codex_runtime(self) -> None:
        """codex runtime 构建 codex exec 命令"""
        from engine.runtimes import build_runtime_command

        cmd, cli, mode = build_runtime_command({"cli": "codex"}, "do something")
        self.assertEqual(cmd[0], "codex")
        self.assertIn("exec", cmd)
        self.assertEqual(mode, "arg")

    def test_opencode_runtime(self) -> None:
        """opencode runtime 构建 opencode run 命令"""
        from engine.runtimes import build_runtime_command

        cmd, cli, mode = build_runtime_command({"cli": "opencode"}, "do something")
        self.assertEqual(cmd[0], "opencode")
        self.assertIn("run", cmd)

    def test_claude_with_model(self) -> None:
        """claude 带 model 参数"""
        from engine.runtimes import build_runtime_command

        cmd, _, _ = build_runtime_command({"cli": "claude"}, "prompt", model="claude-opus-4-7")
        self.assertIn("--model", cmd)
        self.assertIn("claude-opus-4-7", cmd)

    def test_codex_with_model(self) -> None:
        """codex 带 model 参数"""
        from engine.runtimes import build_runtime_command

        cmd, _, _ = build_runtime_command({"cli": "codex"}, "prompt", model="gpt-4")
        self.assertIn("-m", cmd)
        self.assertIn("gpt-4", cmd)

    @patch("engine.runtimes.resolve_auto_cli", return_value=None)
    def test_auto_no_cli_raises(self, mock_resolve) -> None:
        """auto 但无可用 CLI 时抛出 ConfigError"""
        from engine.runtimes import build_runtime_command

        with self.assertRaises(ConfigError):
            build_runtime_command({"cli": "auto"}, "prompt")

    def test_custom_args_override(self) -> None:
        """自定义 args 覆盖默认"""
        from engine.runtimes import build_runtime_command

        cmd, _, _ = build_runtime_command({"cli": "claude", "args": ["--custom"]}, "prompt")
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
            "runtimes": {"Mock": {"cli": "mock", "response": "done"}},
            "runner": {},
        }
        runner = AgentRunner(config)
        agent = AgentDefinition(
            name="test-agent", runtime_id="Mock", role="tester",
            model="primary-model", fallback_models=["fallback-1"],
        )
        runtime = {"cli": "mock", "response": "mock output success"}
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            output_file = cwd / "output.md"
            raw_log = cwd / "raw.log"
            result = runner.run("run-1", "stage-1", agent, runtime, "do something", cwd, output_file, raw_log)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.model_used, "primary-model")


class TestAgentRunnerCostTracking(unittest.TestCase):
    def test_cost_tracker_records_usage(self) -> None:
        """agent 运行后 cost_tracker 记录 token 使用"""
        with tempfile.TemporaryDirectory() as tmp:
            cost_tracker = CostTracker(Path(tmp))
            config = {
                "runtimes": {"Mock": {"cli": "mock", "response": "test output"}},
                "runner": {},
            }
            runner = AgentRunner(config, cost_tracker=cost_tracker)
            agent = AgentDefinition(name="dev", runtime_id="Mock")
            runtime = {"cli": "mock", "response": "hello world"}
            cwd = Path(tmp)
            output_file = cwd / "out.md"
            raw_log = cwd / "raw.log"
            result = runner.run("r1", "s1", agent, runtime, "do something", cwd, output_file, raw_log)
            self.assertEqual(result.status, "completed")
            # cost_tracker should have tracked usage
            costs = cost_tracker.get_run_costs("r1")
            self.assertIsInstance(costs, dict)


class TestDecodeClaudeStreamLineExtended(unittest.TestCase):
    def test_json_list_passthrough(self) -> None:
        """JSON 数组直接返回原文（非 dict）"""
        payload = json.dumps([1, 2, 3])
        self.assertEqual(_decode_claude_stream_line(payload), payload)

    def test_json_int_passthrough(self) -> None:
        """JSON 整数直接返回原文"""
        payload = json.dumps(42)
        self.assertEqual(_decode_claude_stream_line(payload), "42")

    def test_dict_without_type_or_content(self) -> None:
        """dict 既无 type 也无 content 字段时返回原文"""
        payload = json.dumps({"foo": "bar", "baz": 123})
        self.assertEqual(_decode_claude_stream_line(payload), payload)

    def test_dict_with_type_not_assistant_and_no_content(self) -> None:
        """dict 有 type 但不是 assistant，且无 content 字段"""
        payload = json.dumps({"type": "system", "data": "info"})
        self.assertEqual(_decode_claude_stream_line(payload), payload)

    def test_assistant_type_empty_content(self) -> None:
        """assistant 类型但 content 为空列表，返回原文"""
        payload = json.dumps({"type": "assistant", "message": {"content": []}})
        self.assertEqual(_decode_claude_stream_line(payload), payload)

    def test_assistant_type_no_message(self) -> None:
        """assistant 类型但无 message 字段"""
        payload = json.dumps({"type": "assistant"})
        self.assertEqual(_decode_claude_stream_line(payload), payload)

    def test_content_field_non_string(self) -> None:
        """dict 有 content 字段但不是字符串，返回原文"""
        payload = json.dumps({"content": 123})
        self.assertEqual(_decode_claude_stream_line(payload), payload)


class TestBuildCommandOpencode(unittest.TestCase):
    def test_opencode_with_model(self) -> None:
        """opencode runtime 带 model 参数"""
        from engine.runtimes import build_runtime_command

        cmd, cli, mode = build_runtime_command({"cli": "opencode"}, "prompt", model="deepseek-v3")
        self.assertEqual(cmd[0], "opencode")
        self.assertIn("run", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("deepseek-v3", cmd)
        self.assertEqual(mode, "arg")
        self.assertEqual(cli, "opencode")

    def test_opencode_without_model(self) -> None:
        """opencode runtime 不带 model"""
        from engine.runtimes import build_runtime_command

        cmd, cli, mode = build_runtime_command({"cli": "opencode"}, "hello")
        self.assertEqual(cmd, ["opencode", "run", "hello"])


class TestAgentRunnerSubprocessFailure(unittest.TestCase):
    @patch("engine.agent_runner.subprocess.Popen")
    def test_run_subprocess_nonzero_exit(self, mock_popen_cls) -> None:
        """subprocess 以非零退出码结束时，状态为 failed"""
        mock_proc = MagicMock()
        mock_proc.stdout.readline.return_value = ""
        mock_proc.stdout.read.return_value = ""
        mock_proc.poll.return_value = 1
        mock_proc.wait.return_value = 1
        mock_popen_cls.return_value = mock_proc

        config = {"runtimes": {"P": {"cli": "claude"}}, "runner": {}}
        runner = AgentRunner(config)
        agent = AgentDefinition(name="a1", runtime_id="P", model="m1")
        runtime = {"cli": "claude"}

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            output_file = cwd / "out.md"
            raw_log = cwd / "raw.log"
            result = runner.run("r1", "s1", agent, runtime, "prompt", cwd, output_file, raw_log)
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.exit_code, 1)
            self.assertIn("exited with code 1", result.error_message)

    @patch("engine.agent_runner.subprocess.Popen")
    def test_run_subprocess_file_not_found(self, mock_popen_cls) -> None:
        """subprocess.Popen 抛出 FileNotFoundError 时，状态为 failed"""
        mock_popen_cls.side_effect = FileNotFoundError("claude not found")

        config = {"runtimes": {"P": {"cli": "claude"}}, "runner": {}}
        runner = AgentRunner(config)
        agent = AgentDefinition(name="a1", runtime_id="P", model="m1")
        runtime = {"cli": "claude"}

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            output_file = cwd / "out.md"
            raw_log = cwd / "raw.log"
            result = runner.run("r1", "s1", agent, runtime, "prompt", cwd, output_file, raw_log)
            self.assertEqual(result.status, "failed")
            self.assertIn("claude not found", result.error_message)
            self.assertTrue(output_file.exists())
            self.assertTrue(raw_log.exists())

    @patch("engine.agent_runner.time.monotonic")
    @patch("engine.agent_runner.subprocess.Popen")
    def test_run_subprocess_timeout(self, mock_popen_cls, mock_monotonic) -> None:
        """subprocess 超时时状态为 timeout"""
        mock_proc = MagicMock()
        mock_proc.stdout.readline.return_value = ""
        mock_proc.stdout.read.return_value = ""
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = -15
        mock_popen_cls.return_value = mock_proc

        tick = [0.0]

        def advance():
            tick[0] += 0.6
            return tick[0]

        mock_monotonic.side_effect = advance

        config = {"runtimes": {"P": {"cli": "claude"}}, "runner": {}}
        runner = AgentRunner(config)
        agent = AgentDefinition(name="a1", runtime_id="P", model="m1", timeout=1)
        runtime = {"cli": "claude"}

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            output_file = cwd / "out.md"
            raw_log = cwd / "raw.log"
            result = runner.run("r1", "s1", agent, runtime, "prompt", cwd, output_file, raw_log)
            self.assertEqual(result.status, "timeout")
            self.assertIn("timed out", result.error_message)


class TestAgentRunnerComplete(unittest.TestCase):
    def test_complete_records_duration_and_emits_event(self) -> None:
        """_complete 设置 completed_at、duration_seconds 并发射 agent:completed 事件"""
        config = {"runtimes": {}, "runner": {}}
        bus = MagicMock()
        runner = AgentRunner(config, bus=bus)
        agent_run = MagicMock()
        agent_run.model_used = "test-model"
        agent_run.agent_name = "agent-1"
        agent_run.status = "completed"
        agent_run.exit_code = 0
        agent_run.output_file = None

        import time as _time
        started = _time.monotonic() - 1.5
        result = runner._complete(agent_run, started, "run-1", "stage-1")

        self.assertIsNotNone(result.completed_at)
        self.assertIsNotNone(result.duration_seconds)
        self.assertGreaterEqual(result.duration_seconds, 1.0)
        bus.emit.assert_called_once()
        call_args = bus.emit.call_args
        self.assertEqual(call_args[0][0], "agent:completed")

    def test_complete_with_cost_tracker(self) -> None:
        """_complete 在有 cost_tracker 时调用 _track_cost"""
        with tempfile.TemporaryDirectory() as tmp:
            cost_tracker = CostTracker(Path(tmp))
            config = {"runtimes": {"P": {"model": "test-model"}}, "runner": {}}
            runner = AgentRunner(config, cost_tracker=cost_tracker)
            output_path = Path(tmp) / "out.md"
            output_path.write_text("agent output text", encoding="utf-8")

            agent_run = MagicMock()
            agent_run.model_used = "test-model"
            agent_run.agent_name = "agent-1"
            agent_run.status = "completed"
            agent_run.exit_code = 0
            agent_run.output_file = str(output_path)
            agent_run.runtime_id = "P"

            runner._last_prompt = "test prompt content"
            import time as _time
            started = _time.monotonic() - 1.0
            runner._complete(agent_run, started, "run-1", "stage-1")

            costs = cost_tracker.get_run_costs("run-1")
            self.assertIsInstance(costs, dict)


class TestAgentRunnerHeartbeat(unittest.TestCase):
    @patch("engine.agent_runner.subprocess.Popen")
    def test_heartbeat_thread_started(self, mock_popen_cls) -> None:
        """heartbeat_seconds > 0 时启动心跳线程"""
        import time as _time

        mock_proc = MagicMock()
        mock_proc.stdout.readline.return_value = "done\n"
        mock_proc.poll.return_value = 0
        mock_proc.stdout.read.return_value = ""
        mock_proc.wait.return_value = 0
        mock_popen_cls.return_value = mock_proc

        bus = MagicMock()
        config = {"runtimes": {"P": {"cli": "claude"}}, "runner": {"heartbeat_seconds": 1}}
        runner = AgentRunner(config, bus=bus)
        agent = AgentDefinition(name="a1", runtime_id="P", model="m1")
        runtime = {"cli": "claude"}

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            output_file = cwd / "out.md"
            raw_log = cwd / "raw.log"
            result = runner.run("r1", "s1", agent, runtime, "prompt", cwd, output_file, raw_log)
            self.assertEqual(result.status, "completed")


if __name__ == "__main__":
    unittest.main()
