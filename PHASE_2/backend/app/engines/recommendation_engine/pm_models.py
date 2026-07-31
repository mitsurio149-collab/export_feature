"""pm_models.py — Phase 2 PM Decision Intelligence model extensions.

These dataclasses and enums are *additive only*.  They are attached to
Recommendation via the ``pm_intelligence`` field (default=None) so all
existing callers and tests continue to work unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ---------------------------------------------------------------------------
# v3.2 — canonical taxonomy, typed engine sources, structured evidence
# ---------------------------------------------------------------------------

class ImpactDimensionType(str, Enum):
    """
    Stable canonical identifiers for impact dimensions.
    These are the keys — presentation (title, icon, order) lives in the frontend.
    """
    SCHEDULE = "schedule"
    RISK = "risk"
    RESILIENCE = "resilience"
    QUALITY = "quality"
    FORECAST = "forecast"
    GOVERNANCE = "governance"
    RESOURCE = "resource"


class ImpactConfidence(str, Enum):
    VERY_HIGH = "Very High"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class EngineSource(str, Enum):
    """
    Typed identifiers for producing engines.
    Replaces free-text strings; no string comparisons in routing or AI prompts.
    """
    RISK_ENGINE = "risk_engine"
    FORECAST_ENGINE = "forecast_engine"
    RESOURCE_ENGINE = "resource_engine"
    SIMULATION = "simulation"
    HEURISTIC = "heuristic"


@dataclass(frozen=True)
class StructuredEvidence:
    """
    Machine-readable evidence — AI and strategy builder consume this directly.
    `message` is the human-readable fallback for display.
    """
    metric: str    # e.g. "bus_factor", "estimation_error_pct", "delay_days"
    value: float   # numeric value of the metric
    target: str    # e.g. skill name, resource id, sprint id, blocker id
    message: str   # human-readable: "Only 1 of 5 team members cover AUTOSAR"

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "value": round(self.value, 4),
            "target": self.target,
            "message": self.message,
        }


@dataclass(frozen=True)
class ConfidenceWithReason:
    """
    Confidence level + the one-sentence reason it was assigned.
    Trust is earned by explanation, not by assertion.
    """
    level: ImpactConfidence
    reason: str  # e.g. "Simulation validated estimate", "Heuristic; limited historical data"

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "reason": self.reason,
        }


@dataclass
class ImpactDimension:
    """
    A single scored axis of recommendation impact — domain data only.
    Presentation (title, icon, display_order, color, category) lives in
    frontend DimensionConfig, keyed by `type`.

    `type`        canonical ImpactDimensionType value — stable identifier.
    `score`       normalised 0.0-1.0.
    `confidence`  per-dimension certainty with explanation.
    `evidence`    structured machine-readable proof.
    `explanation` one sentence teaching why this matters.
    `source`      typed engine that produced this dimension.
    """
    type: ImpactDimensionType
    score: float
    confidence: ConfidenceWithReason
    evidence: StructuredEvidence
    explanation: str
    source: EngineSource

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "score": round(self.score, 4),
            "confidence": self.confidence.to_dict(),
            "evidence": self.evidence.to_dict(),
            "explanation": self.explanation,
            "source": self.source.value,
        }


class RecommendationIntent(str, Enum):
    RECOVER = "Recover"
    PROTECT = "Protect"
    PREVENT = "Prevent"
    IMPROVE = "Improve"
    GOVERN = "Govern"
    PREPARE = "Prepare"


class ExecutionWindow(str, Enum):
    IMMEDIATELY = "Immediately"
    CURRENT_SPRINT = "Current Sprint"
    NEXT_SPRINT = "Next Sprint"
    BEFORE_RELEASE = "Before Release"
    LONG_TERM = "Long Term"


@dataclass
class RecommendationDecisionContext:
    """What the PM should do and when."""
    intent: RecommendationIntent
    execution_window: ExecutionWindow

    def to_dict(self) -> dict:
        return {
            "intent": self.intent.value,
            "execution_window": self.execution_window.value,
        }


@dataclass
class RecommendationImpactMetrics:
    """
    Scored dimensions with typed source attribution and per-dimension confidence.
    Pure numbers — no prose.
    """
    dimensions: List[ImpactDimension]
    primary_dimension: ImpactDimensionType   # highest-scoring canonical type
    impact_tier: str                          # "High" | "Medium" | "Low"
    aggregate_confidence: ImpactConfidence  # conservative min across dims

    def to_dict(self) -> dict:
        return {
            "dimensions": [d.to_dict() for d in self.dimensions],
            "primary_dimension": self.primary_dimension.value,
            "impact_tier": self.impact_tier,
            "aggregate_confidence": self.aggregate_confidence.value,
        }


# ---------------------------------------------------------------------------
# New enums
# ---------------------------------------------------------------------------

class RecommendationObjective(str, Enum):
    """Primary project management objective this recommendation improves."""
    SCHEDULE_OPTIMIZATION = "Schedule Optimization"
    RISK_MITIGATION = "Risk Mitigation"
    RESOURCE_OPTIMIZATION = "Resource Optimization"
    FORECAST_RELIABILITY = "Forecast Reliability"
    DELIVERY_GOVERNANCE = "Delivery Governance"
    QUALITY_IMPROVEMENT = "Quality Improvement"
    KNOWLEDGE_RESILIENCE = "Knowledge Resilience"
    DELIVERY_CONFIDENCE = "Delivery Confidence"


class RecommendationClassification(str, Enum):
    """Tactical vs. Strategic impact horizon."""
    TACTICAL = "Tactical"
    STRATEGIC = "Strategic"
    HYBRID = "Hybrid"


class ImplementationEffort(str, Enum):
    """Rough effort to implement this recommendation."""
    LOW = "Low"        # < 1 day
    MEDIUM = "Medium"  # 2–3 days
    HIGH = "High"      # 1 sprint


class TriggerReason(str, Enum):
    """Why this recommendation was generated — the detected project signal."""
    CRITICAL_PATH_DEPENDENCY = "Critical Path Dependency"
    RESOURCE_OVERLOAD = "Resource Overload"
    RESOURCE_UNDERUTILIZATION = "Resource Underutilization"
    SINGLE_POINT_OF_FAILURE = "Single Point of Failure"
    HIGH_BLOCKER_EXPOSURE = "High Blocker Exposure"
    SCOPE_VOLATILITY = "Scope Volatility"
    DELIVERY_RISK = "Delivery Risk"
    LOW_FORECAST_CONFIDENCE = "Low Forecast Confidence"
    CAPACITY_IMBALANCE = "Capacity Imbalance"
    RECURRING_BLOCKER = "Recurring Blocker Pattern"
    SKILL_MISMATCH = "Skill Mismatch"
    ESTIMATION_DRIFT = "Estimation Drift"
    REWORK_LOOP = "Rework Loop Detected"
    VELOCITY_DECLINE = "Velocity Decline"
    SPILLOVER_RISK = "Spillover Risk"


# ---------------------------------------------------------------------------
# PM Decision Score — replaces the single delay-reduction number
# ---------------------------------------------------------------------------

@dataclass
class PMDecisionScore:
    """Multi-dimensional scoring that reflects how a PM actually prioritises.

    All sub-scores are normalised 0.0–1.0.
    ``composite`` is the final weighted score used for ranking.
    """
    schedule_benefit: float = 0.0       # delay / OTP improvement
    risk_reduction: float = 0.0         # overall risk delta
    delivery_confidence: float = 0.0    # forecast reliability improvement
    resource_health: float = 0.0        # workload balance / SPOF removal
    governance_improvement: float = 0.0 # review gates, scope freeze, escalation
    implementation_cost: float = 0.0    # 0=cheap, 1=expensive (inverted for ranking)
    urgency: float = 0.0                # overdue multiplier / time-criticality
    forecast_improvement: float = 0.0   # improvement in forecast accuracy/confidence
    long_term_resilience: float = 0.0   # SPOF / bus-factor risk reduction
    composite: float = 0.0              # final weighted score

    def to_dict(self) -> dict:
        return {
            "schedule_benefit": round(self.schedule_benefit, 4),
            "risk_reduction": round(self.risk_reduction, 4),
            "delivery_confidence": round(self.delivery_confidence, 4),
            "resource_health": round(self.resource_health, 4),
            "governance_improvement": round(self.governance_improvement, 4),
            "implementation_cost": round(self.implementation_cost, 4),
            "urgency": round(self.urgency, 4),
            "forecast_improvement": round(self.forecast_improvement, 4),
            "long_term_resilience": round(self.long_term_resilience, 4),
            "composite": round(self.composite, 4),
        }


# ---------------------------------------------------------------------------
# Structured PM Explanation
# ---------------------------------------------------------------------------

@dataclass
class PMExplanation:
    """
    Answers every PM question for a recommendation — the single narrative object.

    v3.2 merges the previous RecommendationNarrative (expected_outcome,
    trade_offs, evidence_narrative) into this dataclass so there is one place
    to maintain explanation logic. The three new fields default to empty so
    existing callers that only populate the original five questions keep
    working unchanged.
    """
    # ── Original fields ──────────────────────────────────────────────────
    trigger_reason: TriggerReason
    trigger_detail: str               # one-sentence signal description with data
    primary_objective: RecommendationObjective
    strategic_benefits: List[str]     # bullet-style benefit statements
    ignore_consequence: str           # what happens if PM ignores this
    implementation_effort: ImplementationEffort
    is_immediate_impact: bool         # True=tactical benefit now, False=future sprint
    impact_horizon: str               # "Immediate" | "Next Sprint" | "Long Term"

    # ── Added in v3.2 (previously RecommendationNarrative) ──────────────
    expected_outcome: str = ""              # one sentence grounded in primary dimension
    trade_offs: List[str] = field(default_factory=list)   # severity-scaled plain-English strings
    evidence_narrative: str = ""            # "Why the engine flagged this" with real metrics

    def to_dict(self) -> dict:
        return {
            "trigger_reason": self.trigger_reason.value,
            "trigger_detail": self.trigger_detail,
            "primary_objective": self.primary_objective.value,
            "strategic_benefits": self.strategic_benefits,
            "ignore_consequence": self.ignore_consequence,
            "implementation_effort": self.implementation_effort.value,
            "is_immediate_impact": self.is_immediate_impact,
            "impact_horizon": self.impact_horizon,
            "expected_outcome": self.expected_outcome,
            "trade_offs": self.trade_offs,
            "evidence_narrative": self.evidence_narrative,
        }


# ---------------------------------------------------------------------------
# Impact profile — thin composition with schema version (v3.2)
# ---------------------------------------------------------------------------

IMPACT_PROFILE_SCHEMA_VERSION = "3.2"


@dataclass
class RecommendationImpactProfile:
    """
    Composes DecisionContext + ImpactMetrics + PMExplanation (extended).
    This is a long-lived API contract — schema_version is serialised on every
    response so consumers can branch on it without silent breakage.
    """
    decision_context: RecommendationDecisionContext
    impact_metrics: RecommendationImpactMetrics
    explanation: PMExplanation   # single narrative; no separate Narrative object

    # Convenience pass-throughs
    @property
    def intent(self) -> RecommendationIntent:
        return self.decision_context.intent

    @property
    def execution_window(self) -> ExecutionWindow:
        return self.decision_context.execution_window

    @property
    def dimensions(self) -> List[ImpactDimension]:
        return self.impact_metrics.dimensions

    @property
    def confidence(self) -> ImpactConfidence:
        return self.impact_metrics.aggregate_confidence

    def impact_tier(self) -> str:
        return self.impact_metrics.impact_tier

    def primary_dimension(self) -> str:
        return self.impact_metrics.primary_dimension.value

    def to_dict(self) -> dict:
        return {
            "schema_version": IMPACT_PROFILE_SCHEMA_VERSION,
            "decision_context": self.decision_context.to_dict(),
            "impact_metrics": self.impact_metrics.to_dict(),
            "explanation": self.explanation.to_dict(),
        }


# ---------------------------------------------------------------------------
# Top-level container attached to Recommendation
# ---------------------------------------------------------------------------

@dataclass
class PMIntelligence:
    """Everything a PM needs to make a smart decision on this recommendation.

    Note: ``explanation`` and ``impact_profile.explanation`` (when present)
    point to the **same** PMExplanation object — the priority engine builds
    one PMExplanation and passes it to both. No duplication.

    ``is_preventive`` is True for actions whose primary value is long-term
    project health (CROSS_TRAIN_BACKUP, FREEZE_SCOPE_REQUEST, etc.) rather
    than an immediately measurable schedule/risk delta.  The frontend uses
    this flag to show a descriptive benefit label instead of a near-zero
    numeric day figure.
    """
    classification: RecommendationClassification
    pm_decision_score: PMDecisionScore
    explanation: PMExplanation
    impact_profile: Optional[RecommendationImpactProfile] = field(default=None)
    is_preventive: bool = False

    def to_dict(self) -> dict:
        d = {
            "classification": self.classification.value,
            "pm_decision_score": self.pm_decision_score.to_dict(),
            "explanation": self.explanation.to_dict(),
            "is_preventive": self.is_preventive,
        }
        if self.impact_profile is not None:
            d["impact_profile"] = self.impact_profile.to_dict()
        return d
