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


class CodeApplierJsonOutputTests(unittest.TestCase):
    """测试 JSON 结构化输出协议解析"""

    def test_parse_pure_json(self):
        """测试纯 JSON 格式"""
        content = '''{
  "files": [
    {
      "path": "src/auth/login.py",
      "action": "create",
      "content": "import os\\n\\ndef login():\\n    pass"
    }
  ]
}'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].filepath, "src/auth/login.py")
            self.assertEqual(changes[0].action, "created")
            target = root / "src" / "auth" / "login.py"
            self.assertTrue(target.exists())
            self.assertIn("def login():", target.read_text(encoding="utf-8"))

    def test_parse_json_in_markdown_code_block(self):
        """测试 markdown 中的 JSON 代码块"""
        content = '''## 代码变更

```json
{
  "files": [
    {
      "path": "utils/helper.py",
      "action": "modify",
      "content": "def helper():\\n    return True"
    }
  ]
}
```

以上是变更内容。'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # 创建已存在的文件
            existing = root / "utils" / "helper.py"
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text("def old_helper():\n    return False", encoding="utf-8")

            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].filepath, "utils/helper.py")
            self.assertEqual(changes[0].action, "modified")
            self.assertIn("def helper():", existing.read_text(encoding="utf-8"))

    def test_json_with_multiple_files(self):
        """测试 JSON 包含多个文件"""
        content = '''{
  "files": [
    {"path": "src/a.py", "action": "create", "content": "# a"},
    {"path": "src/b.py", "action": "create", "content": "# b"},
    {"path": "tests/test_a.py", "action": "create", "content": "# test a"}
  ]
}'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 3)
            self.assertTrue((root / "src" / "a.py").exists())
            self.assertTrue((root / "src" / "b.py").exists())
            self.assertTrue((root / "tests" / "test_a.py").exists())

    def test_json_fallback_to_markdown(self):
        """测试 JSON 解析失败时回退到 markdown"""
        content = '''这不是有效的 JSON

### 修改文件: `fallback.py`
```python
print("fallback")
```
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].filepath, "fallback.py")
            self.assertTrue((root / "fallback.py").exists())

    def test_json_missing_path_skipped(self):
        """测试 JSON 中缺少 path 的条目被跳过"""
        content = '''{
  "files": [
    {"action": "create", "content": "no path"},
    {"path": "valid.py", "action": "create", "content": "valid"}
  ]
}'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].filepath, "valid.py")

    def test_json_outside_root_skipped(self):
        """测试 JSON 中路径超出项目范围的文件被跳过"""
        content = '''{
  "files": [
    {"path": "/etc/passwd", "action": "create", "content": "hacked"}
  ]
}'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 0)

    def test_json_action_aliases(self):
        """测试 JSON 中 action 别名的规范化"""
        content = '''{
  "files": [
    {"path": "a.py", "action": "add", "content": "# a"},
    {"path": "b.py", "action": "update", "content": "# b"},
    {"path": "c.py", "action": "edit", "content": "# c"}
  ]
}'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            applier = CodeApplier(root)
            changes = applier.apply(content)
            self.assertEqual(len(changes), 3)
            # 所有 action 都应该被规范化
            actions = {c.filepath: c.action for c in changes}
            self.assertEqual(actions["a.py"], "created")
            self.assertEqual(actions["b.py"], "modified")
            self.assertEqual(actions["c.py"], "modified")


if __name__ == "__main__":
    unittest.main()
