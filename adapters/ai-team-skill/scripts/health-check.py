#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def platform_root() -> Path:
    override = os.environ.get("AI_TEAM_PLATFORM_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def main() -> int:
    root = platform_root()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    checks = [
        [sys.executable, "-m", "cli.main", "status", "--project", str(root)],
        [sys.executable, "-c", "import engine, cli; print('platform imports ok')"],
    ]
    for command in checks:
        result = subprocess.run(command, cwd=root, env=env)
        if result.returncode != 0:
            return result.returncode
    print(f"AI Team Platform adapter ok: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
