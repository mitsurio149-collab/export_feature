"""
Forecast Lever Mutation Regression Tests

Locks in two fixes made together as a pair:

1. forecast_levers.sample_lever_values() used to snapshot list-typed
   attributes (resource.skill_coverage, sprint.capacity_breakdown) by
   reference, not by value. Appending to those lists in an applicator
   silently mutated the "before" snapshot too, so before == after was
   always True and every list-typed lever falsely reported as unchanged.
   Fixed via _snapshot() copying lists to tuples at sample time.

2. candidate_generator._from_spillover_signal's "resource_unavailable"
   branch built a REBALANCE_SPRINT_LOAD candidate whose target resource
   was the SAME resource already flagged as chronically overloaded/
   unavailable -- a guaranteed self-reassignment no-op, since the
   applicator does `item.assigned_resource = resource_id` and the item
   was already assigned to that resource. Fixed by finding a genuinely
   different, underutilized receiver, and suppressing the candidate
   entirely when no such receiver exists (consistent with the pattern
   already used for the UNDERUTILIZED and Fix #7 code paths).

These tests protect against both classes of regression recurring:
  - a future list-typed lever being sampled by reference again
  - a future signal-to-candidate mapping reintroducing a self-target
"""

import os

import pytest

from app.domain.models import (
    ProjectInfo,
    ProjectState,
    Resource,
    SkillCoverage,
    SkillLevel,
    SkillProficiency,
    Sprint,
    SprintCapacityEntry,
    SprintStatus,
    WorkItem,
    WorkItemStatus,
    WorkItemType,
)
from app.engines.forecast_levers import FORECAST_LEVER_MAP, sample_lever_values
from app.engines.recommendation_engine.models import Recommendation, RecommendationAction


# ──────────────────────────────────────────────────────────────────────────
# Unit-level: sample_lever_values snapshot correctness (scalar + list)
# ──────────────────────────────────────────────────────────────────────────

class _FakeRec:
    """Minimal stand-in for Recommendation -- only the fields sample_lever_values reads."""

    def __init__(self, resource_ids=None, sprint_ids=None, item_ids=None, blocker_ids=None):
        self.affected_resource_ids = resource_ids or []
        self.affected_sprint_ids = sprint_ids or []
        self.affected_item_ids = item_ids or []
        self.affected_blocker_ids = blocker_ids or []


class TestSampleLeverValuesSnapshotting:
    """The bug this class guards against: list-typed levers sampled by
    reference instead of by value, making before == after trivially true
    even when the applicator genuinely mutated the list."""

    def _make_resource(self, resource_id="r1"):
        return Resource(
            resource_id=resource_id,
            name=resource_id,
            role="Software Engineer",
            primary_skill="Backend",
            secondary_skill=None,
            skill_level=SkillLevel.SENIOR,
            allocation_pct=0.5,
            availability_pct=1.0,
            daily_capacity_hrs=8.0,
            skill_coverage=[],
        )

    def test_list_lever_detects_append_after_snapshot(self):
        """This is the exact bug: before was a live reference, so appending
        to the list changed 'before' too, and before == after stayed True."""
        resource = self._make_resource("backup_1")
        rec = _FakeRec(resource_ids=["backup_1"])

        class _FakeState:
            team = [resource]

        before = sample_lever_values(_FakeState(), rec, "resource.skill_coverage")
        resource.skill_coverage.append(
            SkillCoverage(skill="Backend", proficiency=SkillProficiency.BACKUP, certified=False)
        )
        after = sample_lever_values(_FakeState(), rec, "resource.skill_coverage")

        assert before != after, (
            "sample_lever_values must snapshot list-typed attributes by value; "
            "appending to the real list changed 'before' too, meaning the "
            "regression from the snapshot-by-reference bug has come back."
        )

    def test_list_lever_reports_no_change_when_nothing_changed(self):
        """Equally important: don't over-correct into false positives when
        the list genuinely didn't change."""
        resource = self._make_resource("backup_1")
        rec = _FakeRec(resource_ids=["backup_1"])

        class _FakeState:
            team = [resource]

        before = sample_lever_values(_FakeState(), rec, "resource.skill_coverage")
        after = sample_lever_values(_FakeState(), rec, "resource.skill_coverage")
        assert before == after

    def test_scalar_lever_still_detects_change(self):
        """Scalar (float) levers were never affected by the reference bug --
        confirm the _snapshot() pass-through doesn't break them."""
        resource = self._make_resource("r1")
        rec = _FakeRec(resource_ids=["r1"])

        class _FakeState:
            team = [resource]

        before = sample_lever_values(_FakeState(), rec, "resource.allocation_pct")
        resource.allocation_pct = min(1.0, resource.allocation_pct + 0.2)
        after = sample_lever_values(_FakeState(), rec, "resource.allocation_pct")
        assert before != after

    def test_scalar_lever_reports_no_change_when_nothing_changed(self):
        resource = self._make_resource("r1")
        rec = _FakeRec(resource_ids=["r1"])

        class _FakeState:
            team = [resource]

        before = sample_lever_values(_FakeState(), rec, "resource.allocation_pct")
        after = sample_lever_values(_FakeState(), rec, "resource.allocation_pct")
        assert before == after


# ──────────────────────────────────────────────────────────────────────────
# End-to-end: recovery-plans pipeline against the real TIO2 workbook
# ──────────────────────────────────────────────────────────────────────────

WORKBOOK_PATH = os.path.join("..", "INPUT", "TIO2_Sprint_Intelligence_v5_final.xlsx")


def _load_real_state():
    from app.parsers.workbook_parser import WorkbookParser
    return WorkbookParser(WORKBOOK_PATH).parse()


@pytest.mark.skipif(not os.path.exists(WORKBOOK_PATH), reason="TIO2 demo workbook not present")
class TestRecoveryPlansNoFalsePositiveLeverWarnings:
    """Regression test for the specific bugs fixed in this session:
    - forecast lever snapshot-by-reference (list-typed levers)
    - REBALANCE_SPRINT_LOAD self-reassignment in _from_spillover_signal

    Runs the real recommend -> simulate -> recovery-plan pipeline against
    the TIO2 workbook and asserts no applicator logs a false "did not
    modify declared forecast levers" warning.
    """

    def test_recovery_plans_generate_without_lever_warnings(self, caplog):
        import logging
        from app.engines.recommendation_engine.models import ScoringWeights
        from app.engines.recommendation_engine.recommendation_engine_v2 import RecommendationEngineV2
        from app.engines.simulation_engine import SimulationEngine
        from app.engines.recovery_plan_engine import RecoveryPlanEngine

        state = _load_real_state()
        rec_engine = RecommendationEngineV2(
            project_state=state, simulation_count=200, scoring_weights=ScoringWeights()
        )
        upstream = rec_engine._compute_upstream()
        sim_engine = SimulationEngine(
            project_state=rec_engine.project_state,
            metrics=upstream.metrics,
            dag=upstream.dag,
            cp_result=upstream.cp_result,
            spillover=upstream.spillover,
            forecast=upstream.forecast,
            monte_carlo=upstream.monte_carlo,
            risk_result=upstream.risk_result,
            simulation_count=200,
        )
        recovery_engine = RecoveryPlanEngine(simulation_engine=sim_engine)

        with caplog.at_level(logging.WARNING):
            recommendations = rec_engine.generate(top_n=20)
            plans = recovery_engine.generate_recovery_plans(recommendations=recommendations)

        assert len(recommendations) > 0
        assert len(plans) == 3

        lever_warnings = [
            r.message for r in caplog.records
            if "did not modify declared forecast levers" in r.message
        ]
        assert lever_warnings == [], (
            "One or more recommendations declared forecast levers they never "
            f"actually mutated: {lever_warnings}. This is either the snapshot-"
            "by-reference bug (list levers) or a self-targeting candidate "
            "(e.g. REBALANCE_SPRINT_LOAD pointed at the already-overloaded "
            "resource) recurring."
        )

    def test_no_recommendation_targets_itself_as_receiver(self):
        """REBALANCE_SPRINT_LOAD specifically: the resource named as the
        receiver (affected_resource_ids[0]) must never be the resource
        already assigned to every affected item -- that's a guaranteed
        self-reassignment no-op."""
        from app.engines.recommendation_engine.models import ScoringWeights
        from app.engines.recommendation_engine.recommendation_engine_v2 import RecommendationEngineV2

        state = _load_real_state()
        rec_engine = RecommendationEngineV2(
            project_state=state, simulation_count=200, scoring_weights=ScoringWeights()
        )
        recommendations = rec_engine.generate(top_n=20)

        rebalance_recs = [
            r for r in recommendations
            if r.action_type == RecommendationAction.REBALANCE_SPRINT_LOAD
        ]
        items_by_id = {wi.item_id: wi for wi in state.work_items}

        for rec in rebalance_recs:
            if not rec.affected_resource_ids or not rec.affected_item_ids:
                continue
            receiver_id = rec.affected_resource_ids[0]
            for item_id in rec.affected_item_ids:
                item = items_by_id.get(item_id)
                if item is None:
                    continue
                assert getattr(item, "assigned_resource", None) != receiver_id, (
                    f"Recommendation {rec.recommendation_id} targets receiver "
                    f"{receiver_id}, but {item_id} is already assigned to them -- "
                    "this is the self-reassignment no-op bug."
                )


# ──────────────────────────────────────────────────────────────────────────
# Coverage: every registered action has a lever declaration
# ──────────────────────────────────────────────────────────────────────────

class TestForecastLeverMapCoverage:
    """Every action the applicator knows how to handle should declare at
    least one forecast lever, and every declared lever path should be
    well-formed (root.attr)."""

    def test_every_declared_lever_path_is_well_formed(self):
        for action, paths in FORECAST_LEVER_MAP.items():
            assert paths, f"{action} declares an empty lever list"
            for path in paths:
                assert "." in path, f"{action} has malformed lever path: {path!r}"
                root, attr = path.split(".", 1)
                assert root in {"work_item", "resource", "sprint", "blocker", "dependency"}, (
                    f"{action} lever {path!r} has unrecognized root {root!r}"
                )
                assert attr, f"{action} lever {path!r} has empty attribute"
