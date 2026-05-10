from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from .harness import render_harness_summary_markdown, summarize_harness
from .task_board import related_tasks_for_context, render_related_tasks_markdown


WELL_KNOWN_FILES = {
    "Package.swift": "swift-spm",
    "Podfile": "swift-cocoapods",
    "package.json": "node",
    "pnpm-lock.yaml": "node-pnpm",
    "yarn.lock": "node-yarn",
    "requirements.txt": "python",
    "pyproject.toml": "python",
    "setup.py": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "build.gradle": "android-gradle",
    "build.gradle.kts": "android-gradle",
    "pom.xml": "java-maven",
    "Gemfile": "ruby",
    "composer.json": "php",
    "CMakeLists.txt": "cpp-cmake",
    "Makefile": "make",
}

LINT_CONFIGS = [
    ".editorconfig",
    ".swiftlint.yml",
    ".swiftlint.yaml",
    ".eslintrc",
    ".eslintrc.json",
    ".eslintrc.js",
    ".eslintrc.yml",
    ".prettierrc",
    ".prettierrc.json",
    ".prettierrc.js",
    "biome.json",
    "ruff.toml",
    ".flake8",
    ".rubocop.yml",
    "clippy.toml",
]

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".ai",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".tox",
    "dist",
    "build",
    ".build",
    ".next",
    "target",
    "vendor",
    "Pods",
    ".gradle",
    ".idea",
    ".vscode",
    "DerivedData",
    "coverage",
}

DEFAULT_INCLUDE_PATTERNS = [
    "**/*.swift",
    "**/*.ts",
    "**/*.tsx",
    "**/*.js",
    "**/*.jsx",
    "**/*.py",
    "**/*.go",
    "**/*.rs",
    "**/*.java",
    "**/Package.swift",
    "**/package.json",
    "**/pyproject.toml",
    "**/*.md",
]

SENSITIVE_PATTERNS = [
    "*.env",
    ".env.*",
    "*.env.local",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.jwt",
    "*.secret",
    "id_rsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*credentials*",
    "*secrets*",
    ".aws/credentials",
    ".kube/config",
    ".ssh/*",
    ".gnupg/*",
    "firebase-service-account*.json",
    "google-credentials*.json",
    "service-account*.json",
]

SENSITIVE_DIRS = {".ssh", ".aws", ".kube", ".gnupg", ".env"}
INSTRUCTION_FILES = ["AGENTS.md", "CLAUDE.md"]
ENTRY_CANDIDATES = [
    "App.swift",
    "main.swift",
    "src/main.ts",
    "src/main.tsx",
    "src/App.tsx",
    "src/App.ts",
    "app/page.tsx",
    "pages/index.tsx",
    "main.py",
    "app.py",
    "server.py",
    "cmd/main.go",
]


def is_sensitive_path(rel_path: str) -> bool:
    rel = rel_path.replace(os.sep, "/")
    name = Path(rel).name
    parts = Path(rel).parts
    if any(part in SENSITIVE_DIRS for part in parts):
        return True
    for pattern in SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern):
            return True
    return False


def _is_excluded(path: Path, root: Path, exclude_dirs: Set[str]) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in exclude_dirs for part in rel.parts)


def _safe_read(path: Path, max_chars: int) -> Optional[str]:
    try:
        if path.stat().st_size > max_chars * 4:
            return path.read_text(encoding="utf-8", errors="replace")[:max_chars] + "\n\n[truncated]"
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception:
        return None


def _run_git(project_root: Path, args: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def detect_project_types(project_root: Path) -> List[str]:
    types = []
    for filename, project_type in WELL_KNOWN_FILES.items():
        if (project_root / filename).exists():
            types.append(project_type)
    return sorted(set(types))


def parse_implementation_checklist(solution_draft: str) -> List[str]:
    files: List[str] = []
    in_checklist = False
    section_patterns = [r"#+\s*实施清单", r"#+\s*Implementation\s+Checklist"]
    file_patterns = [
        r"[-*]\s+`([^`]+\.[^`]+)`",
        r"[-*]\s+([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)",
    ]
    for line in solution_draft.splitlines():
        stripped = line.strip()
        if any(re.search(pattern, stripped, re.IGNORECASE) for pattern in section_patterns):
            in_checklist = True
            continue
        if in_checklist and re.match(r"^#{1,3}\s+", stripped) and files:
            break
        if not in_checklist:
            continue
        for pattern in file_patterns:
            match = re.search(pattern, stripped)
            if match:
                filepath = match.group(1).strip().strip("`")
                if not is_sensitive_path(filepath) and filepath not in files:
                    files.append(filepath)
    return files


class ContextScanner:
    def __init__(self, project_root: Path, config: Optional[Dict] = None) -> None:
        self.project_root = project_root.resolve()
        self.config = config or {}
        self.exclude_dirs = set(self.config.get("exclude_dirs") or DEFAULT_EXCLUDE_DIRS)
        self.include_patterns = list(self.config.get("include_patterns") or DEFAULT_INCLUDE_PATTERNS)
        self.key_files = list(self.config.get("key_files") or INSTRUCTION_FILES + LINT_CONFIGS)
        self.max_file_size = int(self.config.get("max_file_size") or 50_000)
        self.max_context_files = int(self.config.get("max_context_files") or 40)
        self.max_tree_lines = int(self.config.get("max_tree_lines") or 240)

    def generate_tree(self, max_depth: int = 4) -> str:
        lines: List[str] = [f"{self.project_root.name}/"]
        count = 0

        def walk(dir_path: Path, prefix: str, depth: int) -> None:
            nonlocal count
            if depth > max_depth or count >= self.max_tree_lines:
                return
            try:
                entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except Exception:
                return
            visible = [
                entry
                for entry in entries
                if not _is_excluded(entry, self.project_root, self.exclude_dirs)
                and not is_sensitive_path(str(entry.relative_to(self.project_root)))
            ]
            for index, entry in enumerate(visible):
                if count >= self.max_tree_lines:
                    lines.append(f"{prefix}... (truncated)")
                    return
                connector = "└── " if index == len(visible) - 1 else "├── "
                rel = entry.relative_to(self.project_root)
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{prefix}{connector}{entry.name}{suffix}")
                count += 1
                if entry.is_dir():
                    extension = "    " if index == len(visible) - 1 else "│   "
                    walk(entry, prefix + extension, depth + 1)

        walk(self.project_root, "", 1)
        return "\n".join(lines)

    def dependency_files(self) -> Dict[str, str]:
        files = {}
        for filename in WELL_KNOWN_FILES:
            path = self.project_root / filename
            if path.exists() and path.is_file() and not is_sensitive_path(filename):
                content = _safe_read(path, min(self.max_file_size, 20_000))
                if content is not None:
                    files[filename] = content
        return files

    def lint_configs(self) -> Dict[str, str]:
        files = {}
        for filename in LINT_CONFIGS:
            path = self.project_root / filename
            if path.exists() and path.is_file() and not is_sensitive_path(filename):
                content = _safe_read(path, min(self.max_file_size, 10_000))
                if content is not None:
                    files[filename] = content
        return files

    def instruction_files(self) -> Dict[str, str]:
        files = {}
        for filename in INSTRUCTION_FILES:
            path = self.project_root / filename
            if path.exists() and path.is_file():
                content = _safe_read(path, self.max_file_size)
                if content is not None:
                    files[filename] = content
        return files

    def _matches_include(self, rel: str) -> bool:
        return any(fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(Path(rel).name, pattern) for pattern in self.include_patterns)

    def _walk_candidate_files(self) -> Iterable[Path]:
        for path in self.project_root.rglob("*"):
            if not path.is_file():
                continue
            if _is_excluded(path, self.project_root, self.exclude_dirs):
                continue
            rel = str(path.relative_to(self.project_root)).replace(os.sep, "/")
            if is_sensitive_path(rel):
                continue
            if self._matches_include(rel):
                yield path

    def select_relevant_files(self, checklist_files: Sequence[str]) -> List[Path]:
        selected: List[Path] = []
        seen: Set[Path] = set()

        def add(path: Path) -> None:
            if not path.is_absolute():
                path = self.project_root / path
            try:
                path = path.resolve()
                rel = str(path.relative_to(self.project_root)).replace(os.sep, "/")
            except Exception:
                return
            if not path.exists() or not path.is_file() or is_sensitive_path(rel):
                return
            if _is_excluded(path, self.project_root, self.exclude_dirs):
                return
            if path not in seen:
                selected.append(path)
                seen.add(path)

        for rel in checklist_files:
            add(Path(rel))
        for rel in self.key_files:
            add(Path(rel))
        for rel in ENTRY_CANDIDATES:
            add(Path(rel))

        if len(selected) < self.max_context_files:
            for path in self._walk_candidate_files():
                add(path)
                if len(selected) >= self.max_context_files:
                    break
        return selected[: self.max_context_files]

    def scan(self, solution_draft: str = "", requirement_text: str = "") -> str:
        project_types = detect_project_types(self.project_root)
        checklist_files = parse_implementation_checklist(solution_draft)
        selected_files = self.select_relevant_files(checklist_files)
        git_log = _run_git(self.project_root, ["log", "--oneline", "-20"])
        git_status = _run_git(self.project_root, ["status", "--short"])

        sections = [
            "# Codebase Context",
            "",
            f"- Project root: `{self.project_root}`",
            f"- Detected project types: {', '.join(project_types) if project_types else 'unknown'}",
            f"- Selected context files: {len(selected_files)}",
            "",
            "## Project Tree",
            "```text",
            self.generate_tree(),
            "```",
        ]

        if git_log:
            sections.extend(["", "## Recent Git Log", "```text", git_log, "```"])
        if git_status:
            sections.extend(["", "## Working Tree Status", "```text", git_status, "```"])
        if checklist_files:
            sections.extend(["", "## Implementation Checklist Files", *[f"- `{item}`" for item in checklist_files]])

        harness_markdown = render_harness_summary_markdown(summarize_harness(self.project_root))
        if harness_markdown:
            sections.extend(["", harness_markdown.rstrip()])
        related_tasks = related_tasks_for_context(self.project_root, requirement_text)
        related_markdown = render_related_tasks_markdown(related_tasks)
        if related_markdown:
            sections.extend(["", related_markdown.rstrip()])

        for title, file_map in (
            ("Project Instructions", self.instruction_files()),
            ("Dependencies", self.dependency_files()),
            ("Lint And Format Config", self.lint_configs()),
        ):
            if not file_map:
                continue
            sections.extend(["", f"## {title}"])
            for rel, content in file_map.items():
                sections.extend(["", f"### `{rel}`", "```", content, "```"])

        if selected_files:
            sections.extend(["", "## Relevant Files"])
            for path in selected_files:
                rel = str(path.relative_to(self.project_root)).replace(os.sep, "/")
                content = _safe_read(path, self.max_file_size)
                if content is None:
                    continue
                language = _language_for_path(path)
                sections.extend(["", f"### `{rel}`", f"```{language}", content, "```"])

        return "\n".join(sections).rstrip() + "\n"


def _language_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "jsx",
        ".swift": "swift",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".md": "markdown",
    }.get(suffix, "")


def scan_codebase(
    project_root: Path,
    solution_draft_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    config: Optional[Dict] = None,
    requirement_text: str = "",
) -> str:
    solution_draft = ""
    if solution_draft_path and Path(solution_draft_path).exists():
        solution_draft = Path(solution_draft_path).read_text(encoding="utf-8", errors="replace")
    text = ContextScanner(Path(project_root), config=config).scan(solution_draft, requirement_text=requirement_text)
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(text, encoding="utf-8")
    return text


def scan_to_json(project_root: Path, config: Optional[Dict] = None, requirement_text: str = "") -> str:
    scanner = ContextScanner(project_root, config=config)
    harness_summary = summarize_harness(project_root)
    harness_summary["related_tasks"] = related_tasks_for_context(project_root, requirement_text)
    payload = {
        "project_root": str(project_root),
        "project_types": detect_project_types(project_root),
        "tree": scanner.generate_tree(),
        "harness": harness_summary,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
