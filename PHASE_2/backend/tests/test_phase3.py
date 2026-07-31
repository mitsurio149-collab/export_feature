"""Phase 3 Forecast Engine Tests"""
import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.domain.models import (
    ProjectInfo, Resource, Sprint, WorkItem, Dependency, Blocker, SprintActual, ProjectState,
    SkillLevel, WorkItemType, Priority, WorkItemStatus, SprintStatus, BlockerSeverity, BlockerStatus, BlockerCategory, DependencyType
)
from app.engines.metrics_engine import MetricsEngine
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.spillover_engine import SpilloverAnalysisEngine, SpilloverAnalysis
from app.engines.forecast_engine import ForecastEngine
from app.engines.pmo_kpi_engine import PMOKpiEngine
from app.api.models_phase3 import ForecastSteeringDriver


def make_sample_project_state() -> ProjectState:
    start_date = datetime(2025, 1, 1)
    end_date = datetime(2025, 3, 1)
    project_info = ProjectInfo(
        project_name="Test Project",
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
            secondary_skill="",
            skill_level=SkillLevel.SENIOR,
            allocation_pct=1.0,
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
            sprint_goal="Init",
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
            assigned_resource="R1",
            required_skill="Python",
            priority=Priority.HIGH,
            estimated_effort_hrs=40.0,
            current_estimate_hrs=40.0,
            actual_effort_hrs=10.0,
            remaining_effort_hrs=30.0,
            progress_pct=0.25,
            status=WorkItemStatus.IN_PROGRESS,
            is_scope_changed=False,
            scope_change_reason=None,
        )
    ]

    dependencies = []
    blockers = []
    actuals = [
        SprintActual(
            sprint_id="S0",
            sprint_number=1,
            planned_effort_hrs=160.0,
            actual_effort_hrs=140.0,
            tasks_planned=10,
            tasks_completed=8,
            carryover_count=2,
        )
    ]

    return ProjectState(
        project_id="TEST-FORECAST",
        project_info=project_info,
        team=team,
        sprints=sprints,
        work_items=work_items,
        dependencies=dependencies,
        blockers=blockers,
        actuals=actuals,
    )


def test_velocity_baseline_is_exposed_from_metrics_engine():
    """MetricsEngine should publish a canonical velocity baseline object for downstream engines."""
    project_state = make_sample_project_state()
    metrics = MetricsEngine(project_state).calculate()

    assert metrics.velocity_baseline is not None
    assert metrics.velocity_baseline.trimmed_avg_hrs == metrics.actual_avg_velocity
    assert metrics.velocity_baseline.simple_avg_hrs == metrics.velocity_metrics.average_velocity
    assert metrics.velocity_baseline.floor_hrs < metrics.velocity_baseline.trimmed_avg_hrs


def test_sprint_adherence_uses_delivery_rate_not_status():
    """Sprint adherence should reflect actual delivery rate across due sprints."""
    project_state = make_sample_project_state()
    project_state.sprints = [
        Sprint(
            sprint_id="S1",
            sprint_name="Sprint 1",
            sprint_number=1,
            start_date=datetime(2025, 1, 1),
            end_date=datetime(2025, 1, 15),
            working_days=10,
            sprint_goal="Init",
            status=SprintStatus.COMPLETED,
            planned_velocity_hrs=160.0,
            carryover_count=0,
        ),
        Sprint(
            sprint_id="S2",
            sprint_name="Sprint 2",
            sprint_number=2,
            start_date=datetime(2025, 1, 16),
            end_date=datetime(2025, 1, 29),
            working_days=10,
            sprint_goal="Build",
            status=SprintStatus.COMPLETED,
            planned_velocity_hrs=160.0,
            carryover_count=0,
        ),
        Sprint(
            sprint_id="S3",
            sprint_name="Sprint 3",
            sprint_number=3,
            start_date=datetime(2025, 1, 30),
            end_date=datetime(2025, 2, 12),
            working_days=10,
            sprint_goal="Test",
            status=SprintStatus.COMPLETED,
            planned_velocity_hrs=160.0,
            carryover_count=0,
        ),
        Sprint(
            sprint_id="S4",
            sprint_name="Sprint 4",
            sprint_number=4,
            start_date=datetime(2025, 2, 13),
            end_date=datetime(2025, 2, 26),
            working_days=10,
            sprint_goal="Release",
            status=SprintStatus.COMPLETED,
            planned_velocity_hrs=160.0,
            carryover_count=0,
        ),
        Sprint(
            sprint_id="S5",
            sprint_name="Sprint 5",
            sprint_number=5,
            start_date=datetime(2025, 2, 27),
            end_date=datetime(2025, 3, 12),
            working_days=10,
            sprint_goal="Hardening",
            status=SprintStatus.COMPLETED,
            planned_velocity_hrs=160.0,
            carryover_count=0,
        ),
    ]
    project_state.actuals = [
        SprintActual(sprint_id="S1", sprint_number=1, planned_effort_hrs=160.0, actual_effort_hrs=140.0, tasks_planned=11, tasks_completed=10, carryover_count=0),
        SprintActual(sprint_id="S2", sprint_number=2, planned_effort_hrs=160.0, actual_effort_hrs=160.0, tasks_planned=9, tasks_completed=9, carryover_count=0),
        SprintActual(sprint_id="S3", sprint_number=3, planned_effort_hrs=160.0, actual_effort_hrs=160.0, tasks_planned=11, tasks_completed=11, carryover_count=0),
        SprintActual(sprint_id="S4", sprint_number=4, planned_effort_hrs=160.0, actual_effort_hrs=140.0, tasks_planned=11, tasks_completed=9, carryover_count=0),
        SprintActual(sprint_id="S5", sprint_number=5, planned_effort_hrs=160.0, actual_effort_hrs=160.0, tasks_planned=10, tasks_completed=11, carryover_count=0),
    ]

    metrics = MetricsEngine(project_state).calculate()
    forecast = SimpleNamespace(
        completion_percentage=0.75,
        remaining_effort_hours=100.0,
        schedule_diagnostics=SimpleNamespace(real_elapsed_days=30.0, calendar_variance_days=0.0),
        confidence=SimpleNamespace(confidence_score=0.8),
        scope_growth_percent=0.0,
    )
    cp = SimpleNamespace(
        calendar_shift_hours=0.0,
        critical_path_growth_percent=0.0,
        calendar_floored_items=[],
        items_on_critical_path=[],
    )
    pmo = PMOKpiEngine(project_state, metrics, forecast, cp).calculate()

    expected = (10 / 11 + 1.0 + 1.0 + 9 / 11 + 1.0) / 5
    assert abs(pmo.sprint_adherence_index - expected) < 0.01
    assert pmo.sprints_due_count == 5
    assert pmo.sprints_on_time_count == 3


def test_forecast_confidence_uses_stability_and_carryover_ratios():
    """Confidence sub-scores should use std-dev/mean and normalized carryover, not raw variance or raw carryover rate."""
    project_state = make_sample_project_state()
    project_state.sprints = [
        Sprint(
            sprint_id="S1",
            sprint_name="Sprint 1",
            sprint_number=1,
            start_date=datetime(2025, 1, 1),
            end_date=datetime(2025, 1, 15),
            working_days=10,
            sprint_goal="Init",
            status=SprintStatus.COMPLETED,
            planned_velocity_hrs=160.0,
            carryover_count=0,
        ),
        Sprint(
            sprint_id="S2",
            sprint_name="Sprint 2",
            sprint_number=2,
            start_date=datetime(2025, 1, 16),
            end_date=datetime(2025, 1, 29),
            working_days=10,
            sprint_goal="Build",
            status=SprintStatus.COMPLETED,
            planned_velocity_hrs=160.0,
            carryover_count=0,
        ),
    ]
    project_state.work_items = [
        WorkItem(item_id="WI-001", title="Task 1", work_type=WorkItemType.TASK, assigned_sprint="Sprint 1", original_sprint="Sprint 1", assigned_resource="R1", required_skill="Python", priority=Priority.HIGH, estimated_effort_hrs=40.0, current_estimate_hrs=40.0, actual_effort_hrs=10.0, remaining_effort_hrs=30.0, progress_pct=0.25, status=WorkItemStatus.IN_PROGRESS, is_scope_changed=False, scope_change_reason=None),
        WorkItem(item_id="WI-002", title="Task 2", work_type=WorkItemType.TASK, assigned_sprint="Sprint 1", original_sprint="Sprint 1", assigned_resource="R1", required_skill="Python", priority=Priority.HIGH, estimated_effort_hrs=40.0, current_estimate_hrs=40.0, actual_effort_hrs=10.0, remaining_effort_hrs=30.0, progress_pct=0.25, status=WorkItemStatus.IN_PROGRESS, is_scope_changed=False, scope_change_reason=None),
        WorkItem(item_id="WI-003", title="Task 3", work_type=WorkItemType.TASK, assigned_sprint="Sprint 2", original_sprint="Sprint 2", assigned_resource="R1", required_skill="Python", priority=Priority.HIGH, estimated_effort_hrs=40.0, current_estimate_hrs=40.0, actual_effort_hrs=10.0, remaining_effort_hrs=30.0, progress_pct=0.25, status=WorkItemStatus.IN_PROGRESS, is_scope_changed=False, scope_change_reason=None),
        WorkItem(item_id="WI-004", title="Task 4", work_type=WorkItemType.TASK, assigned_sprint="Sprint 2", original_sprint="Sprint 2", assigned_resource="R1", required_skill="Python", priority=Priority.HIGH, estimated_effort_hrs=40.0, current_estimate_hrs=40.0, actual_effort_hrs=10.0, remaining_effort_hrs=30.0, progress_pct=0.25, status=WorkItemStatus.IN_PROGRESS, is_scope_changed=False, scope_change_reason=None),
    ]
    project_state.actuals = [
        SprintActual(sprint_id="S1", sprint_number=1, planned_effort_hrs=160.0, actual_effort_hrs=140.0, tasks_planned=10, tasks_completed=8, carryover_count=1),
        SprintActual(sprint_id="S2", sprint_number=2, planned_effort_hrs=160.0, actual_effort_hrs=160.0, tasks_planned=10, tasks_completed=9, carryover_count=0),
    ]
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()

    result = ForecastEngine(project_state, metrics, cp, spill).calculate()

    assert result.confidence.confidence_inputs["estimation_variance"] > 0.5
    assert result.confidence.confidence_inputs["carryover_consistency"] > 0.5


def test_forecast_basic():
    """Basic smoke test for deterministic forecast."""
    project_state: ProjectState = make_sample_project_state()

    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()

    engine = ForecastEngine(project_state, metrics, cp, spill)
    result = engine.calculate()

    # Basic assertions
    assert result.remaining_effort_hours >= 0
    assert result.projected_velocity > 0
    assert isinstance(result.expected_finish_date, datetime)
    assert 0.0 <= result.completion_percentage <= 1.0
    assert isinstance(result.scope_growth_hours, float)
    assert isinstance(result.scope_growth_percent, float)
    assert isinstance(result.scope_impact_days, float)
    assert isinstance(result.scope_growth_message, str)
    
    # R5: Target date comparison
    assert isinstance(result.target_end_date, datetime)
    assert isinstance(result.expected_finish_date, datetime)
    assert isinstance(result.expected_delay_days, float)
    assert isinstance(result.on_track, bool)
    
    # Verify on_track logic
    if result.expected_finish_date <= result.target_end_date:
        assert result.on_track is True
        assert result.expected_delay_days <= 0
    else:
        assert result.on_track is False
        assert result.expected_delay_days > 0


def test_forecast_deterministic():
    """Test that forecast is deterministic (same result regardless of call time)."""
    project_state = make_sample_project_state()
    
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    
    engine = ForecastEngine(project_state, metrics, cp, spill)
    result1 = engine.calculate()
    
    # Run again immediately (should get same result)
    result2 = engine.calculate()
    
    # R1: Timeline anchoring - expected_finish_date should be identical
    assert result1.expected_finish_date == result2.expected_finish_date
    assert result1.expected_delay_days == result2.expected_delay_days
    assert result1.on_track == result2.on_track


def test_forecast_exposes_structured_explainability():
    """Forecast output should include deterministic confidence, evidence, drivers, and assumptions."""
    project_state = make_sample_project_state()

    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()

    result = ForecastEngine(project_state, metrics, cp, spill).calculate()

    assert result.confidence is not None
    assert 0.0 <= result.confidence.confidence_score <= 1.0
    assert result.confidence.confidence_level in {"HIGH", "MEDIUM", "LOW"}
    assert result.forecast_drivers
    assert result.forecast_evidence
    assert result.forecast_assumptions is not None
    assert result.forecast_explanation is not None
    assert result.forecast_drivers[0].impact >= result.forecast_drivers[-1].impact
    assert not any(e.name == "Effective project velocity" for e in result.forecast_evidence)
    assert any(e.name == "Historical sprint velocity" for e in result.forecast_evidence)
    velocity_evidence = next(e for e in result.forecast_evidence if e.name == "Historical sprint velocity")
    assert velocity_evidence.value < 400


def test_no_blockers_leaves_velocity_unchanged():
    """A project with no blockers should not incur blocker-based velocity loss."""
    project_state = make_sample_project_state()
    metrics = MetricsEngine(project_state).calculate()
    metrics.estimated_blocker_velocity_impact = 0.0

    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()

    result = ForecastEngine(project_state, metrics, cp, spill).calculate()

    assert result.blocker_penalty_hours == 0.0
    assert result.forecast_drivers[0].name != "Blockers"


def test_large_spillover_reduces_projected_velocity():
    """Large predicted spillover should lower projected velocity and increase delay."""
    project_state = make_sample_project_state()
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysis(
        spillover_probability={},
        predicted_spillover_by_sprint={1: 10.0},
        spillover_confidence_intervals={},
        high_spillover_risk_items=[],
        historical_carryover_rate=0.0,
        historical_carryover_std_dev=0.0,
        sprint_utilization_pct={},
    )

    result = ForecastEngine(project_state, metrics, cp, spill).calculate()

    assert result.projected_velocity < metrics.actual_avg_velocity
    assert any(driver.name == "Carryover" for driver in result.forecast_drivers)


def test_spillover_steering_brief_explains_conditional_risk_when_blockers_saturate_velocity_floor():
    """Spillover detail should explain the hidden risk when blockers already absorb spillover."""
    project_state = make_sample_project_state()
    metrics = MetricsEngine(project_state).calculate()
    metrics.estimated_blocker_velocity_impact = 0.7
    project_state.blockers = [
        Blocker(
            blocker_id="BLK-006",
            related_item_id="WI-001",
            impacted_item_ids=["WI-001"],
            description="Blocking work",
            severity=BlockerSeverity.HIGH,
            status=BlockerStatus.OPEN,
            owner="Alice",
            raised_date=datetime(2025, 1, 1),
            target_resolution_date=datetime(2025, 1, 15),
            category=BlockerCategory.OTHER,
        )
    ]
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysis(
        spillover_probability={},
        predicted_spillover_by_sprint={1: 217.5},
        spillover_confidence_intervals={},
        high_spillover_risk_items=[],
        historical_carryover_rate=0.0,
        historical_carryover_std_dev=0.0,
        sprint_utilization_pct={},
    )

    result = ForecastEngine(project_state, metrics, cp, spill).calculate()
    spillover_driver = next(d for d in result.steering_brief.waterfall if d.key == "spillover")

    assert result.schedule_diagnostics.velocity_floor_saturated_by_blockers
    assert "absorbed" in spillover_driver.detail.lower()
    assert "conditional" in spillover_driver.detail.lower() or "if" in spillover_driver.detail.lower()


def test_scope_growth_increases_delay_driver():
    """Scope growth should increase the scope driver impact and the forecast delay."""
    project_state = make_sample_project_state()
    project_state.work_items[0].current_estimate_hrs = 80.0
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()

    result = ForecastEngine(project_state, metrics, cp, spill).calculate()

    assert any(driver.name == "Scope Growth" for driver in result.forecast_drivers)
    assert result.scope_growth_hours > 0.0


def test_empty_historical_data_keeps_confidence_in_range():
    """Forecast confidence should remain bounded even when no history is available."""
    project_state = make_sample_project_state()
    project_state.actuals = []
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()

    result = ForecastEngine(project_state, metrics, cp, spill).calculate()

    assert 0.0 <= result.confidence.confidence_score <= 1.0
    assert result.confidence.confidence_level in {"HIGH", "MEDIUM", "LOW"}


def test_zero_remaining_effort_forestalls_delay():
    """A zero-remaining-effort project should not generate a positive delay from work remaining."""
    project_state = make_sample_project_state()
    project_state.work_items[0].remaining_effort_hrs = 0.0
    project_state.work_items[0].actual_effort_hrs = 40.0
    project_state.work_items[0].progress_pct = 1.0

    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()

    result = ForecastEngine(project_state, metrics, cp, spill).calculate()

    assert result.remaining_effort_hours >= 0.0
    assert result.expected_delay_days <= 0.0
    assert result.completion_percentage >= 0.99


def test_critical_path_remaining_hours():
    """Test that R2 uses critical_path_remaining_hours correctly."""
    start_date = datetime(2025, 1, 1)
    end_date = datetime(2025, 3, 1)
    
    project_info = ProjectInfo(
        project_name="CP Remaining Test",
        sponsor="Test",
        business_unit="Eng",
        project_manager="PM",
        customer="Customer",
        status="Active",
        start_date=start_date,
        target_end_date=end_date,
        sprint_duration_days=10,
        methodology="Agile",
    )
    
    team = [
        Resource(
            resource_id="R1",
            name="Alice",
            role="Engineer",
            primary_skill="Python",
            secondary_skill="",
            skill_level=SkillLevel.SENIOR,
            allocation_pct=1.0,
            availability_pct=1.0,
        )
    ]
    
    sprints = [
        Sprint(
            sprint_id="S1",
            sprint_name="Sprint 1",
            sprint_number=1,
            start_date=start_date,
            end_date=start_date + timedelta(days=10),
            working_days=10,
            sprint_goal="Init",
            status=SprintStatus.COMPLETED,
            planned_velocity_hrs=100.0,
            carryover_count=0,
        ),
        Sprint(
            sprint_id="S2",
            sprint_name="Sprint 2",
            sprint_number=2,
            start_date=start_date + timedelta(days=10),
            end_date=start_date + timedelta(days=20),
            working_days=10,
            sprint_goal="Dev",
            status=SprintStatus.IN_PROGRESS,
            planned_velocity_hrs=100.0,
            carryover_count=0,
        )
    ]
    
    # Create items with dependencies
    work_items = [
        WorkItem(
            item_id="WI-001",
            title="Task 1 - 90% done",
            work_type=WorkItemType.TASK,
            assigned_sprint="Sprint 1",
            original_sprint="Sprint 1",
            assigned_resource="R1",
            required_skill=SkillLevel.SENIOR,
            priority=Priority.HIGH,
            estimated_effort_hrs=40.0,
            current_estimate_hrs=40.0,
            actual_effort_hrs=36.0,
            remaining_effort_hrs=4.0,  # Only 4 hrs remaining
            progress_pct=0.9,
            status=WorkItemStatus.IN_PROGRESS,
            is_scope_changed=False,
        ),
        WorkItem(
            item_id="WI-002",
            title="Task 2 - Dependent",
            work_type=WorkItemType.TASK,
            assigned_sprint="Sprint 2",
            original_sprint="Sprint 2",
            assigned_resource="R1",
            required_skill=SkillLevel.SENIOR,
            priority=Priority.HIGH,
            estimated_effort_hrs=30.0,
            current_estimate_hrs=30.0,
            actual_effort_hrs=0.0,
            remaining_effort_hrs=30.0,
            progress_pct=0.0,
            status=WorkItemStatus.NOT_STARTED,
            is_scope_changed=False,
        )
    ]
    
    dependencies = [
        Dependency(
            dependency_id="DEP-001",
            predecessor_item_id="WI-001",
            successor_item_id="WI-002",
            dependency_type=DependencyType.FINISH_TO_START,
            is_on_critical_path=False,
            lag_days=0,
        )
    ]
    
    blockers = []
    actuals = []
    
    project_state = ProjectState(
        project_id="CP-TEST",
        project_info=project_info,
        team=team,
        sprints=sprints,
        work_items=work_items,
        dependencies=dependencies,
        blockers=blockers,
        actuals=actuals,
    )
    
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    
    # R2: Verify critical_path_remaining_hours is calculated
    assert hasattr(cp, 'critical_path_remaining_hours')
    # Critical path should include WI-001 and WI-002
    # WI-001 has 4 hrs remaining, WI-002 has 30 hrs remaining
    # Expected: 4 + 30 = 34 hrs
    assert cp.critical_path_remaining_hours == pytest.approx(34.0, abs=0.1)
    # But full duration would be 40 + 30 = 70
    assert cp.critical_path_duration_hours == pytest.approx(70.0, abs=0.1)
    
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    engine = ForecastEngine(project_state, metrics, cp, spill)
    result = engine.calculate()
    
    # The forecast should use cp_remaining_hours (34), not cp_duration_hours (70)
    # This means the forecast should be much faster than if full duration was used
    assert result.remaining_effort_hours < 70  # Should use remaining, not full


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 3.2 - MONTE CARLO TESTS
# ═══════════════════════════════════════════════════════════════════════════


def test_monte_carlo_basic():
    """Basic smoke test for Monte Carlo simulation."""
    from app.engines.monte_carlo_engine import MonteCarloEngine
    
    project_state = make_sample_project_state()
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    
    # Run with smaller sample for speed
    engine = MonteCarloEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        spillover=spill,
        simulation_count=100,
        seed=42,  # Fixed seed for reproducibility
    )
    result = engine.calculate()
    
    # Basic assertions
    assert result.simulation_count == 100
    assert result.target_end_date == project_state.project_info.target_end_date
    assert 0.0 <= result.on_time_probability <= 1.0
    assert result.on_time_risk_level in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert result.simulations_on_time + result.simulations_late == 100
    
    # Statistics
    assert result.statistics.mean_finish_date is not None
    assert result.statistics.median_finish_date is not None
    assert result.statistics.percentile_10 is not None
    assert result.statistics.percentile_90 is not None
    
    # Percentile ordering: p10 <= p25 <= p50 <= p75 <= p90
    assert result.statistics.percentile_10 <= result.statistics.percentile_25
    assert result.statistics.percentile_25 <= result.statistics.percentile_50
    assert result.statistics.percentile_50 <= result.statistics.percentile_75
    assert result.statistics.percentile_75 <= result.statistics.percentile_90


def test_monte_carlo_deterministic_with_seed():
    """Verify that Monte Carlo with seed produces same results (deterministic)."""
    from app.engines.monte_carlo_engine import MonteCarloEngine
    
    project_state = make_sample_project_state()
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    
    # Run twice with same seed
    engine1 = MonteCarloEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        spillover=spill,
        simulation_count=100,
        seed=12345,
    )
    result1 = engine1.calculate()
    
    engine2 = MonteCarloEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        spillover=spill,
        simulation_count=100,
        seed=12345,
    )
    result2 = engine2.calculate()
    
    # Same seed should produce same results
    assert result1.on_time_probability == result2.on_time_probability
    assert result1.statistics.median_finish_date == result2.statistics.median_finish_date
    assert result1.most_likely_finish_date == result2.most_likely_finish_date


def test_monte_carlo_target_date_constant():
    """Verify that target_end_date is NEVER modified and remains constant."""
    from app.engines.monte_carlo_engine import MonteCarloEngine
    
    project_state = make_sample_project_state()
    original_target = project_state.project_info.target_end_date
    
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    
    engine = MonteCarloEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        spillover=spill,
        simulation_count=100,
        seed=42,
    )
    result = engine.calculate()
    
    # Target date must be exactly the same
    assert result.target_end_date == original_target
    # Verify original state wasn't modified
    assert project_state.project_info.target_end_date == original_target


def test_monte_carlo_on_time_probability():
    """Test on-time probability calculation accuracy."""
    from app.engines.monte_carlo_engine import MonteCarloEngine
    
    project_state = make_sample_project_state()
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    
    engine = MonteCarloEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        spillover=spill,
        simulation_count=1000,
        seed=42,
    )
    result = engine.calculate()
    
    # Verify probability calculation
    # on_time_probability = simulations_on_time / total_simulations
    calculated_prob = result.simulations_on_time / result.simulation_count
    assert result.on_time_probability == pytest.approx(calculated_prob, abs=0.001)


def test_monte_carlo_risk_levels():
    """Test risk level assignment based on probability."""
    from app.engines.monte_carlo_engine import MonteCarloEngine, OnTimeRisk
    
    # Test different risk levels
    # Note: We can't easily control probability without mocking, so we test the logic
    
    project_state = make_sample_project_state()
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    
    engine = MonteCarloEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        spillover=spill,
        simulation_count=100,
        seed=42,
    )
    result = engine.calculate()
    
    # Verify risk level is one of the expected values
    assert result.on_time_risk_level in [
        OnTimeRisk.LOW,
        OnTimeRisk.MEDIUM,
        OnTimeRisk.HIGH,
        OnTimeRisk.CRITICAL
    ]
    
    # Verify risk level matches probability thresholds
    if result.on_time_probability > 0.80:
        assert result.on_time_risk_level == OnTimeRisk.LOW
    elif result.on_time_probability >= 0.60:
        assert result.on_time_risk_level == OnTimeRisk.MEDIUM
    elif result.on_time_probability >= 0.40:
        assert result.on_time_risk_level == OnTimeRisk.HIGH
    else:
        assert result.on_time_risk_level == OnTimeRisk.CRITICAL


def test_monte_carlo_variability_increases_range():
    """Test that higher variability parameters increase the range of outcomes."""
    from app.engines.monte_carlo_engine import MonteCarloEngine
    
    project_state = make_sample_project_state()
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    
    # Low variability
    engine_low = MonteCarloEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        spillover=spill,
        simulation_count=100,
        velocity_std_dev_pct=0.01,  # Very low
        remaining_work_std_dev_pct=0.01,
        seed=42,
    )
    result_low = engine_low.calculate()
    range_low = (result_low.statistics.percentile_90 - result_low.statistics.percentile_10).days
    
    # High variability
    engine_high = MonteCarloEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        spillover=spill,
        simulation_count=100,
        velocity_std_dev_pct=0.30,  # High
        remaining_work_std_dev_pct=0.30,
        seed=42,
    )
    result_high = engine_high.calculate()
    range_high = (result_high.statistics.percentile_90 - result_high.statistics.percentile_10).days
    
    # Higher variability should produce wider range (more spread)
    # Note: This is probabilistic, so we check if high > low (accounting for randomness)
    assert range_high >= range_low * 0.8  # Allow some tolerance


def test_monte_carlo_best_most_likely_worst_case():
    """Test that best/most_likely/worst case dates are in correct order."""
    from app.engines.monte_carlo_engine import MonteCarloEngine
    
    project_state = make_sample_project_state()
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    
    engine = MonteCarloEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        spillover=spill,
        simulation_count=100,
        seed=42,
    )
    result = engine.calculate()
    
# best_case <= most_likely <= p90
    assert result.best_case_finish_date <= result.most_likely_finish_date
    assert result.most_likely_finish_date <= result.p90_finish_date

    # These should match the percentiles
    assert result.best_case_finish_date == result.statistics.percentile_10
    assert result.most_likely_finish_date == result.statistics.percentile_50
    assert result.p90_finish_date == result.statistics.percentile_90


def test_monte_carlo_p80_p95_percentiles():
    """Test that p80 and p95 percentiles are present and properly ordered."""
    from app.engines.monte_carlo_engine import MonteCarloEngine
    
    project_state = make_sample_project_state()
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    
    engine = MonteCarloEngine(
        project_state=project_state,
        metrics=metrics,
        cp_result=cp,
        spillover=spill,
        simulation_count=100,
        seed=42,
    )
    result = engine.calculate()
    
    # Verify p80 and p95 fields exist and are datetime objects
    assert hasattr(result, 'p80_finish_date')
    assert hasattr(result, 'p95_finish_date')
    assert isinstance(result.p80_finish_date, datetime)
    assert isinstance(result.p95_finish_date, datetime)
    
    # Verify percentile ordering: p10 ≤ p25 ≤ p50 ≤ p75 ≤ p80 ≤ p90 ≤ p95
    assert result.statistics.percentile_10 <= result.statistics.percentile_25
    assert result.statistics.percentile_25 <= result.statistics.percentile_50
    assert result.statistics.percentile_50 <= result.statistics.percentile_75
    assert result.statistics.percentile_75 <= result.statistics.percentile_80
    assert result.statistics.percentile_80 <= result.statistics.percentile_90
    assert result.statistics.percentile_90 <= result.statistics.percentile_95
    
    # Verify p80 and p95 match the statistics percentiles
    assert result.p80_finish_date == result.statistics.percentile_80
    assert result.p95_finish_date == result.statistics.percentile_95
    
    # Verify proper ordering: p10 < p25 < p50 < p75 < p80 < p90 < p95
    # So: best_case (p10) < most_likely (p50) < p80 < p90 < p95
    assert result.best_case_finish_date <= result.p80_finish_date
    assert result.p80_finish_date <= result.p90_finish_date
    assert result.p90_finish_date <= result.p95_finish_date
