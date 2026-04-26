from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import find_project_root
from .events import EventBus


MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "claude-opus": {"input": 15.0, "output": 75.0},
    "claude-sonnet": {"input": 3.0, "output": 15.0},
    "claude-haiku": {"input": 0.25, "output": 1.25},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
}

DEFAULT_PRICING = {"input": 3.0, "output": 15.0}

ESTIMATE_CHARS_PER_TOKEN = 4


def _load_env_pricing() -> Dict[str, Dict[str, float]]:
    pricing = dict(MODEL_PRICING)
    raw = os.environ.get("AI_TEAM_MODEL_PRICING", "")
    if raw:
        try:
            overrides = json.loads(raw)
            if isinstance(overrides, dict):
                for model, rates in overrides.items():
                    if isinstance(rates, dict):
                        pricing[model] = {
                            "input": float(rates.get("input", DEFAULT_PRICING["input"])),
                            "output": float(rates.get("output", DEFAULT_PRICING["output"])),
                        }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return pricing


def get_pricing(model: str) -> Dict[str, float]:
    pricing = _load_env_pricing()
    for key in (model, model.lower(), model.replace("-", "_")):
        if key in pricing:
            return pricing[key]
    for key, rates in pricing.items():
        if key.replace("-", "_") == model.lower().replace("-", "_"):
            return rates
    return dict(DEFAULT_PRICING)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // ESTIMATE_CHARS_PER_TOKEN)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = get_pricing(model)
    input_cost = (prompt_tokens / 1_000_000) * rates["input"]
    output_cost = (completion_tokens / 1_000_000) * rates["output"]
    return round(input_cost + output_cost, 8)


class CostTracker:
    def __init__(self, project_root: Optional[Path] = None, bus: Optional[EventBus] = None) -> None:
        self._project_root = project_root or find_project_root(".")
        self._bus = bus
        self._db = self._try_get_db()

    @staticmethod
    def _try_get_db():
        try:
            from persistence.db import get_db
            return get_db()
        except Exception:
            return None

    @property
    def _costs_dir(self) -> Path:
        return self._project_root / ".ai" / "costs"

    def track_usage(
        self,
        run_id: str,
        agent_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        stage_id: str = "",
    ) -> None:
        cost = estimate_cost(model, prompt_tokens, completion_tokens)
        if self._db is not None:
            self._db_write(run_id, agent_name, model, prompt_tokens, completion_tokens, cost, stage_id)
        else:
            self._file_write(run_id, agent_name, model, prompt_tokens, completion_tokens, cost, stage_id)

        if self._bus:
            self._bus.emit(
                "cost:tracked",
                run_id,
                agent_name=agent_name,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost=cost,
                stage_id=stage_id,
            )

    def _db_write(
        self,
        run_id: str,
        agent_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
        stage_id: str,
    ) -> None:
        try:
            self._db.execute(
                "INSERT INTO cost_tracking (run_id, agent_name, model, prompt_tokens, completion_tokens, cost, stage_id, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, agent_name, model, prompt_tokens, completion_tokens, cost, stage_id, datetime.now(timezone.utc).isoformat()),
            )
            self._db.commit()
        except Exception:
            self._file_write(run_id, agent_name, model, prompt_tokens, completion_tokens, cost, stage_id)

    def _file_write(
        self,
        run_id: str,
        agent_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
        stage_id: str,
    ) -> None:
        self._costs_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "run_id": run_id,
            "agent_name": agent_name,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated_cost": cost,
            "stage_id": stage_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        filepath = self._costs_dir / f"{run_id}.jsonl"
        with filepath.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get_run_costs(self, run_id: str) -> dict:
        records: List[dict] = []
        if self._db is not None:
            try:
                cursor = self._db.execute(
                    "SELECT agent_name, model, prompt_tokens, completion_tokens, cost, stage_id, timestamp "
                    "FROM cost_tracking WHERE run_id = ? ORDER BY timestamp",
                    (run_id,),
                )
                rows = cursor.fetchall()
                records = [
                    {
                        "agent_name": r[0],
                        "model": r[1],
                        "prompt_tokens": r[2],
                        "completion_tokens": r[3],
                        "estimated_cost": r[4],
                        "stage_id": r[5],
                        "timestamp": r[6],
                    }
                    for r in rows
                ]
            except Exception:
                records = self._file_read_records(run_id)
        else:
            records = self._file_read_records(run_id)

        total_prompt = sum(r.get("prompt_tokens", 0) for r in records)
        total_completion = sum(r.get("completion_tokens", 0) for r in records)
        total_cost = sum(r.get("estimated_cost", 0.0) for r in records)

        return {
            "run_id": run_id,
            "records": records,
            "count": len(records),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "total_cost": round(total_cost, 8),
        }

    def _file_read_records(self, run_id: str) -> List[dict]:
        filepath = self._costs_dir / f"{run_id}.jsonl"
        if not filepath.exists():
            return []
        records = []
        with filepath.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    def get_summary(self, period: str = "daily", project_root: Optional[Path] = None) -> dict:
        root = project_root or self._project_root
        records: List[dict] = []

        if self._db is not None:
            try:
                date_filter = {
                    "daily": "date(timestamp) = date('now')",
                    "weekly": "date(timestamp) >= date('now', 'weekday 0', '-7 days')",
                    "monthly": "strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')",
                }.get(period, "date(timestamp) = date('now')")
                cursor = self._db.execute(
                    f"SELECT run_id, agent_name, model, prompt_tokens, completion_tokens, cost, stage_id, timestamp "
                    f"FROM cost_tracking WHERE {date_filter} ORDER BY timestamp"
                )
                rows = cursor.fetchall()
                records = [
                    {
                        "run_id": r[0],
                        "agent_name": r[1],
                        "model": r[2],
                        "prompt_tokens": r[3],
                        "completion_tokens": r[4],
                        "estimated_cost": r[5],
                        "stage_id": r[6],
                        "timestamp": r[7],
                    }
                    for r in rows
                ]
            except Exception:
                records = self._file_summary(root, period)
        else:
            records = self._file_summary(root, period)

        total_prompt = sum(r.get("prompt_tokens", 0) for r in records)
        total_completion = sum(r.get("completion_tokens", 0) for r in records)
        total_cost = sum(r.get("estimated_cost", 0.0) for r in records)
        runs = list({r["run_id"] for r in records})

        by_model: Dict[str, Dict[str, Any]] = {}
        for r in records:
            model = r.get("model", "unknown")
            if model not in by_model:
                by_model[model] = {"prompt_tokens": 0, "completion_tokens": 0, "estimated_cost": 0.0, "calls": 0}
            by_model[model]["prompt_tokens"] += r.get("prompt_tokens", 0)
            by_model[model]["completion_tokens"] += r.get("completion_tokens", 0)
            by_model[model]["estimated_cost"] += r.get("estimated_cost", 0.0)
            by_model[model]["calls"] += 1

        return {
            "period": period,
            "runs": sorted(runs),
            "run_count": len(runs),
            "total_calls": len(records),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "total_cost": round(total_cost, 8),
            "by_model": {
                m: {
                    "prompt_tokens": d["prompt_tokens"],
                    "completion_tokens": d["completion_tokens"],
                    "estimated_cost": round(d["estimated_cost"], 8),
                    "calls": d["calls"],
                }
                for m, d in by_model.items()
            },
        }

    def _file_summary(self, root: Path, period: str) -> List[dict]:
        costs_dir = root / ".ai" / "costs"
        if not costs_dir.exists():
            return []

        now = datetime.now(timezone.utc)
        if period == "weekly":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff = datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=timezone.utc)
            cutoff_ts = cutoff.timestamp() - (7 * 86400)
        elif period == "monthly":
            cutoff_ts = datetime(now.year, now.month, 1, tzinfo=timezone.utc).timestamp()
        else:
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff_ts = datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=timezone.utc).timestamp()

        records = []
        for filepath in costs_dir.glob("*.jsonl"):
            with filepath.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                        ts = datetime.fromisoformat(r.get("timestamp", ""))
                        if ts.timestamp() >= cutoff_ts:
                            records.append(r)
                    except (json.JSONDecodeError, ValueError):
                        continue
        return records
