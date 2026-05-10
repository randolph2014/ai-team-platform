from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.context_scanner import (
    ContextScanner,
    detect_project_types,
    parse_implementation_checklist,
    scan_codebase,
    scan_to_json,
)


class TestImplementationChecklist(unittest.TestCase):
    def test_parse_checklist_extracts_files(self) -> None:
        """parse_implementation_checklist 从 markdown 提取文件列表"""
        draft = """## 实施清单

- `src/app.py`
- `src/utils.py`
- `tests/test_app.py`

## 其他

一些说明
"""
        files = parse_implementation_checklist(draft)
        self.assertEqual(files, ["src/app.py", "src/utils.py", "tests/test_app.py"])

    def test_parse_checklist_empty_on_no_section(self) -> None:
        """没有实施清单 section 时返回空列表"""
        draft = "## 背景\n\n一些描述\n"
        files = parse_implementation_checklist(draft)
        self.assertEqual(files, [])


class TestMaxFileSizeTruncation(unittest.TestCase):
    def test_large_file_is_truncated(self) -> None:
        """max_file_size 小于文件大小时输出被截断"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            big_content = "x" * 1000
            (root / "src" / "big.py").write_text(big_content, encoding="utf-8")

            scanner = ContextScanner(root, config={"max_file_size": 100, "max_context_files": 5})
            text = scanner.scan("")
            # 文件内容被截断
            self.assertIn("truncated", text)

    def test_scan_to_json(self) -> None:
        """scan_to_json 返回有效的 JSON"""
        import json

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
            result = scan_to_json(root)
            data = json.loads(result)
            self.assertIn("project_root", data)
            self.assertIn("python", data["project_types"])

    def test_scan_codebase_writes_output(self) -> None:
        """scan_codebase 写入输出文件"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            output_path = Path(tmp) / "context.md"
            text = scan_codebase(root, output_path=output_path)
            self.assertTrue(output_path.exists())
            self.assertIn("Codebase Context", text)

    def test_detect_project_types_node(self) -> None:
        """detect_project_types 检测 Node.js 项目"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")
            types = detect_project_types(root)
            self.assertIn("node", types)

    def test_parse_implementation_checklist_english(self) -> None:
        """parse_implementation_checklist 支持 English heading"""
        draft = "## Implementation Checklist\n\n- `src/app.ts`\n- `README.md`\n"
        files = parse_implementation_checklist(draft)
        self.assertEqual(files, ["src/app.ts", "README.md"])


class TestContextScannerHarnessSummary(unittest.TestCase):
    def test_harness_summary_injected_but_ai_tree_stays_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai" / "harness" / "rules").mkdir(parents=True)
            (root / ".ai" / "harness.yaml").write_text(
                "schema_version: '1.0'\n"
                "rules:\n"
                "  - id: security\n"
                "    file: .ai/harness/rules/security.md\n",
                encoding="utf-8",
            )
            (root / ".ai" / "harness" / "rules" / "security.md").write_text("rule", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")

            text = ContextScanner(root).scan("")

        self.assertIn("## Harness Summary", text)
        self.assertIn("Rules: 1", text)
        tree_section = text.split("## Project Tree", 1)[1].split("```", 2)[1]
        self.assertNotIn(".ai", tree_section)

    def test_scan_to_json_includes_harness_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai" / "harness" / "skills").mkdir(parents=True)
            (root / ".ai" / "harness.yaml").write_text(
                "schema_version: '1.0'\n"
                "skills:\n"
                "  - id: safe-refactor\n"
                "    file: .ai/harness/skills/safe-refactor.md\n"
                "    allowed_agents: [developer]\n"
                "    forbidden_capabilities: [bypass_human_gate]\n",
                encoding="utf-8",
            )
            (root / ".ai" / "harness" / "skills" / "safe-refactor.md").write_text("safe", encoding="utf-8")

            data = json.loads(scan_to_json(root))

        self.assertIn("harness", data)
        self.assertEqual(data["harness"]["skills_count"], 1)
        self.assertTrue(data["harness"]["manifest_hash"].startswith("sha256:"))

    def test_harness_summary_labels_skills_as_project_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai" / "harness" / "skills").mkdir(parents=True)
            (root / ".ai" / "harness.yaml").write_text(
                "schema_version: '1.0'\n"
                "skills:\n"
                "  - id: safe-refactor\n"
                "    file: .ai/harness/skills/safe-refactor.md\n"
                "    allowed_agents: [developer]\n"
                "    forbidden_capabilities: [bypass_human_gate]\n",
                encoding="utf-8",
            )
            (root / ".ai" / "harness" / "skills" / "safe-refactor.md").write_text("safe", encoding="utf-8")

            text = ContextScanner(root).scan("")

        self.assertIn("project context", text)
        self.assertIn("must not override system/developer/platform safety policy", text)


class TestContextScannerTaskBoard(unittest.TestCase):
    def test_context_scan_injects_related_harness_tasks(self) -> None:
        from engine.task_board import TaskEvent, record_task_event

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_task_event(
                root,
                TaskEvent(
                    task_id="T-checkout",
                    title="Accepted checkout flow",
                    state="accepted",
                    source_stage="acceptance_confirm",
                    decision="approved",
                    run_id="run-checkout",
                    artifact_dir=str(root / ".ai" / "team-output" / "run-checkout"),
                    decision_ids=["human:run-checkout:acceptance_confirm:1"],
                    requirement="Implement checkout payment flow",
                    tags=["checkout", "payment"],
                    related_files=["src/checkout.py"],
                    decisions=[{"id": "D-checkout", "summary": "Use idempotency key"}],
                ),
            )

            text = scan_codebase(root, requirement_text="Change checkout payment submit behavior")
            data = json.loads(scan_to_json(root, requirement_text="Change checkout payment submit behavior"))

        self.assertIn("## Harness Related Tasks", text)
        self.assertIn("T-checkout", text)
        self.assertEqual(data["harness"]["related_tasks"][0]["task_id"], "T-checkout")

    def test_context_scan_without_related_tasks_keeps_existing_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = json.loads(scan_to_json(root, requirement_text="new unrelated feature"))

        self.assertIn("harness", data)
        self.assertEqual(data["harness"]["related_tasks"], [])


if __name__ == "__main__":
    unittest.main()
