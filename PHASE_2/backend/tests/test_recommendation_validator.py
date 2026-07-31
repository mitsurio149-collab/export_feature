from types import SimpleNamespace

from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    OpportunitySignal,
    Recommendation,
    RecommendationAction,
    SignalCategory,
    SignalSeverity,
)
from app.engines.recommendation_engine.recommendation_validator import RecommendationValidator


def test_validator_builds_recommendation_validation_payload() -> None:
    project_state = SimpleNamespace(
        work_items=[
            SimpleNamespace(item_id="WI-001", required_skill="Backend", status="In Progress")
        ],
        team=[
            SimpleNamespace(resource_id="R1", name="Meena", primary_skill="Backend", secondary_skill=None, daily_capacity_hrs=8.0),
            SimpleNamespace(resource_id="R2", name="Ravi", primary_skill="Backend", secondary_skill=None, daily_capacity_hrs=8.0),
        ],
        blockers=[],
        dependencies=[],
        project_info=SimpleNamespace(sprint_duration_days=10),
    )

    upstream = SimpleNamespace(
        forecast=SimpleNamespace(expected_delay_days=8.4),
        monte_carlo=SimpleNamespace(on_time_probability=0.68),
        metrics=SimpleNamespace(
            resource_metrics=SimpleNamespace(
                developer_metrics=[SimpleNamespace(resource_id="R2", remaining_effort_hours=20.0)]
            )
        ),
    )

    signal = OpportunitySignal(
        signal_id="sig-1",
        category=SignalCategory.CAPACITY,
        severity=SignalSeverity.MEDIUM,
        affected_item_ids=["WI-001"],
        affected_resource_ids=["R1"],
        affected_sprint_ids=[],
        affected_blocker_ids=[],
        evidence=[],
        context={"load_ratio": 1.38},
        detected_at="2026-06-30",
    )

    recommendation = Recommendation(
        recommendation_id="rec-001",
        title="Reassign WI-001 to Ravi",
        description="Reassign the item to a less loaded resource.",
        action_type=RecommendationAction.REASSIGN_ITEM,
        priority_score=0.91,
        confidence=ConfidenceLevel.HIGH,
        estimated_hours_recovered=12.0,
        estimated_delay_reduction_days=3.0,
        estimated_risk_reduction=0.23,
        affected_item_ids=["WI-001"],
        affected_resource_ids=["R1"],
        affected_sprint_ids=[],
        affected_blocker_ids=[],
        root_cause_signal_id="sig-1",
        metadata={"simulation_params": {"receiving_resource_id": "R2"}},
    )

    validator = RecommendationValidator(project_state, upstream, {signal.signal_id: signal})
    validation = validator._validate_one(recommendation, [])

    assert validation.recommendation_id == "rec-001"
    assert validation.delay_reduction_summary == "8.4d → 5.4d"
    assert validation.probability_improvement_summary == "68% → 91%"
    assert any("overloaded" in point.lower() for point in validation.why_selected)
    assert validation.confidence_label == ConfidenceLevel.HIGH
