"""
Root Cause Classifier
======================

Implements Phase 2 ("Diagnose why carry-over is occurring") and Phase 3
("Root Cause Analysis") of the Project Recovery Framework.

Every other part of the pipeline (CandidateGenerator, PriorityEngine,
RecoveryPlanEngine) already answers "what should we do?". Nothing answered
"why is this happening?" as a first-class, PM-readable output — recommendations
were generated straight from signals with no diagnostic label attached, which
is the opposite of how a senior manager works: diagnose before prescribing.

This module is a pure re-labeling layer. It does NOT detect anything new —
it takes the OpportunitySignal objects the 15 detectors already produce and
groups/labels them the way the framework's Phase 3 table does:

    Category   | Root Cause         | Impact
    -----------|---------------------|--------
    Planning   | Underestimation     | Medium
    Scope      | Scope Creep         | High
    Dependency | External Blockers   | High
    Technical  | Solution Complexity | Medium
    Capability | Skill Gap           | Medium
    Quality    | Rework              | High
    Process    | Poor Sprint Planning| Medium
    Execution  | Multitasking        | Medium
    Governance | Slow Decisions      | High

Two of the framework's nine categories (Scope, Governance) currently have
no upstream detector emitting signals for them. Rather than silently
omitting them, the classifier marks them NOT_OBSERVED so the gap is visible
to the PM and to future engineering work, instead of quietly pretending
the diagnosis is complete.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

from app.engines.recommendation_engine.models import (
    OpportunitySignal,
    SignalCategory,
    SignalSeverity,
)


class RootCauseCategory(str, Enum):
    """The nine diagnostic buckets from Phase 2 of the recovery framework."""

    PLANNING_ESTIMATION = "estimation"
    SCOPE = "scope"
    DEPENDENCY = "dependency"
    TECHNICAL_COMPLEXITY = "technical_complexity"
    CAPABILITY = "capability"
    QUALITY = "quality"
    SPRINT_PLANNING = "sprint_planning"
    TEAM_EXECUTION = "team_execution"
    GOVERNANCE_DECISIONS = "governance_decisions"


# Human-readable root-cause label per category, matching the Phase 3 table.
_ROOT_CAUSE_LABEL: Dict[RootCauseCategory, str] = {
    RootCauseCategory.PLANNING_ESTIMATION: "Underestimation",
    RootCauseCategory.SCOPE: "Scope Creep",
    RootCauseCategory.DEPENDENCY: "External Blockers",
    RootCauseCategory.TECHNICAL_COMPLEXITY: "Solution Complexity",
    RootCauseCategory.CAPABILITY: "Skill Gap",
    RootCauseCategory.QUALITY: "Rework",
    RootCauseCategory.SPRINT_PLANNING: "Poor Sprint Planning",
    RootCauseCategory.TEAM_EXECUTION: "Multitasking / High WIP",
    RootCauseCategory.GOVERNANCE_DECISIONS: "Slow Decisions",
}

# Default framework impact rating per category (used only when no signals
# are observed for that category, so the PM still sees the doctrine default
# rather than a blank). When signals ARE observed, impact is derived from
# their actual severity instead — real evidence overrides the default.
_DEFAULT_IMPACT: Dict[RootCauseCategory, str] = {
    RootCauseCategory.PLANNING_ESTIMATION: "Medium",
    RootCauseCategory.SCOPE: "High",
    RootCauseCategory.DEPENDENCY: "High",
    RootCauseCategory.TECHNICAL_COMPLEXITY: "Medium",
    RootCauseCategory.CAPABILITY: "Medium",
    RootCauseCategory.QUALITY: "High",
    RootCauseCategory.SPRINT_PLANNING: "Medium",
    RootCauseCategory.TEAM_EXECUTION: "Medium",
    RootCauseCategory.GOVERNANCE_DECISIONS: "High",
}

# Mapping from the detectors' SignalCategory to the framework's diagnostic
# RootCauseCategory. This is the join between "what fired" and "why it fired".
_SIGNAL_TO_ROOT_CAUSE: Dict[SignalCategory, RootCauseCategory] = {
    SignalCategory.ESTIMATION_RELIABILITY: RootCauseCategory.PLANNING_ESTIMATION,
    SignalCategory.BLOCKER: RootCauseCategory.DEPENDENCY,
    SignalCategory.DEPENDENCY: RootCauseCategory.DEPENDENCY,
    SignalCategory.RECURRING_BLOCKER: RootCauseCategory.DEPENDENCY,
    SignalCategory.SPOF: RootCauseCategory.TECHNICAL_COMPLEXITY,
    SignalCategory.CRITICAL_PATH: RootCauseCategory.TECHNICAL_COMPLEXITY,
    SignalCategory.RESEQUENCING: RootCauseCategory.TECHNICAL_COMPLEXITY,
    SignalCategory.RAMP_UP: RootCauseCategory.CAPABILITY,
    SignalCategory.REWORK_LOOP: RootCauseCategory.QUALITY,
    SignalCategory.SPILLOVER: RootCauseCategory.SPRINT_PLANNING,
    SignalCategory.SPRINT: RootCauseCategory.SPRINT_PLANNING,
    SignalCategory.SCHEDULE: RootCauseCategory.SPRINT_PLANNING,
    SignalCategory.CAPACITY: RootCauseCategory.TEAM_EXECUTION,
    SignalCategory.SWARM_TRADEOFF: RootCauseCategory.TEAM_EXECUTION,
    SignalCategory.RISK: RootCauseCategory.TEAM_EXECUTION,
}

# SkillMismatchDetector and LowVelocityDetector both emit under the coarse
# SignalCategory.CAPACITY (see signal_detectors.py) even though they
# represent two different Phase-2 root causes (Capability vs. Team
# Execution). They set a context["flag"] to distinguish themselves, so we
# key off that before falling back to the coarse category mapping.
_CONTEXT_FLAG_OVERRIDE: Dict[str, RootCauseCategory] = {
    "SKILL_MISMATCH": RootCauseCategory.CAPABILITY,
    "LOW_VELOCITY": RootCauseCategory.TEAM_EXECUTION,
}

_SEVERITY_RANK = {
    SignalSeverity.CRITICAL: 4,
    SignalSeverity.HIGH: 3,
    SignalSeverity.MEDIUM: 2,
    SignalSeverity.LOW: 1,
}

_IMPACT_FROM_SEVERITY = {
    4: "High",
    3: "High",
    2: "Medium",
    1: "Low",
}


@dataclass(frozen=True)
class RootCauseFinding:
    """One row of the Phase 3 root-cause table, backed by real evidence."""

    category: RootCauseCategory
    root_cause: str
    impact: str  # "High" | "Medium" | "Low" | "Not observed"
    observed: bool
    signal_count: int
    max_severity: str | None
    contributing_signal_ids: List[str] = field(default_factory=list)
    sample_explanations: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RootCauseAnalysis:
    """Full Phase 3 diagnostic table plus a one-line PM headline."""

    findings: List[RootCauseFinding]
    primary_root_cause: RootCauseFinding | None
    headline: str


class RootCauseClassifier:
    """
    Groups OpportunitySignals into the framework's nine diagnostic
    categories and produces a Phase-3-style root cause table.

    This performs zero new detection — it is a pure classification/labeling
    pass over signals the detectors already emitted, so it never invents a
    finding that isn't backed by real evidence.
    """

    @staticmethod
    def _category_for(signal: OpportunitySignal) -> RootCauseCategory | None:
        flag = (signal.context or {}).get("flag")
        if flag in _CONTEXT_FLAG_OVERRIDE:
            return _CONTEXT_FLAG_OVERRIDE[flag]
        return _SIGNAL_TO_ROOT_CAUSE.get(signal.category)

    def classify(self, signals: List[OpportunitySignal]) -> RootCauseAnalysis:
        grouped: Dict[RootCauseCategory, List[OpportunitySignal]] = defaultdict(list)
        for signal in signals:
            category = self._category_for(signal)
            if category is not None:
                grouped[category].append(signal)

        findings: List[RootCauseFinding] = []
        for category in RootCauseCategory:
            bucket = grouped.get(category, [])
            if not bucket:
                findings.append(
                    RootCauseFinding(
                        category=category,
                        root_cause=_ROOT_CAUSE_LABEL[category],
                        impact="Not observed",
                        observed=False,
                        signal_count=0,
                        max_severity=None,
                        contributing_signal_ids=[],
                        sample_explanations=[],
                    )
                )
                continue

            worst_rank = max(_SEVERITY_RANK.get(s.severity, 1) for s in bucket)
            worst_severity = next(
                s.severity for s in bucket if _SEVERITY_RANK.get(s.severity, 1) == worst_rank
            )
            impact = _IMPACT_FROM_SEVERITY.get(worst_rank, _DEFAULT_IMPACT[category])

            samples = []
            seen_explanations: set = set()
            for s in sorted(bucket, key=lambda x: _SEVERITY_RANK.get(x.severity, 1), reverse=True):
                if s.evidence:
                    text = s.evidence[0].explanation
                    if text and text not in seen_explanations:
                        seen_explanations.add(text)
                        samples.append(text)
                if len(samples) >= 2:
                    break

            findings.append(
                RootCauseFinding(
                    category=category,
                    root_cause=_ROOT_CAUSE_LABEL[category],
                    impact=impact,
                    observed=True,
                    signal_count=len(bucket),
                    max_severity=worst_severity.value,
                    contributing_signal_ids=[s.signal_id for s in bucket],
                    sample_explanations=samples,
                )
            )

        # Primary root cause = observed finding with highest severity rank,
        # tie-broken by signal count (more corroborating evidence wins).
        observed = [f for f in findings if f.observed]
        primary = None
        if observed:
            severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
            primary = max(
                observed,
                key=lambda f: (severity_order.get(f.max_severity, 0), f.signal_count),
            )

        if primary is None:
            headline = "No active root-cause signals detected — project is tracking to plan."
        else:
            headline = (
                f"Primary root cause: {primary.root_cause} "
                f"({primary.category.value.replace('_', ' ')}, {primary.impact} impact, "
                f"{primary.signal_count} corroborating signal"
                f"{'s' if primary.signal_count != 1 else ''})."
            )

        return RootCauseAnalysis(
            findings=findings, primary_root_cause=primary, headline=headline
        )
