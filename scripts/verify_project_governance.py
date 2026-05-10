#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional


SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}
SKIP_PATH_PARTS = {
    ".ai/team-output",
    ".ai/worktrees",
    "web/node_modules",
}


class Finding:
    def __init__(self, check: str, message: str, path: Optional[Path] = None) -> None:
        self.check = check
        self.message = message
        self.path = path

    def to_dict(self) -> dict[str, str]:
        payload = {"check": self.check, "message": self.message}
        if self.path is not None:
            payload["path"] = self.path.as_posix()
        return payload

    def __str__(self) -> str:
        prefix = f"{self.check}: "
        location = f" [{self.path.as_posix()}]" if self.path is not None else ""
        return f"{prefix}{self.message}{location}"


def _text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if any(rel == part or rel.startswith(f"{part}/") for part in SKIP_PATH_PARTS):
            continue
        if not path.is_file():
            continue
        if path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".gz"}:
            continue
        yield path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _legacy_patterns() -> list[tuple[re.Pattern[str], str]]:
    legacy_entry = "/".join([".ai", "team.yaml"])
    legacy_project_root = "/".join(["project_root", ".ai"])
    return [
        (re.compile(re.escape(legacy_entry)), "legacy project team entry must not appear as a fact source"),
        (re.compile(re.escape(legacy_project_root)), "legacy project root config wording must not reappear"),
        (re.compile(re.escape("项目级配置" + "放在")), "legacy Chinese project config wording must not reappear"),
        (re.compile(re.escape("team.yaml" + "，会优先")), "legacy priority wording must not reappear"),
        (re.compile(re.escape("initialize project with " + "quality gates")), "legacy init wording must not reappear"),
        (re.compile(re.escape("explicit " + "team.yaml path")), "legacy explicit path wording must not reappear"),
        (re.compile(re.escape("已存在 " + "quality_gates 配置")), "legacy existing quality gates wording must not reappear"),
    ]


def check_legacy_entry_patterns(root: Path) -> List[Finding]:
    findings: List[Finding] = []
    patterns = _legacy_patterns()
    for path in _text_files(root):
        text = _read(path)
        for pattern, message in patterns:
            if pattern.search(text):
                findings.append(Finding("legacy-entry", message, path.relative_to(root)))
                break
    return findings


def check_harness_source_of_truth(root: Path) -> List[Finding]:
    findings: List[Finding] = []
    if not (root / ".ai" / "harness.yaml").is_file():
        findings.append(Finding("harness-source", "repository Harness config is missing"))
    if not (root / ".ai" / "harness").is_dir():
        findings.append(Finding("harness-source", "repository Harness asset directory is missing"))
    return findings


def check_harness_checks_runner_boundary(root: Path) -> List[Finding]:
    path = root / "engine" / "harness_checks.py"
    text = _read(path)
    findings: List[Finding] = []
    if "run_quality_gates" not in text:
        findings.append(Finding("runner-boundary", "Harness checks must call the shared quality gate runner", path.relative_to(root)))
    forbidden_terms = ["import subprocess", "os.system", "Popen", "shell=True"]
    for term in forbidden_terms:
        if term in text:
            findings.append(Finding("runner-boundary", f"Harness checks must not contain {term}", path.relative_to(root)))
    return findings


def check_project_id_api_boundary(root: Path) -> List[Finding]:
    path = root / "api" / "routes" / "harness.py"
    text = _read(path)
    findings: List[Finding] = []
    required_terms = [
        '@router.get("/projects/{project_id}/harness")',
        '@router.put("/projects/{project_id}/harness")',
        '@router.post("/projects/{project_id}/harness/validate")',
        '@router.post("/projects/{project_id}/harness/checks/run")',
        '@router.get("/projects/{project_id}/task-board")',
        '@router.post("/projects/{project_id}/task-board/events")',
        "_reject_workdir",
    ]
    for term in required_terms:
        if term not in text:
            findings.append(Finding("project-id-api", f"missing required project-scoped API guard: {term}", path.relative_to(root)))
    if 'event.state == "accepted"' not in text or "final pipeline acceptance" not in text:
        findings.append(Finding("task-board-accepted-guard", "public Task Board API must reject direct accepted writes", path.relative_to(root)))
    return findings


def check_ui_edit_scope(root: Path) -> List[Finding]:
    schema_path = root / "web" / "src" / "lib" / "harnessSchema.ts"
    api_path = root / "web" / "src" / "lib" / "api.ts"
    schema_text = _read(schema_path)
    api_text = _read(api_path)
    findings: List[Finding] = []
    if "path === HARNESS_CONFIG_PATH || path.startsWith(HARNESS_PREFIX)" not in schema_text:
        findings.append(Finding("ui-edit-scope", "UI editable paths must stay limited to Harness assets", schema_path.relative_to(root)))
    required_api_terms = [
        "/projects/${encodeURIComponent(projectId)}/harness",
        "/projects/${encodeURIComponent(projectId)}/harness/validate",
        "/projects/${encodeURIComponent(projectId)}/harness/checks/run",
        "/projects/${encodeURIComponent(projectId)}/task-board",
    ]
    for term in required_api_terms:
        if term not in api_text:
            findings.append(Finding("ui-project-id-api", f"missing projectId UI API call: {term}", api_path.relative_to(root)))
    return findings


def check_phase_reports(root: Path) -> List[Finding]:
    findings: List[Finding] = []
    required_reports = [
        "docs/superpowers/reports/2026-05-10-project-governance-phase-1-final-report.md",
        "docs/superpowers/reports/2026-05-10-project-governance-phase-2-final-report.md",
        "docs/superpowers/reports/2026-05-10-project-governance-phase-3-final-report.md",
        "docs/superpowers/reports/2026-05-10-project-governance-phase-4-final-report.md",
        "docs/superpowers/reports/2026-05-10-project-governance-finalization-report.md",
    ]
    verification_terms = ("Verification", "验证", "fresh verification", "Fresh Verification")
    for rel in required_reports:
        path = root / rel
        if not path.is_file():
            findings.append(Finding("phase-report", "required governance report is missing", Path(rel)))
            continue
        text = _read(path)
        if not any(term in text for term in verification_terms):
            findings.append(Finding("phase-report", "report must contain fresh verification evidence", Path(rel)))
    return findings


def run_checks(root: Path) -> List[Finding]:
    return [
        *check_legacy_entry_patterns(root),
        *check_harness_source_of_truth(root),
        *check_harness_checks_runner_boundary(root),
        *check_project_id_api_boundary(root),
        *check_ui_edit_scope(root),
        *check_phase_reports(root),
    ]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify ai-team-platform project governance invariants.")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--json", action="store_true", help="emit JSON findings")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    findings = run_checks(root)
    if args.json:
        print(json.dumps([item.to_dict() for item in findings], ensure_ascii=False, indent=2))
    elif findings:
        print("project governance checks failed")
        for finding in findings:
            print(f"- {finding}")
    else:
        print("project governance checks passed")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
