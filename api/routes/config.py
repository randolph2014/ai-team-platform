from __future__ import annotations

import shutil
from typing import Any, Dict, List

from engine.config import (
    TEMPLATES_ROOT,
    _read_yaml,
    find_project_root,
    load_config,
    validate_production_config,
)

try:
    from fastapi import APIRouter, HTTPException, Query
except ImportError:  # pragma: no cover
    APIRouter = None

router = APIRouter() if APIRouter else None


KNOWN_PROVIDERS = ["claude", "codex", "opencode"]


def _load_default_yaml() -> Dict[str, Any]:
    if TEMPLATES_ROOT.joinpath("team.yaml").exists():
        return _read_yaml(TEMPLATES_ROOT.joinpath("team.yaml"))
    return {}


if router:

    @router.get("/config/providers")
    def get_providers():
        result: Dict[str, Any] = {"providers": {}}
        for name in KNOWN_PROVIDERS:
            result["providers"][name] = {"cli": name, "available": shutil.which(name) is not None}

        config = _load_default_yaml()
        configured = config.get("providers", {})
        for pname, pcfg in configured.items():
            if pname not in result["providers"]:
                cli = pcfg if isinstance(pcfg, str) else pcfg.get("cli", "")
                result["providers"][pname] = {
                    "cli": cli,
                    "available": shutil.which(cli) is not None if cli and cli != "auto" else True,
                }

        return result

    @router.get("/config/validate")
    def validate_config(workdir: str = Query(default=".")):
        project_root = find_project_root(workdir)
        loaded = load_config(project_root)
        errors: List[str] = []
        warnings: List[str] = list(loaded.warnings or [])

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
