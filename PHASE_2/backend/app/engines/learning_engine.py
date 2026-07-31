"""
EMIOS Stage 17a — LearningEngine (Phase 6a).

Compares predicted outcomes (Monte Carlo on-time probability, forecast
velocity) to actual outcomes when they're available, produces a Brier
score and a velocity-estimate bias, and feeds both into the process-level
CalibrationStore so future forecasts can be corrected. Since real outcomes
don't exist yet in this pipeline, `actual_outcome=None` is a fully
supported, non-error input -- the engine degrades gracefully to
"record created for future calibration" and still returns a valid
LearningRecord.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.domain.emios_models import ActualSprintOutcome, LearningRecord
from app.storage.calibration_store import CalibrationStore


class LearningEngine:
    """Stage 17a: one LearningRecord per pipeline episode, always returned,
    even with no outcome data."""

    def run(
        self,
        pipeline_result,
        actual_outcome: Optional[ActualSprintOutcome],
        team_id: str = "default",
    ) -> LearningRecord:
        forecast_prob = float(
            getattr(
                getattr(pipeline_result, "monte_carlo", None),
                "on_time_probability",
                0.5,
            )
            or 0.5
        )
        forecast_velocity = float(
            getattr(
                getattr(
                    getattr(pipeline_result, "metrics", None), "velocity_metrics", None
                ),
                "average_velocity",
                0.0,
            )
            or 0.0
        )

        if actual_outcome is not None and actual_outcome.actual_delay_days is not None:
            actual = 1.0 if actual_outcome.actual_delay_days <= 0 else 0.0
            brier_score = round((forecast_prob - actual) ** 2, 4)
            velocity_bias = (
                (actual_outcome.actual_velocity_hrs - forecast_velocity) / max(forecast_velocity, 1)
                if forecast_velocity > 0
                else 0.0
            )
            if brier_score < 0.05:
                note = f"Excellent calibration: Brier score {brier_score:.3f} (close to 0)."
            elif brier_score < 0.15:
                note = f"Good calibration: Brier score {brier_score:.3f}."
            else:
                note = (
                    f"Model {'over' if forecast_prob > actual else 'under'}estimated "
                    f"probability by {abs(forecast_prob - actual):.0%} "
                    f"(Brier score {brier_score:.3f})."
                )
        else:
            actual = None
            brier_score = None
            velocity_bias = 0.0
            note = "No outcome data yet — record created for future calibration."

        diagnosis_accuracy = (
            1.0 if actual_outcome and actual_outcome.diagnosis_confirmed is True else
            0.0 if actual_outcome and actual_outcome.diagnosis_confirmed is False else
            None
        )

        diagnosis = getattr(pipeline_result, "diagnosis", None)
        retained_pattern = None
        if diagnosis_accuracy == 1.0 and diagnosis:
            root_cause = getattr(diagnosis, "root_cause", None)
            if root_cause:
                retained_pattern = f"CONFIRMED: {root_cause[:200]}"

        prior_adjustment = 0.0
        if brier_score is not None and brier_score > 0.15:
            prior_adjustment = -0.05  # model was overconfident, lower BLOCKER prior
        elif brier_score is not None and brier_score < 0.05:
            prior_adjustment = 0.02  # model was well-calibrated, slight confidence boost

        _record_id = f"lr-{uuid4().hex[:10]}"
        record = LearningRecord(
            id=_record_id,
            episode_date=datetime.now(timezone.utc),
            forecast_probability=forecast_prob,
            actual_outcome=actual,
            brier_score=brier_score,
            diagnosis_accuracy=diagnosis_accuracy,
            velocity_estimate_bias=velocity_bias,
            calibration_note=note,
            retained_pattern=retained_pattern,
            recommended_prior_adjustment=prior_adjustment,
            # M1 fix: same ID for both fields
            record_id=_record_id,
            diagnosis_was_correct=(
                actual_outcome.diagnosis_confirmed if actual_outcome else None
            ),
        )

        CalibrationStore.update(team_id, record)
        return record
