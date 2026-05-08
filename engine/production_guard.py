from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from engine.constants import DEFAULT_JWT_SECRET

logger = logging.getLogger(__name__)


def is_production_mode() -> bool:
    return os.environ.get("AI_TEAM_PRODUCTION", "").lower() in {"1", "true", "yes"}


class ProductionGuard:
    def __init__(
        self,
        *,
        production: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.production = production or is_production_mode()
        self.config = config or {}

    def check_all(self) -> Tuple[bool, List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []

        for check in (
            self._check_api_keys,
            self._check_jwt_secret,
            self._check_webhook_secret_key,
            self._check_cors_origins,
            self._check_database,
            self._check_redis,
            self._check_no_mock_runtime,
            self._check_quality_gates,
            self._check_worktree,
        ):
            result = check()
            if result is None:
                continue
            level, msg = result
            if level == "error":
                errors.append(msg)
            else:
                warnings.append(msg)

        return (len(errors) == 0, errors, warnings)

    def _check_api_keys(self) -> Optional[Tuple[str, str]]:
        if not self.production:
            return None
        raw = os.environ.get("AI_TEAM_API_KEYS", "").strip()
        if not raw:
            return ("error", "AI_TEAM_API_KEYS is not set")
        return None

    def _check_webhook_secret_key(self) -> Optional[Tuple[str, str]]:
        if not self.production:
            return None
        if not os.environ.get("AI_TEAM_WEBHOOK_SECRET_KEY", "").strip():
            return ("error", "AI_TEAM_WEBHOOK_SECRET_KEY is not set")
        return None

    def _check_jwt_secret(self) -> Optional[Tuple[str, str]]:
        secret = os.environ.get("AI_TEAM_JWT_SECRET", "").strip()
        if not secret:
            if self.production:
                return ("error", "AI_TEAM_JWT_SECRET is not set")
            return ("warning", "AI_TEAM_JWT_SECRET is not set, using default (insecure)")
        if secret == DEFAULT_JWT_SECRET:
            if self.production:
                return ("error", "AI_TEAM_JWT_SECRET is using the default value")
            return ("warning", "AI_TEAM_JWT_SECRET is using the default value (insecure)")
        return None

    def _check_cors_origins(self) -> Optional[Tuple[str, str]]:
        if not self.production:
            return None
        raw = os.environ.get("AI_TEAM_CORS_ORIGINS", "").strip()
        if not raw:
            return ("error", "AI_TEAM_CORS_ORIGINS is not set")
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if origins == ["*"]:
            return ("error", "AI_TEAM_CORS_ORIGINS must not be '*' in production")
        return None

    def _check_database(self) -> Optional[Tuple[str, str]]:
        if not self.production:
            return None
        db_url = os.environ.get("DATABASE_URL") or os.environ.get("AI_TEAM_DB_URL")
        if not db_url:
            return ("error", "DATABASE_URL is not set")
        try:
            from persistence.connection import is_available
            if not is_available():
                return ("error", "DATABASE_URL is set but database is not reachable")
        except Exception as exc:
            return ("error", f"Database check failed: {exc}")
        return None

    def _check_redis(self) -> Optional[Tuple[str, str]]:
        if not self.production:
            return None
        redis_url = os.environ.get("AI_TEAM_REDIS_URL", "").strip()
        if not redis_url:
            return ("error", "AI_TEAM_REDIS_URL is not set")
        try:
            from redis import Redis
            conn = Redis.from_url(redis_url)
            try:
                conn.ping()
            finally:
                conn.close()
        except Exception as exc:
            return ("error", f"Redis is not reachable: {exc}")
        return None

    def _check_no_mock_runtime(self) -> Optional[Tuple[str, str]]:
        if not self.production:
            return None
        runtimes = self.config.get("runtimes", {})
        for runtime_id, runtime in runtimes.items():
            if isinstance(runtime, dict) and runtime.get("cli") == "mock":
                return ("error", f"Runtime '{runtime_id}' uses mock CLI, forbidden in production")
        return None

    def _check_quality_gates(self) -> Optional[Tuple[str, str]]:
        if not self.production:
            return None
        gates = self.config.get("quality_gates", [])
        if not gates:
            return ("error", "quality_gates is empty, at least one gate is required in production")
        return None

    def _check_worktree(self) -> Optional[Tuple[str, str]]:
        if not self.production:
            return None
        worktree = self.config.get("worktree", {})
        if not worktree.get("enabled", True):
            return ("error", "worktree is disabled, must be enabled in production")
        return None
