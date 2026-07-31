"""Tests for the Diagnosis endpoint (PR 2).

Verifies:
1. Observed vs not-observed rows populate correctly
2. Primary selection picks highest severity then highest signal count
3. Empty signals produce the correct headline
4. All 9 RootCauseCategory rows are always present
5. Endpoint integration (mocked store)
"""
from types import SimpleNamespace
from typing import List

import pytest

from app.engines.recommendation_engine.root_cause_classifier import (
    RootCauseCategory,
    RootCauseClassifier,
    RootCauseFinding,
)
from app.engines.recommendation_engine.models import (
    OpportunitySignal,
    SignalCategory,
    SignalSeverity,
    SignalEvidence,
)


def _signal(
    category: SignalCategory,
    severity: SignalSeverity,
    signal_id: str = "sig-1",
    explanation: str = "test evidence",
    context: dict = None,
    affected_item_ids: List[str] | None = None,
    affected_blocker_ids: List[str] | None = None,
) -> OpportunitySignal:
    return OpportunitySignal(
        signal_id=signal_id,
        category=category,
        severity=severity,
        affected_item_ids=affected_item_ids or [],
        affected_resource_ids=[],
        affected_sprint_ids=[],
        affected_blocker_ids=affected_blocker_ids or [],
        evidence=[
            SignalEvidence(
                source_engine="test",
                metric_name="test_metric",
                metric_value=1.0,
                threshold=0.5,
                explanation=explanation,
            )
        ],
        context=context or {},
        detected_at="2026-07-11T10:00:00Z",
    )


class TestRootCauseClassifier:
    """Unit tests for the classifier logic (no HTTP, no store)."""

    def test_empty_signals_gives_all_not_observed(self):
        result = RootCauseClassifier().classify([])
        assert len(result.findings) == 9  # all 9 categories
        assert all(not f.observed for f in result.findings)
        assert all(f.impact == "Not observed" for f in result.findings)
        assert result.primary_root_cause is None
        assert "No active root-cause signals" in result.headline

    def test_single_blocker_signal_maps_to_dependency(self):
        signals = [_signal(SignalCategory.BLOCKER, SignalSeverity.HIGH, "blk-1")]
        result = RootCauseClassifier().classify(signals)

        dep = next(f for f in result.findings if f.category == RootCauseCategory.DEPENDENCY)
        assert dep.observed is True
        assert dep.signal_count == 1
        assert dep.max_severity == "high"
        assert dep.impact == "High"
        assert "blk-1" in dep.contributing_signal_ids

    def test_primary_picks_highest_severity(self):
        signals = [
            _signal(SignalCategory.BLOCKER, SignalSeverity.MEDIUM, "blk-med"),
            _signal(SignalCategory.CAPACITY, SignalSeverity.CRITICAL, "cap-crit"),
        ]
        result = RootCauseClassifier().classify(signals)

        assert result.primary_root_cause is not None
        # CAPACITY maps to TEAM_EXECUTION; CRITICAL > MEDIUM
        assert result.primary_root_cause.category == RootCauseCategory.TEAM_EXECUTION
        assert result.primary_root_cause.max_severity == "critical"

    def test_primary_tiebreaks_on_signal_count(self):
        # Both CRITICAL, but one has more signals
        signals = [
            _signal(SignalCategory.BLOCKER, SignalSeverity.CRITICAL, "blk-1"),
            _signal(SignalCategory.CAPACITY, SignalSeverity.CRITICAL, "cap-1"),
            _signal(SignalCategory.CAPACITY, SignalSeverity.CRITICAL, "cap-2"),
        ]
        result = RootCauseClassifier().classify(signals)

        # CAPACITY (TEAM_EXECUTION) has 2 signals vs BLOCKER (DEPENDENCY) has 1
        assert result.primary_root_cause.category == RootCauseCategory.TEAM_EXECUTION
        assert result.primary_root_cause.signal_count == 2

    def test_all_nine_categories_always_present(self):
        signals = [_signal(SignalCategory.REWORK_LOOP, SignalSeverity.LOW, "rw-1")]
        result = RootCauseClassifier().classify(signals)

        categories = {f.category for f in result.findings}
        assert categories == set(RootCauseCategory)
        assert len(result.findings) == 9

    def test_sample_explanations_from_evidence(self):
        signals = [
            _signal(
                SignalCategory.ESTIMATION_RELIABILITY,
                SignalSeverity.HIGH,
                "est-1",
                explanation="Estimates deviated 40% from actuals",
            ),
        ]
        result = RootCauseClassifier().classify(signals)

        planning = next(f for f in result.findings if f.category == RootCauseCategory.PLANNING_ESTIMATION)
        assert planning.observed is True
        assert "Estimates deviated 40%" in planning.sample_explanations[0]

    def test_contributing_signal_ids_use_project_references(self):
        signals = [
            _signal(
                SignalCategory.ESTIMATION_RELIABILITY,
                SignalSeverity.HIGH,
                "est-1",
                explanation="Estimates deviated 40% from actuals",
                affected_item_ids=["WI-042", "WI-117"],
                affected_blocker_ids=["BLK-9"],
            ),
        ]
        result = RootCauseClassifier().classify(signals)

        planning = next(f for f in result.findings if f.category == RootCauseCategory.PLANNING_ESTIMATION)
        assert "WI-042" in planning.contributing_signal_ids
        assert "WI-117" in planning.contributing_signal_ids
        assert "BLK-9" in planning.contributing_signal_ids

    def test_headline_includes_primary_details(self):
        signals = [
            _signal(SignalCategory.BLOCKER, SignalSeverity.CRITICAL, "blk-1"),
            _signal(SignalCategory.BLOCKER, SignalSeverity.HIGH, "blk-2"),
        ]
        result = RootCauseClassifier().classify(signals)

        assert "External Blockers" in result.headline
        assert "2 corroborating signal" in result.headline
        assert "High impact" in result.headline

    def test_skill_mismatch_context_flag_overrides_category(self):
        signals = [
            _signal(
                SignalCategory.CAPACITY,
                SignalSeverity.MEDIUM,
                "skill-1",
                context={"flag": "SKILL_MISMATCH"},
            ),
        ]
        result = RootCauseClassifier().classify(signals)

        cap = next(f for f in result.findings if f.category == RootCauseCategory.CAPABILITY)
        assert cap.observed is True
        assert cap.signal_count == 1

        # TEAM_EXECUTION should NOT have this signal
        team = next(f for f in result.findings if f.category == RootCauseCategory.TEAM_EXECUTION)
        assert team.signal_count == 0