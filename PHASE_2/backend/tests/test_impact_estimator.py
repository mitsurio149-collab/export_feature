from app.engines.recommendation_engine.candidate_generator import CandidateGenerator
from app.engines.recommendation_engine.impact_estimator import ImpactEstimator
from app.engines.recommendation_engine.models import ConfidenceLevel, RecommendationAction, RecommendationCandidate, UpstreamEngineOutputs
from tests.test_candidate_generator import build_upstream
from tests.test_recommendation_engine import make_recommendation_project_state


def test_impact_estimator_respects_engine_backed_contract():
    project_state = make_recommendation_project_state()
    upstream = build_upstream(project_state)

    candidate = RecommendationCandidate(
        recommendation_id="demo",
        action_type=RecommendationAction.REASSIGN_ITEM,
        title="Reassign item (WI-02)",
        description="Reassign the blocked item",
        affected_item_ids=["WI-02"],
        affected_resource_ids=["R1"],
        affected_sprint_ids=["S2"],
        affected_blocker_ids=["BLK-01"],
        root_cause_signal_id="sig-1",
        supporting_signal_ids=["sig-1"],
        simulation_params={"target_resource_id": "R1", "target_item_id": "WI-02"},
        feasibility_checks={"resource_exists": True, "has_capacity": True},
    )

    estimate = ImpactEstimator(project_state, upstream).estimate(candidate)

    assert estimate.estimated_hours_recovered >= 0.0
    assert estimate.estimated_hours_recovered <= upstream.forecast.remaining_effort_hours
    assert estimate.estimated_delay_reduction_days >= 0.0
    assert all(getattr(ev, "source_engine", None) for ev in estimate.evidence)
    assert all(ev.source_engine in {"MetricsEngine", "ForecastEngine", "CriticalPathEngine", "RiskEngine", "MonteCarloEngine", "SpilloverAnalysisEngine"} for ev in estimate.evidence)


def test_reassign_estimate_clamps_zero_source_rate_to_zero_delay():
    project_state = make_recommendation_project_state()
    upstream = build_upstream(project_state)

    candidate = RecommendationCandidate(
        recommendation_id="demo-zero-rate",
        action_type=RecommendationAction.REASSIGN_ITEM,
        title="Reassign item (WI-02)",
        description="Reassign the blocked item",
        affected_item_ids=["WI-02"],
        affected_resource_ids=["R2", "R1"],
        affected_sprint_ids=["S2"],
        affected_blocker_ids=["BLK-01"],
        root_cause_signal_id="sig-2",
        supporting_signal_ids=["sig-2"],
        simulation_params={"target_resource_id": "R1", "target_item_id": "WI-02"},
        feasibility_checks={"resource_exists": True, "has_capacity": True},
    )

    estimate = ImpactEstimator(project_state, upstream).estimate(candidate)

    assert estimate.estimated_delay_reduction_days == 0.0
    assert estimate.confidence == ConfidenceLevel.LOW
    assert "insufficient history" in estimate.calculation_notes
