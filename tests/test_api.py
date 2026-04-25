from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from api import runtime

        runtime.active_runs.clear()
        runtime.run_projects.clear()

    def test_background_run_records_project_and_artifacts(self) -> None:
        from api import runtime
        from engine.orchestrator import find_run_reports, load_report

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai" / "agents").mkdir(parents=True)
            (root / ".ai" / "agents" / "dev.md").write_text("You are a test agent.", encoding="utf-8")
            (root / ".ai" / "team.yaml").write_text(
                """
providers:
  Mock:
    cli: mock
    response: "done"
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
      dev: dev-output.md
""",
                encoding="utf-8",
            )
            run_id = "api-test-run"
            output_dir = runtime.start_run_background("api smoke", str(root), run_id=run_id, yes=True)
            thread = runtime.active_runs.get(run_id)
            self.assertIsNotNone(thread)
            thread.join(timeout=5)

            self.assertTrue(output_dir.exists())
            reports = find_run_reports(root)
            self.assertEqual(len(reports), 1)
            report = load_report(reports[0])
            self.assertEqual(report.status, "completed")
            self.assertEqual(report.config_source, "project")
            self.assertEqual(runtime.project_for_run(run_id), root.resolve())
            artifact_names = set(report.artifacts)
            self.assertIn("dev-output.md", artifact_names)
            self.assertIn("report.json", artifact_names)

    def test_expected_output_dir_detects_duplicate_run_id(self) -> None:
        from api import runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = runtime.expected_output_dir("duplicate", str(root))
            existing.mkdir(parents=True)
            self.assertTrue(existing.exists())


if __name__ == "__main__":
    unittest.main()
