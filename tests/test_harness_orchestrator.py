from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine.models import RunReport
from engine.orchestrator import Orchestrator


class HarnessOrchestratorTempProject(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / ".ai" / "harness").mkdir(parents=True)
        self.config_path = self.root / "team.yaml"
        self.config_path.write_text(
            "runtimes:\n"
            "  auto:\n"
            "    name: Auto\n"
            "    cli: auto\n"
            "agents: []\n"
            "pipeline:\n"
            "  - id: harness_verify\n"
            "    name: Harness 验证\n"
            "    type: harness_verify\n"
            "    output_file: harness-report.json\n"
            "    required_artifacts: [harness-report.json]\n"
            "worktree:\n"
            "  enabled: false\n"
            "quality_gates: []\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_harness(self, content: str) -> None:
        (self.root / ".ai" / "harness.yaml").write_text(content, encoding="utf-8")


class TestHarnessVerifyStage(HarnessOrchestratorTempProject):
    def test_harness_verify_blocks_pipeline_on_error_check(self) -> None:
        source = self.root / "src" / "app.py"
        source.parent.mkdir()
        source.write_text("eval(user_input)\n", encoding="utf-8")
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: pattern.eval\n"
            "    type: pattern\n"
            "    severity: error\n"
            "    pattern: eval\\(\n"
            "    globs: ['src/**/*.py']\n"
        )

        report = Orchestrator(self.root, config_path=str(self.config_path)).run("verify harness", run_id="run-block")

        output_dir = Path(report.output_dir)
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.stages[0].stage_id, "harness_verify")
        self.assertEqual(report.stages[0].status, "failed")
        self.assertTrue((output_dir / "harness-report.json").exists())
        self.assertTrue((output_dir / "harness-feedback.md").exists())

    def test_harness_verify_keeps_warning_nonblocking(self) -> None:
        source = self.root / "src" / "app.py"
        source.parent.mkdir()
        source.write_text("MessageBox.show('debug')\n", encoding="utf-8")
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: pattern.warning\n"
            "    type: pattern\n"
            "    severity: warning\n"
            "    pattern: MessageBox\n"
            "    globs: ['src/**/*.py']\n"
        )

        report = Orchestrator(self.root, config_path=str(self.config_path)).run("verify harness", run_id="run-warning")

        self.assertEqual(report.status, "completed")
        self.assertEqual(report.stages[0].status, "completed")

    def test_harness_verify_links_project_dependencies_for_worktree_command_checks(self) -> None:
        python_bin = self.root / ".venv" / "bin" / "python"
        python_bin.parent.mkdir(parents=True)
        python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        python_bin.chmod(0o755)
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: command.project-python\n"
            "    type: command\n"
            "    severity: error\n"
            "    blocking: true\n"
            "    command: .venv/bin/python -c \"print('linked')\"\n"
            "    timeout_seconds: 10\n"
        )
        worktree = self.root / "worktree-run"
        worktree.mkdir()
        output_dir = self.root / ".ai" / "runs" / "run-worktree"
        stage = {
            "id": "harness_verify",
            "name": "Harness 验证",
            "type": "harness_verify",
            "output_file": "harness-report.json",
            "required_artifacts": ["harness-report.json"],
        }
        report = RunReport(
            run_id="run-worktree",
            requirement="verify harness",
            project_root=str(self.root),
            output_dir=str(output_dir),
            config_source="customized",
        )

        stage_run = Orchestrator(self.root, config_path=str(self.config_path))._run_harness_verify_stage(
            stage,
            report,
            output_dir,
            worktree,
        )

        self.assertEqual(stage_run.status, "completed")
        self.assertTrue((worktree / ".venv").is_symlink())
        self.assertEqual((worktree / ".venv").resolve(), (self.root / ".venv").resolve())
        self.assertTrue((output_dir / "harness-report.json").exists())


if __name__ == "__main__":
    unittest.main()
