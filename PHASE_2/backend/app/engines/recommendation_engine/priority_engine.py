from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.domain.models import ProjectState
from app.engines.recommendation_engine.models import (
    ImpactEstimate,
    Recommendation,
    RecommendationAction,
    RecommendationCandidate,
    ScoringWeights,
    SignalCategory,
    UpstreamEngineOutputs,
    ConfidenceLevel,
)
from app.engines.recommendation_engine.pm_decision_scorer import (
    PMDecisionScorer,
    classification_for,
)
from app.engines.recommendation_engine.pm_explanation_generator import PMExplanationGenerator
from app.engines.recommendation_engine.pm_models import PMIntelligence


# Actions whose primary value is long-term project health, not an immediately
# measurable schedule/risk delta.  Mirrors PREVENTIVE_ACTIONS in
# recommendation_engine_v2.py (the source of truth for near-zero-delta behaviour)
# plus additional zero-delta-by-design types from that module's _demote_zero_delta set.
_PREVENTIVE_ACTION_TYPES: frozenset = frozenset({
    RecommendationAction.CROSS_TRAIN_BACKUP,
    RecommendationAction.FREEZE_SCOPE_REQUEST,
    RecommendationAction.ESCALATE_BLOCKER_EARLY,
    RecommendationAction.INSERT_REVIEW_GATE,
    RecommendationAction.REBASELINE_ESTIMATE,
})


class PriorityEngine:
    def __init__(
        self,
        upstream: UpstreamEngineOutputs,
        project_state: Optional[ProjectState] = None,
        weights: Optional[ScoringWeights] = None,
    ) -> None:
        self.upstream = upstream
        self.weights = weights or ScoringWeights()
        self._pm_scorer = PMDecisionScorer(upstream)
        self._pm_explainer = PMExplanationGenerator(upstream, project_state)

    def score_and_rank(
        self,
        candidates: List[RecommendationCandidate],
        impact_estimates: Dict[str, ImpactEstimate],
    ) -> List[Recommendation]:
        ranked: List[Recommendation] = []
        for candidate in candidates:
            impact = impact_estimates.get(candidate.recommendation_id)
            if impact is None:
                continue
            legacy_score = self._score(candidate, impact)
            pm_score = self._pm_scorer.score(candidate, impact)
            # Blend: 60% PM multi-dimensional score + 40% legacy (schedule/risk/blocker)
            # This ensures existing tests that depend on score magnitudes remain stable
            # while strategic recs surface above pure delay-savers.
            blended_score = 0.60 * pm_score.composite + 0.40 * legacy_score
            priority_score = max(0.0, min(1.0, blended_score))

            # Build PM intelligence payload (explanation requires a Recommendation shell)
            _rec_shell = Recommendation(
                recommendation_id=candidate.recommendation_id,
                title=candidate.title,
                description=candidate.description,
                action_type=candidate.action_type,
                priority_score=priority_score,
                confidence=impact.confidence,
                estimated_hours_recovered=impact.estimated_hours_recovered,
                estimated_delay_reduction_days=impact.estimated_delay_reduction_days,
                estimated_risk_reduction=impact.estimated_risk_reduction,
                affected_item_ids=candidate.affected_item_ids,
                affected_resource_ids=candidate.affected_resource_ids,
                affected_sprint_ids=candidate.affected_sprint_ids,
                affected_blocker_ids=candidate.affected_blocker_ids,
                root_cause_signal_id=candidate.root_cause_signal_id,
                supporting_signal_ids=candidate.supporting_signal_ids,
                impact_evidence=impact.evidence,
                metadata={
                    "simulation_params": candidate.simulation_params,
                    "feasibility_checks": candidate.feasibility_checks,
                    "historical_pattern": self._historical_pattern_from_candidate(candidate),
                },
            )
            explanation = self._pm_explainer.explain(_rec_shell, impact)
            impact_profile = self._pm_explainer.build_impact_profile(
                _rec_shell, candidate, impact, explanation
            )
            pm_intelligence = PMIntelligence(
                classification=classification_for(candidate.action_type),
                pm_decision_score=pm_score,
                explanation=explanation,
                impact_profile=impact_profile,
                is_preventive=candidate.action_type in _PREVENTIVE_ACTION_TYPES,
            )
            _rec_shell.pm_intelligence = pm_intelligence
            ranked.append(_rec_shell)

        ranked.sort(key=lambda item: (-item.priority_score, item.recommendation_id))
        return ranked

    def _historical_pattern_from_candidate(self, candidate: RecommendationCandidate) -> Dict[str, Any] | None:
        signal_meta = candidate.simulation_params.get("historical_pattern")
        if isinstance(signal_meta, dict):
            return signal_meta
        return None

    def _score(self, candidate: RecommendationCandidate, impact: ImpactEstimate) -> float:
        # C3 fix: use continuous factors instead of binary 0/1
        # so high-severity, high-impact actions score proportionally higher.

        # Blocker factor: severity-weighted (Critical=1.0, High=0.7, Medium=0.4, Low=0.2)
        if RecommendationAction.RESOLVE_BLOCKER == candidate.action_type:
            _sev = str(candidate.simulation_params.get("blocker_severity", "Medium")) if candidate.simulation_params else "Medium"
            blocker_factor = {"Critical": 1.0, "CRITICAL": 1.0, "High": 0.7, "HIGH": 0.7,
                              "Medium": 0.4, "MEDIUM": 0.4, "Low": 0.2, "LOW": 0.2}.get(_sev, 0.4)
            # Scale up further for blockers affecting many items
            _impacted = len(candidate.affected_item_ids or []) + len(candidate.affected_blocker_ids or [])
            blocker_factor = min(1.0, blocker_factor * (1.0 + min(0.5, (_impacted - 1) * 0.1)))
        else:
            blocker_factor = 0.0

        # Schedule factor: proportional to estimated delay reduction (capped at 1.0 for >= 5 days)
        schedule_factor = min(1.0, max(0.0, impact.estimated_delay_reduction_days) / 5.0) if impact.estimated_delay_reduction_days > 0 else 0.0

        # CP factor: 1.0 if directly on critical path, 0.6 for related actions
        cp_factor = (1.0 if candidate.action_type in {RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT,
                                                        RecommendationAction.PARALLELIZE_ITEMS}
                     else 0.6 if candidate.action_type == RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK
                     else 0.0)

        # Capacity factor: proportional — skill mismatch fix scores higher than generic reassign
        capacity_factor = (0.9 if candidate.action_type == RecommendationAction.ADD_RESOURCE_SKILL
                          else 0.6 if candidate.action_type == RecommendationAction.REASSIGN_ITEM
                          else 0.0)

        risk_factor = min(1.0, impact.estimated_risk_reduction)

        hours_factor = min(1.0, impact.estimated_hours_recovered / max(1.0, self.upstream.forecast.remaining_effort_hours))

        overdue_days = candidate.simulation_params.get("overdue_days", 0) if candidate.simulation_params else 0
        sprint_duration = 14
        urgency_multiplier = 1.0 + min(0.5, overdue_days / sprint_duration)

        cascade_count = len(candidate.affected_item_ids) if candidate.action_type in {
            RecommendationAction.RESOLVE_BLOCKER,
            RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT,
            RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK,
        } else 0
        cascade_multiplier = 1.0 + min(0.3, cascade_count * 0.05)

        confidence_multiplier = {"HIGH": 1.1, "MEDIUM": 1.0, "LOW": 0.85}.get(
            impact.confidence.value if hasattr(impact.confidence, "value") else str(impact.confidence), 1.0
        )

        # Rebaseline estimate recommendations are primarily about forecast quality and uncertainty.
        # Grant them schedule weighting even when the current baseline delay is zero so they surface
        # in scenarios where improving estimate reliability is the main actionable signal.
        if candidate.action_type == RecommendationAction.REBASELINE_ESTIMATE:
            schedule_factor = 1.0

        base_score = (
            self.weights.w_risk * risk_factor
            + self.weights.w_schedule * schedule_factor
            + self.weights.w_blocker * blocker_factor
            + self.weights.w_cp * cp_factor
            + self.weights.w_capacity * capacity_factor
            + 0.1 * hours_factor
        )

        # Note: the special-case score floors for CROSS_TRAIN_BACKUP/SWARM_ITEM
        # (max 0.65) and SPOF signals (max 0.70) have been removed.
        # Long-term resilience and forecast improvement are now explicit weighted
        # terms in PMDecisionScorer, so these actions rank appropriately high
        # without ad-hoc floors that contradict the scorer's philosophy.

        if candidate.action_type == RecommendationAction.REBASELINE_ESTIMATE:
            base_score = max(base_score, 0.30)

        return base_score * urgency_multiplier * cascade_multiplier * confidence_multiplier
