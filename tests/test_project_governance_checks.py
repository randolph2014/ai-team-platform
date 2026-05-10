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


if __name__ == "__main__":
    unittest.main()
