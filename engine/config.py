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
from .runtimes import sanitize_runtime_config


PLATFORM_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_ROOT = PLATFORM_ROOT / "templates"
DEFAULT_TEAM_FILE = TEMPLATES_ROOT / "team.yaml"
USER_CONFIG_FILE = PLATFORM_ROOT / ".user-config.yaml"
SKILL_ROOT = Path.home() / ".agents" / "skills" / "ai-team"


DEFAULT_CONFIG: Dict[str, Any] = {
    "runtimes": {"auto": {"name": "Auto", "cli": "auto"}},
    "agents": [
        {"name": "requirements-analyst", "runtime_id": "auto", "role": "analyst", "prompt": "agents/requirements-analyst.md"},
        {"name": "solution-architect", "runtime_id": "auto", "role": "architect", "prompt": "agents/solution-architect.md"},
        {"name": "devils-advocate", "runtime_id": "auto", "role": "reviewer", "prompt": "agents/devils-advocate.md"},
        {"name": "planner", "runtime_id": "auto", "role": "planner", "prompt": "agents/planner.md"},
        {"name": "tech-lead", "runtime_id": "auto", "role": "lead", "prompt": "agents/tech-lead.md"},
        {"name": "qa-automation", "runtime_id": "auto", "role": "tester", "prompt": "agents/qa-automation.md"},
        {"name": "code-reviewer", "runtime_id": "auto", "role": "reviewer", "prompt": "agents/code-reviewer.md"},
        {"name": "retrospect", "runtime_id": "auto", "role": "summarizer", "prompt": "agents/retrospect.md"},
    ],
    "pipeline": [
        {
            "id": "context_scan",
            "name": "代码库扫描",
            "type": "context_scan",
            "output_file": "codebase-context.md",
            "output_json": "codebase-context.json",
        },
        {
            "id": "requirement_analysis",
            "name": "需求分析",
            "parallel": True,
            "agents": ["requirements-analyst", "devils-advocate"],
            "input": ["requirement", "codebase-context.md", "codebase-context.json"],
            "output": {
                "requirements-analyst": "requirement-analysis.md",
                "devils-advocate": "requirement-gap-analysis.md",
            },
            "required_artifacts": ["requirement-analysis.md", "requirement-gap-analysis.md"],
        },
        {
            "id": "requirement_synthesis",
            "name": "需求综合定稿",
            "parallel": False,
            "agents": ["requirements-analyst"],
            "input": [
                "requirement",
                "codebase-context.md",
                "codebase-context.json",
                "requirement-analysis.md",
                "requirement-gap-analysis.md",
                "human-decision-requirement*.json",
            ],
            "output": {"requirements-analyst": "requirement-final.md"},
            "json_artifacts": ["requirement-final.json"],
            "required_artifacts": ["requirement-final.md", "requirement-final.json"],
        },
        {
            "id": "requirement_confirm",
            "name": "需求人工确认",
            "type": "human_review",
            "input": ["requirement-final.md"],
            "output_file": "human-decision-requirement.md",
            "decision_file": "human-decision-requirement.json",
            "allow_auto_approve": False,
            "requires_reason_on_reject": True,
            "reject_to": "requirement_synthesis",
        },
        {
            "id": "planning",
            "name": "方案与任务规划",
            "parallel": False,
            "agents": ["planner"],
            "input": [
                "requirement-final.md",
                "requirement-final.json",
                "codebase-context.md",
                "codebase-context.json",
                "human-decision-requirement.json",
                "human-decision-task-plan*.json",
            ],
            "output": {"planner": "task-plan.md"},
            "json_artifacts": ["solution-plan.json", "task-plan.json"],
            "required_artifacts": ["task-plan.md", "solution-plan.json", "task-plan.json"],
        },
        {
            "id": "task_plan_confirm",
            "name": "任务规划人工确认",
            "type": "human_review",
            "input": ["task-plan.md"],
            "output_file": "human-decision-task-plan.md",
            "decision_file": "human-decision-task-plan.json",
            "allow_auto_approve": False,
            "requires_reason_on_reject": True,
            "reject_to": "planning",
        },
        {
            "id": "develop",
            "name": "开发实施",
            "parallel": False,
            "agents": ["tech-lead"],
            "input": [
                "requirement-final.md",
                "requirement-final.json",
                "codebase-context.md",
                "codebase-context.json",
                "solution-plan.json",
                "task-plan.md",
                "task-plan.json",
                "human-decision-task-plan.json",
                "human-decision-acceptance*.json",
            ],
            "output": {"tech-lead": "implementation-report.md"},
            "json_artifacts": ["implementation-report.json"],
            "required_artifacts": ["implementation-report.md", "implementation-report.json"],
        },
        {
            "id": "qa",
            "name": "自动测试",
            "parallel": False,
            "agents": ["qa-automation"],
            "input": [
                "requirement-final.md",
                "requirement-final.json",
                "solution-plan.json",
                "task-plan.md",
                "task-plan.json",
                "implementation-report.md",
                "implementation-report.json",
                "git-diff",
            ],
            "output": {"qa-automation": "test-report.md"},
            "json_artifacts": ["test-report.json"],
            "required_artifacts": ["test-report.md", "test-report.json"],
            "loopback_to": "develop",
            "loopback_trigger": ["FAILED", "ERROR", "失败", "exit code: 1", "退出码: 1"],
            "max_retries": 2,
        },
        {
            "id": "review",
            "name": "代码审查与风险识别",
            "parallel": False,
            "agents": ["code-reviewer"],
            "input": [
                "requirement-final.md",
                "requirement-final.json",
                "solution-plan.json",
                "task-plan.md",
                "task-plan.json",
                "implementation-report.md",
                "implementation-report.json",
                "test-report.md",
                "test-report.json",
                "git-diff",
            ],
            "output": {"code-reviewer": "review-report.md"},
            "json_artifacts": ["review-report.json"],
            "required_artifacts": ["review-report.md", "review-report.json"],
            "loopback_to": "develop",
            "loopback_trigger": "Request Changes",
            "max_retries": 2,
        },
        {
            "id": "acceptance_confirm",
            "name": "最终人工验收",
            "type": "human_review",
            "input": [
                "requirement-final.md",
                "requirement-final.json",
                "solution-plan.json",
                "task-plan.md",
                "task-plan.json",
                "implementation-report.md",
                "implementation-report.json",
                "test-report.md",
                "test-report.json",
                "review-report.md",
                "review-report.json",
                "git-diff",
            ],
            "output_file": "human-decision-acceptance.md",
            "decision_file": "human-decision-acceptance.json",
            "allow_auto_approve": False,
            "requires_reason_on_reject": True,
            "reject_to": "develop",
        },
        {
            "id": "retrospect",
            "name": "结果复盘",
            "parallel": False,
            "agents": ["retrospect"],
            "input": [
                "requirement-final.md",
                "requirement-final.json",
                "solution-plan.json",
                "task-plan.md",
                "task-plan.json",
                "implementation-report.md",
                "implementation-report.json",
                "test-report.md",
                "test-report.json",
                "review-report.md",
                "review-report.json",
                "human-decision-acceptance.json",
                "git-diff",
            ],
            "output": {"retrospect": "retrospect-report.md"},
            "json_artifacts": ["retrospect-report.json"],
            "required_artifacts": ["retrospect-report.md", "retrospect-report.json"],
        },
    ],
    "runner": {
        "max_input_chars_per_file": None,
        "max_loopback_feedback_chars": 20000,
        "loopback_truncate_strategy": "smart",  # smart | head | tail
        "stop_parallel_on_first_error": True,
        "agent_timeout_seconds": 1800,
        "heartbeat_seconds": 60,
        "parallel_log_mode": "interleaved",
        "production_mode": False,
        "require_worktree": False,
        "require_verify_cmd": False,
        "context_threshold_chars": 100000,
        "auto_split_requirements": True,
    },
}


class ConfigError(RuntimeError):
    pass


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _reject_unsafe_prompt_path(prompt: Path) -> None:
    if any(part == ".." for part in prompt.parts):
        raise ConfigError(f"Prompt path cannot contain '..': {prompt}")


def _safe_prompt_path(path: Path, allowed_roots: Iterable[Path], label: str) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    if any(_path_within(resolved, root) for root in allowed_roots):
        return resolved
    roots = ", ".join(str(root) for root in allowed_roots)
    raise ConfigError(f"{label} must be inside allowed roots ({roots}): {path}")


def find_project_root(start: str) -> Path:
    current = Path(start).expanduser().resolve()
    if current.is_file():
        current = current.parent
    while current != current.parent:
        if (current / ".ai").is_dir() or (current / ".git").exists() or (current / "AGENTS.md").exists():
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

    # explicit_config 仅用于测试，生产环境始终走平台模板
    if explicit_config:
        path = Path(explicit_config).expanduser()
        if not path.is_absolute():
            path = project_root / path
        if path.exists():
            config = _read_yaml(path)
            if "providers" in config or any(isinstance(agent, dict) and "provider" in agent for agent in config.get("agents", [])):
                warnings.append("DEPRECATED: providers/agent.provider 已迁移为 runtimes/agent.runtime_id，请保存配置以写回新结构。")
            return LoadedConfig(config=normalize_config(config, project_root), source="project", path=str(path), warnings=warnings)

    # 始终使用平台模板作为基础配置
    base_config: Dict[str, Any] = {}
    config_source = "platform"
    config_path = str(DEFAULT_TEAM_FILE)

    if DEFAULT_TEAM_FILE.exists():
        base_config = _read_yaml(DEFAULT_TEAM_FILE)
    else:
        base_config = dict(DEFAULT_CONFIG)
        config_source = "default"

    # 合并平台级用户自定义配置（通过 UI 保存的配置）
    if USER_CONFIG_FILE.exists():
        user_config = _read_yaml(USER_CONFIG_FILE)
        if isinstance(user_config, dict):
            _deep_merge(base_config, user_config)
            config_source = "customized"
            config_path = str(USER_CONFIG_FILE)

    if "providers" in base_config or any(isinstance(agent, dict) and "provider" in agent for agent in base_config.get("agents", [])):
        warnings.append("DEPRECATED: providers/agent.provider 已迁移为 runtimes/agent.runtime_id，请保存配置以写回新结构。")

    return LoadedConfig(config=normalize_config(base_config, project_root), source=config_source, path=config_path, warnings=warnings)


def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> None:
    """将 overrides 深度合并到 base 中（原地修改 base）。"""
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


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
                normalized_runtimes[str(runtime_id)] = sanitize_runtime_config(runtime)
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
        forbidden_agent_fields = sorted({"model", "fallback_models"} & set(agent))
        if forbidden_agent_fields:
            raise ConfigError(
                f"Agent {agent.get('name', '<unknown>')} cannot contain {', '.join(forbidden_agent_fields)}; "
                "configure model on the referenced runtime"
            )
        legacy_provider = agent.pop("provider", None)
        if "runtime_id" not in agent:
            agent["runtime_id"] = legacy_provider or default_runtime_id
        elif legacy_provider and legacy_provider != agent["runtime_id"]:
            raise ConfigError(f"Agent {agent.get('name', '<unknown>')} cannot contain both provider and a different runtime_id")
        if agent["runtime_id"] not in normalized_runtimes:
            raise ConfigError(f"Unknown runtime referenced by agent {agent.get('name', '<unknown>')}: {agent['runtime_id']}")
        normalized_agents.append(agent)
    normalized["agents"] = normalized_agents
    pipeline_source = normalized.get("pipeline", [])
    pipeline_settings: Dict[str, Any] = {"execution_mode": "parallel"}
    if isinstance(pipeline_source, dict):
        pipeline_settings.update({k: v for k, v in pipeline_source.items() if k != "stages"})
        pipeline_stages = pipeline_source.get("stages", [])
    elif isinstance(pipeline_source, list):
        pipeline_stages = pipeline_source
    else:
        raise ConfigError("pipeline must be a list or a mapping with stages")
    execution_mode = pipeline_settings.get("execution_mode", "parallel")
    if execution_mode not in {"serial", "parallel", "auto"}:
        raise ConfigError("pipeline.execution_mode must be one of: serial, parallel, auto")
    if not isinstance(pipeline_stages, list):
        raise ConfigError("pipeline.stages must be a list")
    normalized["pipeline"] = pipeline_stages
    normalized["pipeline_settings"] = pipeline_settings

    runner = dict(normalized.get("runner") or {})
    runner.setdefault("context_threshold_chars", 100000)
    runner.setdefault("auto_split_requirements", True)
    normalized["runner"] = runner
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

    allowed_roots = (project_root, TEMPLATES_ROOT, SKILL_ROOT)
    prompt = Path(agent.prompt) if agent.prompt else None
    if prompt:
        if prompt.is_absolute():
            _safe_prompt_path(prompt, allowed_roots, "Prompt path")
        else:
            _reject_unsafe_prompt_path(prompt)

    project_override = project_root / ".ai" / "agents" / f"{agent.name}.md"
    if project_override.exists():
        return _safe_prompt_path(project_override, allowed_roots, "Prompt path")

    if prompt:
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
            safe_candidate = _safe_prompt_path(candidate, allowed_roots, "Prompt path")
            if safe_candidate.exists():
                return safe_candidate

    template = TEMPLATES_ROOT / "agents" / f"{agent.name}.md"
    if template.exists():
        return _safe_prompt_path(template, allowed_roots, "Prompt path")

    skill_prompt = SKILL_ROOT / "agents" / f"{agent.name}.md"
    if skill_prompt.exists():
        warnings.append(
            f"DEPRECATED: prompt {agent.name} 从旧 skill 目录回退读取。请迁移到 templates/agents/ 或项目 .ai/agents/。"
        )
        return _safe_prompt_path(skill_prompt, allowed_roots, "Prompt path")

    raise ConfigError(f"Prompt not found for agent: {agent.name}")


def resolve_prompt_write_path(
    project_root: Path,
    config_path: Optional[str],
    agent: AgentDefinition,
) -> Path:
    prompt = Path(agent.prompt) if agent.prompt else None
    absolute_prompt: Optional[Path] = None
    if prompt:
        if prompt.is_absolute():
            absolute_prompt = _safe_prompt_path(prompt, (project_root,), "Prompt write path")
        else:
            _reject_unsafe_prompt_path(prompt)

    project_override = project_root / ".ai" / "agents" / f"{agent.name}.md"
    if project_override.exists():
        return _safe_prompt_path(project_override, (project_root,), "Prompt write path")

    if prompt:
        if prompt.is_absolute():
            if absolute_prompt and _path_within(absolute_prompt, TEMPLATES_ROOT):
                return _safe_prompt_path(project_override, (project_root,), "Prompt write path")
            return absolute_prompt or _safe_prompt_path(prompt, (project_root,), "Prompt write path")
        if config_path:
            config_parent = Path(config_path).expanduser().resolve(strict=False).parent
            if _path_within(config_parent, project_root) and not _path_within(config_parent, TEMPLATES_ROOT):
                return _safe_prompt_path(config_parent / prompt, (project_root,), "Prompt write path")
        return _safe_prompt_path(project_root / ".ai" / prompt, (project_root,), "Prompt write path")
    return _safe_prompt_path(project_override, (project_root,), "Prompt write path")


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
