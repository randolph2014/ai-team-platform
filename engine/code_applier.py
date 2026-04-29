from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CodeApplierError(RuntimeError):
    pass


class AppliedChange:
    def __init__(self, filepath: str, action: str, lines: int):
        self.filepath = filepath
        self.action = action
        self.lines = lines
        self.blocks = []

    def __repr__(self):
        return f"AppliedChange({self.filepath!r}, {self.action!r}, {self.lines})"


FILEPATH_FINDERS = [
    re.compile(r"###?\s+(?:修改|新增|创建|更新|Modify|Create|Add|Update)\s*(?:文件|File)?:?\s*`([^`]+)`", re.IGNORECASE),
    re.compile(r"[-*]\s+(?:修改|新增|创建|更新|modify|create|add|update)\s*(?:文件|file)?:?\s*`([^`]+)`", re.IGNORECASE),
    re.compile(r"(?:文件|File)[：:]\s*`([^`]+)`", re.IGNORECASE),
    re.compile(r"//\s*file:\s*(\S+)"),
    re.compile(r"#\s*file:\s*(\S+)"),
    re.compile(r"<!--\s*file:\s*(\S+)\s*-->"),
]


def _find_filepath_before(content: str, end_pos: int) -> Optional[str]:
    prefix = content[:end_pos]
    lines = prefix.splitlines()
    for line in reversed(lines):
        for pattern in FILEPATH_FINDERS:
            match = pattern.search(line)
            if match:
                return match.group(1).strip("`").strip()
    return None


def _extract_code_fences(content: str) -> List[Tuple[int, int, Optional[str], str]]:
    pattern = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)
    results: List[Tuple[int, int, Optional[str], str]] = []
    for match in pattern.finditer(content):
        pos = match.start()
        end = match.end()
        language = match.group(1) if match.group(1) else None
        code = match.group(2)
        results.append((pos, end, language, code))
    return results


def _resolve_path(project_root: Path, filepath: str) -> Path:
    path = Path(filepath)
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)


class CodeApplier:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.changes: List[AppliedChange] = []

    def _parse_json_output(self, content: str) -> Optional[List[Dict]]:
        """尝试解析 JSON 结构化输出协议。

        支持两种格式:
        1. 纯 JSON: {"files": [...]}
        2. Markdown 中的 JSON 代码块: ```json\n{"files": [...]}\n```
        """
        # 尝试直接解析
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "files" in data:
                return data["files"]
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown JSON 代码块中提取
        pattern = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)
        match = pattern.search(content)
        if match:
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict) and "files" in data:
                    return data["files"]
            except json.JSONDecodeError:
                pass

        return None

    def _apply_json_files(self, files: List[Dict]) -> List[AppliedChange]:
        """应用 JSON 结构化文件列表。"""
        changes = []
        for file_info in files:
            filepath = file_info.get("path")
            action = file_info.get("action", "create")
            file_content = file_info.get("content")

            if not filepath or file_content is None:
                logger.warning("JSON 文件条目缺少 path 或 content，已跳过: %s", file_info)
                continue

            resolved = _resolve_path(self.project_root, filepath)
            resolved_str = str(resolved)
            root_str = str(self.project_root)

            if not resolved_str.startswith(root_str + "/") and resolved_str != root_str:
                logger.warning("文件路径不在项目范围内(已跳过): %s", filepath)
                continue

            # 规范化 action
            if action in ("create", "add"):
                action = "created"
            elif action in ("modify", "update", "edit"):
                action = "modified"

            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(file_content.strip() + "\n", encoding="utf-8")
            rel = _safe_relative(resolved, self.project_root)
            logger.info("代码写入(JSON): %s [%s]", rel, action)
            changes.append(AppliedChange(rel, action, file_content.count("\n") + 1))

        return changes

    def apply(self, content: str) -> List[AppliedChange]:
        self.changes = []

        # 优先尝试 JSON 解析
        json_files = self._parse_json_output(content)
        if json_files:
            logger.info("检测到 JSON 结构化输出，解析到 %d 个文件", len(json_files))
            self.changes = self._apply_json_files(json_files)
            if self.changes:
                return self.changes
            logger.warning("JSON 解析成功但无有效文件，回退到 markdown 解析")

        # 回退到 markdown 代码块解析
        fences = _extract_code_fences(content)
        applied_paths = set()

        for pos, _end, _language, code in fences:
            filepath = _find_filepath_before(content, pos)
            if not filepath:
                continue
            resolved = _resolve_path(self.project_root, filepath)
            resolved_str = str(resolved)
            root_str = str(self.project_root)

            if not resolved_str.startswith(root_str + "/") and resolved_str != root_str:
                logger.warning("文件路径不在项目范围内(已跳过): %s", filepath)
                continue

            if resolved_str in applied_paths:
                continue
            applied_paths.add(resolved_str)

            action = "modified" if resolved.exists() else "created"
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(code.strip() + "\n", encoding="utf-8")
            rel = _safe_relative(resolved, self.project_root)
            logger.info("代码写入: %s [%s]", rel, action)
            self.changes.append(AppliedChange(rel, action, code.count("\n") + 1))

        return self.changes


def apply_code_from_output(output_text: str, project_root: Path) -> List[AppliedChange]:
    applier = CodeApplier(project_root)
    return applier.apply(output_text)


def extract_diff(content: str) -> Optional[str]:
    match = re.search(r"```diff\n(.*?)```", content, re.DOTALL)
    if match:
        return match.group(1)
    return None


def apply_patch_from_output(output_text: str, project_root: Path) -> None:
    diff = extract_diff(output_text)
    if not diff:
        return
    patch_file = project_root / ".ai" / "temp-patch.diff"
    patch_file.parent.mkdir(parents=True, exist_ok=True)
    patch_file.write_text(diff, encoding="utf-8")
    try:
        check = subprocess.run(
            ["git", "apply", "--check", str(patch_file)],
            cwd=project_root, capture_output=True, text=True, check=False,
        )
        if check.returncode != 0:
            logger.warning("git apply --check 失败: %s", check.stderr)
            return
        subprocess.run(["git", "apply", str(patch_file)], cwd=project_root, check=True)
        logger.info("应用 diff patch 成功")
    finally:
        if patch_file.exists():
            patch_file.unlink(missing_ok=True)
