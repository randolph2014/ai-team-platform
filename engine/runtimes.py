from __future__ import annotations

import os
import subprocess
import shutil
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


RUNTIME_SPECS: Dict[str, Dict[str, Any]] = {
    "claude": {
        "name": "Claude Code",
        "cli": "claude",
        "env": "CLAUDE",
        "args": ["-p", "--output-format", "stream-json"],
        "prompt_mode": "arg",
        "model_arg_style": "long",
        "launch_header": "claude (stream-json)",
        "supported": True,
    },
    "codex": {
        "name": "Codex CLI",
        "cli": "codex",
        "env": "CODEX",
        "args": ["exec"],
        "prompt_mode": "arg",
        "model_arg_style": "codex",
        "launch_header": "codex exec",
        "supported": True,
    },
    "opencode": {
        "name": "OpenCode",
        "cli": "opencode",
        "env": "OPENCODE",
        "args": ["run"],
        "prompt_mode": "arg",
        "model_arg_style": "long",
        "launch_header": "opencode run",
        "supported": True,
    },
    "hermes": {
        "name": "Hermes",
        "cli": "hermes",
        "env": "HERMES",
        "args": ["acp"],
        "prompt_mode": "stdin",
        "launch_header": "hermes acp",
        "supported": False,
        "unsupported_reason": "Hermes uses ACP JSON-RPC; this runner needs a backend adapter before execution.",
    },
    "kiro": {
        "name": "Kiro CLI",
        "cli": "kiro",
        "env": "KIRO",
        "args": [],
        "prompt_mode": "stdin",
        "launch_header": "kiro",
        "supported": False,
        "unsupported_reason": "Kiro CLI protocol is not implemented in this runner yet.",
    },
}

SUPPORTED_AUTO_ORDER = ("claude", "codex", "opencode")
TRANSIENT_RUNTIME_KEYS = {
    "available",
    "configured",
    "path",
    "version",
    "supported",
    "unsupported_reason",
    "launch_header",
    "provider",
    "source",
}


def _config_error(message: str) -> Exception:
    from .config import ConfigError

    return ConfigError(message)


def resolve_auto_cli() -> Optional[str]:
    for name in SUPPORTED_AUTO_ORDER:
        if shutil.which(name):
            return name
    return None


def _runtime_provider(cli: str) -> str:
    return Path(str(cli)).name


def _env_path(spec: Dict[str, Any]) -> Optional[str]:
    env_key = spec.get("env")
    if not env_key:
        return None
    return os.environ.get(f"AI_TEAM_{env_key}_PATH") or os.environ.get(f"MULTICA_{env_key}_PATH")


def _env_model(spec: Dict[str, Any]) -> Optional[str]:
    env_key = spec.get("env")
    if not env_key:
        return None
    value = os.environ.get(f"AI_TEAM_{env_key}_MODEL") or os.environ.get(f"MULTICA_{env_key}_MODEL")
    return value.strip() if value and value.strip() else None


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _first_string(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _read_top_level_toml_string(path: Path, key: str) -> Optional[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            return None
        if not line.startswith(f"{key} "):
            continue
        _, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip() or None
    return None


def _model_from_codex_config(home: Path) -> Optional[str]:
    return _read_top_level_toml_string(home / ".codex" / "config.toml", "model")


def _model_from_claude_config(home: Path) -> Optional[str]:
    data = _read_json_file(home / ".claude" / "settings.json")
    env = data.get("env") if isinstance(data.get("env"), dict) else {}
    configured_model = _first_string(env.get("ANTHROPIC_MODEL"))
    if configured_model:
        return configured_model
    model = _first_string(data.get("model"))
    if model:
        alias = model.upper()
        mapped = _first_string(env.get(f"ANTHROPIC_DEFAULT_{alias}_MODEL"))
        return mapped or model
    return None


def _model_from_opencode_config(home: Path) -> Optional[str]:
    for path in (
        home / ".config" / "opencode" / "opencode.json",
        home / ".config" / "opencode" / "config.json",
    ):
        data = _read_json_file(path)
        model = _first_string(data.get("model"), data.get("default_model"), data.get("defaultModel"))
        if model:
            return model
        agent = data.get("agent")
        if isinstance(agent, dict):
            model = _first_string(agent.get("model"), agent.get("default_model"), agent.get("defaultModel"))
            if model:
                return model
    return None


def _model_from_generic_json(home: Path, relative_path: str) -> Optional[str]:
    data = _read_json_file(home / relative_path)
    return _first_string(data.get("model"), data.get("default_model"), data.get("defaultModel"))


def _cli_config_model(runtime_id: str) -> Optional[str]:
    home = Path.home()
    if runtime_id == "codex":
        return _model_from_codex_config(home)
    if runtime_id == "claude":
        return _model_from_claude_config(home)
    if runtime_id == "opencode":
        return _model_from_opencode_config(home)
    if runtime_id == "kiro":
        return _model_from_generic_json(home, ".kiro/settings.json")
    if runtime_id == "hermes":
        return _model_from_generic_json(home, ".hermes/config.json")
    return None


def detect_cli_version(cli_path: str) -> Optional[str]:
    try:
        result = subprocess.run(
            [cli_path, "--version"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return None
    output = (result.stdout or result.stderr or "").strip()
    return output.splitlines()[0] if output else None


def discover_runtime_candidates() -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for runtime_id, spec in RUNTIME_SPECS.items():
        command = _env_path(spec) or spec["cli"]
        path = shutil.which(command)
        available = path is not None
        item = {
            "id": runtime_id,
            "provider": runtime_id,
            "name": spec["name"],
            "cli": spec["cli"],
            "path": path,
            "available": available,
            "supported": bool(spec.get("supported")),
            "args": list(spec.get("args") or []),
            "prompt_mode": spec.get("prompt_mode", "stdin"),
            "model_arg_style": spec.get("model_arg_style"),
            "launch_header": spec.get("launch_header", spec["cli"]),
            "version": detect_cli_version(path) if available else None,
        }
        if spec.get("unsupported_reason"):
            item["unsupported_reason"] = spec["unsupported_reason"]
        model = _env_model(spec) or _cli_config_model(runtime_id)
        if model:
            item["model"] = model
        candidates.append(item)
    return candidates


def sanitize_runtime_config(runtime: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {key: value for key, value in dict(runtime).items() if key not in TRANSIENT_RUNTIME_KEYS}
    if "default_model" in cleaned and "model" not in cleaned:
        cleaned["model"] = cleaned.pop("default_model")
    else:
        cleaned.pop("default_model", None)
    if not cleaned.get("fallback_models"):
        cleaned.pop("fallback_models", None)
    return cleaned


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
    provider = _runtime_provider(cli)
    spec = RUNTIME_SPECS.get(provider)
    if spec and not spec.get("supported"):
        return False
    return shutil.which(cli) is not None


def build_runtime_command(runtime: Dict[str, Any], prompt: str, model: Optional[str] = None) -> Tuple[List[str], str, str]:
    cli = runtime.get("cli", "auto")
    if cli == "auto":
        cli = resolve_auto_cli()
        if not cli:
            raise _config_error("No supported agent CLI found. Install claude, codex, or opencode, or configure a runtime.")
    if cli == "mock":
        return ["mock"], "mock", "arg"

    provider = _runtime_provider(cli)
    spec = RUNTIME_SPECS.get(provider, {})
    if spec and not spec.get("supported", True):
        raise _config_error(spec.get("unsupported_reason") or f"Runtime CLI is not supported yet: {provider}")

    executable = runtime.get("path") or cli
    args = list(runtime.get("args") or spec.get("args") or [])
    prompt_mode = runtime.get("prompt_mode") or spec.get("prompt_mode") or "stdin"
    command = [executable] + args
    if model:
        model_arg_style = runtime.get("model_arg_style") or spec.get("model_arg_style")
        if model_arg_style == "codex":
            command.extend(["-m", model])
        else:
            command.extend(["--model", model])
    if prompt_mode == "arg":
        command.append(prompt)
    return command, cli, prompt_mode
