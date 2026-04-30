from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from engine.agent_runner import AgentRunner
from engine.models import AgentDefinition, AgentRun
from engine.runtimes import backfill_runtime_models, build_runtime_command


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


# FallbackRetryTest removed — fallback_models feature simplified to single-model execution.


class RuntimeModelBackfillTest(unittest.TestCase):
    """Orchestrator 启动时对未声明 model 的 runtime 从 CLI 配置回填，仅用于可观测性。"""

    @patch("engine.runtimes._cli_config_model")
    @patch("engine.runtimes.resolve_auto_cli")
    def test_backfills_model_when_runtime_has_none(self, mock_resolve, mock_cli_config) -> None:
        mock_resolve.return_value = "claude"
        mock_cli_config.return_value = "claude-sonnet-4-6"
        runtimes = {"auto": {"cli": "auto"}}
        backfill_runtime_models(runtimes)
        self.assertEqual(runtimes["auto"]["model"], "claude-sonnet-4-6")
        self.assertEqual(runtimes["auto"]["_model_source"], "cli-config")
        mock_cli_config.assert_called_once_with("claude")

    @patch("engine.runtimes._cli_config_model")
    def test_preserves_explicit_model(self, mock_cli_config) -> None:
        mock_cli_config.return_value = "should-not-be-used"
        runtimes = {"auto": {"cli": "claude", "model": "claude-opus-4-7"}}
        backfill_runtime_models(runtimes)
        self.assertEqual(runtimes["auto"]["model"], "claude-opus-4-7")
        self.assertNotIn("_model_source", runtimes["auto"])
        mock_cli_config.assert_not_called()

    @patch("engine.runtimes._cli_config_model")
    @patch("engine.runtimes.resolve_auto_cli")
    def test_no_backfill_when_cli_config_empty(self, mock_resolve, mock_cli_config) -> None:
        mock_resolve.return_value = "claude"
        mock_cli_config.return_value = None
        runtimes = {"auto": {"cli": "auto"}}
        backfill_runtime_models(runtimes)
        self.assertNotIn("model", runtimes["auto"])
        self.assertNotIn("_model_source", runtimes["auto"])

    @patch("engine.runtimes._cli_config_model")
    @patch("engine.runtimes.resolve_auto_cli")
    def test_no_backfill_when_auto_cli_unresolved(self, mock_resolve, mock_cli_config) -> None:
        mock_resolve.return_value = None
        runtimes = {"auto": {"cli": "auto"}}
        backfill_runtime_models(runtimes)
        self.assertNotIn("model", runtimes["auto"])
        mock_cli_config.assert_not_called()

    @patch("engine.runtimes._cli_config_model")
    def test_uses_cli_directly_when_not_auto(self, mock_cli_config) -> None:
        mock_cli_config.return_value = "gpt-5"
        runtimes = {"my-codex": {"cli": "codex"}}
        backfill_runtime_models(runtimes)
        self.assertEqual(runtimes["my-codex"]["model"], "gpt-5")
        mock_cli_config.assert_called_once_with("codex")

    @patch("engine.runtimes._cli_config_model")
    def test_handles_multiple_runtimes_independently(self, mock_cli_config) -> None:
        mock_cli_config.side_effect = lambda cli: {"claude": "claude-sonnet-4-6", "codex": "gpt-5"}.get(cli)
        runtimes = {
            "claude-rt": {"cli": "claude"},
            "codex-rt": {"cli": "codex"},
            "explicit-rt": {"cli": "claude", "model": "claude-opus-4-7"},
        }
        backfill_runtime_models(runtimes)
        self.assertEqual(runtimes["claude-rt"]["model"], "claude-sonnet-4-6")
        self.assertEqual(runtimes["codex-rt"]["model"], "gpt-5")
        self.assertEqual(runtimes["explicit-rt"]["model"], "claude-opus-4-7")
        self.assertNotIn("_model_source", runtimes["explicit-rt"])

    def test_empty_runtimes_dict_is_noop(self) -> None:
        runtimes: dict = {}
        backfill_runtime_models(runtimes)
        self.assertEqual(runtimes, {})


if __name__ == "__main__":
    unittest.main()
