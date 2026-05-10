from __future__ import annotations

import fnmatch
import json
import re
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .harness import HarnessCheckRef, HarnessError, compute_harness_manifest, load_harness_bundle, resolve_harness_path
from .models import QualityGateRun, utc_now
from .quality_gates import QualityGateExecutionPolicy, run_quality_gates
from .stage_context import _run_git


DEFAULT_COMMAND_ENV_ALLOWLIST = ["PATH", "HOME", "VIRTUAL_ENV", "PYTHONPATH"]
DEFAULT_OUTPUT_LIMIT = 20_000


class HarnessCheckError(HarnessError):
    pass


def _duration_ms(start: float) -> int:
    return int(round((time.monotonic() - start) * 1000))


def _severity(check: HarnessCheckRef) -> str:
    return check.severity or "error"


def _blocking(check: HarnessCheckRef) -> bool:
    if _severity(check) != "error":
        return False
    return True if check.blocking is None else bool(check.blocking)


def _result_status(has_failure: bool, severity: str, blocking: bool) -> str:
    if not has_failure:
        return "pass"
    if severity == "error" and blocking:
        return "fail"
    return "warning"


def _check_result(
    check: HarnessCheckRef,
    *,
    status: str,
    duration_ms: int,
    exit_code: Optional[int] = None,
    matched_files: Optional[List[str]] = None,
    output_excerpt: str = "",
    evidence_refs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    severity = _severity(check)
    return {
        "id": check.id,
        "type": check.type or "unknown",
        "status": status,
        "severity": severity,
        "blocking": status == "fail" and severity == "error" and _blocking(check),
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "matched_files": matched_files or [],
        "output_excerpt": output_excerpt,
        "evidence_refs": evidence_refs or [],
    }


def _safe_relative_path(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise HarnessCheckError(f"path escapes project root: {path}") from exc


def _iter_pattern_files(root: Path, check: HarnessCheckRef) -> Iterable[Path]:
    globs = check.globs or ["**/*"]
    excludes = check.exclude or []
    seen: set[Path] = set()
    for pattern in globs:
        pure = PurePosixPath(pattern)
        if pure.is_absolute() or any(part == ".." for part in pure.parts):
            raise HarnessCheckError(f"unsafe pattern glob: {pattern}")
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            rel = _safe_relative_path(root, path)
            if any(fnmatch.fnmatch(rel, item) for item in excludes):
                continue
            if ".git/" in rel or rel.startswith(".git/"):
                continue
            resolved = path.resolve(strict=False)
            if resolved in seen:
                continue
            seen.add(resolved)
            yield path


def _run_pattern_check(project_root: Path, check: HarnessCheckRef) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    start = time.monotonic()
    pattern = re.compile(check.pattern or "")
    matches: List[Dict[str, Any]] = []
    matched_files: List[str] = []
    for path in _iter_pattern_files(project_root, check):
        rel = _safe_relative_path(project_root, path)
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for line_no, line in enumerate(lines, start=1):
            if pattern.search(line):
                evidence_ref = f"{rel}:{line_no}"
                matches.append(
                    {
                        "rule_id": check.id,
                        "check_id": check.id,
                        "file": rel,
                        "line": line_no,
                        "severity": _severity(check),
                        "evidence_ref": evidence_ref,
                        "excerpt": line[:300],
                    }
                )
                if rel not in matched_files:
                    matched_files.append(rel)
    status = _result_status(bool(matches), _severity(check), _blocking(check))
    result = _check_result(
        check,
        status=status,
        duration_ms=_duration_ms(start),
        matched_files=matched_files,
        output_excerpt=f"{len(matches)} pattern match(es)",
        evidence_refs=[item["evidence_ref"] for item in matches],
    )
    return result, matches


def _safe_command_cwd(project_root: Path, stage_cwd: Path, check: HarnessCheckRef) -> Path:
    base = stage_cwd.resolve(strict=False)
    if check.cwd:
        pure = PurePosixPath(check.cwd)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise HarnessCheckError(f"unsafe command cwd for check {check.id}: {check.cwd}")
        base = (base / Path(pure.as_posix())).resolve(strict=False)
    roots = [project_root.resolve(strict=False), stage_cwd.resolve(strict=False)]
    if not any(_path_within(base, root) for root in roots):
        raise HarnessCheckError(f"command cwd for check {check.id} escapes project/worktree root")
    return base


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _harness_command_config_dirty(project_root: Path) -> bool:
    inside_work_tree = _run_git(project_root, ["rev-parse", "--is-inside-work-tree"]).strip()
    if inside_work_tree != "true":
        return True
    head = _run_git(project_root, ["rev-parse", "--verify", "HEAD"]).strip()
    if not head:
        return True
    status = _run_git(project_root, ["status", "--porcelain", "--", ".ai/harness.yaml", ".ai/harness"])
    return bool(status.strip())


def _quality_gate_to_check_result(check: HarnessCheckRef, gate: QualityGateRun) -> Dict[str, Any]:
    status = "pass"
    if gate.status == "failed":
        status = "fail" if _blocking(check) else "warning"
    elif gate.status == "warning":
        status = "warning"
    elif gate.status == "skipped":
        status = "skipped"
    evidence_refs = [f"quality_gate:{gate.name}"]
    if gate.output_truncated:
        evidence_refs.append(f"quality_gate:{gate.name}:output_truncated")
    return _check_result(
        check,
        status=status,
        duration_ms=int(round((gate.duration_seconds or 0) * 1000)),
        exit_code=gate.exit_code,
        matched_files=[],
        output_excerpt=gate.output or "",
        evidence_refs=evidence_refs,
    )


def _run_command_checks(
    project_root: Path,
    stage_cwd: Path,
    run_id: str,
    command_checks: Sequence[HarnessCheckRef],
    *,
    production: bool = False,
) -> List[Dict[str, Any]]:
    if production and command_checks and _harness_command_config_dirty(project_root):
        raise HarnessCheckError("production command checks require clean committed Harness command config")

    results: List[Dict[str, Any]] = []
    for check in command_checks:
        command_cwd = _safe_command_cwd(project_root, stage_cwd, check)
        gate = {
            "name": check.id,
            "type": "command",
            "command": check.command,
            "required": _blocking(check),
            "timeout_seconds": check.timeout_seconds,
        }
        policy = QualityGateExecutionPolicy(
            allowed_cwd_roots=[project_root, stage_cwd],
            require_timeout=True,
            output_limit=DEFAULT_OUTPUT_LIMIT,
            env_allowlist=check.env_allowlist or DEFAULT_COMMAND_ENV_ALLOWLIST,
        )
        gate_results = run_quality_gates([gate], command_cwd, run_id, execution_policy=policy)
        results.extend(_quality_gate_to_check_result(check, gate_result) for gate_result in gate_results)
    return results


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HarnessCheckError(f"invalid baseline json {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HarnessCheckError(f"baseline json must be an object: {path}")
    return data


def _committed_file(project_root: Path, rel_path: str) -> str:
    return _run_git(project_root, ["show", f"HEAD:{rel_path}"])


def _run_baseline_check(project_root: Path, check: HarnessCheckRef) -> tuple[Dict[str, Any], Dict[str, Any]]:
    start = time.monotonic()
    rel = check.baseline_file or ""
    path = resolve_harness_path(project_root, rel)
    current = _load_json(path)
    mode = current.get("mode") or "raise_only"
    metrics = current.get("metrics") or {}
    if mode != "raise_only":
        raise HarnessCheckError(f"unsupported baseline mode for {check.id}: {mode}")
    committed = _committed_file(project_root, rel)
    if not committed.strip():
        evidence = {
            "check_id": check.id,
            "baseline_file": rel,
            "status": "warning",
            "reason": "committed baseline not found",
            "mode": mode,
            "changes": [],
        }
        return (
            _check_result(
                check,
                status="warning",
                duration_ms=_duration_ms(start),
                matched_files=[rel],
                output_excerpt="committed baseline not found; no auto update performed",
                evidence_refs=[rel],
            ),
            evidence,
        )
    try:
        previous = json.loads(committed)
    except Exception as exc:
        raise HarnessCheckError(f"invalid committed baseline json {rel}: {exc}") from exc
    previous_metrics = previous.get("metrics") or {}
    lowered: List[Dict[str, Any]] = []
    raised: List[Dict[str, Any]] = []
    equal: List[Dict[str, Any]] = []
    for key, value in metrics.items():
        old = previous_metrics.get(key)
        if not isinstance(value, (int, float)) or not isinstance(old, (int, float)):
            continue
        change = {"metric": key, "previous": old, "current": value}
        if value < old:
            lowered.append(change)
        elif value > old:
            raised.append(change)
        else:
            equal.append(change)
    status = _result_status(bool(lowered), _severity(check), _blocking(check))
    changes = lowered + raised + equal
    evidence = {
        "check_id": check.id,
        "baseline_file": rel,
        "status": status,
        "mode": mode,
        "changes": changes,
    }
    result = _check_result(
        check,
        status=status,
        duration_ms=_duration_ms(start),
        matched_files=[rel],
        output_excerpt="baseline lowered" if lowered else "baseline equal or raised",
        evidence_refs=[f"{rel}:{item['metric']}" for item in changes],
    )
    return result, evidence


def _summary(checks: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "total": len(checks),
        "passed": sum(1 for item in checks if item["status"] == "pass"),
        "warnings": sum(1 for item in checks if item["status"] == "warning"),
        "failed": sum(1 for item in checks if item["status"] == "fail"),
        "skipped": sum(1 for item in checks if item["status"] == "skipped"),
    }


def _report_status(checks: Sequence[Dict[str, Any]]) -> tuple[str, bool]:
    blocking = any(item.get("blocking") and item.get("status") == "fail" for item in checks)
    if blocking:
        return "fail", True
    if any(item.get("status") == "warning" for item in checks):
        return "warning", False
    return "pass", False


def run_harness_verification(
    project_root: Path,
    *,
    run_id: str,
    stage_id: str = "harness_verify",
    project_id: Optional[str] = None,
    artifact_dir: Optional[Path] = None,
    cwd: Optional[Path] = None,
    production: bool = False,
) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    stage_cwd = Path(cwd or root).resolve(strict=False)
    source_root = stage_cwd if (stage_cwd / ".ai").exists() else root
    bundle = load_harness_bundle(source_root)
    checks = bundle.config.checks

    check_results: List[Dict[str, Any]] = []
    baseline_results: List[Dict[str, Any]] = []
    rule_violations: List[Dict[str, Any]] = []
    warnings = list(bundle.warnings)

    for check in checks:
        if check.type == "pattern":
            result, violations = _run_pattern_check(stage_cwd, check)
            check_results.append(result)
            rule_violations.extend(violations)

    command_checks = [check for check in checks if check.type == "command"]
    check_results.extend(_run_command_checks(source_root, stage_cwd, run_id, command_checks, production=production))

    for check in checks:
        if check.type == "baseline":
            result, evidence = _run_baseline_check(source_root, check)
            check_results.append(result)
            baseline_results.append(evidence)

    status, blocking = _report_status(check_results)
    report = {
        "schema_version": "1.0",
        "run_id": run_id,
        "project_id": project_id or "",
        "stage_id": stage_id,
        "harness_config_hash": compute_harness_manifest(source_root)["manifest_hash"],
        "generated_at": utc_now(),
        "status": status,
        "blocking": blocking,
        "summary": _summary(check_results),
        "checks": check_results,
        "baseline_results": baseline_results,
        "rule_violations": rule_violations,
        "warnings": warnings,
        "evidence": [ref for item in check_results for ref in item.get("evidence_refs", [])],
        "next_stage_contract": {
            "blocked": blocking,
            "feedback_file": "harness-feedback.md" if blocking else "",
        },
    }
    if artifact_dir:
        path = Path(artifact_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / "harness-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def render_harness_feedback(report: Dict[str, Any]) -> str:
    lines = ["## Harness Checks Blocking Feedback", ""]
    for check in report.get("checks", []):
        if check.get("status") != "fail" or not check.get("blocking"):
            continue
        lines.extend(
            [
                f"### {check.get('id')}",
                f"- Type: `{check.get('type')}`",
                f"- Severity: `{check.get('severity')}`",
                f"- Exit code: `{check.get('exit_code')}`",
                f"- Evidence: {', '.join(check.get('evidence_refs') or []) or 'none'}",
                "",
                "```text",
                check.get("output_excerpt") or "",
                "```",
                "",
            ]
        )
    lines.append("Fix only the blocking Harness check failures above, then rerun verification.")
    return "\n".join(lines)
