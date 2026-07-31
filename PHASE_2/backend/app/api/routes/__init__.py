"""API routes package initialization."""

from app.api.routes.demo import router as demo_router
from app.api.routes.export import router as export_router
from app.api.routes.forecast import router as forecast_router
from app.api.routes.monte_carlo import router as monte_carlo_router
from app.api.routes.phase2 import router as phase2_router
from app.api.routes.recommendations import router as recommendations_router
from app.api.routes.risk import router as risk_router
from app.api.routes.scope_change import router as scope_change_router
from app.api.routes.upload import router as upload_router

__all__ = [
    "upload_router",
    "phase2_router",
    "forecast_router",
    "export_router",
    "monte_carlo_router",
    "risk_router",
    "recommendations_router",
    "scope_change_router",
    "demo_router",
]
