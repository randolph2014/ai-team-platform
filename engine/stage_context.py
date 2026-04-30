from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_MAX_DIFF_CHARS = 50_000


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _artifact_section(path: Path, max_chars: Optional[int] = None) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    if max_chars and len(content) > max_chars:
        content = content[:max_chars] + "\n\n[truncated]"
    suffix = path.suffix.lstrip(".")
    lang = "markdown" if suffix == "md" else suffix
    return f"## Artifact: `{path.name}`\n```{lang}\n{content}\n```\n"


def _run_git(cwd: Path, args: List[str]) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except Exception:
        return ""
    return result.stdout if result.returncode == 0 else ""


def _merge_base(cwd: Path, base_branch: Optional[str] = None) -> str:
    refs = []
    if base_branch:
        refs.append(base_branch)
    refs.extend(["main", "origin/main", "master", "origin/master"])
    seen = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        base = _run_git(cwd, ["merge-base", "HEAD", ref]).strip()
        if base:
            return base
    return ""


def _git_diff(cwd: Path, base_branch: Optional[str] = None) -> str:
    parts: List[str] = []
    base = _merge_base(cwd, base_branch=base_branch)
    if base:
        committed = _run_git(cwd, ["diff", f"{base}...HEAD", "--"])
        if committed.strip():
            parts.append(f"# committed diff\n{committed.rstrip()}")
    staged = _run_git(cwd, ["diff", "--cached", "--"])
    if staged.strip():
        parts.append(f"# staged diff\n{staged.rstrip()}")
    unstaged = _run_git(cwd, ["diff", "--"])
    if unstaged.strip():
        parts.append(f"# unstaged diff\n{unstaged.rstrip()}")
    return "\n\n".join(parts)


def _truncate_git_diff(diff: str, max_diff_chars: Optional[int]) -> str:
    limit = max_diff_chars if max_diff_chars is not None else DEFAULT_MAX_DIFF_CHARS
    if limit < 0 or len(diff) <= limit:
        return diff
    return f"{diff[:limit]}\n... [git-diff truncated, original chars: {len(diff)}, limit: {limit}]"


def build_stage_context(
    stage: Dict[str, Any],
    output_dir: Path,
    cwd: Path,
    input_items: Iterable[Any],
    extra_feedback: str = "",
    schema_hint: Optional[Dict[str, Any]] = None,
    max_chars: Optional[int] = None,
    base_branch: Optional[str] = None,
    max_diff_chars: Optional[int] = None,
) -> str:
    parts = [
        "## Stage Contract",
        f"- Stage: `{stage.get('id')}` / `{stage.get('name', stage.get('id'))}`",
        f"- Working directory: `{cwd}`",
    ]
    required = [str(item) for item in stage.get("required_artifacts") or []]
    if required:
        parts.append("- Required artifacts:")
        parts.extend([f"  - `{item}`" for item in required])
    parts.extend(
        [
            "- Human gate rule: hard gates require explicit human approval and reject reason.",
            "- Scope rule: only change files required by the confirmed requirement and task plan.",
            "",
        ]
    )
    if schema_hint:
        parts.extend(["## Output Schema", "```json", json.dumps(schema_hint, ensure_ascii=False, indent=2), "```", ""])
    if extra_feedback:
        parts.extend(["## Feedback", extra_feedback.rstrip(), ""])
    for item in _as_list(input_items):
        if item == "requirement":
            path = output_dir / "requirement.md"
            if path.exists():
                parts.extend(["## Requirement", path.read_text(encoding="utf-8", errors="replace"), ""])
        elif item == "git-diff":
            diff = _git_diff(cwd, base_branch=base_branch)
            if diff:
                diff = _truncate_git_diff(diff, max_diff_chars)
            parts.extend(["## git-diff", "```diff", diff or "(no diff)", "```", ""])
        elif isinstance(item, str) and "*" in item:
            for path in sorted(output_dir.glob(item)):
                parts.append(_artifact_section(path, max_chars=max_chars))
        elif isinstance(item, str):
            path = output_dir / item
            if path.exists():
                parts.append(_artifact_section(path, max_chars=max_chars))
    return "\n".join(parts).rstrip() + "\n"
