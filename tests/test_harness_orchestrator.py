from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
