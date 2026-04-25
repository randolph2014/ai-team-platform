from __future__ import annotations

from .runtime import active_runs, event_store, run_projects


def create_app():
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as exc:  # pragma: no cover - exercised in installed env.
        raise RuntimeError("FastAPI is not installed. Install project dependencies first.") from exc

    from .routes.artifacts import router as artifacts_router
    from .routes.runs import router as runs_router
    from .ws import router as ws_router

    app = FastAPI(title="AI Team Platform", version="0.1.0")
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
