"""
Learning outcome route — Phase 6a.

Allows a sprint to be marked delivered on-time or late after the fact,
giving the LearningEngine ground truth for Brier-score calibration.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.api.models import ApiResponse
from app.storage.session_store import store          # singleton is `store`, not `session_store`

router = APIRouter(prefix="/api/learning", tags=["Learning"])


class OutcomePayload(BaseModel):
    session_id: str
    sprint_id: str
    actual_on_time: bool


@router.post("/outcome")
def record_outcome(payload: OutcomePayload):
    """Record actual sprint delivery outcome for learning calibration."""
    session = store.get_session(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    pipeline_result = store.get_pipeline_result(payload.session_id)

    # Attach the outcome to the session's learning_record if it exists
    if pipeline_result is not None:
        lr = getattr(pipeline_result, "learning_record", None)
        if lr is not None:
            # LearningRecord uses `actual_outcome` as a float (1.0=on time, 0.0=late)
            actual_float = 1.0 if payload.actual_on_time else 0.0

            if hasattr(lr, "actual_outcome"):
                lr.actual_outcome = actual_float

            # Recompute Brier score if forecast_probability is present
            if hasattr(lr, "forecast_probability") and lr.forecast_probability is not None:
                pred = float(lr.forecast_probability)
                lr.brier_score = round((pred - actual_float) ** 2, 6)

        # Persist the updated pipeline_result back onto the session
        store.set_pipeline_result(payload.session_id, pipeline_result)

    return ApiResponse(
        success=True,
        message="Outcome recorded",
        data={
            "session_id": payload.session_id,
            "sprint_id": payload.sprint_id,
            "actual_on_time": payload.actual_on_time,
        },
    )


@router.get("/status")
def learning_status(session_id: str = Query(...)):
    """Return learning record status for a session."""
    pipeline_result = store.get_pipeline_result(session_id)
    if pipeline_result is None:
        raise HTTPException(status_code=404, detail="Session not found or pipeline not yet run")

    lr = getattr(pipeline_result, "learning_record", None)
    if lr is None:
        return ApiResponse(
            success=True,
            message="No learning record",
            data={"learning_record": None},
        )

    data = {}
    for field in ("forecast_probability", "actual_outcome", "brier_score",
                  "calibration_note", "diagnosis_accuracy", "velocity_estimate_bias"):
        data[field] = getattr(lr, field, None)

    return ApiResponse(
        success=True,
        message="Learning record retrieved",
        data={"learning_record": data},
    )
