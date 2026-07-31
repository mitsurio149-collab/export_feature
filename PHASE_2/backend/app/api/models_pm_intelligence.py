"""Typed API contract for PM Decision Intelligence (Phase 2 API-layer gap fix).

This module is the *single* place where the domain-layer PM Intelligence
objects (``app.engines.recommendation_engine.pm_models``) are given a typed
API shape. It is consumed by both:

- ``app/api/routes/recommendations.py``   (GET /api/recommendations)
- ``app/api/routes/recovery_plans.py``    (GET /api/recovery-plans)

so the two endpoints expose an identical ``pm_intelligence`` contract instead
of each route hand-rolling its own mapping.

Design choice — why this reuses ``.to_dict()`` instead of re-mapping fields:
The domain dataclasses in ``pm_models.py`` already carry correct, unit-tested
``to_dict()`` methods (see ``tests/test_pm_decision_intelligence.py``). Rather
than duplicating that field-by-field mapping here (which would create a
second, driftable source of truth), these Pydantic models declare the typed
*shape* for OpenAPI/Swagger and client typing, and ``model_validate()``
simply validates the already-correct dict against that shape. If a domain
field is ever renamed, validation fails loudly here instead of silently
drifting — which is the behavior you want at an API boundary.

No business logic, no recalculation, no changes to the domain layer.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Impact Dimension primitives
# ---------------------------------------------------------------------------

class StructuredEvidenceResponse(BaseModel):
    """Machine-readable evidence backing an impact dimension."""

    metric: str = Field(..., description="Metric identifier, e.g. 'bus_factor'")
    value: float = Field(..., description="Numeric value of the metric")
    target: str = Field(..., description="What the metric applies to (skill, resource, sprint, blocker, ...)")
    message: str = Field(..., description="Human-readable evidence statement")


class ConfidenceWithReasonResponse(BaseModel):
    """Confidence level plus the reason it was assigned."""

    level: str = Field(..., description="Very High | High | Medium | Low")
    reason: str = Field(..., description="Why this confidence level was assigned")


class ImpactDimensionResponse(BaseModel):
    """A single scored axis of recommendation impact.

    ``type`` is the stable canonical identifier (schedule, risk, resilience,
    quality, forecast, governance, resource). Presentation (title, icon,
    order, color) is a frontend concern and intentionally not part of this
    contract.
    """

    type: str = Field(..., description="Canonical dimension identifier")
    score: float = Field(..., description="Normalised 0.0-1.0")
    confidence: ConfidenceWithReasonResponse
    evidence: StructuredEvidenceResponse
    explanation: str = Field(..., description="One sentence explaining why this dimension matters")
    source: str = Field(..., description="Typed engine that produced this dimension")


# ---------------------------------------------------------------------------
# Decision Context / Impact Metrics
# ---------------------------------------------------------------------------

class RecommendationDecisionContextResponse(BaseModel):
    """What the PM should do, and when."""

    intent: str = Field(..., description="Recover | Protect | Prevent | Improve | Govern | Prepare")
    execution_window: str = Field(..., description="Immediately | Current Sprint | Next Sprint | Before Release | Long Term")


class RecommendationImpactMetricsResponse(BaseModel):
    """Scored dimensions with typed source attribution."""

    dimensions: List[ImpactDimensionResponse] = Field(default_factory=list)
    primary_dimension: str = Field(..., description="Highest-scoring canonical dimension type")
    impact_tier: str = Field(..., description="High | Medium | Low")
    aggregate_confidence: str = Field(..., description="Very High | High | Medium | Low (conservative min across dimensions)")


# ---------------------------------------------------------------------------
# PM Explanation
# ---------------------------------------------------------------------------

class PMExplanationResponse(BaseModel):
    """Answers every PM question for a recommendation."""

    trigger_reason: str
    trigger_detail: str
    primary_objective: str
    strategic_benefits: List[str] = Field(default_factory=list)
    ignore_consequence: str
    implementation_effort: str
    is_immediate_impact: bool
    impact_horizon: str
    expected_outcome: str = ""
    trade_offs: List[str] = Field(default_factory=list)
    evidence_narrative: str = ""


# ---------------------------------------------------------------------------
# Impact Profile (composition root)
# ---------------------------------------------------------------------------

class RecommendationImpactProfileResponse(BaseModel):
    """Composes decision context + impact metrics + explanation.

    ``schema_version`` is serialised on every response so clients can branch
    on it without silent breakage if this contract evolves.
    """

    schema_version: str
    decision_context: RecommendationDecisionContextResponse
    impact_metrics: RecommendationImpactMetricsResponse
    explanation: PMExplanationResponse


# ---------------------------------------------------------------------------
# PM Decision Score
# ---------------------------------------------------------------------------

class PMDecisionScoreResponse(BaseModel):
    """Multi-dimensional scoring reflecting how a PM actually prioritises."""

    schedule_benefit: float = 0.0
    risk_reduction: float = 0.0
    delivery_confidence: float = 0.0
    resource_health: float = 0.0
    governance_improvement: float = 0.0
    implementation_cost: float = 0.0
    urgency: float = 0.0
    composite: float = 0.0


# ---------------------------------------------------------------------------
# Top-level container
# ---------------------------------------------------------------------------

class PMIntelligenceResponse(BaseModel):
    """Everything a PM needs to make a smart decision on a recommendation.

    ``is_preventive`` mirrors the domain flag — True for recommendations whose
    primary value is long-term project health (e.g. CROSS_TRAIN_BACKUP,
    FREEZE_SCOPE_REQUEST) rather than an immediately measurable schedule delta.
    The frontend uses this to show a descriptive benefit label instead of a
    near-zero day figure.

    Exposed identically by both the Recommendation endpoint and the Recovery
    Plan endpoint via ``serialize_pm_intelligence()`` below.
    """

    classification: str = Field(..., description="Tactical | Strategic | Hybrid")
    pm_decision_score: PMDecisionScoreResponse
    explanation: PMExplanationResponse
    impact_profile: Optional[RecommendationImpactProfileResponse] = None
    is_preventive: bool = Field(
        default=False,
        description=(
            "True for long-term health recommendations (e.g. cross-train, "
            "freeze scope) whose primary value is project resilience rather "
            "than an immediately measurable schedule delta. The frontend uses "
            "this to display a descriptive benefit label instead of a "
            "near-zero day figure."
        ),
    )


# ---------------------------------------------------------------------------
# Shared serializer — single call site for both routes
# ---------------------------------------------------------------------------

def serialize_pm_intelligence(rec) -> Optional[PMIntelligenceResponse]:
    """Build the typed API response for a domain ``Recommendation``'s
    ``pm_intelligence``, or ``None`` if it wasn't attached.

    Delegates the actual field mapping to the domain object's own
    (unit-tested) ``to_dict()`` — this function only validates that dict
    against the typed contract above. No recalculation, no business logic.
    """
    pmi = getattr(rec, "pm_intelligence", None)
    if pmi is None:
        return None
    return PMIntelligenceResponse.model_validate(pmi.to_dict())
