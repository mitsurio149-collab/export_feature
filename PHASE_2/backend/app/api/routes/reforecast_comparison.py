"""
Reforecast Comparison API Route

GET /api/reforecast-comparison

Returns a side-by-side snapshot of three scenarios:
  baseline    – numbers from the original session ProjectAnalysis (the pre-any-action truth)
  current     – numbers from the current (post-apply) ProjectAnalysis
  after_rec   – result of the last simulate-recommendation call (stored on session)

After a recovery plan is applied, `current` reflects the post-plan state and
`baseline` still reflects the pre-plan state, so the delta column is always
"what did this plan actually buy us?" not "what does today look like?".

Additionally exposes `delta_from_last_action` — the improvement since the most
recently applied recovery plan — so a PM who applies multiple plans in sequence
can see each step's marginal contribution.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, Dict, Any

from app.api.models import ApiResponse, ErrorCodes
from app.storage import store

router = APIRouter(prefix="/api", tags=["Reforecast"])


def _snapshot_from_analysis(analysis) -> Dict[str, Any]:
    """Extract the standard comparison snapshot from a ProjectAnalysis."""
    mc = analysis.monte_carlo
    forecast = analysis.forecast
    risk = analysis.risk_result

    p50 = mc.most_likely_finish_date.isoformat() if mc.most_likely_finish_date else None
    p80 = mc.p80_finish_date.isoformat() if mc.p80_finish_date else None
    p95 = mc.p95_finish_date.isoformat() if mc.p95_finish_date else None
    target = mc.target_end_date.isoformat() if mc.target_end_date else None

    return {
        "on_time_probability": round(mc.on_time_probability * 100, 1),
        "on_time_risk_level": (
            mc.on_time_risk_level.value
            if hasattr(mc.on_time_risk_level, "value")
            else str(mc.on_time_risk_level)
        ),
        "expected_delay_days": round(forecast.expected_delay_days, 1),
        "overall_risk_score": round(risk.overall_risk_score, 1),
        "p50_date": p50,
        "p80_date": p80,
        "p95_date": p95,
        "target_end_date": target,
    }


def _deltas(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Compute signed improvement deltas between two snapshots."""
    prob_delta  = round(after["on_time_probability"]  - before["on_time_probability"],  1)
    delay_delta = round(before["expected_delay_days"] - after["expected_delay_days"],   1)
    risk_delta  = round(before["overall_risk_score"]  - after["overall_risk_score"],    1)
    return {
        "probability_gain_pct":  prob_delta,
        "days_saved":            delay_delta,
        "risk_score_reduction":  risk_delta,
        "has_improvement":       prob_delta > 0 or delay_delta > 0,
    }


@router.get("/reforecast-comparison")
async def get_reforecast_comparison(
    session_id: str = Query(..., description="Session ID"),
):
    """Return side-by-side baseline / current / post-recommendation snapshots."""
    try:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail=ApiResponse(
                    success=False,
                    error_code=ErrorCodes.SESSION_NOT_FOUND,
                    message=f"Session {session_id} not found",
                ).model_dump(),
            )

        # Current analysis reflects the live (possibly post-apply) project state.
        current_analysis = store.get_analysis(session_id)
        current = _snapshot_from_analysis(current_analysis)

        # Baseline is the pre-any-action snapshot stored at session creation.
        # Falls back to current if no baseline has been captured yet.
        baseline_snapshot = getattr(session, "baseline_snapshot", None)
        baseline = baseline_snapshot if baseline_snapshot is not None else current.copy()

        # Post-single-recommendation simulation result (from POST /recommendations/simulate).
        after_rec_raw = getattr(session, "last_simulation_result", None)
        if after_rec_raw:
            after_rec = {
                "on_time_probability": round(
                    float(after_rec_raw.get("after_probability",
                          after_rec_raw.get("baseline_probability", 0))) * 100, 1,
                ),
                "on_time_risk_level": "IMPROVED",
                "expected_delay_days": round(
                    float(after_rec_raw.get("after_delay_days",
                          after_rec_raw.get("baseline_delay_days", 0))), 1,
                ),
                "overall_risk_score": round(
                    float(after_rec_raw.get("after_risk_score",
                          after_rec_raw.get("baseline_risk_score", 0))), 1,
                ),
                "p50_date": current.get("p50_date"),
                "p80_date": current.get("p80_date"),
                "p95_date": current.get("p95_date"),
                "target_end_date": current.get("target_end_date"),
                "recommendation_id": after_rec_raw.get("recommendation_id"),
                "summary": after_rec_raw.get("summary", ""),
            }
        else:
            after_rec = {**current, "on_time_risk_level": "NO_SIMULATION_YET"}

        # delta_from_baseline: total improvement since session start
        delta_from_baseline = _deltas(baseline, current)

        # delta_from_last_action: improvement since the most recently applied recovery plan.
        # `pre_apply_snapshot` is written by the apply route before it mutates state.
        pre_apply_snapshot = getattr(session, "pre_apply_snapshot", None)
        delta_from_last_action = (
            _deltas(pre_apply_snapshot, current)
            if pre_apply_snapshot is not None
            else None
        )

        # delta for single-rec simulation vs baseline
        delta_single_rec = _deltas(baseline, after_rec)

        hasSimulation = after_rec.get("on_time_risk_level") != "NO_SIMULATION_YET"

        data = {
            "session_id": session_id,
            "project_name": session.project_state.project_info.project_name,
            "baseline": baseline,
            "current": current,
            "after_recommendation": after_rec,
            # "deltas" is what the frontend reads for the top summary strip.
            # It shows single-rec simulation vs baseline when a simulation exists,
            # or cumulative vs baseline otherwise (e.g. after a recovery plan apply).
            "deltas": delta_single_rec if hasSimulation else delta_from_baseline,
            # Full set for richer clients
            "delta_from_baseline": delta_from_baseline,
            "delta_from_last_action": delta_from_last_action,
            "delta_single_rec": delta_single_rec,
            "plan_applied": pre_apply_snapshot is not None,
            "applied_plan_id": getattr(session, "applied_plan_id", None),
        }

        return ApiResponse(success=True, data=data, message="Reforecast comparison generated")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.PROCESSING_ERROR,
                message=f"Error generating reforecast comparison: {str(e)}",
            ).model_dump(),
        )
