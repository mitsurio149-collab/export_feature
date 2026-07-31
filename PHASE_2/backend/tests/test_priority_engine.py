from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    ImpactEstimate,
    RecommendationAction,
    RecommendationCandidate,
    ScoringWeights,
    UpstreamEngineOutputs,
)
from app.engines.recommendation_engine.priority_engine import PriorityEngine
from tests.test_candidate_generator import build_upstream
from tests.test_recommendation_engine import make_recommendation_project_state


def test_priority_engine_scores_and_ranks_deterministically():
    project_state = make_recommendation_project_state()
    upstream = build_upstream(project_state)
    engine = PriorityEngine(upstream)

    candidates = [
        RecommendationCandidate(
            recommendation_id="a",
            action_type=RecommendationAction.RESOLVE_BLOCKER,
            title="Resolve blocker (BLK-01)",
            description="Resolve blocker",
            affected_item_ids=["WI-02"],
            affected_resource_ids=[],
            affected_sprint_ids=["S1"],
            affected_blocker_ids=["BLK-01"],
            root_cause_signal_id="sig-1",
            supporting_signal_ids=["sig-1"],
            simulation_params={},
            feasibility_checks={},
        ),
        RecommendationCandidate(
            recommendation_id="b",
            action_type=RecommendationAction.REASSIGN_ITEM,
            title="Reassign item (WI-02)",
            description="Reassign item",
            affected_item_ids=["WI-02"],
            affected_resource_ids=["R1"],
            affected_sprint_ids=["S2"],
            affected_blocker_ids=[],
            root_cause_signal_id="sig-2",
            supporting_signal_ids=["sig-2"],
            simulation_params={"target_resource_id": "R1"},
            feasibility_checks={},
        ),
    ]

    impact_estimates = {
        "a": ImpactEstimate(
            estimated_hours_recovered=24.0,
            estimated_delay_reduction_days=2.0,
            estimated_risk_reduction=0.2,
            confidence=ConfidenceLevel.HIGH,
            evidence=[],
            calculation_notes="",
        ),
        "b": ImpactEstimate(
            estimated_hours_recovered=10.0,
            estimated_delay_reduction_days=0.0,
            estimated_risk_reduction=0.1,
            confidence=ConfidenceLevel.MEDIUM,
            evidence=[],
            calculation_notes="",
        ),
    }

    first_pass = engine.score_and_rank(candidates, impact_estimates)
    second_pass = engine.score_and_rank(candidates, impact_estimates)

    assert [item.recommendation_id for item in first_pass] == [item.recommendation_id for item in second_pass]
    assert first_pass[0].priority_score >= first_pass[1].priority_score
    assert 0.0 <= first_pass[0].priority_score <= 1.0
    assert 0.0 <= first_pass[1].priority_score <= 1.0


def test_priority_engine_gives_higher_score_to_overdue_candidates():
    project_state = make_recommendation_project_state()
    upstream = build_upstream(project_state)
    engine = PriorityEngine(upstream)

    base_impact = ImpactEstimate(
        estimated_hours_recovered=10.0,
        estimated_delay_reduction_days=1.0,
        estimated_risk_reduction=0.2,
        confidence=ConfidenceLevel.MEDIUM,
        evidence=[],
        calculation_notes="",
    )

    overdue_candidate = RecommendationCandidate(
        recommendation_id="overdue",
        action_type=RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT,
        title="Advance overdue",
        description="",
        affected_item_ids=["WI-02"],
        affected_resource_ids=[],
        affected_sprint_ids=[],
        affected_blocker_ids=[],
        root_cause_signal_id="",
        simulation_params={"overdue_days": 4},
        feasibility_checks={},
    )
    normal_candidate = RecommendationCandidate(
        recommendation_id="normal",
        action_type=RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT,
        title="Advance normal",
        description="",
        affected_item_ids=["WI-02"],
        affected_resource_ids=[],
        affected_sprint_ids=[],
        affected_blocker_ids=[],
        root_cause_signal_id="",
        simulation_params={"overdue_days": 0},
        feasibility_checks={},
    )

    overdue_score = engine._score(overdue_candidate, base_impact)
    normal_score = engine._score(normal_candidate, base_impact)

    assert overdue_score > normal_score


def test_priority_engine_gives_higher_score_to_high_confidence_candidates():
    project_state = make_recommendation_project_state()
    upstream = build_upstream(project_state)
    engine = PriorityEngine(upstream)

    impact = ImpactEstimate(
        estimated_hours_recovered=10.0,
        estimated_delay_reduction_days=1.0,
        estimated_risk_reduction=0.2,
        confidence=ConfidenceLevel.HIGH,
        evidence=[],
        calculation_notes="",
    )
    low_confidence_impact = ImpactEstimate(
        estimated_hours_recovered=10.0,
        estimated_delay_reduction_days=1.0,
        estimated_risk_reduction=0.2,
        confidence=ConfidenceLevel.LOW,
        evidence=[],
        calculation_notes="",
    )

    high_candidate = RecommendationCandidate(
        recommendation_id="high",
        action_type=RecommendationAction.REASSIGN_ITEM,
        title="Reassign high",
        description="",
        affected_item_ids=["WI-02"],
        affected_resource_ids=["R1"],
        affected_sprint_ids=[],
        affected_blocker_ids=[],
        root_cause_signal_id="",
        simulation_params={},
        feasibility_checks={},
    )
    low_candidate = RecommendationCandidate(
        recommendation_id="low",
        action_type=RecommendationAction.REASSIGN_ITEM,
        title="Reassign low",
        description="",
        affected_item_ids=["WI-02"],
        affected_resource_ids=["R1"],
        affected_sprint_ids=[],
        affected_blocker_ids=[],
        root_cause_signal_id="",
        simulation_params={},
        feasibility_checks={},
    )

    high_score = engine._score(high_candidate, impact)
    low_score = engine._score(low_candidate, low_confidence_impact)

    assert high_score > low_score


def test_priority_engine_gives_higher_score_to_cascade_candidates():
    project_state = make_recommendation_project_state()
    upstream = build_upstream(project_state)
    engine = PriorityEngine(upstream)

    impact = ImpactEstimate(
        estimated_hours_recovered=10.0,
        estimated_delay_reduction_days=1.0,
        estimated_risk_reduction=0.2,
        confidence=ConfidenceLevel.MEDIUM,
        evidence=[],
        calculation_notes="",
    )

    broad_candidate = RecommendationCandidate(
        recommendation_id="broad",
        action_type=RecommendationAction.RESOLVE_BLOCKER,
        title="Resolve broad blocker",
        description="",
        affected_item_ids=["WI-02", "WI-03"],
        affected_resource_ids=[],
        affected_sprint_ids=[],
        affected_blocker_ids=["BLK-01"],
        root_cause_signal_id="",
        simulation_params={},
        feasibility_checks={},
    )
    narrow_candidate = RecommendationCandidate(
        recommendation_id="narrow",
        action_type=RecommendationAction.RESOLVE_BLOCKER,
        title="Resolve narrow blocker",
        description="",
        affected_item_ids=["WI-02"],
        affected_resource_ids=[],
        affected_sprint_ids=[],
        affected_blocker_ids=["BLK-01"],
        root_cause_signal_id="",
        simulation_params={},
        feasibility_checks={},
    )

    broad_score = engine._score(broad_candidate, impact)
    narrow_score = engine._score(narrow_candidate, impact)

    assert broad_score > narrow_score


def test_scoring_weights_must_sum_to_one():
    try:
        ScoringWeights(w_risk=0.2, w_schedule=0.2, w_blocker=0.2, w_cp=0.2, w_capacity=0.1)
    except ValueError:
        return
    raise AssertionError("Expected ValueError for invalid weights")
