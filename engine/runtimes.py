from __future__ import annotations

import shutil
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_RUNTIME_ARGS = {
    "claude": ["-p", "--output-format", "stream-json"],
    "codex": ["exec"],
    "opencode": ["run"],
}

DEFAULT_PROMPT_MODE = {
    "claude": "arg",
    "codex": "arg",
    "opencode": "arg",
}


def _config_error(message: str) -> Exception:
    from .config import ConfigError

    return ConfigError(message)


def resolve_auto_cli() -> Optional[str]:
    for name in ("claude", "codex", "opencode"):
        if shutil.which(name):
            return name
    return None


def runtime_config(config: Dict[str, Any], runtime_id: str) -> Dict[str, Any]:
    runtimes = config.get("runtimes", {})
    runtime = runtimes.get(runtime_id)
    if runtime is None:
        raise _config_error(f"Unknown runtime: {runtime_id}")
    resolved = dict(runtime)
    resolved.setdefault("id", runtime_id)
    return resolved


def runtime_available(runtime: Dict[str, Any]) -> bool:
    cli = runtime.get("cli", "auto")
    if cli == "mock":
        return True
    if cli == "auto":
        return resolve_auto_cli() is not None
    return shutil.which(cli) is not None


def build_runtime_command(runtime: Dict[str, Any], prompt: str, model: Optional[str] = None) -> Tuple[List[str], str, str]:
    cli = runtime.get("cli", "auto")
    if cli == "auto":
        cli = resolve_auto_cli()
        if not cli:
            raise _config_error("No supported agent CLI found. Install claude, codex, or opencode, or configure a runtime.")
    if cli == "mock":
        return ["mock"], "mock", "arg"

    args = list(runtime.get("args") or DEFAULT_RUNTIME_ARGS.get(cli, []))
    prompt_mode = runtime.get("prompt_mode") or DEFAULT_PROMPT_MODE.get(cli, "stdin")
    command = [cli] + args
    if model:
        model_arg_style = runtime.get("model_arg_style")
        if model_arg_style == "codex" or (model_arg_style is None and cli == "codex"):
            command.extend(["-m", model])
        else:
            command.extend(["--model", model])
    if prompt_mode == "arg":
        command.append(prompt)
    return command, cli, prompt_mode
