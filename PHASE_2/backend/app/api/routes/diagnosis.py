"""Diagnosis API Route (PR 2)

Endpoint:
- GET /api/diagnosis

Runs signal detection + RootCauseClassifier independently of recommendation
generation. Diagnosis is a first-class output of the analysis pipeline,
not a side-effect of generate().
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.storage import store
from app.api.models import ApiResponse, ErrorCodes
from app.api.models_diagnosis import (
    DiagnosisResponse,
    RootCauseFindingResponse,
)
from app.engines.recommendation_engine.models import ScoringWeights
from app.engines.recommendation_engine.recommendation_engine_v2 import RecommendationEngineV2

router = APIRouter(prefix="/api", tags=["Diagnosis"])


def _get_engine(session_id: str) -> RecommendationEngineV2:
    """Retrieve or build the engine from the session store.

    Uses the session's cached upstream so no pipeline re-run happens.
    """
    analysis = store.get_analysis(session_id)
    if not analysis:
        raise HTTPException(
            status_code=404,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.SESSION_NOT_FOUND,
                message=f"Session {session_id} not found",
            ).model_dump(mode='json'),
        )
    engine = RecommendationEngineV2(
        project_state=analysis.project_state,
        simulation_count=1000,
        scoring_weights=ScoringWeights(),
    )
    engine._upstream = analysis.upstream
    return engine


@router.get("/diagnosis")
async def get_diagnosis(
    session_id: str = Query(..., description="Session ID"),
):
    """
    Returns the Phase-3 root cause diagnosis table.

    Calls engine.diagnose() — runs ONLY signal detection + RootCauseClassifier.
    Does NOT call generate() or produce recommendations. Diagnosis is independent.
    """
    try:
        session_id = session_id.strip()
        engine = _get_engine(session_id)

        # diagnose() runs signal detection + RootCauseClassifier only.
        # It never generates candidates, simulates, or ranks recommendations.
        rca = engine.diagnose()
        if rca is None:
            return ApiResponse(
                success=True,
                data=DiagnosisResponse(
                    session_id=session_id,
                    headline="No diagnosis available — signal detection has not run.",
                    primary_root_cause=None,
                    findings=[],
                ).model_dump(),
                message="Diagnosis unavailable",
            )

        findings = [
            RootCauseFindingResponse(
                category=f.category.value,
                root_cause=f.root_cause,
                impact=f.impact,
                observed=f.observed,
                signal_count=f.signal_count,
                max_severity=f.max_severity,
                contributing_signal_ids=list(f.contributing_signal_ids),
                sample_explanations=list(f.sample_explanations),
            )
            for f in rca.findings
        ]

        primary = None
        if rca.primary_root_cause is not None:
            p = rca.primary_root_cause
            primary = RootCauseFindingResponse(
                category=p.category.value,
                root_cause=p.root_cause,
                impact=p.impact,
                observed=p.observed,
                signal_count=p.signal_count,
                max_severity=p.max_severity,
                contributing_signal_ids=list(p.contributing_signal_ids),
                sample_explanations=list(p.sample_explanations),
            )

        response = DiagnosisResponse(
            session_id=session_id,
            headline=rca.headline,
            primary_root_cause=primary,
            findings=findings,
        )
        return ApiResponse(success=True, data=response.model_dump(), message="Diagnosis generated")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.INTERNAL_ERROR,
                message=f"Error generating diagnosis: {str(e)}",
            ).model_dump(mode='json'),
        )
