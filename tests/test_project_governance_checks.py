from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


SCRIPT_PATH = Path("scripts/verify_project_governance.py")


def _load_script_module():
    spec = importlib.util.spec_from_file_location("verify_project_governance", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("verify_project_governance.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


class TestProjectGovernanceChecks(unittest.TestCase):
    def test_project_governance_script_passes_current_repository(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("project governance checks passed", result.stdout)

    def test_legacy_entry_scan_detects_forbidden_project_team_entry(self) -> None:
        module = _load_script_module()
        legacy_entry = "/".join([".ai", "team.yaml"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "bad.md").write_text(f"use {legacy_entry} as project source\n", encoding="utf-8")

            findings = module.check_legacy_entry_patterns(root)

        self.assertEqual(len(findings), 1)
        self.assertIn("legacy project team entry", findings[0].message)

    def test_harness_registers_project_governance_check(self) -> None:
        payload = yaml.safe_load(Path(".ai/harness.yaml").read_text(encoding="utf-8"))
        checks = {item["id"]: item for item in payload["checks"]}

        self.assertIn("checks.governance.project-finalization", checks)
        check = checks["checks.governance.project-finalization"]
        self.assertEqual(check["type"], "command")
        self.assertTrue(check["blocking"])
        self.assertIn("scripts/verify_project_governance.py", check["command"])

    def test_deprecated_usage_registry_detects_generic_patterns(self) -> None:
        module = _load_script_module()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / ".ai" / "harness" / "checks" / "deprecated-usage-registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                """
{
  "schema_version": "1.0",
  "patterns": [
    {
      "id": "deprecated.old-api",
      "message": "old_api is deprecated",
      "regex": "old_api\\\\(",
      "severity": "error",
      "globs": ["src/**/*.py"]
    }
  ]
}
""",
                encoding="utf-8",
            )
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("old_api('x')\n", encoding="utf-8")

            findings = module.check_deprecated_usage_registry(root, registry)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].check, "deprecated-usage:deprecated.old-api")
        self.assertEqual(findings[0].path, Path("src/app.py"))

    def test_harness_registers_deprecated_usage_check(self) -> None:
        payload = yaml.safe_load(Path(".ai/harness.yaml").read_text(encoding="utf-8"))
        checks = {item["id"]: item for item in payload["checks"]}

        self.assertIn("checks.deprecated-usage", checks)
        check = checks["checks.deprecated-usage"]
        self.assertEqual(check["type"], "command")
        self.assertTrue(check["blocking"])
        self.assertIn("--deprecated-registry", check["command"])
        self.assertIn(".ai/harness/checks/deprecated-usage-registry.json", check["command"])

    def test_traceability_contracts_are_checked_by_governance_script(self) -> None:
        module = _load_script_module()

        findings = module.check_traceability_contracts(Path.cwd())

        self.assertEqual(findings, [])

    def test_markdown_doc_links_must_target_existing_files(self) -> None:
        module = _load_script_module()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("[missing spec](docs/spec.md)\n", encoding="utf-8")
            (root / "docs").mkdir()

            findings = module.check_markdown_file_links(root)

        self.assertEqual(len(findings), 1)
        self.assertIn("missing local markdown link target", findings[0].message)


if __name__ == "__main__":
    unittest.main()
