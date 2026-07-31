"""
EMIOS Advisor contract — Phase 7 (AI Co-pilot Upgrade).

Upgrades the AI advisor from a forecast narrator (see advisor_contract.py,
unchanged, kept for backward compatibility) to a reasoning co-pilot: instead
of only describing forecast/risk numbers, it explains the reasoning chain
the EMIOS cognitive pipeline already computed -- what was observed, what
was diagnosed, what was ruled out, and why a particular decision was made.

Same hard invariant as the original advisor: this layer NEVER computes a
metric, NEVER forecasts, NEVER generates a recommendation. Every field in
EMIOSAdvisorInput is a projection of a value some upstream EMIOS engine
already produced (see emios_advisor_input_builder.py for exact provenance).
"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Reasoning-chain fact types (Prompt 7.1)
# ---------------------------------------------------------------------------


class ObservationSummaryFact(BaseModel):
    """Projection of PipelineResult.observation_cluster (Stage 1)."""

    primary_signal: str = Field(
        ..., description="e.g. 'On-time probability fell to 21% (baseline: 65%)'"
    )
    cluster_severity: str = Field(..., description="'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'")
    observation_count: int

    model_config = {"frozen": True}


class DiagnosisSummaryFact(BaseModel):
    """Projection of PipelineResult.diagnosis + surviving/eliminated hypotheses (Stage 6)."""

    root_cause: str = Field(..., description="Diagnosis.root_cause")
    confidence_pct: int = Field(..., ge=0, le=100, description="Diagnosis.confidence as integer percent")
    causal_chain: List[str] = Field(
        default_factory=list, description="Diagnosis.causal_chain, max 4 items"
    )
    top_eliminated_hypothesis: str = Field(
        "", description="The most interesting rejected hypothesis + why (Hypothesis.rejection_reason)"
    )

    model_config = {"frozen": True}


class ImpactSummaryFact(BaseModel):
    """Projection of PipelineResult.impact_matrix (Stages 7-11)."""

    dominant_dimension: str = Field(..., description="e.g. 'SCHEDULE'")
    dominant_magnitude: float
    sacrifice_statement: str = Field(
        "", description="What is being traded off to address the dominant impact"
    )

    model_config = {"frozen": True}


class DecisionSummaryFact(BaseModel):
    """Projection of PipelineResult.decision (Stage 14)."""

    chosen_action: str = Field(..., description="Decision.chosen_option.label")
    expected_value: float = Field(..., description="Decision.expected_value")
    top_rejected_alternative: str = Field(
        "", description="Decision.rejected_alternatives[0].rejection_reason"
    )
    confidence_pct: int = Field(..., ge=0, le=100, description="Decision.confidence as integer percent")

    model_config = {"frozen": True}


class EMIOSAdvisorInput(BaseModel):
    """
    The complete, closed universe of facts the EMIOS co-pilot may reference.

    Backward-compatible fields (forecast_snapshot / risk_snapshot /
    project_context) reuse the existing projections from advisor_contract.py
    so both advisor generations can share a builder where facts overlap.
    """

    # --- existing fields, kept for backward compatibility ---
    forecast_snapshot: dict = Field(
        default_factory=dict, description="Flat projection of ForecastResult"
    )
    risk_snapshot: dict = Field(
        default_factory=dict, description="Flat projection of RiskResult"
    )
    project_context: dict = Field(
        default_factory=dict, description="Flat projection of ProjectContextFacts"
    )

    # --- new reasoning chain fields ---
    observation_summary: ObservationSummaryFact
    diagnosis_summary: DiagnosisSummaryFact
    impact_summary: ImpactSummaryFact
    decision_summary: DecisionSummaryFact
    recovery_state: str = Field(
        ..., description="Current RecoveryStateMachine state label, e.g. 'RECOVERY'"
    )

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Output contract (Prompt 7.1)
# ---------------------------------------------------------------------------


class EMIOSAdvisorOutput(BaseModel):
    """
    Four short, plain-English sections explaining the reasoning chain.
    `status` distinguishes an LLM-authored response from the deterministic
    fallback template (both are always fully populated -- fallback is not
    an error state, it's a designed-for path).
    """

    executive_summary: str = Field(..., description="1 sentence: situation + root cause + action")
    reasoning_explanation: str = Field(
        ..., description="2-3 sentences: what the engine found + what it ruled out"
    )
    decision_explanation: str = Field(
        ..., description="2 sentences: why this action, what is being sacrificed"
    )
    confidence_statement: str = Field(..., description="1 sentence: how confident, why")
    status: Literal["ok", "fallback"] = "fallback"
