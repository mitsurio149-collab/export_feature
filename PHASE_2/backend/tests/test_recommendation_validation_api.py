from app.api.models_phase3 import RecommendationSummary
from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    Recommendation,
    RecommendationAction,
    RecommendationValidation,
    TradeOff,
)
from app.api.routes.recommendations import _recommendation_to_summary
from app.engines.recommendation_engine.models import (
    BaselineMetrics,
    Recommendation,
    RecommendationAction,
    SimulatedMetrics,
    SimulationResult,
    ConfidenceLevel,
)


def test_recommendation_to_summary_includes_validation_payload() -> None:
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
        metadata={},
    )

    validation = RecommendationValidation(
        recommendation_id="rec-001",
        why_selected=["Meena is overloaded by 38%"],
        why_better_than_alternatives=["Recovers 2.3 more days"],
        rejected_alternatives=["Alternative A"],
        delay_reduction_summary="8.4d → 5.4d",
        probability_improvement_summary="68% → 91%",
        confidence_label=ConfidenceLevel.HIGH,
        confidence_reasoning="Based on direct staffing data.",
        trade_offs=[TradeOff(description="Uses extra context switching", severity="minor")],
        one_line_pitch="Reassign the item to Ravi — recovers 3.0 days.",
    )

    summary = _recommendation_to_summary(recommendation, validation=validation)

    assert isinstance(summary, RecommendationSummary)
    assert summary.validation is not None
    assert summary.validation.why_selected == ["Meena is overloaded by 38%"]
    assert summary.validation.confidence_label == "HIGH"


def test_recommendation_to_summary_includes_simulation_evidence() -> None:
    recommendation = Recommendation(
        recommendation_id="rec-002",
        title="Resolve blocker BLK-1",
        description="Resolve the blocker to recover schedule.",
        action_type=RecommendationAction.RESOLVE_BLOCKER,
        priority_score=0.85,
        confidence=ConfidenceLevel.MEDIUM,
        estimated_hours_recovered=20.0,
        estimated_delay_reduction_days=2.5,
        estimated_risk_reduction=12.0,
        affected_item_ids=["WI-2"],
        affected_resource_ids=[],
        affected_sprint_ids=["S1"],
        affected_blocker_ids=["BLK-1"],
        root_cause_signal_id="sig-2",
        metadata={},
    )

    baseline_metrics = BaselineMetrics(
        on_time_probability=0.35,
        expected_delay_days=10.0,
        overall_risk_score=68.0,
        schedule_risk=45.0,
        resource_risk=23.0,
        critical_path_hours=80.0,
    )
    simulated_metrics = SimulatedMetrics(
        on_time_probability=0.48,
        expected_delay_days=8.0,
        overall_risk_score=62.0,
        schedule_risk=40.0,
        resource_risk=22.0,
        critical_path_hours=72.0,
    )
    simulation_result = SimulationResult(
        recommendation_ids=["rec-002"],
        baseline_metrics=baseline_metrics,
        simulated_metrics=simulated_metrics,
        delta_on_time_probability=0.13,
        delta_expected_delay_days=2.0,
        delta_spillover_risk=0.0,
        delta_risk_score=6.0,
        delta_projected_velocity=0.0,
        seed_used=42,
        is_positive_impact=True,
        summary="Simulated blocker resolution improves probability and reduces delay.",
    )

    summary = _recommendation_to_summary(recommendation, simulation_result=simulation_result)
    assert summary.simulation_evidence is not None
    assert summary.simulation_evidence.baseline.on_time_probability == 0.35
    assert summary.simulation_evidence.simulated.expected_delay_days == 8.0
    assert summary.simulation_evidence.delta.on_time_probability == 0.13
    assert "blocker_penalty_hours" in summary.simulation_evidence.forecast_lever_names
