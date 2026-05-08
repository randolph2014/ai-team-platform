#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _findings(results: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    findings: List[str] = []
    for file_path, entries in sorted(results.items()):
        for entry in entries:
            line_number = entry.get("line_number", "?")
            secret_type = entry.get("type", "secret")
            findings.append(f"{file_path}:{line_number} {secret_type}")
    return findings


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: fail_on_detect_secrets.py <detect-secrets-baseline.json>", file=sys.stderr)
        return 2

    baseline_path = Path(argv[1])
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    findings = _findings(data.get("results") or {})
    if not findings:
        print("detect-secrets scan passed: no findings")
        return 0

    print("detect-secrets scan failed; review or remove these findings:", file=sys.stderr)
    for finding in findings:
        print(f"  - {finding}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
