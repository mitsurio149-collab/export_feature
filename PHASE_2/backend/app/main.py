"""
Sprint Whisperer Backend Application

FastAPI application setup and route registration.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
import logging

from app.core.config import settings
from app.api.models import ApiResponse
from app.api.routes import upload_router
from app.api.routes import phase2
from app.api.routes import export as export_router
from app.api.routes import forecast
from app.api.routes import demo
from app.api.routes import monte_carlo
from app.api.routes import recommendations
from app.api.routes import recovery_plans
from app.api.routes.reforecast_comparison import router as reforecast_router
from app.api.routes import risk
from app.api.routes import scope_change
from app.ai.config import ai_settings
from app.ai.client import build_client
from app.ai.cache import InMemoryNarrativeCache
from app.ai.exceptions import AIClientError
from app.engines.narrative_service import NarrativeService
from app.api.routes.diagnosis import router as diagnosis_router
from app.api.routes.learning import router as learning_router
from app.api.routes.historical import router as historical_router
from app.api.routes.reasoning_trace import router as reasoning_trace_router
from app.api.routes.session_snapshot import router as session_snapshot_router
from app.api.routes.forecast_trend import router as forecast_trend_router
from app.api.routes.sprint_health import router as sprint_health_router


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""

    app = FastAPI(
        title="Sprint Whisperer",
        description="AI-Powered Sprint Forecasting & Recovery Platform",
        version="2.0.0",
    )

    # ─── Middleware ──────────────────────────────────────────────────────────

    allowed_origins = [settings.frontend_origin] if getattr(settings, "frontend_origin", None) else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── Routes ──────────────────────────────────────────────────────────────

    @app.get("/api/health")
    def health():
        """Health check endpoint."""
        return ApiResponse(
            success=True,
            message="Service is healthy",
            data={
                "status": "ok",
                "version": "2.0.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    # Register singleton AI advisor service
    ai_client = None
    if ai_settings.ai_advisor_enabled:
        try:
            ai_client = build_client(ai_settings)
        except AIClientError as exc:
            logging.warning(
                "AI client initialization failed; AI advisor will run in fallback mode: %s", exc
            )
            ai_client = None
    app.state.narrative_service = NarrativeService(
        client=ai_client,
        settings=ai_settings,
        cache=InMemoryNarrativeCache(),
    )

    # Register routers
    app.include_router(upload_router, prefix="/api", tags=["Upload"])
    app.include_router(phase2.router)
    app.include_router(export_router.router)
    app.include_router(forecast.router)
    app.include_router(monte_carlo.router)
    app.include_router(recommendations.router)
    app.include_router(recovery_plans.router)
    app.include_router(reforecast_router)
    app.include_router(risk.router)
    app.include_router(scope_change.router)
    app.include_router(demo.router)
    app.include_router(diagnosis_router)
    app.include_router(learning_router)
    app.include_router(historical_router)
    app.include_router(forecast_trend_router)
    app.include_router(reasoning_trace_router)   # Phase 3 — reasoning trace
    app.include_router(session_snapshot_router)     # Perf — single-call overview snapshot
    app.include_router(sprint_health_router)          # Sprint Health tab
    return app


# Create app instance
app = create_app()
