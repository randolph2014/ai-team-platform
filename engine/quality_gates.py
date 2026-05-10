from __future__ import annotations

import logging
import operator
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import yaml

from .events import EventBus
from .logging_config import log_gate_result
from .metrics import record_gate_result as record_gate_metric
from .models import QualityGateRun, utc_now

logger = logging.getLogger(__name__)

OPS = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
    "==": operator.eq,
}

_PIPE_ESCAPE_PATTERN = re.compile(r"\|\|\s*true")

_LANG_MARKERS = {
    "python": ["pyproject.toml", "setup.py", "setup.cfg"],
    "node": ["package.json"],
    "go": ["go.mod"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
}

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "quality-gates"


class QualityGateError(RuntimeError):
    pass


@dataclass
class QualityGateExecutionPolicy:
    """Opt-in hardening for command execution.

    Existing quality gate callers keep the historical behavior by omitting this
    policy. Harness command checks must pass it so cwd, timeout, output, and env
    controls are enforced in the shared runner instead of a parallel runner.
    """

    allowed_cwd_roots: List[Path] = field(default_factory=list)
    require_timeout: bool = False
    output_limit: int = 20_000
    env_allowlist: Optional[List[str]] = None


def validate_gates_config(gates: List[Dict], production: bool = False) -> None:
    if production and not gates:
        raise QualityGateError("quality_gates is empty; at least one gate is required in production")
    for gate in gates:
        required = bool(gate.get("required", True))
        command = gate.get("command", "")
        if required and command and _PIPE_ESCAPE_PATTERN.search(command):
            name = gate.get("name") or gate.get("command") or "unknown"
            raise QualityGateError(
                f"Required gate '{name}' contains '|| true' which would mask failures; "
                "remove '|| true' from the command"
            )


def _detect_language(project_root: Path) -> Optional[str]:
    for lang, markers in _LANG_MARKERS.items():
        for marker in markers:
            if (project_root / marker).exists():
                return lang
    return None


def inject_default_gates(project_root: Path, existing_gates: List[Dict]) -> List[Dict]:
    if existing_gates:
        return existing_gates
    lang = _detect_language(project_root)
    if not lang:
        return existing_gates
    template_path = _TEMPLATES_DIR / f"{lang}.yaml"
    if not template_path.exists():
        return existing_gates
    try:
        data = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
        defaults = data.get("quality_gates", [])
        if defaults:
            logger.info("Injected %d default quality gates for %s project", len(defaults), lang)
        return defaults
    except Exception:
        logger.warning("Failed to load default quality gates template for %s", lang)
        return existing_gates


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _policy_failure(policy: Optional[QualityGateExecutionPolicy], cwd: Path, timeout: Optional[int]) -> Optional[str]:
    if policy is None:
        return None
    if not cwd.is_dir():
        return f"Quality gate cwd '{cwd.resolve(strict=False)}' does not exist or is not a directory"
    if policy.allowed_cwd_roots and not any(_path_within(cwd, root) for root in policy.allowed_cwd_roots):
        roots = ", ".join(str(root.resolve(strict=False)) for root in policy.allowed_cwd_roots)
        return f"Quality gate cwd '{cwd.resolve(strict=False)}' is outside allowed roots: {roots}"
    if policy.require_timeout and not timeout:
        return "Quality gate timeout is required by execution policy"
    return None


def _policy_env(policy: Optional[QualityGateExecutionPolicy]) -> Optional[Dict[str, str]]:
    if policy is None or policy.env_allowlist is None:
        return None
    return {key: os.environ[key] for key in policy.env_allowlist if key in os.environ}


def _run_command(
    command: str,
    cwd: Path,
    timeout: Optional[int],
    policy: Optional[QualityGateExecutionPolicy] = None,
) -> Tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=_policy_env(policy),
        )
        output = "\n".join(part for part in [result.stdout, result.stderr] if part)
        return result.returncode, output
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(part for part in [exc.stdout or "", exc.stderr or ""] if part)
        return 124, output + f"\nCommand timed out after {timeout}s"


def _parse_threshold(gate: Dict, output: str) -> Optional[float]:
    parser = gate.get("parse")
    if not parser:
        return None
    if isinstance(parser, str) and parser.startswith("regex:"):
        pattern = parser[len("regex:") :]
        match = re.search(pattern, output)
        if not match:
            return None
        return float(match.group(1))
    return None


def run_quality_gate(
    gate: Dict,
    cwd: Path,
    run_id: str,
    bus: Optional[EventBus] = None,
    retry_count: int = 0,
    execution_policy: Optional[QualityGateExecutionPolicy] = None,
) -> QualityGateRun:
    name = gate.get("name") or gate.get("command") or "quality gate"
    gate_type = gate.get("type", "command")
    required = bool(gate.get("required", True))
    command = gate.get("command")
    timeout = gate.get("timeout_seconds") or gate.get("timeout")
    gate_cwd = Path(gate.get("cwd") or cwd).expanduser().resolve(strict=False)
    output_limit = execution_policy.output_limit if execution_policy else 20_000
    result = QualityGateRun(
        name=name,
        type=gate_type,
        command=command,
        required=required,
        retry_count=retry_count,
        status="running",
        started_at=utc_now(),
        cwd=str(gate_cwd),
    )
    start = time.monotonic()
    if bus:
        bus.emit("gate:started", run_id, gate_name=name, command=command, retry_count=retry_count)

    policy_error = _policy_failure(execution_policy, gate_cwd, timeout)
    if policy_error:
        result.status = "failed" if required else "warning"
        result.output = policy_error
    elif gate_type not in {"command", "threshold"}:
        result.status = "skipped"
        result.output = f"Unsupported gate type: {gate_type}"
    elif not command:
        result.status = "failed" if required else "warning"
        result.output = "Missing gate command"
    else:
        exit_code, output = _run_command(command, gate_cwd, timeout, execution_policy)
        result.exit_code = exit_code
        if output_limit >= 0 and len(output) > output_limit:
            result.output = output[-output_limit:]
            result.output_truncated = True
        else:
            result.output = output
        if gate_type == "threshold":
            actual = _parse_threshold(gate, output)
            threshold = float(gate.get("threshold", 0))
            op_name = gate.get("operator", ">=")
            op = OPS.get(op_name)
            result.actual = actual
            result.threshold = threshold
            if exit_code != 0 or actual is None or op is None or not op(actual, threshold):
                result.status = "failed" if required else "warning"
            else:
                result.status = "passed"
        else:
            result.status = "passed" if exit_code == 0 else ("failed" if required else "warning")

    result.completed_at = utc_now()
    result.duration_seconds = round(time.monotonic() - start, 3)
    record_gate_metric(name, result.status)
    log_gate_result(run_id, name, result.status, result.exit_code)
    if required and result.status == "failed":
        logger.error(
            "Required gate FAILED: name=%s exit_code=%s duration=%.3fs",
            name, result.exit_code, result.duration_seconds,
        )
    if bus:
        bus.emit(
            "gate:result",
            run_id,
            gate_name=name,
            status=result.status,
            output=result.output,
            exit_code=result.exit_code,
            retry_count=retry_count,
        )
    return result


def run_quality_gates(
    gates: Iterable[Dict],
    cwd: Path,
    run_id: str,
    bus: Optional[EventBus] = None,
    retry_count: int = 0,
    execution_policy: Optional[QualityGateExecutionPolicy] = None,
) -> List[QualityGateRun]:
    return [
        run_quality_gate(gate, cwd, run_id, bus=bus, retry_count=retry_count, execution_policy=execution_policy)
        for gate in gates
    ]


def has_blocking_failure(results: Iterable[QualityGateRun]) -> bool:
    return any(result.required and result.status == "failed" for result in results)


def max_retry_count_for_failures(gates: Iterable[Dict], results: Iterable[QualityGateRun]) -> int:
    failed_names = {result.name for result in results if result.required and result.status == "failed"}
    max_retries = 0
    for gate in gates:
        name = gate.get("name") or gate.get("command") or "quality gate"
        if name in failed_names:
            max_retries = max(max_retries, int(gate.get("max_retries", 0) or 0))
    return max_retries


def render_gate_feedback(results: Iterable[QualityGateRun], retry_count: int) -> str:
    failed = [result for result in results if result.required and result.status == "failed"]
    lines = [f"## 质量门禁失败反馈（第 {retry_count} 次重试）", ""]
    for result in failed:
        lines.extend(
            [
                f"### 失败门禁：{result.name}",
                f"- 命令：`{result.command}`",
                f"- 退出码：`{result.exit_code}`",
                "",
                "```text",
                result.output or "",
                "```",
                "",
            ]
        )
    lines.append("请只修复以上失败项，修复后重新提交。")
    return "\n".join(lines)
