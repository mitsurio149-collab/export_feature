"""Blocker attribution and schedule confidence modifier tests for RiskEngine."""

import pytest
from datetime import datetime, timedelta

from app.domain.models import (
    ProjectInfo,
    Resource,
    Sprint,
    WorkItem,
    Dependency,
    Blocker,
    SprintActual,
    ProjectState,
    SkillLevel,
    WorkItemType,
    Priority,
    WorkItemStatus,
    SprintStatus,
    BlockerSeverity,
    BlockerStatus,
    BlockerCategory,
    DependencyType,
)
from app.engines.metrics_engine import MetricsEngine
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.spillover_engine import SpilloverAnalysisEngine
from app.engines.forecast_engine import ForecastEngine
from app.engines.monte_carlo_engine import MonteCarloEngine
from app.engines.impact_scoring_engine import ImpactScoringEngine
from app.engines.risk_engine import RiskEngine


@pytest.fixture
def minimal_project_state():
    start_date = datetime(2025, 1, 1)
    end_date = datetime(2025, 1, 31)
    project_info = ProjectInfo(
        project_name="Minimal Test Project",
        sponsor="Test Sponsor",
        business_unit="Engineering",
        project_manager="Test PM",
        customer="Test Customer",
        status="Active",
        start_date=start_date,
        target_end_date=end_date,
        sprint_duration_days=14,
        methodology="Agile Scrum",
    )
    team = [
        Resource(
            resource_id="R1",
            name="Alice",
            role="Engineer",
            primary_skill="Python",
            secondary_skill="None",
            skill_level=SkillLevel.SENIOR,
            allocation_pct=0.50,
            availability_pct=1.0,
        )
    ]
    sprints = [
        Sprint(
            sprint_id="S1",
            sprint_name="Sprint 1",
            sprint_number=1,
            start_date=start_date,
            end_date=start_date + timedelta(days=14),
            working_days=10,
            sprint_goal="Test",
            status=SprintStatus.IN_PROGRESS,
            planned_velocity_hrs=160.0,
            carryover_count=0,
        )
    ]
    work_items = [
        WorkItem(
            item_id="WI-001",
            title="Task 1",
            work_type=WorkItemType.TASK,
            assigned_sprint="S1",
            original_sprint="S1",
            priority=Priority.MEDIUM,
            status=WorkItemStatus.IN_PROGRESS,
            estimated_effort_hrs=20.0,
            current_estimate_hrs=20.0,
            remaining_effort_hrs=20.0,
            assigned_resource="R1",
            required_skill="Python",
        )
    ]
    return ProjectState(
        project_id="proj-minimal",
        project_info=project_info,
        team=team,
        sprints=sprints,
        work_items=work_items,
        dependencies=[],
        blockers=[],
        actuals=[],
    )


def build_risk_result(
    project_state,
    expected_delay_days,
    on_time_probability,
    spillover_items=0,
    active_blockers=0,
    blocker_severity=BlockerSeverity.HIGH,
    blocker_impact=None,
):
    metrics = MetricsEngine(project_state).calculate()
    if blocker_impact is not None:
        # Override the blocker velocity impact for test control.
        metrics.estimated_blocker_velocity_impact = blocker_impact
    dep_engine = DependencyGraphEngine(project_state)
    dag = dep_engine.build_dag()
    cp_engine = CriticalPathEngine(project_state, dag)
    cp_result = cp_engine.analyze()

    # Create spillover object with each sprint's expected spillover count.
    spillover_values = {s.sprint_number: float(spillover_items) for s in project_state.sprints}
    spillover = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    spillover.predicted_spillover_by_sprint = spillover_values

    forecast = ForecastEngine(project_state, metrics, cp_result, spillover).calculate()
    forecast.expected_delay_days = float(expected_delay_days)

    monte_carlo = MonteCarloEngine(project_state, metrics, cp_result, spillover, simulation_count=10)
    monte_carlo_result = monte_carlo.calculate()
    monte_carlo_result.on_time_probability = float(on_time_probability)

    impact_scores = ImpactScoringEngine(project_state, dag).score()

    risk_engine = RiskEngine(
        project_state,
        metrics,
        cp_result,
        dag,
        spillover,
        forecast,
        monte_carlo_result,
        impact_scores,
    )
    return risk_engine.analyze()


def test_delay_and_ontime_not_independently_additive(minimal_project_state):
    result = build_risk_result(
        minimal_project_state,
        expected_delay_days=60,
        on_time_probability=0.20,
        spillover_items=0,
    )
    assert result.schedule_risk.score == pytest.approx(min(100.0, min(100.0, (60 / 30.0) * 80.0) * (1.0 + (1.0 - 0.20) * 0.20)))
    assert len([d for d in result.schedule_risk.drivers if d.title == "On-Time Probability (Confidence Modifier)"]) == 1


def test_schedule_score_unchanged_with_perfect_ontime(minimal_project_state):
    result = build_risk_result(
        minimal_project_state,
        expected_delay_days=30,
        on_time_probability=1.0,
        spillover_items=0,
    )
    assert result.schedule_risk.score == pytest.approx(min(100.0, (30 / 30.0) * 80.0))
    assert all(
        "confidence" not in d.description.lower()
        for d in result.schedule_risk.drivers
    )


def test_schedule_score_higher_with_low_ontime_same_delay(minimal_project_state):
    result_low = build_risk_result(
        minimal_project_state,
        expected_delay_days=20,
        on_time_probability=0.20,
        spillover_items=0,
    )
    result_high = build_risk_result(
        minimal_project_state,
        expected_delay_days=20,
        on_time_probability=0.80,
        spillover_items=0,
    )
    assert result_low.schedule_risk.score > result_high.schedule_risk.score


def test_schedule_score_unchanged_at_perfect_ontime(minimal_project_state):
    result = build_risk_result(
        minimal_project_state,
        expected_delay_days=60,
        on_time_probability=1.0,
        spillover_items=0,
    )
    assert result.schedule_risk.score == pytest.approx(min(100.0, (60 / 30.0) * 80.0))


def test_spillover_component_independent_of_blocker_impact(minimal_project_state):
    result = build_risk_result(
        minimal_project_state,
        expected_delay_days=0,
        on_time_probability=1.0,
        spillover_items=10,
    )
    assert result.schedule_risk.score == pytest.approx(min(100.0, 10 * 8.0))
    assert all(d.title != "High Expected Delay" for d in result.schedule_risk.drivers)


def test_resource_blocker_driver_suppressed_when_floor_saturated(minimal_project_state):
    project_state = minimal_project_state
    project_state.blockers = [
        Blocker(
            blocker_id=f"B{i}",
            related_item_id="WI-001",
            impacted_item_ids=["WI-001"],
            description="Blocked",
            severity=BlockerSeverity.HIGH,
            status=BlockerStatus.OPEN,
            owner="QA",
            raised_date=datetime(2025, 1, 2),
            target_resolution_date=datetime(2025, 1, 10),
            actual_resolution_date=None,
            category=BlockerCategory.OTHER,
            notes="",
        )
        for i in range(6)
    ]
    result = build_risk_result(
        project_state,
        expected_delay_days=0,
        on_time_probability=1.0,
        spillover_items=0,
        blocker_impact=0.90,
    )
    driver = next(
        (d for d in result.resource_risk.drivers if d.title == "Active Blockers (Captured in Schedule Risk)"),
        None,
    )
    assert driver is not None
    assert driver.score == 0.0
    assert result.resource_risk.score == 0.0


def test_resource_blocker_driver_fires_when_below_floor_threshold(minimal_project_state):
    project_state = minimal_project_state
    project_state.blockers = [
        Blocker(
            blocker_id=f"B{i}",
            related_item_id="WI-001",
            impacted_item_ids=["WI-001"],
            description="Blocked",
            severity=BlockerSeverity.HIGH,
            status=BlockerStatus.OPEN,
            owner="QA",
            raised_date=datetime(2025, 1, 2),
            target_resolution_date=datetime(2025, 1, 10),
            actual_resolution_date=None,
            category=BlockerCategory.OTHER,
            notes="",
        )
        for i in range(6)
    ]
    result = build_risk_result(
        project_state,
        expected_delay_days=0,
        on_time_probability=1.0,
        spillover_items=0,
        blocker_impact=0.50,
    )
    blocker_driver = next(
        (d for d in result.resource_risk.drivers if "Active Blocker" in d.title),
        None,
    )
    assert blocker_driver is not None
    assert blocker_driver.score > 0.0
    assert any("active blockers" in reason.lower() for reason in result.resource_risk.reasons)


def test_resource_blocker_driver_does_not_fire_at_threshold(minimal_project_state):
    project_state = minimal_project_state
    project_state.blockers = [
        Blocker(
            blocker_id=f"B{i}",
            related_item_id="WI-001",
            impacted_item_ids=["WI-001"],
            description="Blocked",
            severity=BlockerSeverity.HIGH,
            status=BlockerStatus.OPEN,
            owner="QA",
            raised_date=datetime(2025, 1, 2),
            target_resolution_date=datetime(2025, 1, 10),
            actual_resolution_date=None,
            category=BlockerCategory.OTHER,
            notes="",
        )
        for i in range(5)
    ]
    result = build_risk_result(
        project_state,
        expected_delay_days=0,
        on_time_probability=1.0,
        spillover_items=0,
        blocker_impact=0.50,
    )
    assert all("Active Blocker" not in d.title for d in result.resource_risk.drivers)


def test_blocker_concentration_within_range(minimal_project_state):
    result = build_risk_result(
        minimal_project_state,
        expected_delay_days=15,
        on_time_probability=0.50,
        spillover_items=0,
        blocker_impact=0.30,
    )
    assert 0.0 <= result.blocker_risk_concentration <= 1.0


def test_blocker_concentration_high_when_many_critical(minimal_project_state):
    project_state = minimal_project_state
    project_state.blockers = [
        Blocker(
            blocker_id=f"B{i}",
            related_item_id="WI-001",
            impacted_item_ids=["WI-001"],
            description="Blocked",
            severity=BlockerSeverity.CRITICAL,
            status=BlockerStatus.OPEN,
            owner="QA",
            raised_date=datetime(2025, 1, 2),
            target_resolution_date=datetime(2025, 1, 10),
            actual_resolution_date=None,
            category=BlockerCategory.OTHER,
            notes="",
        )
        for i in range(5)
    ]
    result = build_risk_result(
        project_state,
        expected_delay_days=30,
        on_time_probability=0.20,
        spillover_items=0,
        blocker_impact=0.65,
    )
    assert result.blocker_risk_concentration > 0.50


def test_blocker_concentration_zero_no_blockers(minimal_project_state):
    result = build_risk_result(
        minimal_project_state,
        expected_delay_days=0,
        on_time_probability=1.0,
        spillover_items=0,
        blocker_impact=0.0,
    )
    assert result.blocker_risk_concentration == 0.0


def test_tio2_regression(minimal_project_state):
    result = build_risk_result(
        minimal_project_state,
        expected_delay_days=45,
        on_time_probability=0.35,
        spillover_items=10,
        blocker_impact=0.65,
    )
    assert result.schedule_risk.score == pytest.approx(90.0)
    assert result.overall_risk_score == pytest.approx(36.0)
    assert result.blocker_risk_concentration == pytest.approx(1.0)
    assert hasattr(result, "blocker_risk_concentration")
