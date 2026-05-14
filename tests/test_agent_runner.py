from __future__ import annotations

import json
import os
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
        self.assertEqual(cmd, ["claude", "-p", "--output-format", "stream-json", "--verbose", "do something"])
        self.assertEqual(mode, "arg")

    @patch("engine.agent_runner.subprocess.Popen")
    def test_claude_stream_json_smoke_reads_minimal_output(self, mock_popen_cls) -> None:
        """claude stream-json smoke：命令包含 --verbose 并能读取最小输出"""
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = [
            json.dumps({"type": "assistant", "message": {"content": [{"text": "ok"}]}}) + "\n",
            "",
        ]
        mock_proc.stdout.read.return_value = ""
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0
        mock_popen_cls.return_value = mock_proc

        config = {"runtimes": {"P": {"cli": "claude", "model": "m1"}}, "runner": {}}
        runner = AgentRunner(config)
        agent = AgentDefinition(name="a1", runtime_id="P")

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            output_file = cwd / "out.md"
            raw_log = cwd / "raw.log"
            result = runner.run("r1", "s1", agent, {"cli": "claude"}, "ping", cwd, output_file, raw_log)
            output_text = output_file.read_text(encoding="utf-8")

        command = mock_popen_cls.call_args.args[0]
        self.assertIn("--verbose", command)
        self.assertEqual(result.status, "completed")
        self.assertEqual(output_text, "ok\n")

    def test_claude_stream_decoder_suppresses_non_text_events(self) -> None:
        non_text_events = [
            {"type": "system", "subtype": "init", "cwd": "/tmp/project"},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "is_error: true"}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}},
        ]

        for event in non_text_events:
            self.assertEqual(_decode_claude_stream_line(json.dumps(event)), "")

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

    def test_runtime_model_arg_style_overrides_cli_default(self) -> None:
        """runtime.model_arg_style 可显式控制模型参数风格"""
        from engine.runtimes import build_runtime_command

        cmd, _, _ = build_runtime_command({"cli": "custom", "args": [], "model_arg_style": "codex"}, "prompt", model="gpt-5")
        self.assertIn("-m", cmd)
        self.assertNotIn("--model", cmd)

    def test_unsupported_runtime_cli_raises(self) -> None:
        """检测但未适配的 CLI 不能被当作可执行 runtime 静默运行"""
        from engine.runtimes import build_runtime_command

        with self.assertRaises(ConfigError):
            build_runtime_command({"cli": "hermes"}, "prompt")

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


class TestDiscoverRuntimeCandidates(unittest.TestCase):
    def tearDown(self) -> None:
        from engine.runtimes import clear_runtime_candidate_cache

        clear_runtime_candidate_cache()

    def test_reads_models_from_cli_config_files(self) -> None:
        """Runtime 候选项从本机 CLI 配置读取默认模型，仅作为 runtime 元信息暴露"""
        from engine.runtimes import discover_runtime_candidates

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / ".codex").mkdir(parents=True)
            (home / ".codex" / "config.toml").write_text(
                'model = "gpt-5.5"\n\n[projects."/tmp/repo"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )
            (home / ".claude").mkdir(parents=True)
            (home / ".claude" / "settings.json").write_text(
                json.dumps({"env": {"ANTHROPIC_MODEL": "mimo-v2.5-pro"}, "model": "opus"}),
                encoding="utf-8",
            )
            (home / ".config" / "opencode").mkdir(parents=True)
            (home / ".config" / "opencode" / "opencode.json").write_text(
                json.dumps({"model": "glm-5"}),
                encoding="utf-8",
            )

            def fake_which(command: str) -> str | None:
                return f"/usr/local/bin/{command}" if command in {"claude", "codex", "opencode"} else None

            with patch("engine.runtimes.Path.home", return_value=home), \
                patch("engine.runtimes.shutil.which", side_effect=fake_which), \
                patch("engine.runtimes.detect_cli_version", return_value=None), \
                patch.dict(os.environ, {}, clear=True):
                by_id = {candidate["id"]: candidate for candidate in discover_runtime_candidates()}

        self.assertEqual(by_id["codex"]["model"], "gpt-5.5")
        self.assertEqual(by_id["claude"]["model"], "mimo-v2.5-pro")
        self.assertEqual(by_id["opencode"]["model"], "glm-5")

    def test_runtime_discovery_caches_version_checks(self) -> None:
        """Runtime 候选项探测缓存版本检查，避免设置页每次加载都等待 CLI --version"""
        from engine.runtimes import clear_runtime_candidate_cache, discover_runtime_candidates

        clear_runtime_candidate_cache()

        def fake_which(command: str) -> str | None:
            return f"/usr/local/bin/{command}" if command in {"claude", "codex"} else None

        with patch("engine.runtimes.shutil.which", side_effect=fake_which), \
             patch("engine.runtimes.detect_cli_version", return_value="1.0.0") as detect_version, \
             patch.dict(os.environ, {}, clear=True):
            first = discover_runtime_candidates()
            second = discover_runtime_candidates()

        first_by_id = {candidate["id"]: candidate for candidate in first}
        second_by_id = {candidate["id"]: candidate for candidate in second}
        self.assertEqual(first_by_id["claude"]["version"], "1.0.0")
        self.assertEqual(second_by_id["codex"]["version"], "1.0.0")
        self.assertEqual(detect_version.call_count, 2)


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

    def test_assistant_thinking_only_event_is_suppressed(self) -> None:
        """assistant thinking-only 流事件不写入最终 Markdown 输出"""
        payload = json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "internal"}]}}
        )
        self.assertEqual(_decode_claude_stream_line(payload), "")

    def test_result_event_is_suppressed(self) -> None:
        """result 汇总事件不重复写入最终 Markdown 输出"""
        payload = json.dumps({"type": "result", "result": "# duplicated final answer"})
        self.assertEqual(_decode_claude_stream_line(payload), "")


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
    def test_mock_runtime_with_model(self) -> None:
        """runtime 带 model 字段时，mock 成功直接记录模型"""
        config = {
            "runtimes": {"Mock": {"cli": "mock", "response": "done", "model": "primary-model"}},
            "runner": {},
        }
        runner = AgentRunner(config)
        agent = AgentDefinition(name="test-agent", runtime_id="Mock", role="tester")
        runtime = {"cli": "mock", "response": "mock output success", "model": "primary-model"}
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

    def test_system_event_is_suppressed(self) -> None:
        """system 事件只保留在 raw log，不能污染最终产物"""
        payload = json.dumps({"type": "system", "data": "info"})
        self.assertEqual(_decode_claude_stream_line(payload), "")

    def test_assistant_type_empty_content(self) -> None:
        """assistant 非文本事件不能污染最终产物"""
        payload = json.dumps({"type": "assistant", "message": {"content": []}})
        self.assertEqual(_decode_claude_stream_line(payload), "")

    def test_assistant_type_no_message(self) -> None:
        """assistant 无 message 时不写入最终产物"""
        payload = json.dumps({"type": "assistant"})
        self.assertEqual(_decode_claude_stream_line(payload), "")

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

        config = {"runtimes": {"P": {"cli": "claude", "model": "m1"}}, "runner": {}}
        runner = AgentRunner(config)
        agent = AgentDefinition(name="a1", runtime_id="P")
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

        config = {"runtimes": {"P": {"cli": "claude", "model": "m1"}}, "runner": {}}
        runner = AgentRunner(config)
        agent = AgentDefinition(name="a1", runtime_id="P")
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

        config = {"runtimes": {"P": {"cli": "claude", "model": "m1"}}, "runner": {}}
        runner = AgentRunner(config)
        agent = AgentDefinition(name="a1", runtime_id="P", timeout=1)
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
        config = {"runtimes": {"P": {"cli": "claude", "model": "m1"}}, "runner": {"heartbeat_seconds": 1}}
        runner = AgentRunner(config, bus=bus)
        agent = AgentDefinition(name="a1", runtime_id="P")
        runtime = {"cli": "claude"}

        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            output_file = cwd / "out.md"
            raw_log = cwd / "raw.log"
            result = runner.run("r1", "s1", agent, runtime, "prompt", cwd, output_file, raw_log)
            self.assertEqual(result.status, "completed")


if __name__ == "__main__":
    unittest.main()
