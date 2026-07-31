"""
Phase 3 Forecast API Route

GET /forecast - deterministic single-point forecast + PMO KPI suite

Reads from the session-level ProjectAnalysis (computed once per session)
so the forecast numbers are always consistent with recommendations,
risk, and Monte Carlo — they all share the same engine outputs.

PMOKpiEngine is run here (not in ProjectAnalysis.build) because it is a
pure consumer of already-computed engine outputs — it never feeds back into
other engines, so there is no ordering constraint that would require it to
live inside the core pipeline. Keeping it here also means adding new KPIs
never risks destabilising the core pipeline's fixed execution order.
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from app.storage import store
from app.api.models import ApiResponse, ErrorCodes
from app.api.models_phase3 import ForecastResponse
from app.engines.pmo_kpi_engine import PMOKpiEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Phase3"])


@router.get("/forecast")
async def get_forecast(session_id: str = Query(..., description="Session ID")):
    """Return the deterministic forecast + PMO KPI suite for the session."""
    try:
        analysis = store.get_analysis(session_id)
        if not analysis:
            raise HTTPException(
                status_code=404,
                detail=ApiResponse(
                    success=False,
                    error_code=ErrorCodes.SESSION_NOT_FOUND,
                    message=f"Session {session_id} not found",
                ).model_dump(),
            )

        # Compute PMO KPIs from already-computed engine outputs.
        # Isolated try/except: a KPI computation failure must never suppress
        # the forecast itself — the dashboard degrades gracefully (pmo_kpi=null)
        # rather than returning a 500 that hides a valid forecast.
        pmo_kpi = None
        try:
            pmo_kpi = PMOKpiEngine(
                project_state=analysis.project_state,
                metrics=analysis.metrics,
                forecast_result=analysis.forecast,
                cp_result=analysis.cp_result,
            ).calculate()
        except Exception as kpi_exc:
            logger.warning(
                "PMOKpiEngine failed for session %s — pmo_kpi will be null in response: %s",
                session_id,
                kpi_exc,
                exc_info=True,
            )

        response = ForecastResponse(
            session_id=session_id,
            project_name=analysis.project_state.project_info.project_name,
            forecast=analysis.forecast,
            pmo_kpi=pmo_kpi,
        )

        return ApiResponse(
            success=True,
            data=response.model_dump(),
            message="Forecast generated",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.PROCESSING_ERROR,
                message=f"Error calculating forecast: {str(e)}",
            ).model_dump(),
        )
