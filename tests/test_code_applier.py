"""CodeApplier 模块测试"""

import tempfile
import unittest
from pathlib import Path

from engine.code_applier import CodeApplier, apply_code_from_output, extract_diff


class CodeApplierExtractBlocksTests(unittest.TestCase):
    def test_extract_named_block_with_file_header(self):
        content = (
            '### 修改文件: `src/foo/bar.swift`\n'
            '```swift\n'
            'import Foundation\n'
            'struct Foo {}\n'
            '```\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].filepath, "src/foo/bar.swift")
            self.assertEqual(changes[0].action, "created")
            target = root / "src" / "foo" / "bar.swift"
            self.assertTrue(target.exists())
            written = target.read_text(encoding="utf-8")
            self.assertIn("struct Foo", written)

    def test_extract_multiple_blocks(self):
        content = (
            '### 修改文件: `a.swift`\n'
            '```swift\n'
            '// a\n'
            '```\n\n'
            '### 新增文件: `b.swift`\n'
            '```swift\n'
            '// b\n'
            '```\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 2)
            self.assertTrue((root / "a.swift").exists())
            self.assertTrue((root / "b.swift").exists())

    def test_apply_preserves_files_outside_root(self):
        content = (
            '### 修改文件: `/etc/passwd`\n'
            '```text\n'
            'hacked\n'
            '```\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 0)

    def test_empty_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            applier = CodeApplier(root)
            changes = applier.apply("")
            self.assertEqual(changes, [])

    def test_code_without_file_header_still_extracts(self):
        content = (
            '文件：`src/config.swift`\n'
            '```swift\n'
            'enum Config {}\n'
            '```\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 1)
            target = root / "src" / "config.swift"
            self.assertTrue(target.exists())

    def test_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            existing = root / "existing.swift"
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text("old content", encoding="utf-8")
            content = (
                '### 修改文件: `existing.swift`\n'
                '```swift\n'
                'new content\n'
                '```\n'
            )
            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].action, "modified")
            self.assertEqual(existing.read_text(encoding="utf-8").strip(), "new content")


class CodeApplierDiffTests(unittest.TestCase):
    def test_extract_diff(self):
        content = (
            '一些描述文字\n'
            '```diff\n'
            '--- a/foo.swift\n'
            '+++ b/foo.swift\n'
            '@@ -1,1 +1,1 @@\n'
            '-old\n'
            '+new\n'
            '```\n'
        )
        diff = extract_diff(content)
        self.assertIsNotNone(diff)
        self.assertIn("-old", diff)
        self.assertIn("+new", diff)

    def test_no_diff_block(self):
        content = "just text"
        diff = extract_diff(content)
        self.assertIsNone(diff)


class CodeApplierConvenienceTests(unittest.TestCase):
    def test_apply_code_from_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            content = (
                '### 修改文件: `hello.py`\n'
                '```python\n'
                'print("hello")\n'
                '```\n'
            )
            changes = apply_code_from_output(content, root)
            self.assertEqual(len(changes), 1)
            target = root / "hello.py"
            self.assertTrue(target.exists())
            self.assertIn("hello", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
