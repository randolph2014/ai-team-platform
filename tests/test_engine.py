from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine.config import load_config, resolve_prompt_path, agent_map
from engine.context_scanner import ContextScanner, is_sensitive_path
from engine.orchestrator import Orchestrator
from engine.quality_gates import run_quality_gate


class EngineTests(unittest.TestCase):
    def test_platform_template_is_default_config_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            loaded = load_config(root)
            self.assertIn(loaded.source, {"platform", "default"})
            self.assertNotEqual(loaded.source, "skill")
            if loaded.path:
                self.assertIn("templates", loaded.path)

    def test_prompt_resolves_from_platform_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            loaded = load_config(root)
            agents = agent_map(loaded.config)
            prompt = resolve_prompt_path(root, loaded.path, agents["tech-lead"])
            self.assertIn("templates/agents/tech-lead.md", str(prompt))

    def test_context_scanner_excludes_sensitive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
            self.assertTrue(is_sensitive_path(".env"))
            text = ContextScanner(root).scan("")
            self.assertIn("src/app.py", text)
            self.assertNotIn("SECRET=1", text)

    def test_quality_gate_command_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_quality_gate(
                {"name": "smoke", "type": "command", "command": "python3 -c \"print('ok')\"", "required": True},
                Path(tmp),
                "test-run",
            )
            self.assertEqual(result.status, "passed")
            self.assertEqual(result.exit_code, 0)

    def test_orchestrator_runs_mock_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / ".ai" / "team.yaml").write_text(
                """
providers:
  Mock:
    cli: mock
    response: "Approve"
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
      dev: tech-lead-output.md
  - id: accept
    name: Accept
    type: human_review
quality_gates:
  - name: smoke
    type: command
    command: "python3 -c \\"print('ok')\\""
    required: true
    max_retries: 0
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root).run("ship it", yes=True)
            self.assertEqual(report.status, "completed")
            self.assertEqual(report.config_source, "project")
            self.assertIn("tech-lead-output.md", report.artifacts)
            self.assertTrue((Path(report.output_dir) / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
