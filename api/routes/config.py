from __future__ import annotations

import shutil
from typing import Any, Dict, List

from engine.config import (
    TEMPLATES_ROOT,
    _read_yaml,
    ConfigError,
    find_project_root,
    load_config,
    validate_production_config,
)
from engine.runtimes import runtime_available
from .settings import _mask_sensitive

try:
    from fastapi import APIRouter, HTTPException, Query
except ImportError:  # pragma: no cover
    APIRouter = None

router = APIRouter() if APIRouter else None


KNOWN_RUNTIMES = ["claude", "codex", "opencode"]


def _load_default_yaml() -> Dict[str, Any]:
    if TEMPLATES_ROOT.joinpath("team.yaml").exists():
        return _read_yaml(TEMPLATES_ROOT.joinpath("team.yaml"))
    return {}


if router:

    @router.get("/config/runtimes")
    def get_runtimes(workdir: str = Query(default=".")):
        result: Dict[str, Any] = {"runtimes": {}}
        for name in KNOWN_RUNTIMES:
            result["runtimes"][name] = {"name": name, "cli": name, "available": shutil.which(name) is not None}

        try:
            loaded = load_config(find_project_root(workdir))
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        configured = loaded.config.get("runtimes", {})
        for runtime_id, runtime in configured.items():
            item = dict(runtime)
            item["available"] = runtime_available(item)
            result["runtimes"][runtime_id] = _mask_sensitive(item)

        return result

    @router.get("/config/validate")
    def validate_config(workdir: str = Query(default=".")):
        project_root = find_project_root(workdir)
        errors: List[str] = []
        warnings: List[str] = []
        try:
            loaded = load_config(project_root)
        except ConfigError as exc:
            return {
                "valid": False,
                "errors": [str(exc)],
                "warnings": warnings,
                "source": None,
                "path": None,
            }
        warnings.extend(loaded.warnings or [])

        try:
            validate_production_config(loaded.config)
        except Exception as exc:
            errors.append(str(exc))

        agents = loaded.config.get("agents", [])
        if not agents:
            warnings.append("No agents configured in pipeline")
        else:
            for agent in agents:
                name = agent.get("name", "unknown")
                runtime_id = agent.get("runtime_id")
                if runtime_id not in loaded.config.get("runtimes", {}):
                    errors.append(f"Unknown runtime referenced by agent '{name}': {runtime_id}")
                prompt = agent.get("prompt", "")
                if not prompt:
                    warnings.append(f"Agent '{name}' has no prompt configured")

                agent_path = project_root / ".ai" / "agents" / f"{name}.md"
                template_path = TEMPLATES_ROOT / "agents" / f"{name}.md"
                if not agent_path.exists() and not template_path.exists():
                    if isinstance(prompt, str) and not prompt.startswith("/"):
                        resolved_path = project_root / ".ai" / prompt
                        template_resolved = TEMPLATES_ROOT / prompt
                        if not resolved_path.exists() and not template_resolved.exists():
                            warnings.append(f"Prompt file not found for agent '{name}': {prompt}")

        pipeline = loaded.config.get("pipeline", [])
        if not pipeline:
            warnings.append("No pipeline stages configured")

        worktree = loaded.config.get("worktree", {})
        if worktree.get("enabled") and not shutil.which("git"):
            errors.append("Worktree enabled but git is not installed")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "source": loaded.source,
            "path": loaded.path,
        }
