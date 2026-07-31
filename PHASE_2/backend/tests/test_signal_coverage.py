"""
tests/test_signal_coverage.py

Integration gate: proves all 17 ObservationEngine detectors fire end-to-end.
Context: EMIOS / Sprint Whisperer project at refine_07.

Fixture wiring notes (discovered by reading cognition_common.py and
domain/models.py directly -- the detectors are picky about *where* data
lives, not just whether it's present):

- resource load (#3) reads metrics.resource_sprint_loads, NOT state.*
- rework rate (#14) reads metrics.quality_metrics + metrics.completed_items,
  NOT state.quality_metrics / quality_metrics.completed_items_count
- critical_path (#8/#9/#10) must be an object with a `.critical_path`
  attribute -- a bare list has no such attribute and resolves to empty
- blocked_item_ids (#8) reads blocker.impacted_item_ids, not blocked_item_ids
- status enums are case-sensitive str Enums ("Open", "Completed", ...),
  not upper-cased strings
- velocity detectors (#1/#17) both read metrics.velocity_metrics.velocity_by_sprint
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.engines.observation_engine import ObservationEngine
from app.domain.models import BlockerStatus, BlockerSeverity, SprintStatus, WorkItemStatus


def _utcnow():
    return datetime.now(timezone.utc)


def _build_rich_state():
    now = _utcnow()
    sprint_duration = 14

    project_info = SimpleNamespace(
        sprint_duration_days=sprint_duration,
        next_milestone_date=now + timedelta(days=30),
    )

    wi_01 = SimpleNamespace(
        item_id="WI-01",
        status=WorkItemStatus.IN_PROGRESS,
        current_estimate_hrs=40,
        estimated_effort_hrs=20,
        added_mid_sprint=True,
        required_skill="AUTOSAR",
        assigned_resource="R-Meena",
    )
    wi_02 = SimpleNamespace(
        item_id="WI-02",
        status=WorkItemStatus.NOT_STARTED,
        current_estimate_hrs=10,
        estimated_effort_hrs=10,
        added_mid_sprint=True,
        required_skill="Python",
        assigned_resource="R-Meena",
    )
    wi_03 = SimpleNamespace(
        item_id="WI-03",
        status=WorkItemStatus.NOT_STARTED,
        current_estimate_hrs=8,
        estimated_effort_hrs=8,
        added_mid_sprint=True,
        required_skill="Python",
        assigned_resource="R-Meena",
    )
    wi_04 = SimpleNamespace(
        item_id="WI-04",
        status=WorkItemStatus.DONE,
        current_estimate_hrs=8,
        estimated_effort_hrs=8,
        added_mid_sprint=False,
        required_skill="Python",
        assigned_resource="R-Meena",
    )

    work_items = [wi_01, wi_02, wi_03, wi_04]

    blocker_1 = SimpleNamespace(
        blocker_id="BLK-01",
        status=BlockerStatus.OPEN,
        severity=BlockerSeverity.CRITICAL,
        estimated_delay_days=20,
        raised_date=now - timedelta(days=35),
        target_resolution_date=None,
        actual_resolution_date=None,
        impacted_item_ids=["WI-01"],
        related_item_id=None,
    )

    blockers = [blocker_1]

    resource_1 = SimpleNamespace(
        resource_id="R-Meena",
        name="Meena",
        primary_skill="Python",
        secondary_skills=[],
        allocation_pct=1.0,
        availability_pct=1.0,
    )

    resources = [resource_1]
    team = resources

    completed_sprint = SimpleNamespace(
        sprint_id="Sprint-5",
        status=SprintStatus.COMPLETED,
        actual_velocity_hrs=50,
        planned_velocity_hrs=100,
    )

    sprints = [completed_sprint]

    dep_1 = SimpleNamespace(
        dependency_id="DEP-01",
        predecessor_item_id="WI-01",
        successor_item_id="WI-02",
        lag_days=20,
    )

    dependencies = [dep_1]

    actual_1 = SimpleNamespace(
        sprint_id="Sprint-5",
        planned_effort_hrs=100,
        actual_effort_hrs=50,
    )

    state = SimpleNamespace(
        project_info=project_info,
        work_items=work_items,
        blockers=blockers,
        resources=resources,
        team=team,
        sprints=sprints,
        dependencies=dependencies,
        actuals=[actual_1],
    )

    velocity_metrics = SimpleNamespace(
        velocity_by_sprint=[100.0, 30.0, 95.0, 20.0, 110.0],
    )

    developer_metric = SimpleNamespace(
        resource_id="R-Meena",
        name="Meena",
        remaining_effort_hours=800,
        available_capacity_hours=640,
        allocation_pct=1.0,
        availability_pct=1.0,
    )

    resource_metrics = SimpleNamespace(
        developer_metrics=[developer_metric],
        total_team_remaining=1000,
    )

    quality_metrics = SimpleNamespace(
        reopened_work_count=5,
    )

    metrics = SimpleNamespace(
        velocity_metrics=velocity_metrics,
        resource_metrics=resource_metrics,
        resource_sprint_loads={"Meena": {"Sprint 6": 1.25}},
        historical_carryover_rate=0.30,
        total_items=5,
        completed_sprints=10,
        quality_metrics=quality_metrics,
        completed_items=20,
    )

    forecast = SimpleNamespace(
        scope_growth_percent=18.0,
        on_time_probability=0.18,
    )

    monte_carlo = SimpleNamespace(
        on_time_probability=0.18,
        p80_completion_date=now + timedelta(days=60),
    )

    critical_path = SimpleNamespace(critical_path=["WI-01"])

    return state, metrics, forecast, monte_carlo, critical_path


def _build_healthy_state():
    now = _utcnow()
    sprint_duration = 14

    project_info = SimpleNamespace(
        sprint_duration_days=sprint_duration,
        next_milestone_date=now + timedelta(days=120),
    )

    wi_01 = SimpleNamespace(
        item_id="WI-H1",
        status=WorkItemStatus.IN_PROGRESS,
        current_estimate_hrs=10,
        estimated_effort_hrs=10,
        added_mid_sprint=False,
        required_skill="Python",
        assigned_resource="R-Dev1",
    )

    work_items = [wi_01]

    resource_1 = SimpleNamespace(
        resource_id="R-Dev1",
        name="Dev1",
        primary_skill="Python",
        secondary_skills=["AUTOSAR"],
        allocation_pct=0.8,
        availability_pct=1.0,
    )

    completed_sprint = SimpleNamespace(
        sprint_id="Sprint-5",
        status=SprintStatus.COMPLETED,
        actual_velocity_hrs=95,
        planned_velocity_hrs=100,
    )

    actual_1 = SimpleNamespace(
        sprint_id="Sprint-5",
        planned_effort_hrs=100,
        actual_effort_hrs=95,
    )

    state = SimpleNamespace(
        project_info=project_info,
        work_items=work_items,
        blockers=[],
        resources=[resource_1],
        team=[resource_1],
        sprints=[completed_sprint],
        dependencies=[],
        actuals=[actual_1],
    )

    velocity_metrics = SimpleNamespace(
        velocity_by_sprint=[100.0, 98.0, 101.0, 99.0, 100.0],
    )

    developer_metric = SimpleNamespace(
        resource_id="R-Dev1",
        name="Dev1",
        remaining_effort_hours=100,
        available_capacity_hours=200,
        allocation_pct=0.8,
        availability_pct=1.0,
    )
    developer_metric_2 = SimpleNamespace(
        resource_id="R-Dev2",
        name="Dev2",
        remaining_effort_hours=100,
        available_capacity_hours=200,
        allocation_pct=0.7,
        availability_pct=1.0,
    )
    developer_metric_3 = SimpleNamespace(
        resource_id="R-Dev3",
        name="Dev3",
        remaining_effort_hours=100,
        available_capacity_hours=200,
        allocation_pct=0.7,
        availability_pct=1.0,
    )

    resource_metrics = SimpleNamespace(
        developer_metrics=[developer_metric, developer_metric_2, developer_metric_3],
        total_team_remaining=300,
    )

    quality_metrics = SimpleNamespace(
        reopened_work_count=0,
    )

    metrics = SimpleNamespace(
        velocity_metrics=velocity_metrics,
        resource_metrics=resource_metrics,
        resource_sprint_loads={},
        historical_carryover_rate=0.02,
        total_items=100,
        completed_sprints=5,
        quality_metrics=quality_metrics,
        completed_items=20,
    )

    forecast = SimpleNamespace(
        scope_growth_percent=2.0,
        on_time_probability=0.85,
    )

    monte_carlo = SimpleNamespace(
        on_time_probability=0.85,
        p80_completion_date=now + timedelta(days=10),
    )

    critical_path = SimpleNamespace(critical_path=[])

    return state, metrics, forecast, monte_carlo, critical_path


def test_all_17_detectors_can_fire():
    state, metrics, forecast, mc, critical_path = _build_rich_state()

    engine = ObservationEngine()
    cluster = engine.run(state, metrics, forecast, mc, critical_path)

    metric_refs = {o.metric_ref for o in cluster.observations}

    assert "velocity" in metric_refs
    assert "on_time_probability" in metric_refs
    assert "resource_load_ratio" in metric_refs
    assert "blocker_delay_days" in metric_refs
    assert "carryover_rate" in metric_refs
    assert "scope_growth_pct" in metric_refs
    assert "estimation_drift" in metric_refs
    assert "critical_path_pressure" in metric_refs
    assert "dependency_lag_days" in metric_refs
    assert "skill_mismatch" in metric_refs
    assert "sprint_completion_rate" in metric_refs
    assert "blocker_age_sprints" in metric_refs
    assert "load_concentration" in metric_refs
    assert "rework_rate" in metric_refs
    assert "scope_churn" in metric_refs
    assert "milestone_risk_days" in metric_refs
    assert "velocity_variance_cv" in metric_refs

    for o in cluster.observations:
        assert o.cause is None

    assert cluster.cluster_severity in ("HIGH", "CRITICAL")


def test_all_17_detectors_silent_on_healthy_project():
    state, metrics, forecast, mc, critical_path = _build_healthy_state()

    engine = ObservationEngine()
    cluster = engine.run(state, metrics, forecast, mc, critical_path)

    assert cluster.cluster_severity == "LOW"
    assert all(o.cause is None for o in cluster.observations)
