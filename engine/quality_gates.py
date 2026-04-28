from __future__ import annotations

import operator
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .events import EventBus
from .logging_config import log_gate_result
from .metrics import record_gate_result as record_gate_metric
from .models import QualityGateRun, utc_now


OPS = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
    "==": operator.eq,
}


class QualityGateError(RuntimeError):
    pass


def _run_command(command: str, cwd: Path, timeout: Optional[int]) -> Tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
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


def run_quality_gate(gate: Dict, cwd: Path, run_id: str, bus: Optional[EventBus] = None, retry_count: int = 0) -> QualityGateRun:
    name = gate.get("name") or gate.get("command") or "quality gate"
    gate_type = gate.get("type", "command")
    required = bool(gate.get("required", True))
    command = gate.get("command")
    timeout = gate.get("timeout_seconds") or gate.get("timeout")
    result = QualityGateRun(
        name=name,
        type=gate_type,
        command=command,
        required=required,
        retry_count=retry_count,
        status="running",
        started_at=utc_now(),
    )
    start = time.monotonic()
    if bus:
        bus.emit("gate:started", run_id, gate_name=name, command=command, retry_count=retry_count)

    if gate_type not in {"command", "threshold"}:
        result.status = "skipped"
        result.output = f"Unsupported gate type: {gate_type}"
    elif not command:
        result.status = "failed" if required else "warning"
        result.output = "Missing gate command"
    else:
        exit_code, output = _run_command(command, cwd, timeout)
        result.exit_code = exit_code
        result.output = output[-20000:]
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


def run_quality_gates(gates: Iterable[Dict], cwd: Path, run_id: str, bus: Optional[EventBus] = None, retry_count: int = 0) -> List[QualityGateRun]:
    return [run_quality_gate(gate, cwd, run_id, bus=bus, retry_count=retry_count) for gate in gates]


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
