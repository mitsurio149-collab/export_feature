"""
EMIOS Pipeline — bridges Sprint Whisperer's 9 deterministic engines to the EMIOS
18-stage cognitive pipeline. Stages 1-11 are LIVE; 12-18 are stubs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.engines.metrics_engine import MetricsEngine, ProjectMetrics
from app.engines.dependency_engine import DependencyGraphEngine, DependencyDAG
from app.engines.critical_path_engine import CriticalPathEngine, CriticalPathResult
from app.engines.spillover_engine import SpilloverAnalysisEngine, SpilloverAnalysis
from app.engines.forecast_engine import ForecastEngine
from app.engines.monte_carlo_engine import MonteCarloEngine
from app.engines.impact_scoring_engine import ImpactScoringEngine
from app.engines.risk_engine import RiskEngine
from app.api.models_phase3 import ForecastResult, MonteCarloResult, RiskResult
from app.engines.recommendation_engine.recommendation_engine_v2 import RecommendationEngineV2
from app.engines.recommendation_engine.models import Recommendation, SimulationResult

from app.domain.models import ProjectState

from app.engines.observation_engine import ObservationEngine
from app.engines.validation_engine import ValidationEngine
from app.engines.evidence_collector import EvidenceCollector
from app.engines.hypothesis_generator import HypothesisGenerator
from app.engines.hypothesis_eliminator import HypothesisEliminator
from app.engines.root_cause_analyzer import RootCauseAnalyzer
from app.engines.impact_assessor import ImpactAssessor

from app.domain.emios_models import (
    ObservationCluster,
    ValidationResult,
    ArtifactType,
    EvidenceBundle,
    Hypothesis,
    Diagnosis,
    ImpactMatrix,
    Risk,
    TradeoffMatrix,
    Decision,
    ExecutionPlan,
    TrajectoryConformance,
    LearningRecord,
    HistoricalAnalysis,
    KnowledgeNode,
    ActualSprintOutcome,
)

MONTE_CARLO_SEED: int = 42
DEFAULT_SIMULATION_COUNT: int = 1000


@dataclass
class PipelineResult:
    metrics: Optional[ProjectMetrics] = None
    dependency_dag: Optional[DependencyDAG] = None
    critical_path: Optional[CriticalPathResult] = None
    spillover: Optional[SpilloverAnalysis] = None
    forecast: Optional[ForecastResult] = None
    monte_carlo: Optional[MonteCarloResult] = None
    risk_result: Optional[RiskResult] = None
    recommendations: Optional[List[Recommendation]] = None
    simulation: Optional[SimulationResult] = None
    risk_scores: Optional[object] = None  # RiskScores from ImpactScoringEngine

    observation_cluster: Optional[ObservationCluster] = None      # Stage 1
    validation_result: Optional[ValidationResult] = None          # Stage 2
    evidence_bundle: Optional[EvidenceBundle] = None              # Stage 3
    hypotheses: Optional[List[Hypothesis]] = None                # Stage 4
    surviving_hypotheses: Optional[List[Hypothesis]] = None      # Stage 5
    diagnosis: Optional[Diagnosis] = None                        # Stage 6
    impact_matrix: Optional[ImpactMatrix] = None                 # Stages 7-11
    risks: Optional[List[Risk]] = None                           # Stage 12
    tradeoff_matrix: Optional[TradeoffMatrix] = None             # Stage 13
    decision: Optional[Decision] = None                          # Stage 14
    execution_plan: Optional[ExecutionPlan] = None               # legacy, unused by Stage 15
    recovery_plans: Optional[list] = None                        # Stage 15 — List[RecoveryPlan] (dataclass, see recovery_plan_engine.models)
    trajectory_conformance: Optional[TrajectoryConformance] = None  # legacy, superseded by recovery_state_machine
    recovery_state_machine: Optional[object] = None               # Stage 16 — RecoveryStateMachineResult
    learning_record: Optional[LearningRecord] = None             # Stage 17
    historical_analysis: Optional[HistoricalAnalysis] = None     # Stage 17b (Phase 6b)
    knowledge_node: Optional[KnowledgeNode] = None               # Stage 18
    advisor_output: Optional[object] = None                       # Phase 7 — EMIOSAdvisorOutput


def _velocity_artifact_suppressed(validation: Optional[ValidationResult]) -> bool:
    if validation is None:
        return False
    for s in getattr(validation, "suppressed", []) or []:
        obs = getattr(s, "observation", None)
        metric = getattr(obs, "metric_ref", None)
        if metric == "velocity" and getattr(s, "artifact_type", None) == ArtifactType.PLANNED_CAPACITY_REDUCTION:
            return True
    return False


def _stage_01_observe(state, result):
    if result.metrics is None or result.forecast is None:
        return None
    return ObservationEngine().run(
        state=state,
        metrics=result.metrics,
        forecast=result.forecast,
        monte_carlo=result.monte_carlo,
        critical_path=result.critical_path,
    )


def _stage_02_validate(state, cluster):
    if cluster is None:
        return None
    return ValidationEngine().run(cluster=cluster, state=state)


def _stage_03_collect_evidence(state, validation, result):
    if validation is None:
        return None
    return EvidenceCollector().run(
        validation, state,
        forecast=result.forecast,
        risk_result=result.risk_result,
        metrics=result.metrics,
        monte_carlo=result.monte_carlo,
        critical_path=result.critical_path,
    )


def _stage_04_generate_hypotheses(bundle, state, result):
    if bundle is None:
        return None
    return HypothesisGenerator().run(
        bundle, state,
        forecast=result.forecast,
        metrics=result.metrics,
        monte_carlo=result.monte_carlo,
        critical_path=result.critical_path,
    )


def _stage_05_eliminate_hypotheses(hypotheses, bundle, state, result):
    if not hypotheses or bundle is None:
        return None
    return HypothesisEliminator().run(
        hypotheses, bundle, state,
        forecast=result.forecast,
        metrics=result.metrics,
        monte_carlo=result.monte_carlo,
        critical_path=result.critical_path,
        velocity_artifact_suppressed=_velocity_artifact_suppressed(result.validation_result),
    )


def _stage_06_root_cause(survivors, state, result):
    if not survivors:
        return None
    return RootCauseAnalyzer().run(
        survivors, state,
        forecast=result.forecast,
        metrics=result.metrics,
        monte_carlo=result.monte_carlo,
        critical_path=result.critical_path,
    )


def _stages_07_11_impact(state, diagnosis, result):
    if result.forecast is None:
        return None
    return ImpactAssessor().run(
        diagnosis, state,
        forecast=result.forecast,
        risk_result=result.risk_result,
        monte_carlo=result.monte_carlo,
        metrics=result.metrics,
        critical_path=result.critical_path,
        impact_scores=result.risk_scores,
    )


def _stage_12_assess_risk(impact, result): return None


def _stage_13_tradeoffs(
    state: ProjectState, result: PipelineResult
) -> Optional[TradeoffMatrix]:
    """Stage 13: project each option across five axes; surface the sacrifice."""
    from app.engines.tradeoff_analyzer import TradeoffAnalyzer

    recommendations = result.recommendations or []
    if not recommendations and not result.impact_matrix:
        return None

    return TradeoffAnalyzer().run(
        recommendations=recommendations,
        impact_matrix=result.impact_matrix,
        state=state,
        forecast=result.forecast,
        monte_carlo=result.monte_carlo,
    )


def _stage_14_decide(
    tradeoff_matrix, diagnosis, state: ProjectState, monte_carlo
):
    """Stage 14: MCDA-scored winner with an explicit, numeric rationale."""
    from app.engines.decision_engine import DecisionEngine

    if tradeoff_matrix is None:
        return None

    return DecisionEngine().run(
        tradeoff_matrix=tradeoff_matrix,
        diagnosis=diagnosis,
        state=state,
        monte_carlo=monte_carlo,
    )
def _stage_15_plan(state: ProjectState, result: PipelineResult):
    """Stage 15 — RecoveryPlanBuilder.

    Feeds the mature RecoveryPlanEngine this pipeline's already-computed
    upstream state.  Critically also passes:
      - critical_path_item_ids: so MINIMAL_DISRUPTION avoids CP items
      - resource_loads: so the generator knows which resources are overloaded
    Without these, all three archetypes collapse to the same rec set.
    """
    from app.engines.recovery_plan_engine import RecoveryPlanEngine
    from app.engines.simulation_engine import SimulationEngine

    recommendations = result.recommendations or []
    if not recommendations or result.metrics is None or result.forecast is None:
        return None

    # ── Extract critical path item IDs ────────────────────────────────────
    cp_item_ids: set = set()
    if result.critical_path is not None:
        cp_item_ids = set(
            getattr(result.critical_path, "items_on_critical_path", [])
            or getattr(result.critical_path, "critical_path_items", [])
            or getattr(result.critical_path, "critical_path", [])
        )

    # ── Extract resource load percentages from metrics ─────────────────────
    # resource_loads: {resource_id -> load_ratio} where >1.0 means overloaded.
    # MINIMAL_DISRUPTION uses this to avoid touching already-stressed resources.
    resource_loads: dict = {}
    try:
        dev_metrics = (
            result.metrics.resource_metrics.developer_metrics
            if result.metrics and hasattr(result.metrics, "resource_metrics")
            else []
        )
        for dm in (dev_metrics or []):
            rid = getattr(dm, "resource_id", None) or getattr(dm, "name", None)
            avail = getattr(dm, "availability_pct", 100.0) or 100.0
            alloc = getattr(dm, "allocation_pct", 0.0) or 0.0
            if rid:
                resource_loads[rid] = round(alloc / max(avail, 1.0), 3)
    except Exception:
        resource_loads = {}

    simulation_engine = SimulationEngine(
        project_state=state,
        metrics=result.metrics,
        dag=result.dependency_dag,
        cp_result=result.critical_path,
        spillover=result.spillover,
        forecast=result.forecast,
        monte_carlo=result.monte_carlo,
        risk_result=result.risk_result,
        simulation_count=1000,
    )
    recovery_plan_engine = RecoveryPlanEngine(simulation_engine=simulation_engine)

    return recovery_plan_engine.generate_recovery_plans(
        recommendations=recommendations,
        critical_path_item_ids=cp_item_ids if cp_item_ids else None,
        resource_loads=resource_loads if resource_loads else None,
    )


def _stage_16_monitor(plan, state): return None


def _stage_16_recovery_state(state: ProjectState, result: PipelineResult):
    """Stage 16 — RecoveryStateMachine (Phase 5).

    NOTE: constructs a fresh machine per pipeline run, matching the spec's
    literal wiring. Multi-run history/consecutive-healthy tracking across
    separate pipeline executions would need a session-scoped instance at
    the API layer -- out of scope for this stage.
    """
    from app.engines.recovery_engine import RecoveryStateMachine

    if result.monte_carlo is None:
        return None

    return RecoveryStateMachine().evaluate(
        monte_carlo=result.monte_carlo,
        risk_result=result.risk_result,
        recovery_plan_result=result.recovery_plans,
        previous_probability=None,
        state=state,
        metrics=result.metrics,
    )
def _stage_17_learn(conformance, decision): return None


def _stage_17a_learning(
    result: PipelineResult,
    actual_outcome: "Optional[ActualSprintOutcome]" = None,
    team_id: str = "default",
):
    """Stage 17a — LearningEngine (Phase 6a). actual_outcome is None on a
    fresh/in-progress sprint (the engine degrades gracefully in that case
    — see learning_engine.py docstring). Once a sprint closes, callers
    should pass the real ActualSprintOutcome (see
    SessionStore.get_actual_outcome / POST /api/learning/outcome)."""
    from app.engines.learning_engine import LearningEngine

    return LearningEngine().run(
        pipeline_result=result,
        actual_outcome=actual_outcome,
        team_id=team_id,
    )


def _stage_17b_historical(state: ProjectState):
    """Stage 17b — HistoricalAnalyzer (Phase 6b). Runs on every pipeline
    execution; does not depend on any other stage's output."""
    from app.engines.historical_analyzer import HistoricalAnalyzer

    return HistoricalAnalyzer().run(state=state)
def _stage_18_retain(learning): return None


def _stage_advisor(result: PipelineResult):
    """Phase 7 — EMIOSAdvisor. Runs the deterministic fallback path by
    default (see app/engines/emios_advisor.py for why the LLM path isn't
    wired to the shared client yet); always returns a fully-populated
    EMIOSAdvisorOutput, never None, so INVARIANT 7 (Final.2) always has
    something to check."""
    from app.engines.emios_advisor import EMIOSAdvisor
    from app.engines.emios_advisor_input_builder import build_emios_advisor_input

    advisor_input = build_emios_advisor_input(result)
    return EMIOSAdvisor().run(advisor_input)


def _enrich_learning_from_history(state: ProjectState, result: "PipelineResult") -> None:
    """
    Pre-populate the learning record with calibration signals from completed sprints.
    Compares planned vs actual velocity across all completed sprints to compute:
    - velocity_estimate_bias: how consistently the team over/under-delivers vs plan
    - A Brier-score proxy: average |planned_probability - 1.0| for completed sprints
      (completed sprints DID deliver, so actual=1.0 for each; planned=planned_velocity/cap)

    This gives the learning engine real signal even before explicit outcome tagging.
    """
    try:
        from datetime import datetime, timezone
        lr = result.learning_record
        if lr is None:
            return

        # Use state.actuals (SprintActual objects) which have both planned and actual hrs
        actuals = getattr(state, "actuals", []) or []
        actuals = [a for a in actuals if
                   float(getattr(a, "planned_effort_hrs", 0) or 0) > 0
                   and float(getattr(a, "actual_effort_hrs", 0) or 0) > 0]
        if not actuals:
            return

        # Compute velocity bias: (actual - planned) / planned per sprint, then average
        # Positive bias = team delivered MORE than planned (pessimistic estimates)
        # Negative bias = team delivered LESS than planned (over-optimistic estimates)
        biases = []
        brier_proxies = []
        for a in actuals:
            planned = float(a.planned_effort_hrs)
            actual_v = float(a.actual_effort_hrs)
            bias = (actual_v - planned) / planned
            biases.append(bias)
            # Brier proxy: how far was completion_rate from 1.0 (full delivery)?
            completion = float(getattr(a, "completion_rate", 1.0) or 1.0)
            brier_proxies.append((1.0 - min(1.0, completion)) ** 2)

        if biases:
            import statistics
            mean_bias = statistics.mean(biases)
            mean_brier = statistics.mean(brier_proxies)

            # Update the learning record fields that the CalibrationStore will use
            lr.velocity_estimate_bias = round(mean_bias, 4)
            lr.brier_score = round(mean_brier, 4)
            lr.calibration_note = (
                f"Auto-calibrated from {len(biases)} completed sprints: "
                f"velocity bias={round(mean_bias*100,1)}% "
                f"({'over-optimistic' if mean_bias < -0.05 else 'pessimistic' if mean_bias > 0.05 else 'well-calibrated'}), "
                f"Brier proxy={round(mean_brier, 3)}"
            )
            # Also push into CalibrationStore so MonteCarloEngine reads it next run
            try:
                from app.storage.calibration_store import CalibrationStore
                team_id = getattr(getattr(state, "project_info", None), "team_id", "default") or "default"
                for bias_val in biases:
                    CalibrationStore.record_episode(team_id, bias_val, 0.0, mean_brier)
            except Exception:
                pass
    except Exception:
        pass  # never crash the pipeline over learning enrichment


def run_emios_pipeline(
    state: ProjectState,
    *,
    simulation_count: int = DEFAULT_SIMULATION_COUNT,
    seed: int = MONTE_CARLO_SEED,
    actual_outcome: Optional[ActualSprintOutcome] = None,
    team_id: str = "default",
) -> PipelineResult:
    result = PipelineResult()

    result.metrics = MetricsEngine(state).calculate()
    result.dependency_dag = DependencyGraphEngine(state).build_dag()
    result.critical_path = CriticalPathEngine(state, result.dependency_dag).analyze()
    result.spillover = SpilloverAnalysisEngine(
        state, result.metrics.average_item_effort
    ).analyze()
    result.forecast = ForecastEngine(
        state, result.metrics, result.critical_path, result.spillover
    ).calculate()
    result.monte_carlo = MonteCarloEngine(
        project_state=state,
        metrics=result.metrics,
        cp_result=result.critical_path,
        spillover=result.spillover,
        simulation_count=simulation_count,
        seed=seed,
    ).calculate()

    # ── P95 guardrail ────────────────────────────────────────────────────────
    # The deterministic engine produces a single-point forecast grounded in
    # real project data (remaining effort, velocity, blocker impact, spillover).
    # The Monte Carlo P95 is the 95th-percentile tail across 10 000 simulations
    # of the same inputs — meaning only 5% of simulation outcomes finish later.
    # If the deterministic date exceeds P95, it has no new information beyond
    # what the simulations already modelled; it is an arithmetic artefact
    # (concurrent risks being double-counted as sequential).  Cap it here so
    # the two models agree on the outer bound and the UI never shows a
    # projected finish that is worse than the 1-in-20 worst-case scenario.
    try:
        _p95 = result.monte_carlo.p95_finish_date if result.monte_carlo else None
        if _p95 and result.forecast.expected_finish_date > _p95:
            # Rebuild only the two date fields that feed the UI; all other
            # forecast fields (velocity, effort, waterfall days) are unchanged.
            result.forecast = result.forecast.model_copy(update={
                "expected_finish_date": _p95,
                "expected_delay_days": float(round(
                    (result.forecast.expected_delay_days
                     - (result.forecast.expected_finish_date - _p95).days),
                    2,
                )),
            })
            # Mirror the cap into steering_brief so Steering Summary and
            # Delivery Outlook show the same date.
            if result.forecast.steering_brief:
                result.forecast = result.forecast.model_copy(update={
                    "steering_brief": result.forecast.steering_brief.model_copy(update={
                        "expected_finish_date": _p95,
                        "expected_delay_days": result.forecast.expected_delay_days,
                    })
                })
    except Exception:
        pass  # guardrail is advisory — never crash the pipeline

    impact_scores = ImpactScoringEngine(state, result.dependency_dag).score()
    result.risk_scores = impact_scores
    result.risk_result = RiskEngine(
        project_state=state,
        metrics=result.metrics,
        cp_result=result.critical_path,
        dag=result.dependency_dag,
        spillover=result.spillover,
        forecast=result.forecast,
        monte_carlo=result.monte_carlo,
        impact_scores=impact_scores,
    ).analyze()

    rec_engine = RecommendationEngineV2(
        project_state=state, simulation_count=simulation_count
    )
    # Widened from 10 -> 30: most "missing" recommendation types weren't a data
    # gap, they existed in the raw candidate pool but were cut before reaching
    # recovery plans, starving MINIMAL_DISRUPTION's already-narrow filters.
    result.recommendations = rec_engine.generate(top_n=30)
    if result.recommendations:
        try:
            result.simulation = rec_engine.simulate(
                result.recommendations[0].recommendation_id
            )
        except Exception:
            result.simulation = None

    # ===== EMIOS cognitive pipeline (Stages 1-11 LIVE) ======================
    result.observation_cluster = _stage_01_observe(state, result)
    result.validation_result = _stage_02_validate(state, result.observation_cluster)
    result.evidence_bundle = _stage_03_collect_evidence(state, result.validation_result, result)
    result.hypotheses = _stage_04_generate_hypotheses(result.evidence_bundle, state, result)
    result.surviving_hypotheses = _stage_05_eliminate_hypotheses(
        result.hypotheses, result.evidence_bundle, state, result
    )
    result.diagnosis = _stage_06_root_cause(result.surviving_hypotheses, state, result)
    result.impact_matrix = _stages_07_11_impact(state, result.diagnosis, result)

    result.risks = _stage_12_assess_risk(result.impact_matrix, result)
    result.tradeoff_matrix = _stage_13_tradeoffs(state, result)
    result.decision = _stage_14_decide(
        result.tradeoff_matrix, result.diagnosis, state, result.monte_carlo
    )
    result.recovery_plans = _stage_15_plan(state, result)
    result.trajectory_conformance = _stage_16_monitor(result.execution_plan, state)
    result.recovery_state_machine = _stage_16_recovery_state(state, result)
    result.historical_analysis = _stage_17b_historical(state)
    result.learning_record = _stage_17a_learning(result, actual_outcome=actual_outcome, team_id=team_id)
    result.knowledge_node = _stage_18_retain(result.learning_record)
    _enrich_learning_from_history(state, result)
    result.advisor_output = _stage_advisor(result)

    return result