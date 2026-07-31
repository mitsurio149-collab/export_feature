"""
tests/test_historical_analyzer.py

Integration tests for Phase 6b / Stage 17b: HistoricalAnalyzer.

Field-name note: WorkItem has no `sprint_id` -- the current sprint is
`assigned_sprint` (a sprint *name*, e.g. "Sprint 5"), and the originally
planned sprint is `original_sprint`. Blocker has no `estimated_delay_days`
field; it's derived from (target_resolution_date - raised_date).days.
See historical_analyzer.py module docstring for the full rationale.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.engines.historical_analyzer import HistoricalAnalyzer
from app.domain.models import (
    Blocker,
    BlockerCategory,
    BlockerSeverity,
    BlockerStatus,
    Dependency,
    DependencyType,
    ProjectInfo,
    ProjectState,
    Priority,
    Resource,
    SkillLevel,
    Sprint,
    SprintActual,
    SprintStatus,
    WorkItem,
    WorkItemStatus,
    WorkItemType,
)


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------

START = datetime(2026, 1, 1)


def _project_info() -> ProjectInfo:
    return ProjectInfo(
        project_name="Historical Test",
        sponsor="Sponsor",
        business_unit="Engineering",
        project_manager="PM",
        customer="Customer",
        status="Active",
        start_date=START,
        target_end_date=START + timedelta(days=90),
        sprint_duration_days=14,
        methodology="Agile Scrum",
    )


def _team() -> list:
    return [
        Resource(
            resource_id="R1", name="Alice", role="Engineer",
            primary_skill="Python", secondary_skill="SQL",
            skill_level=SkillLevel.SENIOR, allocation_pct=0.8,
            availability_pct=0.8, daily_capacity_hrs=8.0,
        ),
    ]


def _sprint(n: int, status: SprintStatus = SprintStatus.COMPLETED) -> Sprint:
    return Sprint(
        sprint_id=f"S{n}",
        sprint_name=f"Sprint {n}",
        sprint_number=n,
        start_date=START + timedelta(days=14 * (n - 1)),
        end_date=START + timedelta(days=14 * n - 1),
        working_days=10,
        sprint_goal="Build",
        status=status,
        planned_velocity_hrs=160.0,
        carryover_count=0,
    )


def _item(
    item_id: str,
    *,
    status: WorkItemStatus,
    current_estimate_hrs: float = 20.0,
    actual_effort_hrs: float = 0.0,
    assigned_sprint: str = "Sprint 1",
    original_sprint: str | None = None,
    assigned_resource: str = "R1",
    required_skill: str = "Python",
) -> WorkItem:
    return WorkItem(
        item_id=item_id,
        title=f"Item {item_id}",
        work_type=WorkItemType.TASK,
        assigned_sprint=assigned_sprint,
        original_sprint=original_sprint,
        assigned_resource=assigned_resource,
        required_skill=required_skill,
        priority=Priority.MEDIUM,
        estimated_effort_hrs=current_estimate_hrs,
        current_estimate_hrs=current_estimate_hrs,
        actual_effort_hrs=actual_effort_hrs,
        remaining_effort_hrs=0.0,
        progress_pct=1.0 if status in (WorkItemStatus.DONE, WorkItemStatus.COMPLETED) else 0.5,
        status=status,
    )


def _blocker(
    blocker_id: str,
    *,
    impacted_item_ids: list,
    category: BlockerCategory = BlockerCategory.OTHER,
    status: BlockerStatus = BlockerStatus.RESOLVED,
    raised_offset_days: int = 0,
    resolution_offset_days: int = 5,
) -> Blocker:
    return Blocker(
        blocker_id=blocker_id,
        related_item_id=impacted_item_ids[0],
        impacted_item_ids=impacted_item_ids,
        description="Test blocker",
        severity=BlockerSeverity.MEDIUM,
        status=status,
        owner="Alice",
        raised_date=START + timedelta(days=raised_offset_days),
        target_resolution_date=START + timedelta(days=raised_offset_days + resolution_offset_days),
        category=category,
    )


def _dependency(dep_id: str, predecessor: str, successor: str) -> Dependency:
    return Dependency(
        dependency_id=dep_id,
        predecessor_item_id=predecessor,
        successor_item_id=successor,
        dependency_type=DependencyType.FINISH_TO_START,
    )


def _state(
    *,
    work_items: list,
    sprints: list,
    blockers: list | None = None,
    dependencies: list | None = None,
) -> ProjectState:
    return ProjectState(
        project_id="test-proj",
        project_info=_project_info(),
        team=_team(),
        sprints=sprints,
        work_items=work_items,
        dependencies=dependencies or [],
        blockers=blockers or [],
        actuals=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_overbilling_detected_on_closed_items_only():
    """A DONE item with actual > 110% of estimate must be detected."""
    state = _state(
        work_items=[
            _item("WI-1", status=WorkItemStatus.DONE, current_estimate_hrs=10.0, actual_effort_hrs=15.0),
        ],
        sprints=[_sprint(1)],
    )
    result = HistoricalAnalyzer().run(state)
    assert len(result.overbilling) == 1
    assert result.overbilling[0].item_id == "WI-1"
    assert result.overbilling[0].overrun_hrs == pytest.approx(5.0)


def test_overbilling_not_detected_on_open_items():
    """An IN_PROGRESS item, however overrun, must not count as overbilling
    (only closed items reflect settled actuals)."""
    state = _state(
        work_items=[
            _item("WI-1", status=WorkItemStatus.IN_PROGRESS, current_estimate_hrs=10.0, actual_effort_hrs=25.0),
        ],
        sprints=[_sprint(1)],
    )
    result = HistoricalAnalyzer().run(state)
    assert len(result.overbilling) == 0


def test_overbilling_flagged_when_blocker_existed():
    """was_flagged must be True when a blocker's impacted_item_ids includes
    the overrun item."""
    state = _state(
        work_items=[
            _item("WI-1", status=WorkItemStatus.DONE, current_estimate_hrs=10.0, actual_effort_hrs=15.0),
        ],
        sprints=[_sprint(1)],
        blockers=[_blocker("BLK-1", impacted_item_ids=["WI-1"])],
    )
    result = HistoricalAnalyzer().run(state)
    assert result.overbilling[0].was_flagged is True
    assert result.overbilling[0].first_flagged_sprint is not None


def test_spillover_detected_when_original_sprint_differs():
    """original_sprint != assigned_sprint must produce a SpilloverInstance."""
    state = _state(
        work_items=[
            _item("WI-1", status=WorkItemStatus.DONE, original_sprint="Sprint 1", assigned_sprint="Sprint 2"),
        ],
        sprints=[_sprint(1), _sprint(2)],
    )
    result = HistoricalAnalyzer().run(state)
    assert len(result.spillover) == 1
    assert result.spillover[0].item_id == "WI-1"
    assert result.spillover[0].sprints_delayed == 1


def test_spillover_reason_blocker_when_open_blocker_exists():
    """An open blocker impacting the item -> reason_category == BLOCKER."""
    state = _state(
        work_items=[
            _item("WI-1", status=WorkItemStatus.DONE, original_sprint="Sprint 1", assigned_sprint="Sprint 2"),
        ],
        sprints=[_sprint(1), _sprint(2)],
        blockers=[
            _blocker("BLK-1", impacted_item_ids=["WI-1"], status=BlockerStatus.OPEN),
        ],
    )
    result = HistoricalAnalyzer().run(state)
    assert result.spillover[0].reason_category == "BLOCKER"
    assert result.spillover[0].root_blocker_id == "BLK-1"


def test_spillover_reason_dependency_when_dependency_exists():
    """No open blocker, but a dependency has this item as successor
    -> reason_category == DEPENDENCY."""
    state = _state(
        work_items=[
            _item("WI-1", status=WorkItemStatus.DONE, current_estimate_hrs=10.0),
            _item("WI-2", status=WorkItemStatus.DONE, original_sprint="Sprint 1", assigned_sprint="Sprint 2"),
        ],
        sprints=[_sprint(1), _sprint(2)],
        dependencies=[_dependency("DEP-1", predecessor="WI-1", successor="WI-2")],
    )
    result = HistoricalAnalyzer().run(state)
    spill = [s for s in result.spillover if s.item_id == "WI-2"][0]
    assert spill.reason_category == "DEPENDENCY"


def test_recurring_blocker_systemic_at_3_occurrences():
    """3+ blockers in the same category with none open -> SYSTEMIC."""
    state = _state(
        work_items=[_item("WI-1", status=WorkItemStatus.DONE)],
        sprints=[_sprint(1)],
        blockers=[
            _blocker("BLK-1", impacted_item_ids=["WI-1"], category=BlockerCategory.HARDWARE, status=BlockerStatus.RESOLVED),
            _blocker("BLK-2", impacted_item_ids=["WI-1"], category=BlockerCategory.HARDWARE, status=BlockerStatus.RESOLVED),
            _blocker("BLK-3", impacted_item_ids=["WI-1"], category=BlockerCategory.HARDWARE, status=BlockerStatus.RESOLVED),
        ],
    )
    result = HistoricalAnalyzer().run(state)
    hw = [p for p in result.recurring_blockers if p.category == "Hardware"][0]
    assert hw.occurrences == 3
    assert hw.recurrence_verdict == "SYSTEMIC"


def test_recurring_blocker_coincidental_at_2_occurrences():
    """Exactly 2 blockers, none open -> COINCIDENTAL (not yet systemic)."""
    state = _state(
        work_items=[_item("WI-1", status=WorkItemStatus.DONE)],
        sprints=[_sprint(1)],
        blockers=[
            _blocker("BLK-1", impacted_item_ids=["WI-1"], category=BlockerCategory.TOOL_ISSUE, status=BlockerStatus.RESOLVED),
            _blocker("BLK-2", impacted_item_ids=["WI-1"], category=BlockerCategory.TOOL_ISSUE, status=BlockerStatus.RESOLVED),
        ],
    )
    result = HistoricalAnalyzer().run(state)
    tool = [p for p in result.recurring_blockers if p.category == "Tool Issue"][0]
    assert tool.occurrences == 2
    assert tool.recurrence_verdict == "COINCIDENTAL"


def test_cascade_detected_when_overrun_causes_spillover():
    """An overrunning item that is the predecessor of a dependency-caused
    spillover must produce a CascadePattern."""
    state = _state(
        work_items=[
            _item("WI-1", status=WorkItemStatus.DONE, current_estimate_hrs=10.0, actual_effort_hrs=20.0),
            _item("WI-2", status=WorkItemStatus.DONE, original_sprint="Sprint 1", assigned_sprint="Sprint 2"),
        ],
        sprints=[_sprint(1), _sprint(2)],
        dependencies=[_dependency("DEP-1", predecessor="WI-1", successor="WI-2")],
    )
    result = HistoricalAnalyzer().run(state)
    assert len(result.cascade_patterns) == 1
    assert result.cascade_patterns[0].trigger_item_id == "WI-1"
    assert "WI-2" in result.cascade_patterns[0].cascade_item_ids


def test_prevention_rec_generated_for_unflagged_overbilling():
    """2+ unflagged overbilling items -> RULE 1 prevention rec, HIGH confidence."""
    state = _state(
        work_items=[
            _item("WI-1", status=WorkItemStatus.DONE, current_estimate_hrs=10.0, actual_effort_hrs=15.0),
            _item("WI-2", status=WorkItemStatus.DONE, current_estimate_hrs=10.0, actual_effort_hrs=16.0),
        ],
        sprints=[_sprint(1)],
    )
    result = HistoricalAnalyzer().run(state)
    unflagged_recs = [
        r for r in result.prevention_recommendations
        if "no blocker raised" in r.trigger
    ]
    assert len(unflagged_recs) == 1
    assert unflagged_recs[0].confidence == "HIGH"
    assert unflagged_recs[0].sprint_to_apply == "NEXT"


def test_prevention_rec_generated_for_systemic_blocker():
    """A SYSTEMIC recurring blocker pattern -> RULE 3 prevention rec."""
    state = _state(
        work_items=[_item("WI-1", status=WorkItemStatus.DONE)],
        sprints=[_sprint(1)],
        blockers=[
            _blocker("BLK-1", impacted_item_ids=["WI-1"], category=BlockerCategory.VENDOR, status=BlockerStatus.RESOLVED),
            _blocker("BLK-2", impacted_item_ids=["WI-1"], category=BlockerCategory.VENDOR, status=BlockerStatus.RESOLVED),
            _blocker("BLK-3", impacted_item_ids=["WI-1"], category=BlockerCategory.VENDOR, status=BlockerStatus.RESOLVED),
        ],
    )
    result = HistoricalAnalyzer().run(state)
    systemic_recs = [r for r in result.prevention_recommendations if "Vendor" in r.trigger]
    assert len(systemic_recs) == 1
    assert systemic_recs[0].sprint_to_apply == "IMMEDIATELY"
    assert systemic_recs[0].confidence == "HIGH"


def test_empty_state_returns_empty_analysis_not_error():
    """ProjectState itself requires >=1 sprint and >=1 work item, so a truly
    empty state can't be constructed. The real 'no error on empty analysis'
    case is a minimal state where nothing triggers any pattern: no crash,
    every list comes back empty."""
    state = _state(
        work_items=[_item("WI-1", status=WorkItemStatus.NOT_STARTED)],
        sprints=[_sprint(1, status=SprintStatus.NOT_STARTED)],
    )
    result = HistoricalAnalyzer().run(state)
    assert result.sprints_analysed == 0
    assert result.overbilling == []
    assert result.spillover == []
    assert result.recurring_blockers == []
    assert result.cascade_patterns == []
    assert result.prevention_recommendations == []
    assert result.summary != ""


def test_summary_contains_sprint_count():
    state = _state(
        work_items=[_item("WI-1", status=WorkItemStatus.DONE)],
        sprints=[_sprint(1), _sprint(2), _sprint(3, status=SprintStatus.IN_PROGRESS)],
    )
    result = HistoricalAnalyzer().run(state)
    assert "2 completed sprints" in result.summary
    assert result.sprints_analysed == 2
