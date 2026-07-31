"""
EMIOSAdvisorInputBuilder — Phase 7 (AI Co-pilot Upgrade).

Projects a EMIOS PipelineResult (app/pipeline/emios_pipeline.py) into the
closed EMIOSAdvisorInput snapshot. Pure function, no engine calls, no
computation beyond simple formatting -- mirrors the existing
AdvisorInputBuilder pattern in app/engines/advisor_input_builder.py.

Field provenance (do not add a field here unless it maps to one of these):
    observation_summary  <- PipelineResult.observation_cluster       (Stage 1)
    diagnosis_summary    <- PipelineResult.diagnosis,
                             PipelineResult.surviving_hypotheses,
                             PipelineResult.hypotheses                (Stage 4-6)
    impact_summary       <- PipelineResult.impact_matrix              (Stage 7-11)
    decision_summary     <- PipelineResult.decision                   (Stage 14)
    recovery_state       <- PipelineResult.recovery_state_machine.current_state (Stage 16)
"""
from __future__ import annotations

from typing import Any, Optional

from app.engines.emios_advisor_contract import (
    DecisionSummaryFact,
    DiagnosisSummaryFact,
    EMIOSAdvisorInput,
    ImpactSummaryFact,
    ObservationSummaryFact,
)

_DEFAULT_OBSERVATION = ObservationSummaryFact(
    primary_signal="No observation data available.",
    cluster_severity="LOW",
    observation_count=0,
)
_DEFAULT_DIAGNOSIS = DiagnosisSummaryFact(
    root_cause="Not yet diagnosed.",
    confidence_pct=0,
    causal_chain=[],
    top_eliminated_hypothesis="",
)
_DEFAULT_IMPACT = ImpactSummaryFact(
    dominant_dimension="UNKNOWN",
    dominant_magnitude=0.0,
    sacrifice_statement="",
)
_DEFAULT_DECISION = DecisionSummaryFact(
    chosen_action="No action selected yet.",
    expected_value=0.0,
    top_rejected_alternative="",
    confidence_pct=0,
)


def _pct(fraction: Optional[float]) -> int:
    """0.0-1.0 fraction -> integer percent. None/invalid -> 0."""
    try:
        return round(float(fraction or 0.0) * 100)
    except (TypeError, ValueError):
        return 0


def _format_primary_signal(observation_cluster: Any) -> str:
    """
    Builds a human sentence from the cluster's primary_signal Observation,
    e.g. 'On-time probability fell to 21% (baseline: 65%)'.
    Falls back to observation_cluster.summary, then a generic default.
    """
    primary = getattr(observation_cluster, "primary_signal", None)
    if primary is not None:
        metric = getattr(primary, "metric_ref", "a key metric")
        current = getattr(primary, "current_value", None)
        baseline = getattr(primary, "baseline_value", None)
        direction = getattr(primary, "direction", None)
        direction_str = getattr(direction, "value", direction) or "moved"
        if current is not None and baseline is not None:
            return (
                f"{metric.replace('_', ' ').capitalize()} {direction_str} to "
                f"{current:.0f} (baseline: {baseline:.0f})"
            )
        return f"{metric.replace('_', ' ').capitalize()} {direction_str} significantly"

    summary = getattr(observation_cluster, "summary", None)
    return summary or _DEFAULT_OBSERVATION.primary_signal


def _build_observation_summary(observation_cluster: Any) -> ObservationSummaryFact:
    if observation_cluster is None:
        return _DEFAULT_OBSERVATION
    observations = getattr(observation_cluster, "observations", None) or []
    return ObservationSummaryFact(
        primary_signal=_format_primary_signal(observation_cluster),
        cluster_severity=getattr(observation_cluster, "cluster_severity", "LOW") or "LOW",
        observation_count=len(observations),
    )


def _top_eliminated_hypothesis(hypotheses: Any, surviving_hypotheses: Any) -> str:
    """
    Picks the most interesting rejected hypothesis: the one with the
    highest prior that still didn't survive (i.e. the one that looked
    most plausible before evidence ruled it out).
    """
    all_h = list(hypotheses or [])
    surviving_ids = {getattr(h, "hypothesis_id", None) for h in (surviving_hypotheses or [])}
    rejected = [h for h in all_h if getattr(h, "hypothesis_id", None) not in surviving_ids]
    if not rejected:
        return ""
    rejected.sort(key=lambda h: getattr(h, "prior", 0.0), reverse=True)
    top = rejected[0]
    statement = getattr(top, "statement", "")
    reason = getattr(top, "rejection_reason", None) or "evidence did not support it"
    return f"{statement[0].lower() + statement[1:].rstrip('.')} — {reason}" if statement else ""


def _build_diagnosis_summary(diagnosis: Any, hypotheses: Any, surviving_hypotheses: Any) -> DiagnosisSummaryFact:
    if diagnosis is None:
        return _DEFAULT_DIAGNOSIS
    causal_chain = list(getattr(diagnosis, "causal_chain", None) or [])[:4]
    return DiagnosisSummaryFact(
        root_cause=getattr(diagnosis, "root_cause", None) or _DEFAULT_DIAGNOSIS.root_cause,
        confidence_pct=_pct(getattr(diagnosis, "confidence", 0.0)),
        causal_chain=causal_chain,
        top_eliminated_hypothesis=_top_eliminated_hypothesis(hypotheses, surviving_hypotheses),
    )


def _build_impact_summary(impact_matrix: Any) -> ImpactSummaryFact:
    if impact_matrix is None:
        return _DEFAULT_IMPACT
    dominant_dimension = getattr(impact_matrix, "dominant_dimension", None)
    estimates = getattr(impact_matrix, "estimates", None) or {}
    dominant_estimate = estimates.get(dominant_dimension) if dominant_dimension else None
    dominant_magnitude = getattr(dominant_estimate, "magnitude", 0.0) if dominant_estimate else 0.0
    sacrifice_statement = getattr(dominant_estimate, "explanation", "") if dominant_estimate else ""
    return ImpactSummaryFact(
        dominant_dimension=(dominant_dimension or "UNKNOWN").upper()
        if isinstance(dominant_dimension, str)
        else str(dominant_dimension or "UNKNOWN").upper(),
        dominant_magnitude=float(dominant_magnitude or 0.0),
        sacrifice_statement=sacrifice_statement or "",
    )


def _build_decision_summary(decision: Any) -> DecisionSummaryFact:
    if decision is None:
        return _DEFAULT_DECISION
    chosen_option = getattr(decision, "chosen_option", None)
    chosen_action = getattr(chosen_option, "label", None) or _DEFAULT_DECISION.chosen_action
    rejected_alternatives = getattr(decision, "rejected_alternatives", None) or []
    top_rejected_reason = ""
    if rejected_alternatives:
        top_rejected_reason = getattr(rejected_alternatives[0], "rejection_reason", "") or ""
    expected_value = getattr(decision, "expected_value", None)
    if expected_value is None:
        expected_value = getattr(chosen_option, "net_expected_value", 0.0) or 0.0
    return DecisionSummaryFact(
        chosen_action=chosen_action,
        expected_value=float(expected_value or 0.0),
        top_rejected_alternative=top_rejected_reason,
        confidence_pct=_pct(getattr(decision, "confidence", 0.0)),
    )


def _build_recovery_state(recovery_state_machine: Any) -> str:
    if recovery_state_machine is None:
        return "HEALTHY"
    return getattr(recovery_state_machine, "current_state", None) or "HEALTHY"


def build_emios_advisor_input(
    pipeline_result: Any,
    forecast_snapshot: Optional[dict] = None,
    risk_snapshot: Optional[dict] = None,
    project_context: Optional[dict] = None,
) -> EMIOSAdvisorInput:
    """
    Project a PipelineResult into EMIOSAdvisorInput.

    forecast_snapshot / risk_snapshot / project_context are optional flat
    dicts for backward compatibility with the original advisor's fields --
    pass them through from the existing AdvisorInputBuilder projections if
    the caller already has them; they default to empty dicts otherwise
    (the reasoning-chain fields below do not depend on them).
    """
    return EMIOSAdvisorInput(
        forecast_snapshot=forecast_snapshot or {},
        risk_snapshot=risk_snapshot or {},
        project_context=project_context or {},
        observation_summary=_build_observation_summary(
            getattr(pipeline_result, "observation_cluster", None)
        ),
        diagnosis_summary=_build_diagnosis_summary(
            getattr(pipeline_result, "diagnosis", None),
            getattr(pipeline_result, "hypotheses", None),
            getattr(pipeline_result, "surviving_hypotheses", None),
        ),
        impact_summary=_build_impact_summary(getattr(pipeline_result, "impact_matrix", None)),
        decision_summary=_build_decision_summary(getattr(pipeline_result, "decision", None)),
        recovery_state=_build_recovery_state(
            getattr(pipeline_result, "recovery_state_machine", None)
        ),
    )
