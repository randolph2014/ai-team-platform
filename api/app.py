from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from .runtime import event_store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app):
    """应用生命周期：启动时执行数据库迁移，关闭时释放连接池"""
    try:
        from persistence import run_migrations

        await run_migrations()
    except Exception:
        logger.exception("Database migration failed")
    yield
    try:
        from persistence import close_pool

        await close_pool()
    except Exception:
        logger.exception("Database pool shutdown failed")


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.event_store = event_store

    # ---- Auth routes (must be registered before auth-dependent routes) ----
    from .auth import auth_enabled, handle_login

    @app.get("/api/auth/status")
    def auth_status():
        return {"auth_enabled": auth_enabled()}

    @app.post("/api/auth/login")
    async def login(api_key: str):
        """Exchange an API key for a JWT access token."""
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
