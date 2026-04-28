from __future__ import annotations

import unittest
from pathlib import Path

from engine.agent_runner import AgentRunner
from engine.models import AgentDefinition, AgentRun
from engine.runtimes import build_runtime_command


class BuildCommandWithModelTest(unittest.TestCase):
    def test_claude_includes_model_flag(self) -> None:
        runtime = {"cli": "claude"}
        cmd, cli, _ = build_runtime_command(runtime, "do something", model="claude-opus-4-7")
        self.assertEqual(cli, "claude")
        self.assertIn("--model", cmd)
        idx = cmd.index("--model")
        self.assertEqual(cmd[idx + 1], "claude-opus-4-7")

    def test_codex_uses_dash_m(self) -> None:
        runtime = {"cli": "codex"}
        cmd, cli, _ = build_runtime_command(runtime, "do something", model="o3")
        self.assertEqual(cli, "codex")
        self.assertIn("-m", cmd)
        idx = cmd.index("-m")
        self.assertEqual(cmd[idx + 1], "o3")

    def test_opencode_includes_model_flag(self) -> None:
        runtime = {"cli": "opencode"}
        cmd, cli, _ = build_runtime_command(runtime, "do something", model="gemini-2.5-pro")
        self.assertEqual(cli, "opencode")
        self.assertIn("--model", cmd)
        idx = cmd.index("--model")
        self.assertEqual(cmd[idx + 1], "gemini-2.5-pro")

    def test_no_model_omits_flag(self) -> None:
        runtime = {"cli": "claude"}
        cmd, _, _ = build_runtime_command(runtime, "do something", model=None)
        self.assertNotIn("--model", cmd)

    def test_mock_runtime_ignores_model(self) -> None:
        runtime = {"cli": "mock"}
        cmd, cli, _ = build_runtime_command(runtime, "do something", model="any-model")
        self.assertEqual(cli, "mock")
        self.assertEqual(cmd, ["mock"])


class FallbackRetryTest(unittest.TestCase):
    def test_runtime_fallback_tries_next_model_on_failure(self) -> None:
        """runtime 主模型失败后回退到 fallback_models，最终用 fallback 成功"""
        attempts: list = []

        def tracking_try_model(
            run_id, stage_id, agent, runtime, prompt, cwd, output_file, raw_log_file, model, model_requested, timeout, heartbeat_seconds
        ):
            attempts.append(model)
            if model == "primary-model":
                return AgentRun(
                    agent_name=agent.name, runtime_id=agent.runtime_id, model_used=model, status="failed", error_message="unavailable"
                )
            return AgentRun(agent_name=agent.name, runtime_id=agent.runtime_id, model_used=model, status="completed")

        runner = AgentRunner({"runtimes": {}, "runner": {}})
        runner._try_model = tracking_try_model

        agent_def = AgentDefinition(name="dev", runtime_id="Mock")
        runtime_cfg = {"cli": "mock", "model": "primary-model", "fallback_models": ["fallback-a"]}
        result = runner.run(
            run_id="test-run",
            stage_id="develop",
            agent=agent_def,
            runtime=runtime_cfg,
            prompt="test",
            cwd=Path("/tmp"),
            output_file=Path("/tmp/test-output.md"),
            raw_log_file=Path("/tmp/test-raw.log"),
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.model_used, "fallback-a")
        self.assertEqual(attempts, ["primary-model", "fallback-a"])

    def test_all_models_fail_returns_last_error(self) -> None:
        """所有模型都失败时返回最后一个错误"""
        attempts: list = []

        def always_fail(
            run_id, stage_id, agent, runtime, prompt, cwd, output_file, raw_log_file, model, model_requested, timeout, heartbeat_seconds
        ):
            attempts.append(model)
            return AgentRun(
                agent_name=agent.name, runtime_id=agent.runtime_id, model_used=model, status="failed", error_message=f"{model}-unavailable"
            )

        runner = AgentRunner({"runtimes": {}, "runner": {}})
        runner._try_model = always_fail

        agent_def = AgentDefinition(name="dev", runtime_id="Mock")
        runtime_cfg = {"cli": "mock", "model": "model-a", "fallback_models": ["model-b", "model-c"]}
        result = runner.run(
            run_id="test-run",
            stage_id="develop",
            agent=agent_def,
            runtime=runtime_cfg,
            prompt="test",
            cwd=Path("/tmp"),
            output_file=Path("/tmp/test-output.md"),
            raw_log_file=Path("/tmp/test-raw.log"),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.model_used, "model-c")
        self.assertIn("model-c-unavailable", result.error_message)
        self.assertEqual(attempts, ["model-a", "model-b", "model-c"])


if __name__ == "__main__":
    unittest.main()
