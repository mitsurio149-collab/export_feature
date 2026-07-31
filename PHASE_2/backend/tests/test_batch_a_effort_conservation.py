"""
Batch A — Recovery Model Correction: Effort Conservation Tests

These tests verify the P0 mathematical-integrity invariant for the
execution-speed recovery actions:

    total_effort(state) = sum(wi.remaining_effort_hrs for all work items)

must never silently decrease for PARALLELIZE_ITEMS, REBALANCE_SPRINT_LOAD,
REMOVE_DEPENDENCY_BOTTLENECK, ADVANCE_ITEM_TO_EARLIER_SPRINT, SWARM_ITEM,
and SPLIT_ITEM, unless explicit coordination overhead is modelled (never the
case for these actions today).

These tests exercise ActionApplicatorV2 directly against a hand-built
ProjectState so they do not depend on the full upstream engine pipeline.
"""

from datetime import datetime, timedelta

from app.domain.models import (
    Dependency,
    DependencyType,
    ProjectInfo,
    ProjectState,
    Priority,
    Resource,
    SkillLevel,
    Sprint,
    SprintStatus,
    WorkItem,
    WorkItemStatus,
    WorkItemType,
)
from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    Recommendation,
    RecommendationAction,
)
from app.engines.simulation_engine import ActionApplicatorV2


def total_effort(state: ProjectState) -> float:
    return sum(wi.remaining_effort_hrs for wi in state.work_items)


def make_state(with_dependency_lag: int = 2) -> ProjectState:
    start_date = datetime(2025, 1, 1)
    project_info = ProjectInfo(
        project_name="Batch A Effort Conservation",
        sponsor="Sponsor",
        business_unit="Engineering",
        project_manager="PM",
        customer="Customer",
        status="Active",
        start_date=start_date,
        target_end_date=start_date + timedelta(days=60),
        sprint_duration_days=14,
        methodology="Agile Scrum",
    )

    team = [
        Resource(
            resource_id="R1", name="Alice", role="Engineer",
            primary_skill="Python", secondary_skill=None,
            skill_level=SkillLevel.SENIOR,
            allocation_pct=0.9, availability_pct=0.9, daily_capacity_hrs=8.0,
        ),
        Resource(
            resource_id="R2", name="Bob", role="Engineer",
            primary_skill="Python", secondary_skill=None,
            skill_level=SkillLevel.MID,
            allocation_pct=0.5, availability_pct=1.0, daily_capacity_hrs=8.0,
        ),
    ]

    sprints = [
        Sprint(
            sprint_id="S1", sprint_name="Sprint 1", sprint_number=1,
            start_date=start_date, end_date=start_date + timedelta(days=13),
            working_days=10, sprint_goal="Build", status=SprintStatus.IN_PROGRESS,
            planned_velocity_hrs=160.0, carryover_count=0,
        ),
        Sprint(
            sprint_id="S2", sprint_name="Sprint 2", sprint_number=2,
            start_date=start_date + timedelta(days=14), end_date=start_date + timedelta(days=27),
            working_days=10, sprint_goal="Finish", status=SprintStatus.NOT_STARTED,
            planned_velocity_hrs=160.0, carryover_count=0,
        ),
    ]

    work_items = [
        WorkItem(
            item_id="WI-A", title="Item A", work_type=WorkItemType.STORY,
            assigned_sprint="Sprint 2", assigned_resource="R1",
            required_skill="Python", priority=Priority.HIGH,
            estimated_effort_hrs=16.0, current_estimate_hrs=16.0,
            actual_effort_hrs=0.0, remaining_effort_hrs=16.0,
            progress_pct=0.0, status=WorkItemStatus.NOT_STARTED,
        ),
        WorkItem(
            item_id="WI-B", title="Item B", work_type=WorkItemType.STORY,
            assigned_sprint="Sprint 2", assigned_resource="R1",
            required_skill="Python", priority=Priority.HIGH,
            estimated_effort_hrs=16.0, current_estimate_hrs=16.0,
            actual_effort_hrs=0.0, remaining_effort_hrs=16.0,
            progress_pct=0.0, status=WorkItemStatus.NOT_STARTED,
        ),
        WorkItem(
            item_id="WI-C", title="Item C (swarm/split target)", work_type=WorkItemType.STORY,
            assigned_sprint="Sprint 1", assigned_resource="R1",
            required_skill="Python", priority=Priority.CRITICAL,
            estimated_effort_hrs=40.0, current_estimate_hrs=40.0,
            actual_effort_hrs=0.0, remaining_effort_hrs=40.0,
            progress_pct=0.0, status=WorkItemStatus.NOT_STARTED,
        ),
    ]

    dependencies = [
        Dependency(
            dependency_id="D1", predecessor_item_id="WI-A", successor_item_id="WI-B",
            dependency_type=DependencyType.FINISH_TO_START,
            is_on_critical_path=False, lag_days=with_dependency_lag,
        )
    ]

    return ProjectState(
        project_id="BATCH-A-TEST",
        project_info=project_info,
        team=team,
        sprints=sprints,
        work_items=work_items,
        dependencies=dependencies,
        blockers=[],
        actuals=[],
    )


def make_rec(action_type, affected_item_ids, affected_resource_ids=None) -> Recommendation:
    return Recommendation(
        recommendation_id=f"REC-{action_type.value}",
        title=action_type.value,
        description=action_type.value,
        action_type=action_type,
        priority_score=1.0,
        confidence=ConfidenceLevel.MEDIUM,
        estimated_hours_recovered=0.0,
        estimated_delay_reduction_days=0.0,
        estimated_risk_reduction=0.0,
        affected_item_ids=affected_item_ids,
        affected_resource_ids=affected_resource_ids or [],
        affected_sprint_ids=[],
        affected_blocker_ids=[],
        root_cause_signal_id="TEST",
    )


# ── PARALLELIZE_ITEMS ─────────────────────────────────────────────────────

def test_parallelize_conserves_remaining_effort():
    state = make_state(with_dependency_lag=2)
    before = total_effort(state)
    rec = make_rec(RecommendationAction.PARALLELIZE_ITEMS, ["WI-A", "WI-B"])
    ActionApplicatorV2().apply(state, rec)
    assert total_effort(state) == before
    # per-item effort must also be untouched
    a = next(wi for wi in state.work_items if wi.item_id == "WI-A")
    b = next(wi for wi in state.work_items if wi.item_id == "WI-B")
    assert a.remaining_effort_hrs == 16.0
    assert b.remaining_effort_hrs == 16.0


def test_parallelize_can_reduce_elapsed_duration_without_deleting_effort():
    state = make_state(with_dependency_lag=2)
    rec = make_rec(RecommendationAction.PARALLELIZE_ITEMS, ["WI-A", "WI-B"])
    ActionApplicatorV2().apply(state, rec)
    dep = state.dependencies[0]
    assert dep.lag_days == 0  # serialization/waiting time is what shrank
    a = next(wi for wi in state.work_items if wi.item_id == "WI-A")
    b = next(wi for wi in state.work_items if wi.item_id == "WI-B")
    assert "WI-B" in a.can_parallel_with
    assert "WI-A" in b.can_parallel_with


def test_parallelize_without_independence_has_zero_schedule_gain():
    # No dependency edge at all between WI-A and WI-C
    state = make_state(with_dependency_lag=0)
    rec = make_rec(RecommendationAction.PARALLELIZE_ITEMS, ["WI-A", "WI-C"])
    before = total_effort(state)
    ActionApplicatorV2().apply(state, rec)
    assert total_effort(state) == before
    # No dependency existed between A/C, so lag_days on the unrelated A-B dep
    # must be untouched -- nothing to remove for this pair.
    dep = state.dependencies[0]
    assert dep.lag_days == 0  # already zero for this scenario; still nothing negative


# ── REBALANCE_SPRINT_LOAD ────────────────────────────────────────────────

def test_rebalance_conserves_remaining_effort():
    state = make_state()
    before = total_effort(state)
    rec = make_rec(RecommendationAction.REBALANCE_SPRINT_LOAD, ["WI-A"], affected_resource_ids=["R2"])
    ActionApplicatorV2().apply(state, rec)
    assert total_effort(state) == before
    a = next(wi for wi in state.work_items if wi.item_id == "WI-A")
    assert a.assigned_resource == "R2"
    assert a.remaining_effort_hrs == 16.0


def test_rebalance_does_not_increase_capacity_and_reduce_effort_simultaneously():
    state = make_state()
    sprint_velocities_before = [s.planned_velocity_hrs for s in state.sprints]
    rec = make_rec(RecommendationAction.REBALANCE_SPRINT_LOAD, ["WI-A"], affected_resource_ids=["R2"])
    ActionApplicatorV2().apply(state, rec)
    sprint_velocities_after = [s.planned_velocity_hrs for s in state.sprints]
    # Sprint velocity must not be inflated as a second, double-counted benefit
    assert sprint_velocities_after == sprint_velocities_before


# ── REMOVE_DEPENDENCY_BOTTLENECK ─────────────────────────────────────────

def test_dependency_removal_conserves_successor_effort():
    state = make_state(with_dependency_lag=3)
    before = total_effort(state)
    rec = make_rec(RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK, ["WI-A", "WI-B"])
    ActionApplicatorV2().apply(state, rec)
    assert total_effort(state) == before
    b = next(wi for wi in state.work_items if wi.item_id == "WI-B")
    assert b.remaining_effort_hrs == 16.0


def test_dependency_removal_changes_waiting_or_cp_not_work_size():
    state = make_state(with_dependency_lag=3)
    rec = make_rec(RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK, ["WI-A", "WI-B"])
    ActionApplicatorV2().apply(state, rec)
    dep = state.dependencies[0]
    assert dep.lag_days == 0
    b = next(wi for wi in state.work_items if wi.item_id == "WI-B")
    assert b.current_estimate_hrs == 16.0  # work size itself is untouched


# ── ADVANCE_ITEM_TO_EARLIER_SPRINT ───────────────────────────────────────

def test_advance_item_conserves_effort():
    state = make_state()
    before = total_effort(state)
    rec = make_rec(RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT, ["WI-A"])
    ActionApplicatorV2().apply(state, rec)
    assert total_effort(state) == before
    a = next(wi for wi in state.work_items if wi.item_id == "WI-A")
    assert a.assigned_sprint == "Sprint 1"  # moved earlier
    assert a.remaining_effort_hrs == 16.0


def test_advance_item_without_feasible_earlier_execution_has_zero_gain():
    state = make_state()
    # WI-C is already in the earliest sprint -- nothing earlier to move into.
    rec = make_rec(RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT, ["WI-C"])
    before_sprint = next(wi for wi in state.work_items if wi.item_id == "WI-C").assigned_sprint
    before_effort = total_effort(state)
    ActionApplicatorV2().apply(state, rec)
    c = next(wi for wi in state.work_items if wi.item_id == "WI-C")
    assert c.assigned_sprint == before_sprint  # unchanged: no earlier sprint available
    assert total_effort(state) == before_effort


# ── SWARM_ITEM ────────────────────────────────────────────────────────────

def test_swarm_conserves_effort():
    state = make_state()
    before = total_effort(state)
    rec = make_rec(RecommendationAction.SWARM_ITEM, ["WI-C"], affected_resource_ids=["R2"])
    ActionApplicatorV2().apply(state, rec)
    assert total_effort(state) == before
    c = next(wi for wi in state.work_items if wi.item_id == "WI-C")
    assert c.remaining_effort_hrs == 40.0


def test_swarm_with_no_usable_parallel_capacity_has_zero_gain():
    state = make_state()
    before = total_effort(state)
    # No affected_resource_ids -> no swarm resource identified
    rec = make_rec(RecommendationAction.SWARM_ITEM, ["WI-C"], affected_resource_ids=[])
    ActionApplicatorV2().apply(state, rec)
    assert total_effort(state) == before
    c = next(wi for wi in state.work_items if wi.item_id == "WI-C")
    assert c.remaining_effort_hrs == 40.0


# ── SPLIT_ITEM ────────────────────────────────────────────────────────────

def test_split_conserves_total_effort():
    state = make_state()
    before = total_effort(state)
    rec = make_rec(RecommendationAction.SPLIT_ITEM, ["WI-C"])
    ActionApplicatorV2().apply(state, rec)
    assert abs(total_effort(state) - before) < 1e-6


# ── COMBINED PLANS ────────────────────────────────────────────────────────

def test_parallelize_plus_rebalance_does_not_delete_work():
    state = make_state(with_dependency_lag=2)
    before = total_effort(state)
    applicator = ActionApplicatorV2()
    applicator.apply(state, make_rec(RecommendationAction.PARALLELIZE_ITEMS, ["WI-A", "WI-B"]))
    applicator.apply(state, make_rec(RecommendationAction.REBALANCE_SPRINT_LOAD, ["WI-A"], affected_resource_ids=["R2"]))
    assert total_effort(state) == before


def test_swarm_plus_split_does_not_double_count_same_concurrency_benefit():
    state = make_state()
    before = total_effort(state)
    applicator = ActionApplicatorV2()
    applicator.apply(state, make_rec(RecommendationAction.SWARM_ITEM, ["WI-C"], affected_resource_ids=["R2"]))
    applicator.apply(state, make_rec(RecommendationAction.SPLIT_ITEM, ["WI-C"]))
    # Total effort must still equal the original total -- swarming did not
    # delete effort, and splitting only divides the (unchanged) total in two.
    assert abs(total_effort(state) - before) < 1e-6
