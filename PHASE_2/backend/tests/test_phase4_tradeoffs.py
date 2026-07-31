"""
tests/test_phase4_tradeoffs.py

Integration tests for Phase 4 Stage 13: TradeoffAnalyzer.
Gate: pytest tests/test_phase4_tradeoffs.py -v — all pass.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.engines.tradeoff_analyzer import TradeoffAnalyzer
from app.engines.recommendation_engine.models import (
    Recommendation,
    RecommendationAction,
    ConfidenceLevel,
)
from app.domain.emios_models import ImpactMatrix, ImpactEstimate, ImpactDimension


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _utcnow():
    return datetime.now(timezone.utc)


def _make_rec(
    action: RecommendationAction,
    *,
    delay_days: float = 5.0,
    title: str = "Test recommendation",
    rec_id: str = "rec-001",
    blocker_ids: list | None = None,
) -> Recommendation:
    return Recommendation(
        recommendation_id=rec_id,
        title=title,
        description="Test description",
        action_type=action,
        priority_score=0.8,
        confidence=ConfidenceLevel.HIGH,
        estimated_hours_recovered=40.0,
        estimated_delay_reduction_days=delay_days,
        estimated_risk_reduction=0.3,
        affected_item_ids=["WI-01"],
        affected_resource_ids=["R-Meena"],
        affected_sprint_ids=["Sprint-5"],
        affected_blocker_ids=blocker_ids or [],
        root_cause_signal_id="sig-001",
    )


def _make_impact_matrix() -> ImpactMatrix:
    return ImpactMatrix(
        diagnosis_id="diag-001",
        estimates={
            "schedule": ImpactEstimate(
                dimension=ImpactDimension.SCHEDULE,
                magnitude=10.0,
                unit="days",
                confidence=0.8,
                explanation="10 days delay",
            ),
            "quality": ImpactEstimate(
                dimension=ImpactDimension.QUALITY,
                magnitude=3.0,
                unit="score",
                confidence=0.7,
                explanation="Quality degradation",
            ),
            "business": ImpactEstimate(
                dimension=ImpactDimension.BUSINESS,
                magnitude=5.0,
                unit="score",
                confidence=0.6,
                explanation="Business impact",
            ),
        },
    )


def _make_state() -> SimpleNamespace:
    blocker = SimpleNamespace(
        blocker_id="BLK-01",
        description="Hardware procurement delayed",
        owner="Meena",
        estimated_delay_days=15,
        status="Open",
    )
    project_info = SimpleNamespace(sprint_duration_days=14)
    return SimpleNamespace(
        project_info=project_info,
        blockers=[blocker],
        work_items=[],
        resources=[],
        team=[],
        sprints=[],
        dependencies=[],
        actuals=[],
    )


def _make_forecast(delay: float = 12.0) -> SimpleNamespace:
    return SimpleNamespace(expected_delay_days=delay)


def _make_monte_carlo(otp: float = 0.35) -> SimpleNamespace:
    return SimpleNamespace(
        on_time_probability=otp,
        p80_completion_date=_utcnow() + timedelta(days=60),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_null_option_always_present():
    """Null option must be present even with zero recommendations."""
    analyzer = TradeoffAnalyzer()
    matrix = analyzer.run(
        recommendations=[],
        impact_matrix=_make_impact_matrix(),
        state=_make_state(),
        forecast=_make_forecast(),
        monte_carlo=_make_monte_carlo(),
    )
    assert matrix.null_option is not None
    assert matrix.null_option.recommendation_id is None
    assert matrix.null_option.label == "Do nothing"
    assert matrix.null_option in matrix.options


def test_null_option_has_negative_net_ev():
    """Null option must always have negative net_expected_value
    when there is measurable delay/impact."""
    analyzer = TradeoffAnalyzer()
    matrix = analyzer.run(
        recommendations=[],
        impact_matrix=_make_impact_matrix(),
        state=_make_state(),
        forecast=_make_forecast(delay=12.0),
        monte_carlo=_make_monte_carlo(),
    )
    assert matrix.null_option.net_expected_value < 0


def test_dominated_options_computed_correctly():
    """An option with lower NEV and equal/higher disruption is dominated."""
    rec_weak = _make_rec(
        RecommendationAction.FREEZE_SCOPE_REQUEST,
        delay_days=1.0,
        title="Weak scope freeze",
        rec_id="rec-weak",
    )
    rec_strong = _make_rec(
        RecommendationAction.PARALLELIZE_ITEMS,
        delay_days=8.0,
        title="Strong parallelize",
        rec_id="rec-strong",
    )

    analyzer = TradeoffAnalyzer()
    matrix = analyzer.run(
        recommendations=[rec_weak, rec_strong],
        impact_matrix=_make_impact_matrix(),
        state=_make_state(),
        forecast=_make_forecast(),
        monte_carlo=_make_monte_carlo(),
    )

    # rec_weak: gains={SCHEDULE:1, RESOURCE:2} - sacrifices={BUSINESS:4} = NEV -1
    # HIGH disruption, not reversible.
    # rec_strong: gains={SCHEDULE:8} - sacrifices={QUALITY:1.5, ORGANIZATIONAL:1} = NEV 5.5
    # LOW disruption.
    # rec_strong dominates rec_weak (higher NEV, lower disruption)
    assert "rec-weak" in matrix.dominated_options
    assert "rec-strong" not in matrix.dominated_options


def test_resolve_blocker_gains_schedule():
    """RESOLVE_BLOCKER action must produce SCHEDULE gain from delay days."""
    rec = _make_rec(
        RecommendationAction.RESOLVE_BLOCKER,
        delay_days=7.0,
        title="Resolve HW blocker",
        blocker_ids=["BLK-01"],
    )

    analyzer = TradeoffAnalyzer()
    matrix = analyzer.run(
        recommendations=[rec],
        impact_matrix=_make_impact_matrix(),
        state=_make_state(),
        forecast=_make_forecast(),
        monte_carlo=_make_monte_carlo(),
    )

    opt = [o for o in matrix.options if o.recommendation_id is not None][0]
    assert "SCHEDULE" in opt.gains
    assert opt.gains["SCHEDULE"] == 7.0
    assert opt.disruption_level == "MEDIUM"
    assert opt.reversible is True
    assert "RESOURCE" in opt.sacrifices


def test_add_resource_flags_brooks_risk_in_statement():
    """ADD_RESOURCE_SKILL action must mention Brooks risk in sacrifice_statement."""
    rec = _make_rec(
        RecommendationAction.ADD_RESOURCE_SKILL,
        delay_days=4.0,
        title="Add AUTOSAR specialist",
    )

    analyzer = TradeoffAnalyzer()
    matrix = analyzer.run(
        recommendations=[rec],
        impact_matrix=_make_impact_matrix(),
        state=_make_state(),
        forecast=_make_forecast(),
        monte_carlo=_make_monte_carlo(),
    )

    opt = [o for o in matrix.options if o.recommendation_id is not None][0]
    assert "Brooks" in opt.sacrifice_statement
    assert opt.disruption_level == "HIGH"
    assert "ORGANIZATIONAL" in opt.sacrifices


def test_reduce_scope_is_not_reversible():
    """FREEZE_SCOPE_REQUEST (reduce scope) must be flagged as not reversible."""
    rec = _make_rec(
        RecommendationAction.FREEZE_SCOPE_REQUEST,
        delay_days=6.0,
        title="Defer low-priority features",
    )

    analyzer = TradeoffAnalyzer()
    matrix = analyzer.run(
        recommendations=[rec],
        impact_matrix=_make_impact_matrix(),
        state=_make_state(),
        forecast=_make_forecast(),
        monte_carlo=_make_monte_carlo(),
    )

    opt = [o for o in matrix.options if o.recommendation_id is not None][0]
    assert opt.reversible is False
    assert opt.disruption_level == "HIGH"
    assert "BUSINESS" in opt.sacrifices
    assert "stakeholder" in opt.sacrifice_statement.lower()
