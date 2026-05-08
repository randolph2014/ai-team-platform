from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import List

from .runtime import event_store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app):
    from engine.production_guard import ProductionGuard, is_production_mode

    config = None
    _is_prod = is_production_mode()
    if _is_prod:
        try:
            from pathlib import Path
            from engine.config import load_config
            project_root = Path(os.environ.get("AI_TEAM_PROJECT_ROOT", os.getcwd()))
            loaded_config = load_config(project_root)
            config = loaded_config.config
        except Exception:
            logger.debug("Could not load config for production guard")

    guard = ProductionGuard(config=config)
    if guard.production:
        passed, errors, warnings = guard.check_all()
        for w in warnings:
            logger.warning("production guard warning: %s", w)
        if not passed:
            for e in errors:
                logger.error("production guard error: %s", e)
            raise RuntimeError(
                "Production guard checks failed:\n" + "\n".join(f"  - {e}" for e in errors)
            )

    from persistence import run_migrations

    if _is_prod:
        await run_migrations()
    else:
        try:
            await run_migrations()
        except Exception:
            logger.exception("Database migration failed")
    yield
    try:
        from persistence import close_pool

        await close_pool()
    except Exception:
        logger.exception("Database pool shutdown failed")


def _get_cors_origins() -> List[str]:
    raw = os.environ.get("AI_TEAM_CORS_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app():
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as exc:  # pragma: no cover - exercised in installed env.
        raise RuntimeError("FastAPI is not installed. Install project dependencies first.") from exc

    from .routes.artifacts import router as artifacts_router
    from .routes.config import router as config_router
    from .routes.costs import router as costs_router
    from .routes.eval import router as eval_router
    from .routes.pipelines import router as pipelines_router
    from .routes.runs import router as runs_router
    from .routes.settings import router as settings_router
    from .routes.webhooks import router as webhooks_router
    from .ws import router as ws_router

    app = FastAPI(title="AI Team Platform", version="0.1.0", lifespan=_lifespan)

    cors_origins = _get_cors_origins()
    allow_credentials = cors_origins != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.event_store = event_store

    from .auth import auth_enabled, handle_login
    from fastapi import Body

    @app.get("/api/auth/status")
    def auth_status():
        return {"auth_enabled": auth_enabled()}

    @app.post("/api/auth/login")
    async def login(api_key: str = Body(..., embed=True)):
        return await handle_login(api_key)

    # ---- Application routes ----
    app.include_router(runs_router, prefix="/api")
    app.include_router(artifacts_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(costs_router, prefix="/api")
    app.include_router(eval_router, prefix="/api")
    app.include_router(pipelines_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(webhooks_router, prefix="/api")
    app.include_router(ws_router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics():
        from engine.metrics import get_metrics_output

        body, content_type = get_metrics_output()
        from fastapi.responses import Response

        return Response(content=body, media_type=content_type)

    return app
