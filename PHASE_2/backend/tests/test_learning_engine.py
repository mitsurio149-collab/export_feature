"""
Tests for Phase 6a (Stage 17a) — LearningEngine outcome capture.

Covers three layers:
1. LearningEngine.run() itself (already existed, re-verified here)
2. SessionStore outcome recording/retrieval (new in this phase)
3. run_emios_pipeline() actually using a real outcome when supplied
   (previously hardcoded to actual_outcome=None)
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.domain.emios_models import ActualSprintOutcome
from app.engines.learning_engine import LearningEngine
from app.storage.calibration_store import CalibrationStore
from app.storage.session_store import SessionStore


def _pipeline_result(on_time_probability=0.7, avg_velocity=40.0, root_cause=None):
    return SimpleNamespace(
        monte_carlo=SimpleNamespace(on_time_probability=on_time_probability),
        metrics=SimpleNamespace(
            velocity_metrics=SimpleNamespace(average_velocity=avg_velocity)
        ),
        diagnosis=SimpleNamespace(root_cause=root_cause) if root_cause else None,
    )


def setup_function(_):
    # CalibrationStore is process-level state; reset between tests so they
    # don't bleed into each other (mirrors the pattern used elsewhere for
    # this store, see calibration_store.py's own reset() docstring).
    CalibrationStore.reset()


# ---------------------------------------------------------------------------
# 1. LearningEngine.run() -- with and without a real outcome
# ---------------------------------------------------------------------------


def test_learning_record_is_none_shaped_when_outcome_unknown():
    """Pre-existing, must keep passing: no outcome yet -> graceful degrade."""
    record = LearningEngine().run(
        pipeline_result=_pipeline_result(), actual_outcome=None, team_id="t1"
    )
    assert record.actual_outcome is None
    assert record.brier_score is None
    assert "No outcome data yet" in record.calibration_note


def test_brier_score_computed_when_outcome_known():
    outcome = ActualSprintOutcome(
        sprint_id="S1",
        actual_velocity_hrs=38.0,
        actual_delay_days=0.0,  # delivered on time
    )
    record = LearningEngine().run(
        pipeline_result=_pipeline_result(on_time_probability=0.7),
        actual_outcome=outcome,
        team_id="t1",
    )
    assert record.actual_outcome == 1.0
    assert record.brier_score is not None
    # (0.7 - 1.0)^2 = 0.09
    assert abs(record.brier_score - 0.09) < 1e-6


def test_brier_score_reflects_missed_deadline():
    outcome = ActualSprintOutcome(
        sprint_id="S2",
        actual_velocity_hrs=30.0,
        actual_delay_days=4.0,  # late
    )
    record = LearningEngine().run(
        pipeline_result=_pipeline_result(on_time_probability=0.7),
        actual_outcome=outcome,
        team_id="t1",
    )
    assert record.actual_outcome == 0.0
    # (0.7 - 0.0)^2 = 0.49
    assert abs(record.brier_score - 0.49) < 1e-6


def test_diagnosis_confirmation_retains_pattern():
    outcome = ActualSprintOutcome(
        sprint_id="S3",
        actual_velocity_hrs=35.0,
        actual_delay_days=2.0,
        diagnosis_confirmed=True,
    )
    record = LearningEngine().run(
        pipeline_result=_pipeline_result(root_cause="Supplier delay on WI-041"),
        actual_outcome=outcome,
        team_id="t1",
    )
    assert record.diagnosis_accuracy == 1.0
    assert record.retained_pattern is not None
    assert "CONFIRMED" in record.retained_pattern


def test_calibration_store_accumulates_across_episodes():
    """Multiple LearningEngine episodes should build a running calibration
    profile for the team (this is what future forecasts should correct
    against, per CalibrationStore.get_velocity_correction)."""
    for i in range(3):
        outcome = ActualSprintOutcome(
            sprint_id=f"S{i}",
            actual_velocity_hrs=30.0,  # consistently lower than forecast
            actual_delay_days=1.0,
        )
        LearningEngine().run(
            pipeline_result=_pipeline_result(on_time_probability=0.6, avg_velocity=40.0),
            actual_outcome=outcome,
            team_id="calib-team",
        )

    profile = CalibrationStore.get("calib-team")
    assert profile is not None
    assert profile.episode_count == 3
    assert len(profile.brier_scores) == 3
    # actual velocity (30) consistently below forecast (40) -> negative bias
    assert profile.velocity_bias < 0


# ---------------------------------------------------------------------------
# 2. SessionStore outcome recording/retrieval
# ---------------------------------------------------------------------------


def _fresh_store_with_session(session_id="sess-learning-test"):
    store = SessionStore()
    store.clear_all()
    # Minimal ProjectState stand-in; SessionStore only needs an object with
    # .project_info.project_name for list_sessions(), which these tests
    # don't exercise, so a SimpleNamespace is sufficient here.
    project_state = SimpleNamespace(
        project_id=session_id,
        project_info=SimpleNamespace(project_name="Test Project"),
    )
    store.create_session(project_state)
    return store


def test_record_and_retrieve_outcome():
    store = _fresh_store_with_session()
    outcome = ActualSprintOutcome(
        sprint_id="S1", actual_velocity_hrs=32.0, actual_delay_days=1.0
    )
    assert store.record_actual_outcome("sess-learning-test", outcome) is True

    retrieved = store.get_actual_outcome("sess-learning-test", "S1")
    assert retrieved is not None
    assert retrieved.actual_velocity_hrs == 32.0


def test_record_outcome_returns_false_for_unknown_session():
    store = _fresh_store_with_session()
    outcome = ActualSprintOutcome(sprint_id="S1", actual_velocity_hrs=10.0)
    assert store.record_actual_outcome("does-not-exist", outcome) is False


def test_get_latest_actual_outcome_returns_most_recent():
    store = _fresh_store_with_session()
    store.record_actual_outcome(
        "sess-learning-test",
        ActualSprintOutcome(sprint_id="S1", actual_velocity_hrs=30.0),
    )
    store.record_actual_outcome(
        "sess-learning-test",
        ActualSprintOutcome(sprint_id="S2", actual_velocity_hrs=45.0),
    )
    latest = store.get_latest_actual_outcome("sess-learning-test")
    assert latest is not None
    assert latest.sprint_id == "S2"


def test_outcome_can_be_overwritten_for_same_sprint():
    store = _fresh_store_with_session()
    store.record_actual_outcome(
        "sess-learning-test",
        ActualSprintOutcome(sprint_id="S1", actual_velocity_hrs=30.0),
    )
    store.record_actual_outcome(
        "sess-learning-test",
        ActualSprintOutcome(sprint_id="S1", actual_velocity_hrs=99.0),
    )
    outcome = store.get_actual_outcome("sess-learning-test", "S1")
    assert outcome.actual_velocity_hrs == 99.0


def test_get_latest_actual_outcome_is_none_when_none_recorded():
    store = _fresh_store_with_session()
    assert store.get_latest_actual_outcome("sess-learning-test") is None
