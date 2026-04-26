from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from .runtime import active_runs, event_store, run_projects

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
    from .routes.runs import router as runs_router
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
    app.state.active_runs = active_runs
    app.state.run_projects = run_projects
    app.include_router(runs_router, prefix="/api")
    app.include_router(artifacts_router, prefix="/api")
    app.include_router(ws_router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
