"""
Historical Analysis API Route (Phase 6b — Stage 17b)

Endpoint:
- GET /api/historical-analysis?session_id=...  — Full HistoricalAnalysis object
"""

from fastapi import APIRouter, HTTPException, Query

from app.api.models import ApiResponse, ErrorCodes
from app.engines.historical_analyzer import HistoricalAnalyzer
from app.storage import store

router = APIRouter(prefix="/api", tags=["Historical Analysis"])


@router.get("/historical-analysis")
async def get_historical_analysis(
    session_id: str = Query(..., description="Session ID"),
) -> dict:
    """
    Analyse patterns across all sprints for this session: overbilling,
    spillover, recurring blockers, cascade chains, and concrete
    prevention recommendations grounded in that evidence.
    """
    try:
        session_id = session_id.strip()
        project_state = store.get_project_state(session_id)
        if not project_state:
            raise HTTPException(
                status_code=404,
                detail=ApiResponse(
                    success=False,
                    error_code=ErrorCodes.SESSION_NOT_FOUND,
                    message=f"Session {session_id} not found",
                ).model_dump(mode="json"),
            )

        analysis = HistoricalAnalyzer().run(state=project_state)

        return ApiResponse(
            success=True,
            data=analysis.model_dump(mode="json"),
            message="Historical analysis generated successfully",
        ).model_dump()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.INTERNAL_ERROR,
                message=f"Failed to generate historical analysis: {str(e)}",
            ).model_dump(mode="json"),
        )
