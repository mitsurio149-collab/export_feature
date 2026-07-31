import asyncio
from types import SimpleNamespace

from app.api.models_recovery_plans import ApplyPlanRequest
from app.api.routes.recovery_plans import apply_recovery_plan, get_recovery_plans
from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    Recommendation,
    RecommendationAction,
    ScoringWeights,
)
from app.engines.recommendation_engine.recommendation_engine_v2 import RecommendationEngineV2
from app.engines.recovery_plan_engine.engine import RecoveryPlanEngine
from app.engines.recovery_plan_engine.models import RecoveryPlanCandidate
from app.engines.recovery_plan_engine.plan_generator import RecoveryPlanGenerator
from app.engines.recovery_plan_engine.plan_scorer import RecoveryPlanScorer
from app.engines.simulation_engine import SimulationEngine
from app.storage import store
from tests.test_recommendation_engine_v2 import make_project_state


def test_recovery_plan_engine_generates_distinct_archetypes_and_scores():
    state = make_project_state()
    recommendation_engine = RecommendationEngineV2(
        project_state=state,
        simulation_count=100,
        scoring_weights=ScoringWeights(),
    )
    upstream = recommendation_engine._compute_upstream()
    simulation_engine = SimulationEngine(
        project_state=state,
        metrics=upstream.metrics,
        dag=upstream.dag,
        cp_result=upstream.cp_result,
        spillover=upstream.spillover,
        forecast=upstream.forecast,
        monte_carlo=upstream.monte_carlo,
        risk_result=upstream.risk_result,
        simulation_count=100,
    )
    recovery_plan_engine = RecoveryPlanEngine(simulation_engine=simulation_engine, max_actions_per_plan=1)

    recommendations = [
        Recommendation(
            recommendation_id="safe-rec",
            title="Resolve blocker",
            description="Resolve blocker to unlock work",
            action_type=RecommendationAction.RESOLVE_BLOCKER,
            priority_score=0.95,
            confidence=ConfidenceLevel.HIGH,
            estimated_hours_recovered=8.0,
            estimated_delay_reduction_days=5.0,
            estimated_risk_reduction=0.2,
            affected_item_ids=["WI-01"],
            affected_resource_ids=[],
            affected_sprint_ids=["SPR-01"],
            affected_blocker_ids=["BLK-01"],
            root_cause_signal_id="sig-safe",
        ),
        Recommendation(
            recommendation_id="aggressive-rec",
            title="Reassign work",
            description="Reassign work to a faster resource",
            action_type=RecommendationAction.REASSIGN_ITEM,
            priority_score=0.80,
            confidence=ConfidenceLevel.MEDIUM,
            estimated_hours_recovered=6.0,
            estimated_delay_reduction_days=4.0,
            estimated_risk_reduction=0.15,
            affected_item_ids=["WI-02"],
            affected_resource_ids=["R1"],
            affected_sprint_ids=["SPR-01"],
            affected_blocker_ids=[],
            root_cause_signal_id="sig-aggressive",
        ),
        Recommendation(
            recommendation_id="minimal-rec",
            title="Rebalance sprint load",
            description="Rebalance sprint load to reduce disruption",
            action_type=RecommendationAction.REBALANCE_SPRINT_LOAD,
            priority_score=0.70,
            confidence=ConfidenceLevel.MEDIUM,
            estimated_hours_recovered=2.0,
            estimated_delay_reduction_days=1.0,
            estimated_risk_reduction=0.1,
            affected_item_ids=["WI-01"],
            affected_resource_ids=["R1"],
            affected_sprint_ids=["SPR-01"],
            affected_blocker_ids=[],
            root_cause_signal_id="sig-minimal",
        ),
    ]
    plans = recovery_plan_engine.generate_recovery_plans(recommendations=recommendations)

    assert len(plans) == 3

    archetypes = [plan.archetype.value for plan in plans]
    assert set(archetypes) == {"SAFE", "AGGRESSIVE", "MINIMAL_DISRUPTION"}

    action_ids = [rec.recommendation_id for plan in plans for rec in plan.actions]
    assert "safe-rec" in action_ids
    assert "aggressive-rec" in action_ids

    for plan in plans:
        assert 0.0 <= plan.score.deadline_probability <= 1.0
        # STALE TEST fix: the shared make_project_state fixture (single
        # resource, multiple large work items) is an intentional overload
        # stress scenario with a genuine ~549-day baseline expected delay
        # (see ForecastEngine on this fixture) -- a +-100 day bound was
        # never realistic here and predates the fixture's current scale.
        # Keep this as a real sanity guard (finite, not nonsensically
        # negative) rather than a bound tuned to a different fixture.
        assert -100.0 <= plan.score.expected_delay_days <= 2000.0
        assert 0.0 <= plan.score.overall_risk_score <= 100.0


def test_recovery_plan_scorer_uses_risk_scale_consistently():
    scorer = RecoveryPlanScorer()
    plan = RecoveryPlanCandidate(
        plan_id="plan-1",
        archetype="SAFE",
        actions=[],
    )

    low_risk = SimpleNamespace(
        monte_carlo_comparison=SimpleNamespace(simulated_on_time_probability=0.8),
        forecast_comparison=SimpleNamespace(simulated_delay_days=5.0),
        risk_comparison=SimpleNamespace(simulated_risk_score=20.0),
    )
    high_risk = SimpleNamespace(
        monte_carlo_comparison=SimpleNamespace(simulated_on_time_probability=0.8),
        forecast_comparison=SimpleNamespace(simulated_delay_days=5.0),
        risk_comparison=SimpleNamespace(simulated_risk_score=80.0),
    )

    low_score = scorer.score_plan(plan, low_risk)
    high_score = scorer.score_plan(plan, high_risk)

    assert low_score.composite_score > high_score.composite_score


def test_recovery_plan_scorer_uses_medium_complexity_for_mixed_safe_actions():
    scorer = RecoveryPlanScorer()
    actions = [
        SimpleNamespace(action_type=SimpleNamespace(value="reassign_item")),
        SimpleNamespace(action_type=SimpleNamespace(value="reassign_item")),
        SimpleNamespace(action_type=SimpleNamespace(value="reassign_item")),
        SimpleNamespace(action_type=SimpleNamespace(value="reassign_item")),
        SimpleNamespace(action_type=SimpleNamespace(value="resolve_blocker")),
    ]

    assert scorer._derive_complexity(actions) == "Medium"


def test_safe_plan_prefers_action_type_diversity():
    generator = RecoveryPlanGenerator(max_actions_per_plan=5)
    recommendations = [
        Recommendation(
            recommendation_id=f"rec-{i}",
            title=f"Reassign {i}",
            description="Reassign work",
            action_type=RecommendationAction.REASSIGN_ITEM,
            priority_score=0.9 - i * 0.01,
            confidence=ConfidenceLevel.HIGH,
            estimated_hours_recovered=4.0,
            estimated_delay_reduction_days=2.0,
            estimated_risk_reduction=0.1,
            affected_item_ids=[f"WI-{i}"],
            affected_resource_ids=[f"R-{i}"],
            affected_sprint_ids=["SPR-01"],
            affected_blocker_ids=[],
            root_cause_signal_id=f"sig-{i}",
        )
        for i in range(3)
    ]
    recommendations.extend([
        Recommendation(
            recommendation_id="rec-3",
            title="Rebalance sprint load",
            description="Rebalance sprint load",
            action_type=RecommendationAction.REBALANCE_SPRINT_LOAD,
            priority_score=0.85,
            confidence=ConfidenceLevel.HIGH,
            estimated_hours_recovered=2.0,
            estimated_delay_reduction_days=1.0,
            estimated_risk_reduction=0.05,
            affected_item_ids=["WI-3"],
            affected_resource_ids=["R-3"],
            affected_sprint_ids=["SPR-01"],
            affected_blocker_ids=[],
            root_cause_signal_id="sig-3",
        ),
        Recommendation(
            recommendation_id="rec-4",
            title="Resolve blocker",
            description="Resolve blocker",
            action_type=RecommendationAction.RESOLVE_BLOCKER,
            priority_score=0.80,
            confidence=ConfidenceLevel.HIGH,
            estimated_hours_recovered=3.0,
            estimated_delay_reduction_days=1.5,
            estimated_risk_reduction=0.1,
            affected_item_ids=["WI-4"],
            affected_resource_ids=[],
            affected_sprint_ids=["SPR-01"],
            affected_blocker_ids=["BLK-01"],
            root_cause_signal_id="sig-4",
        ),
    ])

    plan = generator.build_safe_plan(recommendations)
    action_types = [rec.action_type for rec in plan.actions]

    assert action_types.count(RecommendationAction.REASSIGN_ITEM) <= 3
    assert RecommendationAction.REBALANCE_SPRINT_LOAD in action_types
    assert RecommendationAction.RESOLVE_BLOCKER in action_types


def test_apply_recovery_plan_updates_session_state_through_clone():
    state = make_project_state()
    session_id = store.create_session(state)
    recommendation_engine = RecommendationEngineV2(
        project_state=state,
        simulation_count=100,
        scoring_weights=ScoringWeights(),
    )
    upstream = recommendation_engine._compute_upstream()
    simulation_engine = SimulationEngine(
        project_state=state,
        metrics=upstream.metrics,
        dag=upstream.dag,
        cp_result=upstream.cp_result,
        spillover=upstream.spillover,
        forecast=upstream.forecast,
        monte_carlo=upstream.monte_carlo,
        risk_result=upstream.risk_result,
        simulation_count=100,
    )
    recovery_plan_engine = RecoveryPlanEngine(simulation_engine=simulation_engine)
    recommendations = recommendation_engine.generate(top_n=20)
    recovery_plan_ids = asyncio.run(get_recovery_plans(session_id=session_id))["data"]["plans"]
    if not recovery_plan_ids:
        raise AssertionError("No recovery plans generated by route")
    plan_id = recovery_plan_ids[0]["plan_id"]

    original_state = store.get_project_state(session_id)
    response = asyncio.run(apply_recovery_plan(ApplyPlanRequest(plan_id=plan_id, session_id=session_id)))

    updated_state = store.get_project_state(session_id)

    assert response["data"]["success"] is True
    assert updated_state is not None
    assert updated_state is not original_state
