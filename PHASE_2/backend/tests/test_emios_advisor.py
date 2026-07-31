"""
Tests for Phase 7 — EMIOS AI Co-pilot Upgrade (Stage 7).

Covers:
1. EMIOSAdvisorOutput fallback rendering — all 4 fields always populated,
   the low-confidence disclosure rule, and the counterfactual-style
   percentage requirement (INVARIANT 7 from Final.2 requires
   str(round(diagnosis.confidence*100)) to appear in confidence_statement).
2. build_emios_advisor_input() projecting a PipelineResult-shaped object
   correctly, including graceful defaults when stages haven't run yet.
3. EMIOSAdvisor.run_with_ai() falling back cleanly on any failure.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.engines.emios_advisor import EMIOSAdvisor, EMIOS_SYSTEM_PROMPT, render_fallback
from app.engines.emios_advisor_contract import (
    DecisionSummaryFact,
    DiagnosisSummaryFact,
    EMIOSAdvisorInput,
    ImpactSummaryFact,
    ObservationSummaryFact,
)
from app.engines.emios_advisor_input_builder import build_emios_advisor_input


def _full_input(confidence_pct=72, recovery_state="RECOVERY"):
    return EMIOSAdvisorInput(
        observation_summary=ObservationSummaryFact(
            primary_signal="On-time probability fell to 21% (baseline: 65%)",
            cluster_severity="HIGH",
            observation_count=3,
        ),
        diagnosis_summary=DiagnosisSummaryFact(
            root_cause="Supplier delay on critical dependency",
            confidence_pct=confidence_pct,
            causal_chain=["Symptom", "Cause1", "Cause2", "Root"],
            top_eliminated_hypothesis="Capacity shortfall — ruled out because velocity was stable",
        ),
        impact_summary=ImpactSummaryFact(
            dominant_dimension="SCHEDULE",
            dominant_magnitude=7.5,
            sacrifice_statement="2 sprints of buffer",
        ),
        decision_summary=DecisionSummaryFact(
            chosen_action="Resolve blocker B-03",
            expected_value=4.2,
            top_rejected_alternative="Add resource (Brooks risk)",
            confidence_pct=confidence_pct,
        ),
        recovery_state=recovery_state,
    )


# ---------------------------------------------------------------------------
# 1. Fallback rendering
# ---------------------------------------------------------------------------


def test_fallback_populates_all_four_fields():
    out = render_fallback(_full_input())
    assert out.executive_summary
    assert out.reasoning_explanation
    assert out.decision_explanation
    assert out.confidence_statement
    assert out.status == "fallback"


def test_fallback_confidence_statement_contains_confidence_number():
    """INVARIANT 7 (Final.2): str(round(diagnosis.confidence*100)) must
    appear in confidence_statement."""
    out = render_fallback(_full_input(confidence_pct=72))
    assert "72" in out.confidence_statement


def test_fallback_flags_low_confidence():
    out = render_fallback(_full_input(confidence_pct=45))
    assert "45" in out.confidence_statement
    assert "below the 60%" in out.confidence_statement


def test_fallback_does_not_flag_high_confidence():
    out = render_fallback(_full_input(confidence_pct=85))
    assert "below the 60%" not in out.confidence_statement


def test_fallback_mentions_recovery_state():
    out = render_fallback(_full_input(recovery_state="CRITICAL"))
    assert "CRITICAL" in out.confidence_statement


def test_fallback_describes_dismissed_hypothesis_without_internal_labels():
    out = render_fallback(_full_input())
    assert "we also checked whether" in out.reasoning_explanation.lower()
    assert "capacity shortfall" in out.reasoning_explanation.lower()
    assert "ruled out because" not in out.reasoning_explanation.lower()
    assert "eliminated:" not in out.reasoning_explanation.lower()


def test_fallback_handles_no_eliminated_hypothesis_gracefully():
    inp = _full_input()
    inp = inp.model_copy(
        update={
            "diagnosis_summary": inp.diagnosis_summary.model_copy(
                update={"top_eliminated_hypothesis": ""}
            )
        }
    )
    out = render_fallback(inp)
    assert "no other cause" in out.reasoning_explanation.lower()


def test_emios_advisor_run_uses_fallback():
    out = EMIOSAdvisor().run(_full_input())
    assert out.status == "fallback"
    assert out.executive_summary


@pytest.mark.asyncio
async def test_run_with_ai_falls_back_when_no_client():
    out = await EMIOSAdvisor().run_with_ai(_full_input(), client=None)
    assert out.status == "fallback"


@pytest.mark.asyncio
async def test_run_with_ai_falls_back_when_disabled():
    class _StubClient:
        async def generate(self, system_prompt, user_message):
            return {
                "executive_summary": "x",
                "reasoning_explanation": "x",
                "decision_explanation": "x",
                "confidence_statement": "x",
            }

    out = await EMIOSAdvisor().run_with_ai(
        _full_input(), client=_StubClient(), ai_advisor_enabled=False
    )
    assert out.status == "fallback"


@pytest.mark.asyncio
async def test_run_with_ai_falls_back_on_client_exception():
    class _BrokenClient:
        async def generate(self, system_prompt, user_message):
            raise RuntimeError("network error")

    out = await EMIOSAdvisor().run_with_ai(_full_input(), client=_BrokenClient())
    assert out.status == "fallback"


@pytest.mark.asyncio
async def test_run_with_ai_returns_ok_status_on_success():
    class _GoodClient:
        async def generate(self, system_prompt, user_message):
            return {
                "executive_summary": "Project is at risk due to a supplier delay.",
                "reasoning_explanation": "The engine found a critical dependency was blocked.",
                "decision_explanation": "Resolving the blocker was chosen over adding resources.",
                "confidence_statement": "Confidence is 72%.",
            }

    out = await EMIOSAdvisor().run_with_ai(_full_input(), client=_GoodClient())
    assert out.status == "ok"
    assert "supplier delay" in out.executive_summary.lower()


@pytest.mark.asyncio
async def test_run_with_ai_passes_correct_roles_to_client():
    class _RecordingClient:
        def __init__(self):
            self.received = None

        async def generate(self, user_message, system_prompt=None):
            self.received = (user_message, system_prompt)
            return {
                "executive_summary": "x",
                "reasoning_explanation": "x",
                "decision_explanation": "x",
                "confidence_statement": "x",
            }

    client = _RecordingClient()
    await EMIOSAdvisor().run_with_ai(inp=_full_input(), client=client)

    user_msg, sys_prompt = client.received
    assert sys_prompt == EMIOS_SYSTEM_PROMPT
    assert "reasoning-chain snapshot" in user_msg


# ---------------------------------------------------------------------------
# 2. build_emios_advisor_input() projection
# ---------------------------------------------------------------------------


def _pipeline_result_stub():
    observation = SimpleNamespace(
        metric_ref="on_time_probability",
        current_value=21.0,
        baseline_value=65.0,
        direction=SimpleNamespace(value="fell"),
    )
    observation_cluster = SimpleNamespace(
        observations=[observation, observation, observation],
        cluster_severity="HIGH",
        primary_signal=observation,
        summary="On-time probability dropped sharply",
    )

    survivor = SimpleNamespace(hypothesis_id="H1", prior=0.3, statement="Root cause confirmed")
    rejected = SimpleNamespace(
        hypothesis_id="H2",
        prior=0.6,
        statement="Capacity shortfall",
        rejection_reason="velocity was stable across sprints",
    )
    diagnosis = SimpleNamespace(
        root_cause="Supplier delay on critical dependency",
        confidence=0.72,
        causal_chain=["Symptom", "Cause1", "Cause2", "Root", "Extra-should-be-truncated"],
    )

    estimate = SimpleNamespace(magnitude=7.5, explanation="2 sprints of buffer")
    impact_matrix = SimpleNamespace(
        dominant_dimension="schedule",
        estimates={"schedule": estimate},
    )

    chosen_option = SimpleNamespace(label="Resolve blocker B-03", net_expected_value=4.2)
    rejected_alt = SimpleNamespace(rejection_reason="Add resource (Brooks risk)")
    decision = SimpleNamespace(
        chosen_option=chosen_option,
        expected_value=4.2,
        rejected_alternatives=[rejected_alt],
        confidence=0.72,
    )

    recovery_state_machine = SimpleNamespace(current_state="RECOVERY")

    return SimpleNamespace(
        observation_cluster=observation_cluster,
        diagnosis=diagnosis,
        hypotheses=[survivor, rejected],
        surviving_hypotheses=[survivor],
        impact_matrix=impact_matrix,
        decision=decision,
        recovery_state_machine=recovery_state_machine,
    )


def test_build_emios_advisor_input_full_projection():
    result = _pipeline_result_stub()
    inp = build_emios_advisor_input(result)

    assert inp.observation_summary.cluster_severity == "HIGH"
    assert inp.observation_summary.observation_count == 3

    assert inp.diagnosis_summary.root_cause == "Supplier delay on critical dependency"
    assert inp.diagnosis_summary.confidence_pct == 72
    assert len(inp.diagnosis_summary.causal_chain) == 4  # truncated to max 4
    assert "capacity shortfall" in inp.diagnosis_summary.top_eliminated_hypothesis.lower()

    assert inp.impact_summary.dominant_dimension == "SCHEDULE"
    assert inp.impact_summary.dominant_magnitude == 7.5

    assert inp.decision_summary.chosen_action == "Resolve blocker B-03"
    assert inp.decision_summary.top_rejected_alternative == "Add resource (Brooks risk)"

    assert inp.recovery_state == "RECOVERY"


def test_build_emios_advisor_input_handles_missing_stages_gracefully():
    """Early in the pipeline (or if a stage failed), fields may be None --
    the builder must never raise, and should return sane defaults."""
    empty_result = SimpleNamespace(
        observation_cluster=None,
        diagnosis=None,
        hypotheses=None,
        surviving_hypotheses=None,
        impact_matrix=None,
        decision=None,
        recovery_state_machine=None,
    )
    inp = build_emios_advisor_input(empty_result)

    assert inp.observation_summary.observation_count == 0
    assert inp.diagnosis_summary.confidence_pct == 0
    assert inp.impact_summary.dominant_dimension == "UNKNOWN"
    assert inp.decision_summary.chosen_action == "No action selected yet."
    assert inp.recovery_state == "HEALTHY"

    # And the advisor must still produce a fully-populated output from this.
    out = EMIOSAdvisor().run(inp)
    assert out.executive_summary and out.reasoning_explanation
    assert out.decision_explanation and out.confidence_statement


def test_build_emios_advisor_input_top_eliminated_hypothesis_prefers_highest_prior():
    result = _pipeline_result_stub()
    # Add a second, lower-prior rejected hypothesis -- the higher-prior one
    # (H2, prior 0.6) should still be selected over this new one (prior 0.1).
    low_prior_rejected = SimpleNamespace(
        hypothesis_id="H3",
        prior=0.1,
        statement="Minor scope creep",
        rejection_reason="too small to explain the delay",
    )
    result.hypotheses = result.hypotheses + [low_prior_rejected]

    inp = build_emios_advisor_input(result)
    assert "capacity shortfall" in inp.diagnosis_summary.top_eliminated_hypothesis.lower()
    assert "minor scope creep" not in inp.diagnosis_summary.top_eliminated_hypothesis.lower()
    assert "ruled out because" not in inp.diagnosis_summary.top_eliminated_hypothesis.lower()
