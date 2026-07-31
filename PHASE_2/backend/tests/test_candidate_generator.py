import re

from app.engines.metrics_engine import MetricsEngine
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.spillover_engine import SpilloverAnalysisEngine
from app.engines.forecast_engine import ForecastEngine
from app.engines.monte_carlo_engine import MonteCarloEngine
from app.engines.impact_scoring_engine import ImpactScoringEngine
from app.engines.risk_engine import RiskEngine
from app.engines.recommendation_engine.candidate_generator import CandidateGenerator
from app.engines.recommendation_engine.models import RecommendationAction, UpstreamEngineOutputs
from app.engines.recommendation_engine.signal_detectors import (
    BlockerDetector,
    CapacityDetector,
    CriticalPathDetector,
    ScheduleDetector,
    SprintDetector,
)
from tests.test_recommendation_engine import make_recommendation_project_state


def build_upstream(project_state):
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    forecast = ForecastEngine(project_state, metrics, cp, spill).calculate()
    monte_carlo = MonteCarloEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        spillover=spill,
        simulation_count=20,
        seed=42,
    ).calculate()
    impact_scores = ImpactScoringEngine(project_state, dag).score()
    risk_result = RiskEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        dag=dag,
        spillover=spill,
        forecast=forecast,
        monte_carlo=monte_carlo,
        impact_scores=impact_scores,
    ).analyze()
    return UpstreamEngineOutputs(
        metrics=metrics,
        dag=dag,
        cp_result=cp,
        spillover=spill,
        forecast=forecast,
        monte_carlo=monte_carlo,
        impact_scores=impact_scores,
        risk_result=risk_result,
    )


def test_candidate_generator_respects_v2_contract():
    project_state = make_recommendation_project_state()
    upstream = build_upstream(project_state)

    signals = []
    signals.extend(BlockerDetector(project_state, upstream.cp_result, upstream.dag, upstream.impact_scores).detect())
    signals.extend(CapacityDetector(project_state, upstream.metrics, upstream.cp_result, upstream.impact_scores).detect())
    signals.extend(SprintDetector(project_state, upstream.metrics, upstream.spillover, upstream.forecast).detect())
    signals.extend(CriticalPathDetector(project_state, upstream.cp_result, upstream.dag, upstream.impact_scores).detect())
    signals.extend(ScheduleDetector(project_state, upstream.forecast, upstream.monte_carlo, upstream.risk_result, upstream.metrics).detect())

    candidates = CandidateGenerator(project_state, upstream).generate(signals)

    assert all(candidate.action_type.value != "critical_path_optimization" for candidate in candidates)
    assert len(candidates) == len({candidate.recommendation_id for candidate in candidates})

    for candidate in candidates:
        if candidate.affected_resource_ids:
            assert "target_resource_id" in candidate.simulation_params
        assert candidate.title
        if candidate.action_type == RecommendationAction.RESOLVE_BLOCKER:
            assert any(blocker_id in candidate.title for blocker_id in candidate.affected_blocker_ids)
        else:
            assert re.search(r"\([^)]+\)$", candidate.title)
        assert candidate.feasibility_checks == {} or all(candidate.feasibility_checks.values())


def test_blocker_candidate_uses_blocker_context():
    project_state = make_recommendation_project_state()
    upstream = build_upstream(project_state)
    signals = BlockerDetector(project_state, upstream.cp_result, upstream.dag, upstream.impact_scores).detect()
    candidates = CandidateGenerator(project_state, upstream).generate(signals)

    blocker_candidates = [
        c for c in candidates if c.action_type == RecommendationAction.RESOLVE_BLOCKER
    ]
    assert blocker_candidates
    blocker_candidate = blocker_candidates[0]

    assert "BLK-01" in blocker_candidate.title
    assert "Environment issue blocking Python API deployment" in blocker_candidate.description
    # Owner is included in the title by CandidateGenerator
    assert "Owner: DevOps" in blocker_candidate.title
    assert "WI-02" in blocker_candidate.description
