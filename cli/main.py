from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engine.config import PLATFORM_ROOT, ConfigError, find_project_root
from engine.orchestrator import Orchestrator, find_run_reports, load_report
from engine.worktree import WorktreeManager


def _read_requirement(args: argparse.Namespace) -> str:
    if args.spec_file:
        return Path(args.spec_file).expanduser().read_text(encoding="utf-8")
    if args.requirement:
        return args.requirement
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("requirement or --spec-file is required")


def _project_root(args: argparse.Namespace) -> Path:
    root = getattr(args, "project", None) or getattr(args, "workdir", None) or os.getcwd()
    return find_project_root(root)


def cmd_run(args: argparse.Namespace) -> int:
    project_root = _project_root(args)
    requirement = _read_requirement(args)
    orchestrator = Orchestrator(project_root, config_path=args.config)
    report = orchestrator.run(
        requirement,
        run_id=args.run_id,
        only_stage=args.only_stage,
        skip_stages=args.skip_stages or [],
        yes=args.yes,
        production=args.production,
        merge=args.merge,
    )
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(f"run_id: {report.run_id}")
        print(f"status: {report.status}")
        print(f"output_dir: {report.output_dir}")
        if report.error_message:
            print(f"error: {report.error_message}", file=sys.stderr)
    return 0 if report.status in {"completed", "waiting"} else 1


def cmd_status(args: argparse.Namespace) -> int:
    project_root = _project_root(args)
    reports = find_run_reports(project_root)
    if args.run_id:
        reports = [path for path in reports if path.parent.name == args.run_id]
    if args.latest and reports:
        reports = [reports[0]]
    payload = [load_report(path).model_dump(mode="json") for path in reports]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not payload:
        print("No runs found")
        return 0
    for item in payload:
        print(f"{item['run_id']}  {item['status']}  {item.get('duration_seconds') or '-'}s  {item['output_dir']}")
    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    project_root = _project_root(args)
    manager = WorktreeManager(project_root)
    cleaned = manager.cleanup_orphans()
    print(json.dumps({"cleaned": cleaned}, ensure_ascii=False, indent=2) if args.json else f"cleaned: {', '.join(cleaned) or 'none'}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("uvicorn is not installed. Install with `pip install -e .` or `pip install uvicorn fastapi`.") from exc
    app_path = "api.app:create_app"
    uvicorn.run(app_path, factory=True, host=args.host, port=args.port, reload=args.reload)
    return 0


def _source_commit() -> Optional[str]:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PLATFORM_ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def cmd_install_skill(args: argparse.Namespace) -> int:
    source = PLATFORM_ROOT / "adapters" / "ai-team-skill"
    target = Path(args.target).expanduser()
    if not source.exists():
        raise SystemExit(f"adapter source does not exist: {source}")
    if target.exists() or target.is_symlink():
        if not args.force:
            raise SystemExit(f"target exists: {target}. Pass --force to replace it.")
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == "symlink":
        target.symlink_to(source, target_is_directory=True)
    else:
        shutil.copytree(source, target)

    version_file = target / "adapter-version.json"
    version_file.write_text(
        json.dumps(
            {
                "platform_version": "0.1.0",
                "adapter_version": "0.1.0",
                "source_commit": _source_commit(),
                "source_path": str(source),
                "installed_at": datetime.now(timezone.utc).isoformat(),
                "mode": args.mode,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"installed adapter: {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-team", description="AI Team Platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a pipeline")
    run.add_argument("requirement", nargs="?", help="requirement text")
    run.add_argument("--spec-file", help="read requirement from a file")
    run.add_argument("--project", "--workdir", dest="project", help="project root")
    run.add_argument("--config", help="explicit team.yaml path")
    run.add_argument("--run-id", help="stable run id")
    run.add_argument("--only-stage", help="run only one stage")
    run.add_argument("--skip-stages", nargs="*", help="stage ids to skip")
    run.add_argument("--yes", action="store_true", help="auto-accept human review")
    run.add_argument("--production", action="store_true", help="enable production checks declared by config")
    run.add_argument("--merge", action="store_true", help="merge successful worktree back to base branch")
    run.add_argument("--json", action="store_true", help="print JSON report")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="list run status")
    status.add_argument("--project", "--workdir", dest="project", help="project root")
    status.add_argument("--run-id", help="filter by run id")
    status.add_argument("--latest", action="store_true", help="show latest run only")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    cleanup = sub.add_parser("cleanup", help="cleanup orphan worktrees")
    cleanup.add_argument("--project", "--workdir", dest="project", help="project root")
    cleanup.add_argument("--json", action="store_true")
    cleanup.set_defaults(func=cmd_cleanup)

    serve = sub.add_parser("serve", help="start REST API and WebSocket service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    install = sub.add_parser("install-skill", help="install optional ai-team skill adapter")
    install.add_argument("--target", default="~/.agents/skills/ai-team")
    install.add_argument("--mode", choices=["symlink", "copy"], default="symlink")
    install.add_argument("--force", action="store_true")
    install.set_defaults(func=cmd_install_skill)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
