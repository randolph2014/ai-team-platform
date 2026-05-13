#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from fnmatch import fnmatch
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
DEFAULT_DEPRECATED_REGISTRY = Path(".ai/harness/checks/deprecated-usage-registry.json")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


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


def _path_matches_any(rel: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        candidates = [pattern]
        if pattern.startswith("**/"):
            candidates.append(pattern[3:])
        if "/**/" in pattern:
            candidates.append(pattern.replace("/**/", "/"))
        if any(fnmatch(rel, candidate) for candidate in candidates):
            return True
        if any(Path(rel).match(candidate) for candidate in candidates):
            return True
    return False


def _resolve_registry_path(root: Path, registry_path: Optional[Path] = None) -> Path:
    path = registry_path or DEFAULT_DEPRECATED_REGISTRY
    if path.is_absolute():
        return path
    return root / path


def check_deprecated_usage_registry(root: Path, registry_path: Optional[Path] = None) -> List[Finding]:
    registry = _resolve_registry_path(root, registry_path)
    rel_registry = registry.relative_to(root).as_posix() if registry.is_relative_to(root) else registry.as_posix()
    if not registry.is_file():
        return [Finding("deprecated-usage", "deprecated usage registry is missing", Path(rel_registry))]
    try:
        payload = json.loads(_read(registry))
    except Exception as exc:
        return [Finding("deprecated-usage", f"deprecated usage registry is invalid json: {exc}", Path(rel_registry))]
    if not isinstance(payload, dict) or not isinstance(payload.get("patterns"), list):
        return [Finding("deprecated-usage", "deprecated usage registry must contain a patterns array", Path(rel_registry))]

    findings: List[Finding] = []
    compiled = []
    for index, item in enumerate(payload["patterns"]):
        if not isinstance(item, dict):
            findings.append(Finding("deprecated-usage", f"registry pattern #{index + 1} must be an object", Path(rel_registry)))
            continue
        pattern_id = str(item.get("id") or f"pattern-{index + 1}")
        regex = str(item.get("regex") or "")
        message = str(item.get("message") or "deprecated usage detected")
        if not regex:
            findings.append(Finding("deprecated-usage", f"{pattern_id} regex is required", Path(rel_registry)))
            continue
        try:
            compiled.append((
                pattern_id,
                re.compile(regex),
                message,
                [str(glob) for glob in item.get("globs", ["**/*"])],
                {str(path) for path in item.get("allowed_paths", [])} | {rel_registry},
            ))
        except re.error as exc:
            findings.append(Finding("deprecated-usage", f"{pattern_id} regex is invalid: {exc}", Path(rel_registry)))

    for path in _text_files(root):
        rel = path.relative_to(root).as_posix()
        text = _read(path)
        for pattern_id, regex, message, globs, allowed_paths in compiled:
            if not _path_matches_any(rel, globs):
                continue
            if rel in allowed_paths or _path_matches_any(rel, list(allowed_paths)):
                continue
            if regex.search(text):
                findings.append(Finding(f"deprecated-usage:{pattern_id}", message, path.relative_to(root)))
                break
    return findings


def check_traceability_contracts(root: Path) -> List[Finding]:
    findings: List[Finding] = []
    schema_expectations = {
        "engine/schemas/implementation-report.json": ["acceptance_coverage", "evidence", "traceability"],
        "engine/schemas/test-report.json": ["acceptance_coverage", "evidence", "traceability"],
        "engine/schemas/review-report.json": ["review_dimensions", "evidence", "risks", "traceability"],
    }
    for rel, required_fields in schema_expectations.items():
        path = root / rel
        if not path.is_file():
            findings.append(Finding("traceability-contract", "required schema is missing", Path(rel)))
            continue
        try:
            schema = json.loads(_read(path))
        except Exception as exc:
            findings.append(Finding("traceability-contract", f"schema json is invalid: {exc}", Path(rel)))
            continue
        required = set(schema.get("required") or [])
        for field in required_fields:
            if field not in required:
                findings.append(Finding("traceability-contract", f"schema must require {field}", Path(rel)))
        traceability = schema.get("properties", {}).get("traceability", {})
        if traceability.get("minItems", 0) < 1:
            findings.append(Finding("traceability-contract", "traceability must require at least one row", Path(rel)))
        item_props = traceability.get("items", {}).get("properties", {})
        for field in ("evidence_refs", "files", "tests"):
            if item_props.get(field, {}).get("minItems", 0) < 1:
                findings.append(Finding("traceability-contract", f"traceability.{field} must require at least one item", Path(rel)))

    requirement_schema = root / "engine/schemas/requirement-final.json"
    if requirement_schema.is_file():
        schema = json.loads(_read(requirement_schema))
        if schema.get("title") != "Task Contract":
            findings.append(Finding("task-contract", "requirement-final.json schema title must be Task Contract", Path("engine/schemas/requirement-final.json")))
    return findings


def _local_markdown_target(source: Path, target: str) -> Optional[Path]:
    raw = target.strip().split("#", 1)[0].split("?", 1)[0]
    if not raw or raw.startswith("#"):
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw):
        return None
    return (source.parent / raw).resolve(strict=False)


def check_markdown_file_links(root: Path, files: Optional[list[str]] = None) -> List[Finding]:
    findings: List[Finding] = []
    for rel in files or ["README.md"]:
        source = root / rel
        if not source.is_file():
            continue
        for match in MARKDOWN_LINK_RE.finditer(_read(source)):
            target = _local_markdown_target(source, match.group(1))
            if target is None:
                continue
            if not target.exists():
                findings.append(Finding("markdown-link", f"missing local markdown link target: {match.group(1)}", Path(rel)))
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


def run_checks(root: Path, deprecated_registry: Optional[Path] = None) -> List[Finding]:
    return [
        *check_legacy_entry_patterns(root),
        *check_deprecated_usage_registry(root, deprecated_registry),
        *check_traceability_contracts(root),
        *check_markdown_file_links(root),
        *check_harness_source_of_truth(root),
        *check_harness_checks_runner_boundary(root),
        *check_project_id_api_boundary(root),
        *check_ui_edit_scope(root),
        *check_phase_reports(root),
    ]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify ai-team-platform project governance invariants.")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--deprecated-registry", default=None, help="Harness deprecated usage registry path")
    parser.add_argument("--json", action="store_true", help="emit JSON findings")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    registry_path = Path(args.deprecated_registry) if args.deprecated_registry else None
    findings = run_checks(root, deprecated_registry=registry_path)
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
