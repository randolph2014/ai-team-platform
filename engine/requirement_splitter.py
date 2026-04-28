from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .agent_runner import AgentRunner
from .config import ConfigError, agent_map
from .context_scanner import scan_to_json
from .events import EventBus
from .models import RequirementUnit
from .runtimes import runtime_config


def estimate_prompt_size(requirement: str, artifacts: Iterable[Path]) -> int:
    size = len(requirement or "")
    for artifact in artifacts:
        try:
            if artifact.exists() and artifact.is_file():
                size += len(artifact.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return size


def should_split(config: Dict[str, Any], size: int) -> bool:
    runner = config.get("runner", {})
    if not runner.get("auto_split_requirements"):
        return False
    threshold = int(runner.get("context_threshold_chars") or 100000)
    return size >= threshold


def parse_requirement_units(raw: str) -> List[RequirementUnit]:
    payload = _load_json_payload(raw)
    units = payload.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("requirement split output must contain a non-empty units list")
    parsed = [RequirementUnit(**unit) for unit in units]
    unit_ids = {unit.id for unit in parsed}
    if len(unit_ids) != len(parsed):
        raise ValueError("requirement unit ids must be unique")
    for unit in parsed:
        missing = [dep for dep in unit.depends_on if dep not in unit_ids]
        if missing:
            raise ValueError(f"requirement unit {unit.id} depends on unknown units: {', '.join(missing)}")
    return parsed


def split_requirement(
    project_root: Path,
    requirement: str,
    config: Dict[str, Any],
    output_dir: Optional[Path] = None,
    event_bus: Optional[EventBus] = None,
) -> List[RequirementUnit]:
    agents = agent_map(config)
    agent = agents.get("solution-architect")
    if not agent:
        raise ConfigError("auto_split_requirements requires a solution-architect agent")
    runtime = runtime_config(config, agent.runtime_id)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "requirement-units.raw.md"
        raw_log_file = output_dir / "requirement-split.raw.log"
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="ai-team-split-"))
        output_file = temp_dir / "requirement-units.raw.md"
        raw_log_file = temp_dir / "requirement-split.raw.log"

    codebase_context = scan_to_json(project_root, config.get("context_scanner"))
    prompt = _render_split_prompt(requirement, codebase_context)
    runner = AgentRunner(config, bus=event_bus)
    result = runner.run(
        run_id="requirement-split",
        stage_id="requirement_split",
        agent=agent,
        runtime=runtime,
        prompt=prompt,
        cwd=project_root,
        output_file=output_file,
        raw_log_file=raw_log_file,
    )
    if result.status != "completed":
        raise RuntimeError(result.error_message or "requirement split failed")
    return parse_requirement_units(output_file.read_text(encoding="utf-8", errors="replace"))


def _load_json_payload(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("requirement split output is not valid JSON")
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ValueError("requirement split output is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("requirement split output must be a JSON object")
    return payload


def _render_split_prompt(requirement: str, codebase_context: str) -> str:
    return "\n".join(
        [
            "你是需求拆分架构师。请把大需求拆分为多个可以独立交付的需求单元。",
            "",
            "## 输出要求",
            "只输出 JSON，不要输出 Markdown 解释。格式如下：",
            '{"units":[{"id":"unit-1","title":"...","description":"...","priority":1,"depends_on":[],"requirement_text":"..."}]}',
            "",
            "## 拆分原则",
            "- 按功能模块拆分，每个单元应可独立开发和验收。",
            "- 用 depends_on 表达跨单元依赖，不要在 requirement_text 中丢失验收约束。",
            "- 不要伪造需求；原始需求没有的信息保持在单元描述中显式说明。",
            "",
            "## 代码库上下文",
            "```json",
            codebase_context,
            "```",
            "",
            "## 原始需求",
            requirement,
        ]
    )
