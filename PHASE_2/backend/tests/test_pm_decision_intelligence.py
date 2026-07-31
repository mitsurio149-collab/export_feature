"""tests/test_pm_decision_intelligence.py

Unit and regression tests for the Phase 2 PM Decision Intelligence refactor.

Verifies:
- PMDecisionScore is computed with all required dimensions
- Strategic recommendations (cross_train, review gate, freeze scope, etc.)
  score above 0.0 even when delay_reduction_days == 0
- Classification (Tactical/Strategic/Hybrid) is assigned correctly
- PMExplanation answers all 5 PM questions with non-empty strings
- pm_intelligence is attached to every Recommendation produced by PriorityEngine
- Diversity reranking does not exceed max_per_objective per PM objective
- Existing Recommendation.to_api_dict() remains backward compatible
- pm_intelligence.to_dict() is present in to_api_dict() output
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    ImpactEstimate,
    Recommendation,
    RecommendationAction,
    RecommendationCandidate,
    SignalCategory,
    SignalEvidence,
    ScoringWeights,
    UpstreamEngineOutputs,
    stable_id,
)
from app.engines.recommendation_engine.pm_decision_scorer import (
    PMDecisionScorer,
    classification_for,
    effort_for,
    objective_for,
    trigger_for,
)
from app.engines.recommendation_engine.pm_explanation_generator import PMExplanationGenerator
from app.engines.recommendation_engine.pm_models import (
    ImplementationEffort,
    PMDecisionScore,
    PMIntelligence,
    RecommendationClassification,
    RecommendationObjective,
)
from app.engines.recommendation_engine.priority_engine import PriorityEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_upstream() -> UpstreamEngineOutputs:
    """Minimal mock of UpstreamEngineOutputs sufficient for PM scorer tests."""
    mc = SimpleNamespace(on_time_probability=0.60)
    forecast = SimpleNamespace(remaining_effort_hours=400.0)
    risk = SimpleNamespace(overall_risk_score=0.55)
    metrics = SimpleNamespace(team_utilization=0.80, avg_velocity=80.0)
    cp = SimpleNamespace(
        items_on_critical_path=["WI-001", "WI-002"],
        critical_path_duration_hours=160.0,
    )
    dag = SimpleNamespace()
    spillover = SimpleNamespace(spillover_risk=0.30)
    impact_scores = SimpleNamespace()
    return UpstreamEngineOutputs(
        metrics=metrics,
        dag=dag,
        cp_result=cp,
        spillover=spillover,
        forecast=forecast,
        monte_carlo=mc,
        impact_scores=impact_scores,
        risk_result=risk,
    )


def _candidate(
    action: RecommendationAction,
    item_ids: List[str] = None,
    resource_ids: List[str] = None,
    blocker_ids: List[str] = None,
    signal_category: Optional[str] = None,
    overdue_days: float = 0.0,
    on_cp: bool = False,
) -> RecommendationCandidate:
    item_ids = item_ids or ["WI-001"]
    resource_ids = resource_ids or ["R1"]
    blocker_ids = blocker_ids or []
    rec_id = stable_id(action.value, item_ids + resource_ids + blocker_ids)
    params: Dict[str, Any] = {}
    if signal_category:
        params["signal_category"] = signal_category
    if overdue_days:
        params["overdue_days"] = overdue_days
    if on_cp:
        params["on_critical_path"] = True
    return RecommendationCandidate(
        recommendation_id=rec_id,
        action_type=action,
        title=f"Test: {action.value}",
        description="Test candidate",
        affected_item_ids=item_ids,
        affected_resource_ids=resource_ids,
        affected_sprint_ids=["sp1"],
        affected_blocker_ids=blocker_ids,
        root_cause_signal_id="sig-0001",
        simulation_params=params,
    )


def _zero_impact(confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM) -> ImpactEstimate:
    """Impact estimate with zero delay reduction — mimics strategic recs."""
    return ImpactEstimate(
        estimated_hours_recovered=0.0,
        estimated_delay_reduction_days=0.0,
        estimated_risk_reduction=0.0,
        confidence=confidence,
        evidence=[],
        calculation_notes="zero-impact for test",
    )


def _delay_impact(days: float, risk: float = 0.30) -> ImpactEstimate:
    return ImpactEstimate(
        estimated_hours_recovered=days * 8,
        estimated_delay_reduction_days=days,
        estimated_risk_reduction=risk,
        confidence=ConfidenceLevel.HIGH,
        evidence=[],
        calculation_notes=f"{days}d impact",
    )


# ---------------------------------------------------------------------------
# 1. PMDecisionScorer — basic structure
# ---------------------------------------------------------------------------

class TestPMDecisionScorer:
    def test_score_returns_pm_decision_score(self):
        upstream = _mock_upstream()
        scorer = PMDecisionScorer(upstream)
        candidate = _candidate(RecommendationAction.RESOLVE_BLOCKER, blocker_ids=["BL-001"], on_cp=True)
        impact = _delay_impact(3.0, risk=0.50)
        result = scorer.score(candidate, impact)
        assert isinstance(result, PMDecisionScore)
        assert 0.0 <= result.composite <= 1.0

    def test_all_dimensions_present(self):
        upstream = _mock_upstream()
        scorer = PMDecisionScorer(upstream)
        candidate = _candidate(RecommendationAction.CROSS_TRAIN_BACKUP, resource_ids=["R1", "R2"],
                                signal_category=SignalCategory.SPOF.value)
        impact = _zero_impact()
        result = scorer.score(candidate, impact)
        assert hasattr(result, "schedule_benefit")
        assert hasattr(result, "risk_reduction")
        assert hasattr(result, "delivery_confidence")
        assert hasattr(result, "resource_health")
        assert hasattr(result, "governance_improvement")
        assert hasattr(result, "implementation_cost")
        assert hasattr(result, "urgency")
        assert hasattr(result, "composite")

    def test_strategic_recs_score_above_zero_with_no_delay(self):
        """SPOF / cross-train / review gate must score > 0 even with zero delay."""
        upstream = _mock_upstream()
        scorer = PMDecisionScorer(upstream)

        strategic_actions = [
            RecommendationAction.CROSS_TRAIN_BACKUP,
            RecommendationAction.INSERT_REVIEW_GATE,
            RecommendationAction.FREEZE_SCOPE_REQUEST,
            RecommendationAction.ESCALATE_BLOCKER_EARLY,
            RecommendationAction.REBASELINE_ESTIMATE,
        ]
        for action in strategic_actions:
            cand = _candidate(action)
            score = scorer.score(cand, _zero_impact())
            assert score.composite > 0.0, (
                f"{action.value} scored 0 with zero delay — strategic rec should still have value"
            )

    def test_spof_resource_health_high(self):
        upstream = _mock_upstream()
        scorer = PMDecisionScorer(upstream)
        cand = _candidate(
            RecommendationAction.CROSS_TRAIN_BACKUP,
            resource_ids=["R1", "R2"],
            signal_category=SignalCategory.SPOF.value,
        )
        score = scorer.score(cand, _zero_impact())
        assert score.resource_health >= 0.80

    def test_blocker_urgency_elevated_when_on_cp(self):
        upstream = _mock_upstream()
        scorer = PMDecisionScorer(upstream)
        cand = _candidate(
            RecommendationAction.RESOLVE_BLOCKER,
            blocker_ids=["BL-001"],
            on_cp=True,
        )
        score = scorer.score(cand, _zero_impact())
        assert score.urgency >= 0.60

    def test_governance_actions_score_governance_dimension(self):
        upstream = _mock_upstream()
        scorer = PMDecisionScorer(upstream)
        for action in [RecommendationAction.INSERT_REVIEW_GATE, RecommendationAction.FREEZE_SCOPE_REQUEST]:
            cand = _candidate(action)
            score = scorer.score(cand, _zero_impact())
            assert score.governance_improvement >= 0.70, (
                f"{action.value} should have high governance score"
            )

    def test_high_delay_rec_has_high_schedule_benefit(self):
        upstream = _mock_upstream()
        scorer = PMDecisionScorer(upstream)
        cand = _candidate(RecommendationAction.PARALLELIZE_ITEMS, item_ids=["WI-001", "WI-002"])
        impact = _delay_impact(6.0)
        score = scorer.score(cand, impact)
        assert score.schedule_benefit >= 1.0 - 1e-6  # capped at 1.0 (6 days >= 5 day cap)

    def test_composite_is_bounded(self):
        upstream = _mock_upstream()
        scorer = PMDecisionScorer(upstream)
        for action in RecommendationAction:
            cand = _candidate(action)
            score = scorer.score(cand, _delay_impact(10.0, risk=1.0))
            assert 0.0 <= score.composite <= 1.0, f"{action.value} composite out of bounds"

    def test_score_to_dict_contains_all_keys(self):
        upstream = _mock_upstream()
        scorer = PMDecisionScorer(upstream)
        cand = _candidate(RecommendationAction.RESOLVE_BLOCKER)
        d = scorer.score(cand, _zero_impact()).to_dict()
        expected_keys = {
            "schedule_benefit", "risk_reduction", "delivery_confidence",
            "resource_health", "governance_improvement", "implementation_cost",
            "urgency", "composite",
        }
        assert expected_keys.issubset(d.keys())


# ---------------------------------------------------------------------------
# 2. Classification and lookups
# ---------------------------------------------------------------------------

class TestClassificationLookups:
    def test_tactical_actions(self):
        tactical = [
            RecommendationAction.REASSIGN_ITEM,
            RecommendationAction.SPLIT_ITEM,
            RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT,
            RecommendationAction.PULL_FORWARD_ITEM,
        ]
        for action in tactical:
            cls = classification_for(action)
            assert cls == RecommendationClassification.TACTICAL, (
                f"{action.value} should be Tactical"
            )

    def test_strategic_actions(self):
        strategic = [
            RecommendationAction.CROSS_TRAIN_BACKUP,
            RecommendationAction.REBASELINE_ESTIMATE,
            RecommendationAction.APPLY_RAMP_UP_DISCOUNT,
        ]
        for action in strategic:
            cls = classification_for(action)
            assert cls == RecommendationClassification.STRATEGIC, (
                f"{action.value} should be Strategic"
            )

    def test_hybrid_actions(self):
        hybrid = [
            RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK,
            RecommendationAction.REBALANCE_SPRINT_LOAD,
            RecommendationAction.FREEZE_SCOPE_REQUEST,
        ]
        for action in hybrid:
            cls = classification_for(action)
            assert cls == RecommendationClassification.HYBRID, (
                f"{action.value} should be Hybrid"
            )

    def test_effort_low_for_quick_actions(self):
        low_effort = [
            RecommendationAction.ESCALATE_BLOCKER_EARLY,
            RecommendationAction.REASSIGN_ITEM,
            RecommendationAction.REBASELINE_ESTIMATE,
            RecommendationAction.INSERT_REVIEW_GATE,
        ]
        for action in low_effort:
            assert effort_for(action) == ImplementationEffort.LOW, (
                f"{action.value} should have Low effort"
            )

    def test_effort_high_for_complex_actions(self):
        high_effort = [
            RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK,
            RecommendationAction.ADD_RESOURCE_SKILL,
        ]
        for action in high_effort:
            assert effort_for(action) == ImplementationEffort.HIGH, (
                f"{action.value} should have High effort"
            )

    def test_every_action_has_objective(self):
        for action in RecommendationAction:
            obj = objective_for(action)
            assert isinstance(obj, RecommendationObjective)

    def test_every_action_has_classification(self):
        for action in RecommendationAction:
            cls = classification_for(action)
            assert isinstance(cls, RecommendationClassification)

    def test_every_action_has_effort(self):
        for action in RecommendationAction:
            eff = effort_for(action)
            assert isinstance(eff, ImplementationEffort)


# ---------------------------------------------------------------------------
# 3. PMExplanationGenerator — answers 5 PM questions
# ---------------------------------------------------------------------------

class TestPMExplanationGenerator:
    def _make_rec(self, action: RecommendationAction) -> Recommendation:
        return Recommendation(
            recommendation_id="rec-001",
            title="Test",
            description="Test",
            action_type=action,
            priority_score=0.75,
            confidence=ConfidenceLevel.HIGH,
            estimated_hours_recovered=8.0,
            estimated_delay_reduction_days=1.0,
            estimated_risk_reduction=0.20,
            affected_item_ids=["WI-001"],
            affected_resource_ids=["R1", "R2"],
            affected_sprint_ids=["sp1"],
            affected_blocker_ids=[],
            root_cause_signal_id="sig-001",
        )

    def test_explanation_has_all_fields(self):
        upstream = _mock_upstream()
        gen = PMExplanationGenerator(upstream)
        rec = self._make_rec(RecommendationAction.CROSS_TRAIN_BACKUP)
        explanation = gen.explain(rec)
        assert explanation.trigger_reason is not None
        assert len(explanation.trigger_detail) > 10
        assert explanation.primary_objective is not None
        assert len(explanation.strategic_benefits) >= 1
        assert len(explanation.ignore_consequence) > 10
        assert explanation.implementation_effort is not None
        assert isinstance(explanation.is_immediate_impact, bool)
        assert explanation.impact_horizon in ("Immediate", "Next Sprint", "Long Term")

    def test_cross_train_classified_as_not_immediate(self):
        upstream = _mock_upstream()
        gen = PMExplanationGenerator(upstream)
        rec = self._make_rec(RecommendationAction.CROSS_TRAIN_BACKUP)
        explanation = gen.explain(rec)
        assert explanation.is_immediate_impact is False

    def test_resolve_blocker_classified_as_immediate(self):
        upstream = _mock_upstream()
        gen = PMExplanationGenerator(upstream)
        rec = self._make_rec(RecommendationAction.RESOLVE_BLOCKER)
        rec.affected_blocker_ids = ["BL-001"]
        explanation = gen.explain(rec)
        assert explanation.impact_horizon == "Immediate"

    def test_explanation_to_dict_structure(self):
        upstream = _mock_upstream()
        gen = PMExplanationGenerator(upstream)
        rec = self._make_rec(RecommendationAction.FREEZE_SCOPE_REQUEST)
        d = gen.explain(rec).to_dict()
        required_keys = {
            "trigger_reason", "trigger_detail", "primary_objective",
            "strategic_benefits", "ignore_consequence",
            "implementation_effort", "is_immediate_impact", "impact_horizon",
        }
        assert required_keys.issubset(d.keys())
        assert isinstance(d["strategic_benefits"], list)
        assert len(d["strategic_benefits"]) >= 1

    def test_all_action_types_produce_non_empty_explanation(self):
        upstream = _mock_upstream()
        gen = PMExplanationGenerator(upstream)
        for action in RecommendationAction:
            rec = self._make_rec(action)
            expl = gen.explain(rec)
            assert expl.trigger_detail, f"{action.value} produced empty trigger_detail"
            assert expl.ignore_consequence, f"{action.value} produced empty ignore_consequence"
            assert expl.strategic_benefits, f"{action.value} produced empty strategic_benefits"


# ---------------------------------------------------------------------------
# 4. PriorityEngine — pm_intelligence attached
# ---------------------------------------------------------------------------

class TestPriorityEnginePMIntelligence:
    def test_pm_intelligence_attached_to_every_recommendation(self):
        upstream = _mock_upstream()
        weights = ScoringWeights()
        engine = PriorityEngine(upstream, weights=weights)
        candidates = [
            _candidate(RecommendationAction.RESOLVE_BLOCKER, blocker_ids=["BL-001"]),
            _candidate(RecommendationAction.CROSS_TRAIN_BACKUP, resource_ids=["R1", "R2"]),
            _candidate(RecommendationAction.REBASELINE_ESTIMATE),
            _candidate(RecommendationAction.INSERT_REVIEW_GATE),
        ]
        impacts = {c.recommendation_id: _delay_impact(2.0) for c in candidates}
        # CROSS_TRAIN and INSERT_REVIEW_GATE often produce zero delay
        impacts[candidates[1].recommendation_id] = _zero_impact()
        impacts[candidates[2].recommendation_id] = _zero_impact()
        impacts[candidates[3].recommendation_id] = _zero_impact()

        ranked = engine.score_and_rank(candidates, impacts)
        assert len(ranked) == len(candidates)
        for rec in ranked:
            assert rec.pm_intelligence is not None, (
                f"{rec.action_type.value} is missing pm_intelligence"
            )
            assert isinstance(rec.pm_intelligence, PMIntelligence)

    def test_pm_intelligence_has_valid_classification(self):
        upstream = _mock_upstream()
        engine = PriorityEngine(upstream)
        cand = _candidate(RecommendationAction.CROSS_TRAIN_BACKUP, resource_ids=["R1", "R2"])
        ranked = engine.score_and_rank([cand], {cand.recommendation_id: _zero_impact()})
        assert ranked[0].pm_intelligence.classification == RecommendationClassification.STRATEGIC

    def test_strategic_rec_not_ranked_last_when_delay_zero(self):
        """Cross-train should not rank last even with 0 delay, given SPOF signal."""
        upstream = _mock_upstream()
        engine = PriorityEngine(upstream)
        # Candidate with delay = 0 but SPOF signal (strategic)
        spof_cand = _candidate(
            RecommendationAction.CROSS_TRAIN_BACKUP,
            resource_ids=["R1", "R2"],
            signal_category=SignalCategory.SPOF.value,
        )
        # Candidate with tiny 0.1-day delay (tactical)
        trivial_cand = _candidate(
            RecommendationAction.REASSIGN_ITEM,
            item_ids=["WI-002"],
            resource_ids=["R2"],
        )
        impacts = {
            spof_cand.recommendation_id: _zero_impact(),
            trivial_cand.recommendation_id: _delay_impact(0.1, risk=0.01),
        }
        ranked = engine.score_and_rank([spof_cand, trivial_cand], impacts)
        # SPOF cross-train should rank first (resource_health floors at 0.85)
        assert ranked[0].action_type == RecommendationAction.CROSS_TRAIN_BACKUP, (
            "SPOF cross-train should rank above a trivial delay reduction"
        )


# ---------------------------------------------------------------------------
# 5. to_api_dict backward compatibility
# ---------------------------------------------------------------------------

class TestApiDictBackwardCompat:
    def _base_rec(self) -> Recommendation:
        return Recommendation(
            recommendation_id="rec-compat",
            title="Compat Test",
            description="Testing",
            action_type=RecommendationAction.RESOLVE_BLOCKER,
            priority_score=0.80,
            confidence=ConfidenceLevel.HIGH,
            estimated_hours_recovered=16.0,
            estimated_delay_reduction_days=2.0,
            estimated_risk_reduction=0.40,
            affected_item_ids=["WI-001"],
            affected_resource_ids=["R1"],
            affected_sprint_ids=["sp1"],
            affected_blocker_ids=["BL-001"],
            root_cause_signal_id="sig-001",
        )

    def test_existing_fields_present_without_pm_intelligence(self):
        rec = self._base_rec()
        d = rec.to_api_dict()
        required = {
            "recommendation_id", "action_type", "title", "description",
            "priority_score", "confidence", "estimated_hours_recovered",
            "estimated_delay_reduction_days", "estimated_risk_reduction",
            "affected_item_ids", "affected_resource_ids", "affected_sprint_ids",
            "affected_blocker_ids", "root_cause_signal_id", "metadata",
        }
        assert required.issubset(d.keys())
        # pm_intelligence should be absent when not set
        assert "pm_intelligence" not in d

    def test_pm_intelligence_present_when_set(self):
        upstream = _mock_upstream()
        engine = PriorityEngine(upstream)
        cand = _candidate(RecommendationAction.RESOLVE_BLOCKER, blocker_ids=["BL-001"])
        ranked = engine.score_and_rank([cand], {cand.recommendation_id: _delay_impact(3.0)})
        d = ranked[0].to_api_dict()
        assert "pm_intelligence" in d
        pm = d["pm_intelligence"]
        assert "classification" in pm
        assert "pm_decision_score" in pm
        assert "explanation" in pm
        assert "composite" in pm["pm_decision_score"]
        assert "trigger_reason" in pm["explanation"]
        assert "primary_objective" in pm["explanation"]
        assert "strategic_benefits" in pm["explanation"]
        assert "ignore_consequence" in pm["explanation"]
        assert "implementation_effort" in pm["explanation"]


# ---------------------------------------------------------------------------
# 6. Diversity reranking — tested via a mock of the engine internals
# ---------------------------------------------------------------------------

class TestDiversityReranking:
    """Test _diversity_rerank by instantiating a minimal engine."""

    def _make_rec(self, action: RecommendationAction, score: float) -> Recommendation:
        return Recommendation(
            recommendation_id=stable_id(action.value, [str(score)]),
            title=action.value,
            description="",
            action_type=action,
            priority_score=score,
            confidence=ConfidenceLevel.MEDIUM,
            estimated_hours_recovered=0.0,
            estimated_delay_reduction_days=0.0,
            estimated_risk_reduction=0.0,
            affected_item_ids=[],
            affected_resource_ids=[],
            affected_sprint_ids=[],
            affected_blocker_ids=[],
            root_cause_signal_id="sig-x",
        )

    def test_diversity_no_more_than_max_per_objective_in_first_n(self):
        """Diversity pass should not put > max_per_objective same-objective recs first."""
        from app.engines.recommendation_engine.recommendation_engine_v2 import RecommendationEngineV2
        from unittest.mock import patch

        # Build 5 schedule-optimization recs + 1 risk + 1 knowledge
        schedule_actions = [
            RecommendationAction.PARALLELIZE_ITEMS,
            RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT,
            RecommendationAction.SPLIT_ITEM,
            RecommendationAction.PULL_FORWARD_ITEM,
            RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM,
        ]
        recs = [self._make_rec(a, 0.9 - i * 0.05) for i, a in enumerate(schedule_actions)]
        recs.append(self._make_rec(RecommendationAction.RESOLVE_BLOCKER, 0.55))
        recs.append(self._make_rec(RecommendationAction.CROSS_TRAIN_BACKUP, 0.50))

        # Use a dummy project state (just needs model_copy)
        try:
            from app.domain.models import ProjectState, ProjectInfo
        except ImportError:
            pytest.skip("ProjectState not available in this environment")

        # We test _diversity_rerank directly by calling it through a patched engine
        # Create a minimal state mock
        state_mock = MagicMock()
        state_mock.model_copy.return_value = state_mock
        state_mock.work_items = []
        state_mock.sprints = []
        state_mock.team = []
        state_mock.blockers = []

        engine = RecommendationEngineV2.__new__(RecommendationEngineV2)
        result = engine._diversity_rerank(recs, max_per_objective=2)

        # Count schedule-objective recs in first 4 positions (max_per_objective=2 per obj)
        from app.engines.recommendation_engine.pm_decision_scorer import objective_for
        from app.engines.recommendation_engine.pm_models import RecommendationObjective
        schedule_obj = RecommendationObjective.SCHEDULE_OPTIMIZATION.value
        first_4_schedule = sum(
            1 for r in result[:4]
            if objective_for(r.action_type).value == schedule_obj
        )
        assert first_4_schedule <= 2, (
            f"Expected ≤2 schedule-optimization recs in top 4, got {first_4_schedule}"
        )

    def test_diversity_preserves_all_recommendations(self):
        """Diversity reranking must not drop any recommendation."""
        from app.engines.recommendation_engine.recommendation_engine_v2 import RecommendationEngineV2

        recs = [
            self._make_rec(action, 0.9 - i * 0.05)
            for i, action in enumerate(list(RecommendationAction)[:8])
        ]
        engine = RecommendationEngineV2.__new__(RecommendationEngineV2)
        result = engine._diversity_rerank(recs, max_per_objective=2)
        assert len(result) == len(recs)
