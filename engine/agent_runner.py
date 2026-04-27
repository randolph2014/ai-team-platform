from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import ConfigError
from .cost_tracker import CostTracker, estimate_tokens
from .events import EventBus
from .models import AgentDefinition, AgentRun, utc_now


DEFAULT_PROVIDER_ARGS = {
    "claude": ["-p", "--output-format", "stream-json"],
    "codex": ["exec"],
    "opencode": ["run"],
}

DEFAULT_PROMPT_MODE = {
    "claude": "arg",
    "codex": "arg",
    "opencode": "arg",
}


class AgentExecutionError(RuntimeError):
    pass


def resolve_auto_cli() -> Optional[str]:
    for name in ("claude", "codex", "opencode"):
        if shutil.which(name):
            return name
    return None


def build_command(provider: Dict[str, Any], prompt: str, model: Optional[str] = None) -> Tuple[List[str], str, str]:
    cli = provider.get("cli", "auto")
    if cli == "auto":
        cli = resolve_auto_cli()
        if not cli:
            raise ConfigError("No supported agent CLI found. Install claude, codex, or opencode, or configure a provider.")
    if cli == "mock":
        return ["mock"], "mock", "arg"
    args = list(provider.get("args") or DEFAULT_PROVIDER_ARGS.get(cli, []))
    prompt_mode = provider.get("prompt_mode") or DEFAULT_PROMPT_MODE.get(cli, "stdin")
    command = [cli] + args
    if model:
        if cli == "codex":
            command.extend(["-m", model])
        else:
            command.extend(["--model", model])
    if prompt_mode == "arg":
        command.append(prompt)
    return command, cli, prompt_mode


def _decode_claude_stream_line(line: str) -> str:
    try:
        payload = json.loads(line)
    except Exception:
        return line
    if isinstance(payload, dict):
        if payload.get("type") == "assistant":
            message = payload.get("message") or {}
            content = message.get("content") or []
            parts = [item.get("text", "") for item in content if isinstance(item, dict)]
            return "".join(parts) or line
        if "content" in payload and isinstance(payload["content"], str):
            return payload["content"]
    return line


class AgentRunner:
    def __init__(self, config: Dict[str, Any], bus: Optional[EventBus] = None, cost_tracker: Optional[CostTracker] = None) -> None:
        self.config = config
        self.bus = bus or EventBus()
        self.runner_config = config.get("runner", {})
        self.cost_tracker = cost_tracker

    def run(
        self,
        run_id: str,
        stage_id: str,
        agent: AgentDefinition,
        provider: Dict[str, Any],
        prompt: str,
        cwd: Path,
        output_file: Path,
        raw_log_file: Path,
    ) -> AgentRun:
        self._last_prompt = prompt
        overall_start = time.monotonic()
        timeout = agent.timeout or self.runner_config.get("agent_timeout_seconds") or 1800
        heartbeat_seconds = int(self.runner_config.get("heartbeat_seconds") or 0)

        primary_model = agent.model or provider.get("default_model")
        models_to_try: List[Optional[str]] = []
        if primary_model:
            models_to_try.append(primary_model)
        models_to_try.extend(agent.fallback_models)
        if not models_to_try:
            models_to_try = [None]

        last_run: Optional[AgentRun] = None
        remaining_models = list(models_to_try)
        for model in models_to_try:
            remaining_models.pop(0)
            elapsed = time.monotonic() - overall_start
            remaining_timeout = max(int(timeout - elapsed), 1)

            agent_run = self._try_model(
                run_id=run_id,
                stage_id=stage_id,
                agent=agent,
                provider=provider,
                prompt=prompt,
                cwd=cwd,
                output_file=output_file,
                raw_log_file=raw_log_file,
                model=model,
                model_requested=primary_model,
                timeout=remaining_timeout,
                heartbeat_seconds=heartbeat_seconds,
            )
            if agent_run.status == "completed":
                return self._complete(agent_run, overall_start, run_id, stage_id)
            if remaining_models:
                self.bus.emit(
                    "agent:fallback",
                    run_id,
                    stage_id=stage_id,
                    agent_name=agent.name,
                    failed_model=model,
                    next_model=remaining_models[0],
                    error=agent_run.error_message,
                )
            last_run = agent_run

        return self._complete(last_run, overall_start, run_id, stage_id)

    def _try_model(
        self,
        run_id: str,
        stage_id: str,
        agent: AgentDefinition,
        provider: Dict[str, Any],
        prompt: str,
        cwd: Path,
        output_file: Path,
        raw_log_file: Path,
        model: Optional[str],
        model_requested: Optional[str],
        timeout: int,
        heartbeat_seconds: int,
    ) -> AgentRun:
        attempt_start = time.monotonic()
        agent_run = AgentRun(
            agent_name=agent.name,
            provider=agent.provider,
            role=agent.role,
            model_requested=model_requested,
            model_used=model,
            status="running",
            started_at=utc_now(),
            output_file=str(output_file),
            raw_log_file=str(raw_log_file),
        )
        self.bus.emit("agent:started", run_id, stage_id=stage_id, agent_name=agent.name, provider=agent.provider)

        try:
            command, cli, prompt_mode = build_command(provider, prompt, model=model)
            if cli == "mock":
                content = provider.get("response") or f"Mock agent `{agent.name}` completed stage `{stage_id}`."
                output_file.write_text(content + "\n", encoding="utf-8")
                raw_log_file.write_text(content + "\n", encoding="utf-8")
                agent_run.status = "completed"
                agent_run.exit_code = 0
                self.bus.emit("agent:output", run_id, stage_id=stage_id, agent_name=agent.name, text=content)
                return agent_run

            output_file.parent.mkdir(parents=True, exist_ok=True)
            raw_log_file.parent.mkdir(parents=True, exist_ok=True)
            with raw_log_file.open("w", encoding="utf-8") as raw_log, output_file.open("w", encoding="utf-8") as final_output:
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    stdin=subprocess.PIPE if prompt_mode == "stdin" else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                if prompt_mode == "stdin" and process.stdin:
                    process.stdin.write(prompt)
                    process.stdin.close()

                last_output = time.monotonic()
                timed_out = False
                heartbeat_stop = threading.Event()

                def heartbeat() -> None:
                    while not heartbeat_stop.wait(heartbeat_seconds):
                        if heartbeat_seconds <= 0:
                            return
                        elapsed = int(time.monotonic() - attempt_start)
                        idle = int(time.monotonic() - last_output)
                        self.bus.emit(
                            "agent:heartbeat",
                            run_id,
                            stage_id=stage_id,
                            agent_name=agent.name,
                            elapsed=elapsed,
                            idle=idle,
                            timeout=timeout,
                        )

                heartbeat_thread = None
                if heartbeat_seconds > 0:
                    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
                    heartbeat_thread.start()

                try:
                    while True:
                        if process.stdout is None:
                            break
                        line = process.stdout.readline()
                        if line:
                            last_output = time.monotonic()
                            raw_log.write(line)
                            raw_log.flush()
                            decoded = _decode_claude_stream_line(line.rstrip("\n"))
                            if decoded:
                                final_output.write(decoded + "\n")
                                final_output.flush()
                                self.bus.emit("agent:output", run_id, stage_id=stage_id, agent_name=agent.name, text=decoded)
                        if process.poll() is not None:
                            remainder = process.stdout.read() if process.stdout else ""
                            if remainder:
                                raw_log.write(remainder)
                                for raw_line in remainder.splitlines():
                                    decoded = _decode_claude_stream_line(raw_line)
                                    final_output.write(decoded + "\n")
                                    self.bus.emit("agent:output", run_id, stage_id=stage_id, agent_name=agent.name, text=decoded)
                            break
                        if time.monotonic() - attempt_start > timeout:
                            timed_out = True
                            process.terminate()
                            try:
                                process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                process.kill()
                            break
                finally:
                    heartbeat_stop.set()
                    if heartbeat_thread:
                        heartbeat_thread.join(timeout=1)

                exit_code = process.wait()
                agent_run.exit_code = exit_code
                if timed_out:
                    agent_run.status = "timeout"
                    agent_run.error_message = f"Agent timed out after {timeout}s"
                elif exit_code == 0:
                    agent_run.status = "completed"
                else:
                    agent_run.status = "failed"
                    agent_run.error_message = f"Agent exited with code {exit_code}"
        except Exception as exc:
            agent_run.status = "failed"
            agent_run.error_message = str(exc)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(f"ERROR: {exc}\n", encoding="utf-8")
            raw_log_file.parent.mkdir(parents=True, exist_ok=True)
            raw_log_file.write_text(f"ERROR: {exc}\n", encoding="utf-8")

        return agent_run

    def _complete(self, agent_run: AgentRun, started: float, run_id: str, stage_id: str) -> AgentRun:
        agent_run.completed_at = utc_now()
        agent_run.duration_seconds = round(time.monotonic() - started, 3)

        if self.cost_tracker:
            try:
                self._track_cost(agent_run, run_id, stage_id)
            except Exception:
                pass

        self.bus.emit(
            "agent:completed",
            run_id,
            stage_id=stage_id,
            agent_name=agent_run.agent_name,
            status=agent_run.status,
            duration=agent_run.duration_seconds,
            output_file=agent_run.output_file,
        )
        return agent_run

    def _track_cost(self, agent_run: AgentRun, run_id: str, stage_id: str) -> None:
        output_text = ""
        if agent_run.output_file:
            output_path = Path(agent_run.output_file)
            if output_path.exists():
                try:
                    output_text = output_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

        prompt_tokens = estimate_tokens(getattr(self, "_last_prompt", ""))
        completion_tokens = estimate_tokens(output_text)

        provider_config = self.config.get("providers", {}).get(agent_run.provider, {})
        model = agent_run.model_used or (provider_config.get("model") if isinstance(provider_config, dict) else None) or "default"

        self.cost_tracker.track_usage(
            run_id=run_id,
            agent_name=agent_run.agent_name,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            stage_id=stage_id,
        )
