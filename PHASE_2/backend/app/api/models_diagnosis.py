"""Response models for the Diagnosis endpoint (PR 2).

Mirrors the dataclass shapes in root_cause_classifier.py as Pydantic v2
models suitable for API serialization.
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class RootCauseFindingResponse(BaseModel):
    """One row of the Phase-3 root cause table."""

    category: str = Field(
        ...,
        description=(
            "Diagnostic category: estimation, scope, dependency, "
            "technical_complexity, capability, quality, sprint_planning, "
            "team_execution, governance_decisions"
        ),
    )
    root_cause: str = Field(
        ...,
        description="Human-readable root cause label (e.g. 'Underestimation', 'External Blockers')",
    )
    impact: str = Field(
        ...,
        description="Impact rating: 'High', 'Medium', 'Low', or 'Not observed'",
    )
    observed: bool = Field(
        ...,
        description="True if at least one signal was detected for this category",
    )
    signal_count: int = Field(
        ...,
        ge=0,
        description="Number of corroborating signals detected",
    )
    max_severity: Optional[str] = Field(
        None,
        description="Worst severity among contributing signals (critical/high/medium/low)",
    )
    contributing_signal_ids: List[str] = Field(
        default_factory=list,
        description="IDs of signals backing this finding",
    )
    sample_explanations: List[str] = Field(
        default_factory=list,
        description="Top 1-2 evidence explanations from the highest-severity signals",
    )


class DiagnosisResponse(BaseModel):
    """Full Phase-3 diagnosis payload."""

    session_id: str = Field(..., description="Session ID")
    headline: str = Field(
        ...,
        description=(
            "One-line PM-readable diagnosis headline. E.g. "
            "'Primary root cause: External Blockers (dependency, High impact, 3 signals).'"
        ),
    )
    primary_root_cause: Optional[RootCauseFindingResponse] = Field(
        None,
        description="The observed finding with highest severity (tie-broken by signal count)",
    )
    findings: List[RootCauseFindingResponse] = Field(
        default_factory=list,
        description="All 9 diagnostic category rows (observed + not-observed)",
    )
