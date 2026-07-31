"""
EMIOS Domain Models — Cognition + Knowledge contexts.

Pydantic v2 models for the EMIOS 18-stage cognitive pipeline built on top of
Sprint Whisperer's 9 deterministic engines.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class ObservationDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class DataConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class HypothesisStatus(str, Enum):
    OPEN = "open"
    SUPPORTED = "supported"
    REJECTED = "rejected"


class ImpactDimension(str, Enum):
    SCHEDULE = "schedule"
    QUALITY = "quality"
    RESOURCE = "resource"
    BUSINESS = "business"
    ORGANIZATIONAL = "organizational"


class HealthState(str, Enum):
    HEALTHY = "healthy"
    WATCH = "watch"
    WARNING = "warning"
    CRITICAL = "critical"
    RECOVERY = "recovery"
    RECOVERED = "recovered"


class DecisionStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    EXECUTED = "executed"
    EVALUATED = "evaluated"


class ExecutionPlanStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ADJUSTING = "adjusting"
    COMPLETED = "completed"
    ABORTED = "aborted"


# ---------------------------------------------------------------------------
# Stage 1 — Observation
# ---------------------------------------------------------------------------
class Observation(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    observation_id: str
    metric_ref: str = Field(..., description="Which metric this observes, e.g. 'velocity'")
    magnitude: float = Field(..., description="Signed magnitude of the deviation")
    direction: ObservationDirection
    significance: Literal["HIGH", "MEDIUM", "LOW"] = Field(
        "LOW", description="Coarse significance band, stored directly"
    )
    baseline_ref: Optional[str] = Field(None, description="Baseline this was compared against")
    detected_at: datetime = Field(default_factory=_utcnow)
    source_engine: Optional[str] = Field(None, description="Engine/detector that emitted it")
    current_value: Optional[float] = Field(None, description="Observed metric value")
    baseline_value: Optional[float] = Field(None, description="Expected/baseline metric value")
    deviation_pct: Optional[float] = Field(None, description="(current - baseline) / baseline")
    entity_id: Optional[str] = Field(None, description="sprint_id, resource_id, or None")
    cause: None = Field(None, description="ALWAYS None — an Observation never contains a cause")


class ObservationCluster(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    cluster_id: str
    observations: List[Observation] = Field(default_factory=list)
    detected_at: datetime = Field(default_factory=_utcnow)
    summary: str = Field("", description="Neutral one-line summary, still no cause")
    cluster_severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(
        "LOW", description="Worst observation band; escalates to CRITICAL when 2+ HIGH coincide"
    )
    primary_signal: Optional[Observation] = Field(
        None, description="Single highest-significance observation (also causeless)"
    )


# ---------------------------------------------------------------------------
# Stage 2 — Validation
# ---------------------------------------------------------------------------
class DataQualityIssue(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    issue_type: str = Field(..., description="e.g. 'data_lag', 'mislabeled_sprint', 'pto'")
    description: str
    suppresses_downstream: bool = Field(
        False, description="True if this issue should halt reasoning on the observation"
    )


class ValidatedObservation(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    observation: Observation
    data_confidence: DataConfidence = DataConfidence.MEDIUM
    triangulated_sources: List[str] = Field(default_factory=list)
    issues: List[DataQualityIssue] = Field(default_factory=list)
    is_valid: bool = Field(True, description="False if a suppressing data-quality issue was found")
    validated_at: datetime = Field(default_factory=_utcnow)


class ArtifactType(str, Enum):
    """Why an observation was suppressed during validation."""
    PLANNED_CAPACITY_REDUCTION = "planned_capacity_reduction"  # PTO / part-time sprint
    ESTIMATE_OUTLIER = "estimate_outlier"                      # one giant item skews carryover
    INSUFFICIENT_HISTORY = "insufficient_history"              # < 2 completed sprints
    EARLY_BLOCKER = "early_blocker"                            # raised this sprint, too young
    DELIBERATE_RESCOPE = "deliberate_rescope"                  # NEW: planned re-estimate / spike
    SECONDARY_SKILL_COVERS = "secondary_skill_covers"          # NEW: resource covers req skill


class SuppressedObservation(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    observation: Observation
    artifact_type: ArtifactType
    reason: str = Field(..., description="Human-readable suppression reason")


class ValidationResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    validated: List[Observation] = Field(
        default_factory=list, description="Observations that passed validation"
    )
    suppressed: List[SuppressedObservation] = Field(
        default_factory=list, description="Observations removed as artifacts, with reasons"
    )
    data_confidence: float = Field(
        1.0, ge=0.0, le=1.0, description="1.0 = all validated; drops as observations are suppressed"
    )
    warnings: List[str] = Field(
        default_factory=list, description="Human-readable data-quality notes"
    )
    validated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Stage 3 — Evidence Collection
# ---------------------------------------------------------------------------
class EvidenceItem(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    fact: str
    source: str = Field(..., description="Which engine/entity produced this fact")
    weight: float = Field(1.0, description="Relative evidential weight")
    timestamp: datetime = Field(default_factory=_utcnow)
    supports_hypothesis_ids: List[str] = Field(default_factory=list)
    contradicts_hypothesis_ids: List[str] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    bundle_id: str
    triggered_by_observation_ids: List[str] = Field(default_factory=list)
    items: List[EvidenceItem] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=_utcnow)
    low_confidence_flag: bool = Field(
        False, description="True when upstream data_confidence < 0.5"
    )
    data_confidence: float = Field(
        1.0, ge=0.0, le=1.0, description="Inherited from ValidationResult.data_confidence"
    )


# ---------------------------------------------------------------------------
# Stages 4 & 5 — Hypothesis
# ---------------------------------------------------------------------------
class Hypothesis(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    hypothesis_id: str
    statement: str
    testable_prediction: str = Field(..., description="What must be true if this holds")
    prior: float = Field(0.0, ge=0.0, le=1.0)
    posterior: float = Field(0.0, ge=0.0, le=1.0)
    status: HypothesisStatus = HypothesisStatus.OPEN
    rejection_reason: Optional[str] = Field(
        None, description="Why the evidence killed it (explainability gold)"
    )
    supporting_evidence_ids: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 6 — Root Cause Analysis
# ---------------------------------------------------------------------------
class Diagnosis(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    diagnosis_id: str
    root_cause: str
    causal_chain: List[str] = Field(
        default_factory=list, description="Ordered chain from symptom to root cause (5-Whys)"
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    confidence_interval: Optional[List[float]] = Field(
        None, description="[low, high] bounds on confidence"
    )
    contributing_factors: List[str] = Field(default_factory=list)
    alternative_diagnoses: List[str] = Field(default_factory=list)
    supporting_hypothesis_id: Optional[str] = None
    diagnosed_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Stages 7-11 — Multi-dimensional Impact
# ---------------------------------------------------------------------------
class ImpactEstimate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dimension: ImpactDimension
    magnitude: float = Field(..., description="Dimension-specific magnitude")
    unit: str = Field("", description="Unit of magnitude, e.g. 'days', 'USD', 'score'")
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    explanation: str = ""


class ImpactMatrix(BaseModel):
    """Stages 7-11 output: impact across all five dimensions."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    diagnosis_id: Optional[str] = None
    estimates: Dict[str, ImpactEstimate] = Field(
        default_factory=dict, description="Keyed by ImpactDimension value"
    )
    dominant_dimension: Optional[str] = Field(
        None,
        description=(
            "ImpactDimension.value of the highest-magnitude estimate. Read by the "
            "AI advisor's ImpactSummaryFact and the ReasoningTrace Stage-6 header. "
            "None only when estimates is empty."
        ),
    )
    computed_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Stage 12 — Risk Assessment
# ---------------------------------------------------------------------------
class Risk(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    risk_id: str
    title: str
    probability: float = Field(0.0, ge=0.0, le=1.0)
    severity: float = Field(0.0, description="Impact severity if it materializes")
    exposure_window_days: Optional[float] = Field(None, description="How long the exposure persists")
    time_to_materialize_days: Optional[float] = None
    trend: Optional[str] = Field(None, description="'growing' | 'decaying' | 'stable'")
    owner: Optional[str] = None
    mitigation: Optional[str] = None


# ---------------------------------------------------------------------------
# Stage 13 — Tradeoff Analysis -> TradeoffMatrix
# ---------------------------------------------------------------------------
class TradeoffOption(BaseModel):
    """One candidate action projected across impact dimensions,
    with its explicit sacrifice stated (iron triangle + people + debt).
    There is NEVER a free option — every gain has a cost."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    option_id: str
    recommendation_id: Optional[str] = Field(
        None, description="None for the null (do-nothing) option"
    )
    label: str
    gains: Dict[str, float] = Field(
        default_factory=dict,
        description="dimension -> improvement magnitude (positive = better)",
    )
    sacrifices: Dict[str, float] = Field(
        default_factory=dict,
        description="dimension -> cost magnitude (positive = cost)",
    )
    net_expected_value: float = Field(
        0.0, description="sum(gains) - sum(sacrifices)"
    )
    disruption_level: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"
    reversible: bool = True
    sacrifice_statement: str = Field(
        "", description="Plain English, uses actual data values"
    )
    # Keep backward compat aliases
    projected_impacts: Dict[str, float] = Field(
        default_factory=dict, description="Legacy alias for gains"
    )
    sacrifice: str = Field("", description="Legacy alias for sacrifice_statement")
    expected_value: Optional[float] = Field(
        None, description="Legacy alias for net_expected_value"
    )


class TradeoffMatrix(BaseModel):
    """Stage 13 output: all options with their sacrifices side by side."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    options: List[TradeoffOption] = Field(default_factory=list)
    null_option: Optional[TradeoffOption] = Field(
        None, description="Reference to the do-nothing option"
    )
    dominated_options: List[str] = Field(
        default_factory=list,
        description="recommendation_ids of dominated options",
    )
    computed_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Stage 14 — Decision Making
# ---------------------------------------------------------------------------
class FeasibilityCheck(BaseModel):
    """Stage 14 support model: can the chosen option actually be executed."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    engineering_feasible: bool = Field(
        True, description="EMIOS cannot assess code complexity; defaults True"
    )
    organizational_feasible: bool = True
    blockers: List[str] = Field(default_factory=list)


class BrooksLawCheck(BaseModel):
    """Stage 14 support model: Brooks's Law guardrail for capacity-add options."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    triggered: bool = False
    ramp_window_sprints: int = 0
    verdict: Literal["SAFE", "RISKY", "REJECT"] = "SAFE"
    reasoning: str = ""


class RejectedAlternative(BaseModel):
    """Stage 14 support model: a non-chosen option with its explicit reason."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    option: TradeoffOption
    score: float = 0.0
    rejection_reason: str = ""


class Decision(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # --- canonical Stage 14 fields ---
    id: Optional[str] = None
    chosen_option: Optional[TradeoffOption] = None
    weighted_score: float = 0.0
    rationale: str = ""
    rejected_alternatives: List[RejectedAlternative] = Field(default_factory=list)
    expected_value: Optional[float] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    feasibility_check: Optional[FeasibilityCheck] = None
    brooks_law_check: Optional[BrooksLawCheck] = None
    warning: Optional[str] = Field(
        None, description="Set when all options scored <= 0 and null was chosen"
    )

    # --- legacy aliases (kept so nothing downstream breaks) ---
    decision_id: Optional[str] = None
    chosen_option_id: Optional[str] = None
    rejected_option_ids: List[str] = Field(default_factory=list)
    rejected_reasons: Dict[str, str] = Field(
        default_factory=dict, description="option_id -> why it was rejected"
    )
    feasibility_gates_passed: bool = True
    status: DecisionStatus = DecisionStatus.PROPOSED
    decided_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Stage 15 — Execution Planning
# ---------------------------------------------------------------------------
class ExecutionStep(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_id: str
    description: str
    owner: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)
    kpi_target: Optional[str] = None


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    plan_id: str
    decision_id: Optional[str] = None
    steps: List[ExecutionStep] = Field(default_factory=list)
    kpi_targets: Dict[str, float] = Field(default_factory=dict)
    exit_conditions: List[str] = Field(default_factory=list)
    rollback_plan: Optional[str] = None
    target_health_state: HealthState = HealthState.RECOVERED
    status: ExecutionPlanStatus = ExecutionPlanStatus.DRAFT
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Stage 16 — Monitoring
# ---------------------------------------------------------------------------
class KPIDeviation(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    kpi_name: str
    predicted: float
    actual: float
    deviation: float = Field(..., description="actual - predicted")
    within_tolerance: bool = True


class TrajectoryConformance(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    plan_id: Optional[str] = None
    deviations: List[KPIDeviation] = Field(default_factory=list)
    on_trajectory: bool = True
    early_abort_triggered: bool = False
    current_health_state: HealthState = HealthState.HEALTHY
    checked_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Stage 17 — Learning
# ---------------------------------------------------------------------------
class ActualSprintOutcome(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    sprint_id: str
    actual_velocity_hrs: float
    actual_delay_days: Optional[float] = Field(None, description="None if sprint in progress")
    blocker_ids_resolved: List[str] = Field(default_factory=list)
    item_ids_completed: List[str] = Field(default_factory=list)
    diagnosis_confirmed: Optional[bool] = Field(None, description="PM manually flags correctness")


class LearningRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # --- canonical Stage 17a fields ---
    id: Optional[str] = None
    episode_date: datetime = Field(default_factory=_utcnow)
    forecast_probability: float = 0.5
    actual_outcome: Optional[float] = Field(
        None, description="1.0=on time, 0.0=late, None=unknown"
    )
    brier_score: Optional[float] = Field(None, description="(forecast - actual)^2, None if no outcome")
    diagnosis_accuracy: Optional[float] = Field(
        None, description="1.0=confirmed, 0.0=denied, None=unknown"
    )
    velocity_estimate_bias: float = 0.0
    calibration_note: str = ""
    retained_pattern: Optional[str] = None
    recommended_prior_adjustment: float = 0.0

    # --- legacy aliases (kept so nothing downstream breaks) ---
    record_id: Optional[str] = None
    episode_ref: Optional[str] = Field(None, description="Which decision/plan episode this evaluates")
    diagnosis_was_correct: Optional[bool] = None
    decision_was_good: Optional[bool] = None
    what_worked: List[str] = Field(default_factory=list)
    what_didnt: List[str] = Field(default_factory=list)
    updated_priors: Dict[str, float] = Field(default_factory=dict)
    learned_at: datetime = Field(default_factory=_utcnow)


class CalibrationProfile(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    team_id: str
    velocity_bias: float = 0.0
    probability_overestimate: float = 0.0
    brier_scores: List[float] = Field(default_factory=list)
    episode_count: int = 0
    last_updated: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Stage 18 — Knowledge Retention
# ---------------------------------------------------------------------------
class KnowledgeNode(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    node_id: str
    pattern: str = Field(..., description="The reusable lesson/pattern")
    context_tags: List[str] = Field(
        default_factory=list, description="e.g. domain, team-type, scale"
    )
    applicability_conditions: List[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    provenance: Optional[str] = Field(None, description="Which engine + model version produced it")
    retained_at: datetime = Field(default_factory=_utcnow)

# ---------------------------------------------------------------------------
# Stage 17b — HistoricalAnalyzer (Phase 6b)
# ---------------------------------------------------------------------------
class OverbillingInstance(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    item_id: str
    item_title: str
    sprint_id: str
    estimated_hrs: float
    actual_hrs: float
    overrun_hrs: float
    overrun_pct: float
    assigned_to: str
    required_skill: str
    was_flagged: bool = Field(False, description="True if a blocker existed for this item")
    first_flagged_sprint: Optional[str] = None


class SpilloverInstance(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    item_id: str
    item_title: str
    original_sprint: str
    landed_sprint: str
    sprints_delayed: int
    reason_category: Literal["BLOCKER", "DEPENDENCY", "CAPACITY", "UNKNOWN"]
    recurred: bool = Field(False, description="True if delayed more than once (sprints_delayed > 1)")
    root_blocker_id: Optional[str] = None


class RecurringBlockerPattern(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    category: str
    occurrences: int
    sprint_ids: List[str] = Field(default_factory=list)
    total_delay_days: float = 0.0
    was_resolved_permanently: bool = False
    recurrence_verdict: Literal["SYSTEMIC", "COINCIDENTAL", "UNRESOLVED"] = "COINCIDENTAL"


class CascadePattern(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    trigger_item_id: str
    cascade_item_ids: List[str] = Field(default_factory=list)
    total_cascade_delay_sprints: int = 0


class PreventionRecommendation(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    trigger: str
    action: str
    sprint_to_apply: Literal["NEXT", "PLANNING", "IMMEDIATELY"]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    evidence: List[str] = Field(default_factory=list)


class HistoricalAnalysis(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    analysis_id: str
    sprints_analysed: int
    overbilling: List[OverbillingInstance] = Field(default_factory=list)
    spillover: List[SpilloverInstance] = Field(default_factory=list)
    recurring_blockers: List[RecurringBlockerPattern] = Field(default_factory=list)
    cascade_patterns: List[CascadePattern] = Field(default_factory=list)
    prevention_recommendations: List[PreventionRecommendation] = Field(default_factory=list)
    summary: str = ""
    generated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Stage 16 — RecoveryStateMachine (Phase 5)
# ---------------------------------------------------------------------------
class StateTransition(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    from_state: str
    to_state: str
    trigger: str = Field(..., description="Plain English reason")
    probability_at_transition: float
    timestamp: datetime = Field(default_factory=_utcnow)


class ExitKPI(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    metric: str
    current_value: float
    target_value: float
    target_by: str = Field(..., description='Sprint name or "Next sprint"')
    status: Literal["ON_TRACK", "AT_RISK", "BREACHED"]


class ActiveRecoveryPlan(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    actions: List[str] = Field(
        default_factory=list, description="Action labels, not full Recommendation objects"
    )
    state_label: str
    urgency: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    owner: str = Field(..., description='First action owner or "Project Manager"')
    narrative: str


class RecoveryStateMachineResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    current_state: str
    previous_state: Optional[str] = None
    transition_occurred: bool = False
    transition_reason: Optional[str] = None
    active_plan: ActiveRecoveryPlan
    exit_kpis: List[ExitKPI] = Field(default_factory=list)
    rollback_trigger: str
    monitoring_intensity: Literal["STANDARD", "ELEVATED", "INTENSIVE"]
