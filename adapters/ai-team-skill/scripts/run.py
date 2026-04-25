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
    command = [sys.executable, "-m", "cli.main", "run"] + sys.argv[1:]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(command, cwd=root, env=env)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
