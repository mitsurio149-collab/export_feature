"""
tests/test_phase4_recovery_plans.py

Integration test for Phase 4 Stage 15: RecoveryPlanBuilder.

Design note: unlike Stage 13/14, Stage 15 is NOT a from-scratch engine --
it's a thin adapter (`_stage_15_plan` in emios_pipeline.py) over the
existing, mature `RecoveryPlanEngine` (app/engines/recovery_plan_engine/),
which already generates 3 simulated, scored, ranked plans. Because that
engine's scoring depends on real simulated interactions between actions
(SimulationEngine), hand-built SimpleNamespace fixtures would just be
testing our own assumptions about simulator behavior rather than the real
thing. So this test runs the actual pipeline against the actual demo
workbook, the same way scripts/validate_emios_pipeline.py is expected to.
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

# Prime the pre-existing circular import between forecast_engine.py and
# app/api/routes/demo.py by importing app.api first. See test_phase4_tradeoffs.py
# / test_phase4_decision.py handoff notes for the same issue.
import app.api  # noqa: F401

from app.core.config import settings
from app.parsers.workbook_parser import WorkbookParser
from app.pipeline.emios_pipeline import run_emios_pipeline
from app.engines.recovery_plan_engine.models import RecoveryPlanArchetype


@pytest.fixture(scope="module")
def pipeline_result():
    parser = WorkbookParser(settings.demo_workbook_path)
    state = parser.parse()
    return run_emios_pipeline(state)


def test_recovery_plans_present(pipeline_result):
    assert pipeline_result.recovery_plans is not None
    assert len(pipeline_result.recovery_plans) > 0


def test_three_distinct_archetypes(pipeline_result):
    """Spec: 3 strategies (SAFE, AGGRESSIVE, MINIMAL_DISRUPTION)."""
    archetypes = {p.archetype for p in pipeline_result.recovery_plans}
    assert archetypes == {
        RecoveryPlanArchetype.SAFE,
        RecoveryPlanArchetype.AGGRESSIVE,
        RecoveryPlanArchetype.MINIMAL_DISRUPTION,
    }


def test_exactly_one_recommended_plan(pipeline_result):
    recommended = [p for p in pipeline_result.recovery_plans if p.label == "Recommended"]
    assert len(recommended) == 1


def test_plans_ranked_by_composite_score_descending(pipeline_result):
    """
    STALE TEST fix: RecoveryPlanEngine's ranking (Step 6 in engine.py) is
    documented, intentional composite_score order EXCEPT when (a) one plan
    strictly outcome-dominates another (probability >=, delay <=, risk <=,
    strictly better on at least one), or (b) the "Recommended-plan quality
    gate" ranks a meaningful_improvement=True plan ahead of an ineligible
    one. Both are deliberate P0 fixes (see engine.py Step 6 docstring), not
    bugs -- a plan must never rank above a strictly-better plan just
    because it has a slightly higher composite_score from a smaller
    complexity penalty. This test now verifies the actual invariant:
    within each eligibility group (meaningful_improvement True/False),
    no earlier plan is outcome-dominated by a later one, and eligible
    plans are never ranked after ineligible ones.
    """
    plans = pipeline_result.recovery_plans

    def dominates(a, b) -> bool:
        prob_ge = a.score.deadline_probability >= b.score.deadline_probability
        delay_le = a.score.expected_delay_days <= b.score.expected_delay_days
        risk_le = a.score.overall_risk_score <= b.score.overall_risk_score
        strictly_better = (
            a.score.deadline_probability > b.score.deadline_probability
            or a.score.expected_delay_days < b.score.expected_delay_days
            or a.score.overall_risk_score < b.score.overall_risk_score
        )
        return prob_ge and delay_le and risk_le and strictly_better

    # Eligible (meaningful_improvement) plans must never rank after
    # ineligible ones.
    eligibility_flags = [p.score.meaningful_improvement for p in plans]
    assert eligibility_flags == sorted(eligibility_flags, reverse=True)

    # No earlier plan may be strictly outcome-dominated by a later plan.
    for earlier_idx in range(len(plans)):
        for later_idx in range(earlier_idx + 1, len(plans)):
            assert not dominates(plans[later_idx], plans[earlier_idx]), (
                f"Plan at rank {later_idx} outcome-dominates plan at rank "
                f"{earlier_idx} but ranks below it."
            )


def test_each_plan_has_marginal_outcome_metrics(pipeline_result):
    """'Marginals' = each plan must carry its own projected on-time
    probability, expected delay, and risk -- not a shared/global number."""
    seen = set()
    for p in pipeline_result.recovery_plans:
        assert 0.0 <= p.score.deadline_probability <= 1.0
        assert isinstance(p.score.expected_delay_days, float)
        assert p.score.overall_risk_score >= 0.0
        seen.add((p.score.deadline_probability, p.score.expected_delay_days))
    # marginals must actually differ across plans, not be a copy-pasted constant
    assert len(seen) > 1


def test_each_plan_has_narrative_explanation(pipeline_result):
    for p in pipeline_result.recovery_plans:
        assert p.explanation.narrative_summary.strip() != ""
        assert len(p.explanation.why_recommended) > 0
