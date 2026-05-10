from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine.harness import (
    HarnessConflictError,
    HarnessPathError,
    HarnessSchemaError,
    apply_harness_files,
    compute_harness_manifest,
    load_harness_bundle,
    render_harness_summary_markdown,
    resolve_harness_path,
    summarize_harness,
    validate_harness_files,
)


class HarnessTempProject(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / ".git").mkdir()
        (self.root / ".ai" / "harness").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_harness(self, content: str) -> None:
        (self.root / ".ai" / "harness.yaml").write_text(content, encoding="utf-8")


class TestHarnessSchemaValidation(HarnessTempProject):
    def test_valid_minimal_harness_yaml_loads(self) -> None:
        self.write_harness("schema_version: '1.0'\nrules: []\nskills: []\n")

        bundle = load_harness_bundle(self.root)

        self.assertTrue(bundle.validation["valid"])
        self.assertEqual(bundle.config.schema_version, "1.0")
        self.assertEqual(bundle.summary["rules_count"], 0)

    def test_missing_harness_yaml_returns_empty_bundle_warning(self) -> None:
        bundle = load_harness_bundle(self.root)

        self.assertTrue(bundle.validation["valid"])
        self.assertIn("harness_config_missing", bundle.warnings)

    def test_invalid_harness_yaml_fails(self) -> None:
        self.write_harness("schema_version: [")

        with self.assertRaises(HarnessSchemaError):
            load_harness_bundle(self.root)

    def test_invalid_top_level_type_fails(self) -> None:
        self.write_harness("- not-a-mapping\n")

        with self.assertRaises(HarnessSchemaError):
            load_harness_bundle(self.root)

    def test_unknown_top_level_field_fails(self) -> None:
        self.write_harness("schema_version: '1.0'\nunknown: true\n")

        with self.assertRaises(HarnessSchemaError):
            load_harness_bundle(self.root)

    def test_unknown_or_unsafe_file_reference_fails(self) -> None:
        self.write_harness(
            "schema_version: '1.0'\n"
            "rules:\n"
            "  - id: bad\n"
            "    file: ../outside.md\n"
        )

        with self.assertRaises(HarnessPathError):
            load_harness_bundle(self.root)

    def test_skill_metadata_requires_allowed_agents_and_forbidden_capabilities(self) -> None:
        self.write_harness(
            "schema_version: '1.0'\n"
            "skills:\n"
            "  - id: safe-refactor\n"
            "    file: .ai/harness/skills/safe-refactor.md\n"
            "    allowed_agents: []\n"
        )

        with self.assertRaises(HarnessSchemaError):
            load_harness_bundle(self.root)

    def test_valid_skill_metadata_loads(self) -> None:
        (self.root / ".ai" / "harness" / "skills").mkdir()
        (self.root / ".ai" / "harness" / "skills" / "safe-refactor.md").write_text("safe", encoding="utf-8")
        self.write_harness(
            "schema_version: '1.0'\n"
            "skills:\n"
            "  - id: safe-refactor\n"
            "    title: Safe Refactor\n"
            "    file: .ai/harness/skills/safe-refactor.md\n"
            "    allowed_agents: [developer, reviewer]\n"
            "    forbidden_capabilities: [modify_baselines, disable_checks]\n"
        )

        bundle = load_harness_bundle(self.root)

        self.assertTrue(bundle.validation["valid"])
        self.assertEqual(bundle.summary["skills_count"], 1)

    def test_check_schema_requires_command_timeout_and_metadata(self) -> None:
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: cmd.missing-timeout\n"
            "    type: command\n"
            "    command: \"echo ok\"\n"
        )

        with self.assertRaises(HarnessSchemaError):
            load_harness_bundle(self.root)

        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: cmd.valid\n"
            "    type: command\n"
            "    command: \"echo ok\"\n"
            "    timeout_seconds: 5\n"
        )

        bundle = load_harness_bundle(self.root)
        self.assertEqual(bundle.config.checks[0].id, "cmd.valid")

    def test_check_schema_rejects_unsafe_command_cwd(self) -> None:
        self.write_harness(
            "schema_version: '1.0'\n"
            "checks:\n"
            "  - id: cmd.unsafe-cwd\n"
            "    type: command\n"
            "    command: \"echo ok\"\n"
            "    timeout_seconds: 5\n"
            "    cwd: ../outside\n"
        )

        with self.assertRaises(HarnessSchemaError):
            load_harness_bundle(self.root)


class TestHarnessPathSafety(HarnessTempProject):
    def test_allows_only_harness_yaml_and_harness_directory(self) -> None:
        self.assertEqual(
            resolve_harness_path(self.root, ".ai/harness.yaml"),
            (self.root / ".ai" / "harness.yaml").resolve(strict=False),
        )
        self.assertEqual(
            resolve_harness_path(self.root, ".ai/harness/rules/security.md"),
            (self.root / ".ai" / "harness" / "rules" / "security.md").resolve(strict=False),
        )
        with self.assertRaises(HarnessPathError):
            resolve_harness_path(self.root, ".ai/not-harness.yaml")

    def test_rejects_absolute_path(self) -> None:
        with self.assertRaises(HarnessPathError):
            resolve_harness_path(self.root, str(self.root / ".ai" / "harness.yaml"))

    def test_rejects_parent_traversal(self) -> None:
        with self.assertRaises(HarnessPathError):
            resolve_harness_path(self.root, ".ai/harness/../not-harness.yaml")

    def test_rejects_symlink_escape(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir()
        link = self.root / ".ai" / "harness" / "escape"
        link.symlink_to(outside, target_is_directory=True)

        with self.assertRaises(HarnessPathError):
            resolve_harness_path(self.root, ".ai/harness/escape/file.md")

    def test_manifest_scan_rejects_symlink_file_escape_as_harness_path_error(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside-file.md"
        outside.write_text("outside", encoding="utf-8")
        link = self.root / ".ai" / "harness" / "escape.md"
        link.symlink_to(outside)

        try:
            with self.assertRaises(HarnessPathError):
                compute_harness_manifest(self.root)
        finally:
            outside.unlink(missing_ok=True)

    def test_rejects_directory_target(self) -> None:
        with self.assertRaises(HarnessPathError):
            resolve_harness_path(self.root, ".ai/harness")


class TestHarnessManifest(HarnessTempProject):
    def test_manifest_hash_is_stable_and_reproducible(self) -> None:
        self.write_harness("schema_version: '1.0'\n")
        first = compute_harness_manifest(self.root)
        second = compute_harness_manifest(self.root)

        self.assertEqual(first["manifest_hash"], second["manifest_hash"])
        self.assertEqual(first["files"], second["files"])

    def test_manifest_changes_when_another_harness_file_changes(self) -> None:
        self.write_harness("schema_version: '1.0'\n")
        rules_dir = self.root / ".ai" / "harness" / "rules"
        rules_dir.mkdir()
        rule_file = rules_dir / "security.md"
        rule_file.write_text("v1", encoding="utf-8")
        first = compute_harness_manifest(self.root)

        rule_file.write_text("v2", encoding="utf-8")
        second = compute_harness_manifest(self.root)

        self.assertNotEqual(first["manifest_hash"], second["manifest_hash"])

    def test_empty_manifest_hash_is_stable(self) -> None:
        manifest = compute_harness_manifest(self.root)

        self.assertTrue(manifest["manifest_hash"].startswith("sha256:"))
        self.assertEqual(manifest["files"], [])

    def test_changed_files_are_reported(self) -> None:
        self.write_harness("schema_version: '1.0'\n")
        first = compute_harness_manifest(self.root)
        (self.root / ".ai" / "harness" / "rules").mkdir()
        (self.root / ".ai" / "harness" / "rules" / "security.md").write_text("new", encoding="utf-8")
        second = compute_harness_manifest(self.root, previous=first)

        self.assertEqual(second["changed_files"], [".ai/harness/rules/security.md"])


class TestHarnessWriteValidation(HarnessTempProject):
    def test_validate_harness_files_uses_candidate_assets(self) -> None:
        result = validate_harness_files(
            self.root,
            [
                {"path": ".ai/harness.yaml", "content": "schema_version: '1.0'\nrules:\n  - id: r1\n    file: .ai/harness/rules/r1.md\n"},
                {"path": ".ai/harness/rules/r1.md", "content": "rule"},
            ],
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["summary"]["rules_count"], 1)

    def test_invalid_schema_does_not_write(self) -> None:
        self.write_harness("schema_version: '1.0'\n")
        manifest = compute_harness_manifest(self.root)

        with self.assertRaises(HarnessSchemaError):
            apply_harness_files(
                self.root,
                [{"path": ".ai/harness.yaml", "content": "schema_version: '1.0'\nunknown: true\n"}],
                manifest["manifest_hash"],
            )

        self.assertEqual((self.root / ".ai" / "harness.yaml").read_text(encoding="utf-8"), "schema_version: '1.0'\n")

    def test_stale_manifest_raises_conflict_with_changed_files(self) -> None:
        self.write_harness("schema_version: '1.0'\n")
        stale = compute_harness_manifest(self.root)
        (self.root / ".ai" / "harness" / "rules").mkdir()
        (self.root / ".ai" / "harness" / "rules" / "security.md").write_text("changed", encoding="utf-8")

        with self.assertRaises(HarnessConflictError) as ctx:
            apply_harness_files(
                self.root,
                [{"path": ".ai/harness.yaml", "content": "schema_version: '1.0'\n"}],
                stale["manifest_hash"],
            )

        self.assertIn(".ai/harness/rules/security.md", ctx.exception.changed_files)


class TestHarnessSkillPolicy(HarnessTempProject):
    def test_harness_skill_summary_is_project_context_not_platform_policy(self) -> None:
        (self.root / ".ai" / "harness" / "skills").mkdir()
        (self.root / ".ai" / "harness" / "skills" / "safe-refactor.md").write_text("safe", encoding="utf-8")
        self.write_harness(
            "schema_version: '1.0'\n"
            "skills:\n"
            "  - id: safe-refactor\n"
            "    file: .ai/harness/skills/safe-refactor.md\n"
            "    allowed_agents: [developer]\n"
            "    forbidden_capabilities: [bypass_human_gate]\n"
        )

        summary = summarize_harness(self.root)
        markdown = render_harness_summary_markdown(summary)

        self.assertIn("project context", markdown)
        self.assertIn("must not override system/developer/platform safety policy", markdown)
        self.assertIn("human gates", markdown)


class TestRepositoryHarnessGovernanceAssets(unittest.TestCase):
    def test_phase3_governance_assets_declare_executable_command_check(self) -> None:
        root = Path.cwd()

        bundle = load_harness_bundle(root)

        self.assertEqual(bundle.warnings, [])
        self.assertEqual(bundle.config.schema_version, "1.0")
        self.assertGreaterEqual(bundle.summary["rules_count"], 3)
        self.assertGreaterEqual(bundle.summary["skills_count"], 2)
        self.assertGreaterEqual(bundle.summary["checks_count"], 1)
        self.assertGreaterEqual(bundle.summary["baselines_count"], 1)
        command_checks = [check for check in bundle.config.checks if check.type == "command"]
        self.assertGreaterEqual(len(command_checks), 1)
        command_check = command_checks[0]
        self.assertTrue(command_check.id.startswith("checks."))
        self.assertTrue(command_check.command)
        self.assertGreater(command_check.timeout_seconds or 0, 0)
        self.assertEqual(command_check.severity, "error")
        self.assertTrue(command_check.blocking)
        self.assertTrue(command_check.file)
        self.assertTrue((root / command_check.file).is_file())

        forbidden_capabilities = {
            capability
            for skill in bundle.config.skills
            for capability in skill.forbidden_capabilities
        }
        self.assertIn("bypass_human_gate", forbidden_capabilities)
        self.assertIn("bypass_quality_gate", forbidden_capabilities)
        self.assertIn("disable_checks", forbidden_capabilities)
        self.assertIn("modify_baselines", forbidden_capabilities)

        self.assertTrue((root / ".ai" / "harness" / "tasks" / "task-memory-contract.md").is_file())
        self.assertTrue((root / ".ai" / "harness" / "tasks" / "state-model.md").is_file())

        agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Harness Governance Layer", agents_text)
        self.assertIn("不能绕过 human gate", agents_text)
        self.assertIn("不能把 DB 作为 Harness 配置真相源", agents_text)


if __name__ == "__main__":
    unittest.main()
