"""pm_decision_scorer.py — Phase 2 PM Decision Intelligence Scorer.

Replaces the single delay-reduction ranking axis with a multi-dimensional
PMDecisionScore that reflects how an experienced Project Manager actually
prioritises.

Scoring philosophy
------------------
* Schedule benefit matters, but it is NOT the only axis.
* Risk mitigation, forecast reliability, resource health, and governance
  all count independently so that "zero-delay" recommendations can still
  rank high when they are strategically important.
* Implementation cost penalises the score, but gently — a high-cost action
  that removes a critical SPOF should still beat a zero-effort action that
  delivers no real value.

Weights (must sum to 1.0 excluding implementation_cost which is a penalty)
--------------------------------------------------------------------------
  schedule_benefit      : 0.15
  risk_reduction        : 0.20
  delivery_confidence   : 0.15
  resource_health       : 0.10
  governance_improvement: 0.10
  urgency               : 0.10
  forecast_improvement  : 0.10
  long_term_resilience  : 0.10
  (cost penalty)        : up to −0.10
"""
from __future__ import annotations

from typing import Optional

from app.engines.recommendation_engine.models import (
    ImpactEstimate,
    Recommendation,
    RecommendationAction,
    RecommendationCandidate,
    SignalCategory,
    SimulationResult,
    UpstreamEngineOutputs,
)
from app.engines.recommendation_engine.pm_models import (
    ImplementationEffort,
    PMDecisionScore,
    RecommendationClassification,
    RecommendationObjective,
    TriggerReason,
)


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
_W_SCHEDULE = 0.15
_W_RISK = 0.20
_W_CONFIDENCE = 0.15
_W_RESOURCE = 0.10
_W_GOVERNANCE = 0.10
_W_URGENCY = 0.10
_W_FORECAST = 0.10
_W_RESILIENCE = 0.10
_COST_MAX_PENALTY = 0.10   # max penalty for implementation cost

_ASSERT_SUM = abs(
    _W_SCHEDULE + _W_RISK + _W_CONFIDENCE + _W_RESOURCE
    + _W_GOVERNANCE + _W_URGENCY + _W_FORECAST + _W_RESILIENCE - 1.0
)
assert _ASSERT_SUM < 0.001, f"PM scorer weights must sum to 1.0, diff={_ASSERT_SUM}"


# ---------------------------------------------------------------------------
# Action → PM objective mapping
# ---------------------------------------------------------------------------
_ACTION_OBJECTIVE: dict[RecommendationAction, RecommendationObjective] = {
    RecommendationAction.RESOLVE_BLOCKER: RecommendationObjective.DELIVERY_CONFIDENCE,
    RecommendationAction.ESCALATE_BLOCKER_EARLY: RecommendationObjective.RISK_MITIGATION,
    RecommendationAction.REASSIGN_ITEM: RecommendationObjective.RESOURCE_OPTIMIZATION,
    RecommendationAction.REBALANCE_SPRINT_LOAD: RecommendationObjective.RESOURCE_OPTIMIZATION,
    RecommendationAction.ADD_RESOURCE_SKILL: RecommendationObjective.RESOURCE_OPTIMIZATION,
    RecommendationAction.SPLIT_ITEM: RecommendationObjective.SCHEDULE_OPTIMIZATION,
    RecommendationAction.SPLIT_AND_PAIR: RecommendationObjective.SCHEDULE_OPTIMIZATION,
    RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT: RecommendationObjective.SCHEDULE_OPTIMIZATION,
    RecommendationAction.PULL_FORWARD_ITEM: RecommendationObjective.SCHEDULE_OPTIMIZATION,
    RecommendationAction.PARALLELIZE_ITEMS: RecommendationObjective.SCHEDULE_OPTIMIZATION,
    RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM: RecommendationObjective.SCHEDULE_OPTIMIZATION,
    RecommendationAction.SWARM_ITEM: RecommendationObjective.SCHEDULE_OPTIMIZATION,
    RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK: RecommendationObjective.RISK_MITIGATION,
    RecommendationAction.REBASELINE_ESTIMATE: RecommendationObjective.FORECAST_RELIABILITY,
    RecommendationAction.APPLY_RAMP_UP_DISCOUNT: RecommendationObjective.FORECAST_RELIABILITY,
    RecommendationAction.CROSS_TRAIN_BACKUP: RecommendationObjective.KNOWLEDGE_RESILIENCE,
    RecommendationAction.PAIR_REVIEWER: RecommendationObjective.QUALITY_IMPROVEMENT,
    RecommendationAction.ASSIGN_AS_SECOND_REVIEWER: RecommendationObjective.QUALITY_IMPROVEMENT,
    RecommendationAction.INSERT_REVIEW_GATE: RecommendationObjective.DELIVERY_GOVERNANCE,
    RecommendationAction.FREEZE_SCOPE_REQUEST: RecommendationObjective.DELIVERY_GOVERNANCE,
}

# Action → classification
_ACTION_CLASSIFICATION: dict[RecommendationAction, RecommendationClassification] = {
    # Tactical — improves current sprint immediately
    RecommendationAction.RESOLVE_BLOCKER: RecommendationClassification.TACTICAL,
    RecommendationAction.REASSIGN_ITEM: RecommendationClassification.TACTICAL,
    RecommendationAction.SPLIT_ITEM: RecommendationClassification.TACTICAL,
    RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT: RecommendationClassification.TACTICAL,
    RecommendationAction.PARALLELIZE_ITEMS: RecommendationClassification.TACTICAL,
    RecommendationAction.PULL_FORWARD_ITEM: RecommendationClassification.TACTICAL,
    RecommendationAction.SWARM_ITEM: RecommendationClassification.TACTICAL,
    RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM: RecommendationClassification.TACTICAL,
    # Strategic — improves future delivery
    RecommendationAction.CROSS_TRAIN_BACKUP: RecommendationClassification.STRATEGIC,
    RecommendationAction.PAIR_REVIEWER: RecommendationClassification.STRATEGIC,
    RecommendationAction.ASSIGN_AS_SECOND_REVIEWER: RecommendationClassification.STRATEGIC,
    RecommendationAction.REBASELINE_ESTIMATE: RecommendationClassification.STRATEGIC,
    RecommendationAction.APPLY_RAMP_UP_DISCOUNT: RecommendationClassification.STRATEGIC,
    RecommendationAction.ADD_RESOURCE_SKILL: RecommendationClassification.STRATEGIC,
    # Hybrid — immediate + future benefit
    RecommendationAction.RESOLVE_BLOCKER: RecommendationClassification.HYBRID,  # overridden below
    RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK: RecommendationClassification.HYBRID,
    RecommendationAction.REBALANCE_SPRINT_LOAD: RecommendationClassification.HYBRID,
    RecommendationAction.FREEZE_SCOPE_REQUEST: RecommendationClassification.HYBRID,
    RecommendationAction.ESCALATE_BLOCKER_EARLY: RecommendationClassification.HYBRID,
    RecommendationAction.SPLIT_AND_PAIR: RecommendationClassification.HYBRID,
    RecommendationAction.INSERT_REVIEW_GATE: RecommendationClassification.HYBRID,
}

# Implementation effort map
_ACTION_EFFORT: dict[RecommendationAction, ImplementationEffort] = {
    RecommendationAction.RESOLVE_BLOCKER: ImplementationEffort.MEDIUM,
    RecommendationAction.ESCALATE_BLOCKER_EARLY: ImplementationEffort.LOW,
    RecommendationAction.REASSIGN_ITEM: ImplementationEffort.LOW,
    RecommendationAction.REBALANCE_SPRINT_LOAD: ImplementationEffort.LOW,
    RecommendationAction.SPLIT_ITEM: ImplementationEffort.LOW,
    RecommendationAction.SPLIT_AND_PAIR: ImplementationEffort.MEDIUM,
    RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT: ImplementationEffort.LOW,
    RecommendationAction.PULL_FORWARD_ITEM: ImplementationEffort.LOW,
    RecommendationAction.PARALLELIZE_ITEMS: ImplementationEffort.MEDIUM,
    RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM: ImplementationEffort.LOW,
    RecommendationAction.SWARM_ITEM: ImplementationEffort.MEDIUM,
    RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK: ImplementationEffort.HIGH,
    RecommendationAction.ADD_RESOURCE_SKILL: ImplementationEffort.HIGH,
    RecommendationAction.REBASELINE_ESTIMATE: ImplementationEffort.LOW,
    RecommendationAction.APPLY_RAMP_UP_DISCOUNT: ImplementationEffort.LOW,
    RecommendationAction.CROSS_TRAIN_BACKUP: ImplementationEffort.MEDIUM,
    RecommendationAction.PAIR_REVIEWER: ImplementationEffort.LOW,
    RecommendationAction.ASSIGN_AS_SECOND_REVIEWER: ImplementationEffort.LOW,
    RecommendationAction.INSERT_REVIEW_GATE: ImplementationEffort.LOW,
    RecommendationAction.FREEZE_SCOPE_REQUEST: ImplementationEffort.LOW,
}

_EFFORT_COST_SCORE: dict[ImplementationEffort, float] = {
    ImplementationEffort.LOW: 0.1,
    ImplementationEffort.MEDIUM: 0.5,
    ImplementationEffort.HIGH: 1.0,
}

# Signal category → trigger reason
_SIGNAL_TRIGGER: dict[SignalCategory, TriggerReason] = {
    SignalCategory.BLOCKER: TriggerReason.HIGH_BLOCKER_EXPOSURE,
    SignalCategory.CAPACITY: TriggerReason.RESOURCE_OVERLOAD,
    SignalCategory.SPRINT: TriggerReason.VELOCITY_DECLINE,
    SignalCategory.CRITICAL_PATH: TriggerReason.CRITICAL_PATH_DEPENDENCY,
    SignalCategory.SCHEDULE: TriggerReason.DELIVERY_RISK,
    SignalCategory.RISK: TriggerReason.DELIVERY_RISK,
    SignalCategory.SPILLOVER: TriggerReason.SPILLOVER_RISK,
    SignalCategory.DEPENDENCY: TriggerReason.CRITICAL_PATH_DEPENDENCY,
    SignalCategory.ESTIMATION_RELIABILITY: TriggerReason.ESTIMATION_DRIFT,
    SignalCategory.SPOF: TriggerReason.SINGLE_POINT_OF_FAILURE,
    SignalCategory.RECURRING_BLOCKER: TriggerReason.RECURRING_BLOCKER,
    SignalCategory.REWORK_LOOP: TriggerReason.REWORK_LOOP,
    SignalCategory.RAMP_UP: TriggerReason.LOW_FORECAST_CONFIDENCE,
    SignalCategory.RESEQUENCING: TriggerReason.CAPACITY_IMBALANCE,
    SignalCategory.SWARM_TRADEOFF: TriggerReason.CAPACITY_IMBALANCE,
}


# ---------------------------------------------------------------------------
# Helper lookups
# ---------------------------------------------------------------------------

def objective_for(action: RecommendationAction) -> RecommendationObjective:
    return _ACTION_OBJECTIVE.get(action, RecommendationObjective.RISK_MITIGATION)


def classification_for(action: RecommendationAction) -> RecommendationClassification:
    return _ACTION_CLASSIFICATION.get(action, RecommendationClassification.HYBRID)


def effort_for(action: RecommendationAction) -> ImplementationEffort:
    return _ACTION_EFFORT.get(action, ImplementationEffort.MEDIUM)


def trigger_for(signal_category: Optional[SignalCategory]) -> TriggerReason:
    if signal_category is None:
        return TriggerReason.DELIVERY_RISK
    return _SIGNAL_TRIGGER.get(signal_category, TriggerReason.DELIVERY_RISK)


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class PMDecisionScorer:
    """Compute a PMDecisionScore for a Recommendation.

    Inputs
    ------
    candidate   : the RecommendationCandidate (for action_type + signal context)
    impact      : ImpactEstimate from ImpactEstimator
    sim_result  : SimulationResult (optional — used when available)
    upstream    : UpstreamEngineOutputs (for normalisation baselines)
    """

    def __init__(self, upstream: UpstreamEngineOutputs) -> None:
        self.upstream = upstream
        self._remaining_effort = max(1.0, upstream.forecast.remaining_effort_hours)
        self._baseline_otp = getattr(upstream.monte_carlo, "on_time_probability", 0.5) or 0.5
        self._baseline_risk = getattr(upstream.risk_result, "overall_risk_score", 0.5) or 0.5

    def score(
        self,
        candidate: RecommendationCandidate,
        impact: ImpactEstimate,
        sim_result: Optional[SimulationResult] = None,
    ) -> PMDecisionScore:
        action = candidate.action_type
        effort = effort_for(action)

        # ---- Schedule benefit ----
        schedule_benefit = self._schedule_benefit(impact, sim_result)

        # ---- Risk reduction ----
        risk_reduction = self._risk_reduction(action, impact, sim_result)

        # ---- Delivery confidence ----
        delivery_confidence = self._delivery_confidence(action, impact, sim_result)

        # ---- Resource health ----
        resource_health = self._resource_health(action, candidate)

        # ---- Governance ----
        governance = self._governance(action)

        # ---- Urgency ----
        urgency = self._urgency(candidate)

        # ---- Forecast improvement ----
        forecast_improvement = self._forecast_improvement_factor(action, impact)

        # ---- Long-term resilience ----
        long_term_resilience = self._long_term_resilience_factor(action, candidate)

        # ---- Cost penalty ----
        cost = _EFFORT_COST_SCORE[effort]

        composite = (
            _W_SCHEDULE * schedule_benefit
            + _W_RISK * risk_reduction
            + _W_CONFIDENCE * delivery_confidence
            + _W_RESOURCE * resource_health
            + _W_GOVERNANCE * governance
            + _W_URGENCY * urgency
            + _W_FORECAST * forecast_improvement
            + _W_RESILIENCE * long_term_resilience
            - _COST_MAX_PENALTY * cost
        )
        composite = max(0.0, min(1.0, composite))

        return PMDecisionScore(
            schedule_benefit=round(schedule_benefit, 4),
            risk_reduction=round(risk_reduction, 4),
            delivery_confidence=round(delivery_confidence, 4),
            resource_health=round(resource_health, 4),
            governance_improvement=round(governance, 4),
            implementation_cost=round(cost, 4),
            urgency=round(urgency, 4),
            forecast_improvement=round(forecast_improvement, 4),
            long_term_resilience=round(long_term_resilience, 4),
            composite=round(composite, 4),
        )

    # ------------------------------------------------------------------
    # Sub-score helpers
    # ------------------------------------------------------------------

    def _schedule_benefit(
        self, impact: ImpactEstimate, sim: Optional[SimulationResult]
    ) -> float:
        """Normalised 0-1: max benefit = 5 days saved or 10% OTP gain."""
        delay_days = float(impact.estimated_delay_reduction_days or 0.0)
        otp_gain = 0.0
        if sim:
            otp_gain = float(getattr(sim, "delta_on_time_probability", 0.0) or 0.0)
        delay_score = min(1.0, delay_days / 5.0)
        otp_score = min(1.0, otp_gain / 0.10)
        return max(delay_score, otp_score)

    def _risk_reduction(
        self,
        action: RecommendationAction,
        impact: ImpactEstimate,
        sim: Optional[SimulationResult],
    ) -> float:
        base = min(1.0, float(impact.estimated_risk_reduction or 0.0))
        sim_risk = 0.0
        if sim:
            sim_risk = min(1.0, abs(float(getattr(sim, "delta_risk_score", 0.0) or 0.0)))
        # Blocker resolution and SPOF actions have inherently high risk reduction
        if action in {
            RecommendationAction.RESOLVE_BLOCKER,
            RecommendationAction.ESCALATE_BLOCKER_EARLY,
            RecommendationAction.CROSS_TRAIN_BACKUP,
            RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK,
        }:
            base = max(base, 0.60)
        return max(base, sim_risk)

    def _delivery_confidence(
        self,
        action: RecommendationAction,
        impact: ImpactEstimate,
        sim: Optional[SimulationResult],
    ) -> float:
        confidence_actions = {
            RecommendationAction.REBASELINE_ESTIMATE,
            RecommendationAction.APPLY_RAMP_UP_DISCOUNT,
            RecommendationAction.INSERT_REVIEW_GATE,
            RecommendationAction.RESOLVE_BLOCKER,
        }
        base = 0.4 if action in confidence_actions else 0.1
        if sim:
            otp_gain = float(getattr(sim, "delta_on_time_probability", 0.0) or 0.0)
            base = max(base, min(1.0, otp_gain / 0.10))
        return min(1.0, base)

    def _resource_health(
        self,
        action: RecommendationAction,
        candidate: RecommendationCandidate,
    ) -> float:
        resource_actions = {
            RecommendationAction.REASSIGN_ITEM,
            RecommendationAction.REBALANCE_SPRINT_LOAD,
            RecommendationAction.ADD_RESOURCE_SKILL,
            RecommendationAction.CROSS_TRAIN_BACKUP,
            RecommendationAction.SPLIT_AND_PAIR,
        }
        spof_signal = (
            candidate.simulation_params.get("signal_category") == SignalCategory.SPOF.value
            if candidate.simulation_params else False
        )
        if action == RecommendationAction.CROSS_TRAIN_BACKUP or spof_signal:
            return 0.85  # SPOF removal is high resource health value
        if action in resource_actions:
            n_resources = len(candidate.affected_resource_ids or [])
            return min(1.0, 0.50 + 0.10 * n_resources)
        return 0.05

    def _governance(self, action: RecommendationAction) -> float:
        governance_actions = {
            RecommendationAction.INSERT_REVIEW_GATE: 0.90,
            RecommendationAction.FREEZE_SCOPE_REQUEST: 0.80,
            RecommendationAction.ESCALATE_BLOCKER_EARLY: 0.70,
            RecommendationAction.PAIR_REVIEWER: 0.60,
            RecommendationAction.ASSIGN_AS_SECOND_REVIEWER: 0.55,
            RecommendationAction.REBASELINE_ESTIMATE: 0.50,
        }
        return governance_actions.get(action, 0.05)

    def _urgency(self, candidate: RecommendationCandidate) -> float:
        params = candidate.simulation_params or {}
        overdue_days = float(params.get("overdue_days", 0) or 0)
        sprint_duration = 14.0
        urgency = min(1.0, overdue_days / sprint_duration)
        # Blockers on critical path are always urgent
        if params.get("on_critical_path") or params.get("signal_category") == SignalCategory.BLOCKER.value:
            urgency = max(urgency, 0.70)
        # SPOF: medium-high urgency even when not yet overdue
        if params.get("signal_category") == SignalCategory.SPOF.value:
            urgency = max(urgency, 0.55)
        return urgency

    def _forecast_improvement_factor(
        self,
        action: RecommendationAction,
        impact: ImpactEstimate,
    ) -> float:
        """0-1: how much this action improves forecast accuracy/confidence.

        Uses ``ImpactEstimate.estimated_forecast_confidence_gain`` when populated
        (set by ImpactEstimator for REBASELINE_ESTIMATE and APPLY_RAMP_UP_DISCOUNT).
        For other actions the gain is 0.0 (no forecast reliability benefit).
        """
        return float(getattr(impact, "estimated_forecast_confidence_gain", 0.0) or 0.0)

    def _long_term_resilience_factor(
        self,
        action: RecommendationAction,
        candidate: RecommendationCandidate,
    ) -> float:
        """0-1: how much this action reduces SPOF / bus-factor exposure.

        CROSS_TRAIN_BACKUP directly adds a backup owner — highest resilience value.
        Any candidate triggered by a SPOF signal (signal_category == SPOF) carries
        meaningful resilience value even if the action type is different.
        All other actions return 0.0 so the term doesn't pollute unrelated scores.
        """
        is_spof_signal = (
            (candidate.simulation_params or {}).get("signal_category") == SignalCategory.SPOF.value
        )
        if action == RecommendationAction.CROSS_TRAIN_BACKUP:
            # Number of backup resources being trained boosts the resilience value;
            # each additional backup beyond the first adds 0.10 (cap at 1.0).
            n_backups = max(0, len(candidate.affected_resource_ids or []) - 1)
            return min(1.0, 0.80 + n_backups * 0.10)
        if is_spof_signal:
            # Action triggered by a SPOF signal — partial resilience credit.
            return 0.55
        return 0.0
