from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - dependency is declared for production.
    yaml = None

from .models import AgentDefinition, LoadedConfig


PLATFORM_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_ROOT = PLATFORM_ROOT / "templates"
DEFAULT_TEAM_FILE = TEMPLATES_ROOT / "team.yaml"
SKILL_ROOT = Path.home() / ".agents" / "skills" / "ai-team"


DEFAULT_CONFIG: Dict[str, Any] = {
    "runtimes": {"auto": {"name": "Auto", "cli": "auto"}},
    "agents": [
        {"name": "solution-architect", "runtime_id": "auto", "role": "architect", "prompt": "agents/solution-architect.md"},
        {"name": "tech-lead", "runtime_id": "auto", "role": "lead", "prompt": "agents/tech-lead.md"},
        {"name": "qa-automation", "runtime_id": "auto", "role": "tester", "prompt": "agents/qa-automation.md"},
        {"name": "code-reviewer", "runtime_id": "auto", "role": "reviewer", "prompt": "agents/code-reviewer.md"},
    ],
    "pipeline": [
        {
            "id": "architect",
            "name": "方案定稿",
            "agents": ["solution-architect"],
            "input": "requirement",
            "output": {"solution-architect": "solution-draft.md"},
        },
        {"id": "context", "name": "代码库扫描", "type": "context_scan", "output_file": "codebase-context.md"},
        {
            "id": "develop",
            "name": "开发",
            "agents": ["tech-lead"],
            "input": ["requirement", "solution-draft.md", "codebase-context.md"],
            "output": {"tech-lead": "tech-lead-output.md"},
        },
        {"id": "code_apply", "name": "代码应用", "type": "code_apply", "input": ["tech-lead-output.md"]},
        {
            "id": "verify",
            "name": "测试与审查",
            "parallel": True,
            "agents": ["qa-automation", "code-reviewer"],
            "input": ["requirement", "solution-draft.md", "codebase-context.md", "tech-lead-output.md", "git-diff"],
            "output": {"qa-automation": "test-report.md", "code-reviewer": "review-report.md"},
            "loopback_to": "develop",
            "loopback_trigger": ["Request Changes", "FAILED", "ERROR", "失败"],
            "max_retries": 2,
        },
        {"id": "accept", "name": "人工验收", "type": "human_review"},
    ],
    "runner": {
        "max_input_chars_per_file": None,
        "max_loopback_feedback_chars": 20000,
        "stop_parallel_on_first_error": True,
        "agent_timeout_seconds": 1800,
        "heartbeat_seconds": 60,
        "parallel_log_mode": "interleaved",
        "production_mode": False,
        "require_worktree": False,
        "require_verify_cmd": False,
    },
}


class ConfigError(RuntimeError):
    pass


def find_project_root(start: str) -> Path:
    current = Path(start).expanduser().resolve()
    if current.is_file():
        current = current.parent
    while current != current.parent:
        if (current / ".ai" / "team.yaml").exists() or (current / ".git").exists() or (current / "AGENTS.md").exists():
            return current
        current = current.parent
    return Path(start).expanduser().resolve()


def _read_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise ConfigError("PyYAML is required to read YAML configuration")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ConfigError(f"Failed to read YAML config {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"Config file must be a mapping: {path}")
    return loaded


def load_config(project_root: Path, explicit_config: Optional[str] = None) -> LoadedConfig:
    warnings: List[str] = []
    candidates: List[Tuple[Path, str]] = []
    if explicit_config:
        candidates.append((Path(explicit_config).expanduser(), "project"))
    candidates.append((project_root / ".ai" / "team.yaml", "project"))
    candidates.append((DEFAULT_TEAM_FILE, "platform"))

    for path, source in candidates:
        if not path.is_absolute():
            path = project_root / path
        if path.exists():
            config = _read_yaml(path)
            if source == "platform":
                warnings.append(f"未找到项目级 .ai/team.yaml，使用平台模板: {path}")
            if "providers" in config or any(isinstance(agent, dict) and "provider" in agent for agent in config.get("agents", [])):
                warnings.append("DEPRECATED: providers/agent.provider 已迁移为 runtimes/agent.runtime_id，请保存配置以写回新结构。")
            return LoadedConfig(config=normalize_config(config, project_root), source=source, path=str(path), warnings=warnings)

    warnings.append("未找到项目级配置或平台模板，使用内置默认配置")
    return LoadedConfig(config=normalize_config(DEFAULT_CONFIG, project_root), source="default", warnings=warnings)


def normalize_config(config: Dict[str, Any], project_root: Optional[Path] = None) -> Dict[str, Any]:
    normalized = dict(config)
    legacy_providers = normalized.pop("providers", None)
    if legacy_providers is not None and normalized.get("runtimes"):
        raise ConfigError("Config cannot contain both runtimes and legacy providers")

    runtime_source = normalized.get("runtimes")
    if runtime_source is None:
        runtime_source = legacy_providers or {"auto": {"name": "Auto", "cli": "auto"}}
    if not runtime_source:
        runtime_source = {"auto": {"name": "Auto", "cli": "auto"}}

    normalized_runtimes: Dict[str, Dict[str, Any]] = {}
    if isinstance(runtime_source, list):
        for runtime in runtime_source:
            if not isinstance(runtime, dict) or not runtime.get("id"):
                raise ConfigError("Runtime list entries must be mappings with an id")
            runtime_id = str(runtime["id"])
            runtime_config = dict(runtime)
            runtime_config.pop("id", None)
            normalized_runtimes[runtime_id] = runtime_config
    elif isinstance(runtime_source, dict):
        for runtime_id, runtime in runtime_source.items():
            if isinstance(runtime, str):
                normalized_runtimes[str(runtime_id)] = {"cli": runtime}
            elif isinstance(runtime, dict):
                normalized_runtimes[str(runtime_id)] = dict(runtime)
            else:
                raise ConfigError(f"Invalid runtime config for {runtime_id}")
    else:
        raise ConfigError("runtimes must be a mapping or a list")

    if not normalized_runtimes:
        normalized_runtimes["auto"] = {"name": "Auto", "cli": "auto"}
    for runtime_id, runtime in normalized_runtimes.items():
        runtime.setdefault("name", runtime_id)
        runtime.setdefault("cli", "auto")
    normalized["runtimes"] = normalized_runtimes

    normalized_agents: List[Dict[str, Any]] = []
    default_runtime_id = next(iter(normalized_runtimes))
    for item in normalized.get("agents", []) or []:
        if not isinstance(item, dict):
            raise ConfigError("Agent config entries must be mappings")
        agent = dict(item)
        legacy_provider = agent.pop("provider", None)
        if "runtime_id" not in agent:
            agent["runtime_id"] = legacy_provider or default_runtime_id
        elif legacy_provider and legacy_provider != agent["runtime_id"]:
            raise ConfigError(f"Agent {agent.get('name', '<unknown>')} cannot contain both provider and a different runtime_id")
        if agent["runtime_id"] not in normalized_runtimes:
            raise ConfigError(f"Unknown runtime referenced by agent {agent.get('name', '<unknown>')}: {agent['runtime_id']}")
        normalized_agents.append(agent)
    normalized["agents"] = normalized_agents
    normalized.setdefault("pipeline", [])
    normalized.setdefault("runner", {})
    normalized.setdefault("worktree", {"enabled": True})
    normalized.setdefault("quality_gates", [])

    return normalized


def agent_map(config: Dict[str, Any]) -> Dict[str, AgentDefinition]:
    agents: Dict[str, AgentDefinition] = {}
    for item in config.get("agents", []):
        agent = AgentDefinition(**item)
        agents[agent.name] = agent
    return agents


def resolve_prompt_path(
    project_root: Path,
    config_path: Optional[str],
    agent: AgentDefinition,
    warnings: Optional[List[str]] = None,
) -> Path:
    warnings = warnings if warnings is not None else []

    project_override = project_root / ".ai" / "agents" / f"{agent.name}.md"
    if project_override.exists():
        return project_override

    if agent.prompt:
        prompt = Path(agent.prompt)
        candidates = []
        if prompt.is_absolute():
            candidates.append(prompt)
        else:
            if config_path:
                candidates.append(Path(config_path).parent / prompt)
            candidates.append(project_root / ".ai" / prompt)
            candidates.append(project_root / prompt)
            candidates.append(TEMPLATES_ROOT / prompt)
        for candidate in candidates:
            if candidate.exists():
                return candidate

    template = TEMPLATES_ROOT / "agents" / f"{agent.name}.md"
    if template.exists():
        return template

    skill_prompt = SKILL_ROOT / "agents" / f"{agent.name}.md"
    if skill_prompt.exists():
        warnings.append(
            f"DEPRECATED: prompt {agent.name} 从旧 skill 目录回退读取。请迁移到 templates/agents/ 或项目 .ai/agents/。"
        )
        return skill_prompt

    raise ConfigError(f"Prompt not found for agent: {agent.name}")


def read_prompt(project_root: Path, config_path: Optional[str], agent: AgentDefinition, warnings: Optional[List[str]] = None) -> str:
    path = resolve_prompt_path(project_root, config_path, agent, warnings)
    return path.read_text(encoding="utf-8")


def validate_production_config(config: Dict[str, Any]) -> None:
    runner = config.get("runner", {})
    if not runner.get("production_mode") and not runner.get("require_worktree") and not runner.get("require_verify_cmd"):
        return
    if runner.get("require_worktree") and not config.get("worktree", {}).get("enabled"):
        raise ConfigError("Production mode requires worktree.enabled=true")
    if runner.get("require_verify_cmd") and not config.get("quality_gates"):
        raise ConfigError("Production mode requires at least one quality_gates entry")


def executable_exists(name: str) -> bool:
    return shutil.which(name) is not None


def load_json_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def expand_env(value: str) -> str:
    return os.path.expandvars(value)
