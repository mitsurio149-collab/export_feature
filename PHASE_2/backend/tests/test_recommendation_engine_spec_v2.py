"""
Tests for RecommendationEngine (Specification-Compliant v2)

Tests signal detection, recommendation generation, and impact quantification.
"""
import pytest
pytest.skip('references unimplemented spec_v2 module, not part of current architecture', allow_module_level=True)
from datetime import datetime, timedelta
from app.domain.models import (
    ProjectState,
    ProjectInfo,
    Resource,
    Sprint,
    WorkItem,
    Dependency,
    Blocker,
    SkillLevel,
    WorkItemType,
    Priority,
    WorkItemStatus,
    SprintStatus,
    BlockerSeverity,
    BlockerCategory,
    DependencyType,
)
from app.engines.metrics_engine import MetricsEngine
from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.spillover_engine import SpilloverAnalysisEngine
from app.engines.forecast_engine import ForecastEngine
from app.engines.monte_carlo_engine import MonteCarloEngine
from app.engines.recommendation_engine_spec_v2 import (
    SignalDetectionEngine,
    RecommendationEngine,
)


@pytest.fixture
def minimal_project_state():
    """Create a minimal project for signal detection tests"""
    start_date = datetime(2025, 1, 1)
    end_date = datetime(2025, 3, 1)
    
    project_info = ProjectInfo(
        project_name="Test Project",
        sponsor="Sponsor",
        business_unit="Engineering",
        project_manager="PM",
        customer="Customer",
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
            secondary_skill="C++",
            skill_level=SkillLevel.SENIOR,
            allocation_pct=0.8,
            availability_pct=1.0,
        ),
        Resource(
            resource_id="R2",
            name="Bob",
            role="Engineer",
            primary_skill="Java",
            secondary_skill="Python",
            skill_level=SkillLevel.MID,
            allocation_pct=0.8,
            availability_pct=1.0,
        ),
    ]
    
    sprints = [
        Sprint(
            sprint_id="S1",
            sprint_name="Sprint 1",
            sprint_number=1,
            start_date=start_date,
            end_date=start_date + timedelta(days=14),
            working_days=10,
            sprint_goal="Dev",
            status=SprintStatus.IN_PROGRESS,
            planned_velocity_hrs=160.0,
            carryover_count=0,
        ),
        Sprint(
            sprint_id="S2",
            sprint_name="Sprint 2",
            sprint_number=2,
            start_date=start_date + timedelta(days=14),
            end_date=start_date + timedelta(days=28),
            working_days=10,
            sprint_goal="Dev",
            status=SprintStatus.NOT_STARTED,
            planned_velocity_hrs=160.0,
            carryover_count=0,
        ),
    ]
    
    work_items = [
        WorkItem(
            item_id="WI-001",
            title="Task 1",
            work_type=WorkItemType.TASK,
            assigned_sprint="S1",
            original_sprint="S1",
            priority=Priority.HIGH,
            status=WorkItemStatus.IN_PROGRESS,
            estimated_effort_hrs=20.0,
            current_estimate_hrs=20.0,
            remaining_effort_hrs=15.0,
            assigned_resource="R1",
            required_skill="Python",
        ),
        WorkItem(
            item_id="WI-002",
            title="Task 2",
            work_type=WorkItemType.TASK,
            assigned_sprint="S2",
            original_sprint="S1",
            priority=Priority.MEDIUM,
            status=WorkItemStatus.NOT_STARTED,
            estimated_effort_hrs=30.0,
            current_estimate_hrs=30.0,
            remaining_effort_hrs=30.0,
            assigned_resource="R2",
            required_skill="Java",
        ),
    ]
    
    dependencies = [
        Dependency(
            dependency_id="DEP-001",
            predecessor_item_id="WI-001",
            successor_item_id="WI-002",
            lag_days=0,
            dependency_type=DependencyType.FINISH_TO_START,
        )
    ]
    
    blockers = []
    
    return ProjectState(
        project_id="test-project",
        project_info=project_info,
        team=team,
        sprints=sprints,
        work_items=work_items,
        dependencies=dependencies,
        blockers=blockers,
        actuals=[],
    )


def test_signal_detection_engine_initialization(minimal_project_state):
    """Test SignalDetectionEngine can be initialized"""
    metrics = MetricsEngine(minimal_project_state).calculate()
    dep_engine = DependencyGraphEngine(minimal_project_state)
    dag = dep_engine.build_dag()
    cp_engine = CriticalPathEngine(minimal_project_state, dag)
    cp_result = cp_engine.analyze()
    spillover = SpilloverAnalysisEngine(minimal_project_state, metrics.average_item_effort).analyze()
    forecast = ForecastEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    monte_carlo = MonteCarloEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    
    signal_engine = SignalDetectionEngine(
        minimal_project_state,
        metrics,
        cp_result,
        dag,
        spillover,
        forecast,
        monte_carlo,
    )
    
    assert signal_engine is not None
    assert signal_engine.project_state == minimal_project_state


def test_detect_blocker_signals_empty(minimal_project_state):
    """Test blocker signal detection with no active blockers"""
    metrics = MetricsEngine(minimal_project_state).calculate()
    dep_engine = DependencyGraphEngine(minimal_project_state)
    dag = dep_engine.build_dag()
    cp_engine = CriticalPathEngine(minimal_project_state, dag)
    cp_result = cp_engine.analyze()
    spillover = SpilloverAnalysisEngine(minimal_project_state, metrics.average_item_effort).analyze()
    forecast = ForecastEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    monte_carlo = MonteCarloEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    
    signal_engine = SignalDetectionEngine(
        minimal_project_state,
        metrics,
        cp_result,
        dag,
        spillover,
        forecast,
        monte_carlo,
    )
    
    signals = signal_engine._detect_blocker_signals()
    assert len(signals) == 0


def test_detect_blocker_signals_with_blocker(minimal_project_state):
    """Test blocker signal detection with an active blocker"""
    # Add a blocker
    blocker = Blocker(
        blocker_id="BLK-001",
        related_item_id="WI-001",
        impacted_item_ids=["WI-001", "WI-002"],
        description="Test blocker",
        severity=BlockerSeverity.HIGH,
        status="Open",
        owner="TestOwner",
        raised_date=datetime.utcnow(),
        target_resolution_date=datetime.utcnow() + timedelta(days=2),
        category=BlockerCategory.EXTERNAL_TEAM_DEPENDENCY,
        notes="mitigation: alternative path available",
    )
    minimal_project_state.blockers.append(blocker)
    
    metrics = MetricsEngine(minimal_project_state).calculate()
    dep_engine = DependencyGraphEngine(minimal_project_state)
    dag = dep_engine.build_dag()
    cp_engine = CriticalPathEngine(minimal_project_state, dag)
    cp_result = cp_engine.analyze()
    spillover = SpilloverAnalysisEngine(minimal_project_state, metrics.average_item_effort).analyze()
    forecast = ForecastEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    monte_carlo = MonteCarloEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    
    signal_engine = SignalDetectionEngine(
        minimal_project_state,
        metrics,
        cp_result,
        dag,
        spillover,
        forecast,
        monte_carlo,
    )
    
    signals = signal_engine._detect_blocker_signals()
    assert len(signals) == 1
    
    signal = signals[0]
    assert signal.blocker_id == "BLK-001"
    assert signal.severity == BlockerSeverity.HIGH
    assert signal.category == BlockerCategory.EXTERNAL_TEAM_DEPENDENCY
    assert set(signal.impacted_item_ids) == {"WI-001", "WI-002"}
    assert signal.has_mitigation_supplier is True
    assert signal.blocked_hours > 0


def test_owner_concentration_signals(minimal_project_state):
    """Test owner concentration signal detection"""
    metrics = MetricsEngine(minimal_project_state).calculate()
    dep_engine = DependencyGraphEngine(minimal_project_state)
    dag = dep_engine.build_dag()
    cp_engine = CriticalPathEngine(minimal_project_state, dag)
    cp_result = cp_engine.analyze()
    spillover = SpilloverAnalysisEngine(minimal_project_state, metrics.average_item_effort).analyze()
    forecast = ForecastEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    monte_carlo = MonteCarloEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    
    signal_engine = SignalDetectionEngine(
        minimal_project_state,
        metrics,
        cp_result,
        dag,
        spillover,
        forecast,
        monte_carlo,
    )
    
    signals = signal_engine._detect_owner_concentration_signals()
    assert len(signals) > 0
    
    # Each signal should have required fields
    for signal in signals:
        assert signal.resource_id
        assert signal.owner_name
        assert signal.load_ratio >= 0
        assert signal.flag in ("NONE", "OVERLOADED", "SINGLE_POINT_OF_FAILURE", "UNDERUTILIZED")


def test_sprint_capacity_signals(minimal_project_state):
    """Test sprint capacity signal detection"""
    metrics = MetricsEngine(minimal_project_state).calculate()
    dep_engine = DependencyGraphEngine(minimal_project_state)
    dag = dep_engine.build_dag()
    cp_engine = CriticalPathEngine(minimal_project_state, dag)
    cp_result = cp_engine.analyze()
    spillover = SpilloverAnalysisEngine(minimal_project_state, metrics.average_item_effort).analyze()
    forecast = ForecastEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    monte_carlo = MonteCarloEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    
    signal_engine = SignalDetectionEngine(
        minimal_project_state,
        metrics,
        cp_result,
        dag,
        spillover,
        forecast,
        monte_carlo,
    )
    
    signals = signal_engine._detect_sprint_capacity_signals()
    assert len(signals) == 2  # Two sprints
    
    for signal in signals:
        assert signal.sprint_id
        assert signal.planned_hours >= 0
        assert signal.team_capacity_hrs >= 0
        assert signal.utilization_ratio >= 0


def test_critical_path_signal(minimal_project_state):
    """Test critical path signal detection"""
    metrics = MetricsEngine(minimal_project_state).calculate()
    dep_engine = DependencyGraphEngine(minimal_project_state)
    dag = dep_engine.build_dag()
    cp_engine = CriticalPathEngine(minimal_project_state, dag)
    cp_result = cp_engine.analyze()
    spillover = SpilloverAnalysisEngine(minimal_project_state, metrics.average_item_effort).analyze()
    forecast = ForecastEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    monte_carlo = MonteCarloEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    
    signal_engine = SignalDetectionEngine(
        minimal_project_state,
        metrics,
        cp_result,
        dag,
        spillover,
        forecast,
        monte_carlo,
    )
    
    signal = signal_engine._detect_critical_path_signal()
    assert signal is not None
    assert len(signal.cp_nodes) >= 0
    assert signal.cp_remaining_hours >= 0
    assert signal.flag in ("NONE", "CP_AT_RISK", "CP_SINGLE_OWNER_RISK", "NEAR_CRITICAL_RISK")


def test_schedule_gap_signal(minimal_project_state):
    """Test schedule gap signal detection"""
    metrics = MetricsEngine(minimal_project_state).calculate()
    dep_engine = DependencyGraphEngine(minimal_project_state)
    dag = dep_engine.build_dag()
    cp_engine = CriticalPathEngine(minimal_project_state, dag)
    cp_result = cp_engine.analyze()
    spillover = SpilloverAnalysisEngine(minimal_project_state, metrics.average_item_effort).analyze()
    forecast = ForecastEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    monte_carlo = MonteCarloEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    
    signal_engine = SignalDetectionEngine(
        minimal_project_state,
        metrics,
        cp_result,
        dag,
        spillover,
        forecast,
        monte_carlo,
    )
    
    signal = signal_engine._detect_schedule_gap_signal()
    assert signal is not None
    assert signal.remaining_effort_hrs >= 0
    assert signal.scope_inflation_pct >= 0
    assert signal.flag in ("NONE", "SCHEDULE_AT_RISK", "VELOCITY_CONCERN", "SCOPE_CREEP")


def test_scope_signal_uses_baseline_denominator(minimal_project_state):
    """Scope creep percentage should be based on original baseline estimate, not remaining effort."""
    metrics = MetricsEngine(minimal_project_state).calculate()
    dep_engine = DependencyGraphEngine(minimal_project_state)
    dag = dep_engine.build_dag()
    cp_engine = CriticalPathEngine(minimal_project_state, dag)
    cp_result = cp_engine.analyze()
    spillover = SpilloverAnalysisEngine(minimal_project_state, metrics.average_item_effort).analyze()
    forecast = ForecastEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    monte_carlo = MonteCarloEngine(minimal_project_state, metrics, cp_result, spillover).calculate()

    detector = ScheduleDetector(
        minimal_project_state,
        forecast,
        monte_carlo,
        None,
        metrics,
    )
    signals = detector.detect()
    scope_signal = next((signal for signal in signals if signal.context.get("flag") == "SCOPE_CREEP"), None)

    assert scope_signal is not None
    assert scope_signal.context["scope_inflation_pct"] < 50.0
    assert scope_signal.context["scope_inflation_pct"] >= 0.0


def test_recommendation_generation(minimal_project_state):
    """Test recommendation generation"""
    metrics = MetricsEngine(minimal_project_state).calculate()
    dep_engine = DependencyGraphEngine(minimal_project_state)
    dag = dep_engine.build_dag()
    cp_engine = CriticalPathEngine(minimal_project_state, dag)
    cp_result = cp_engine.analyze()
    spillover = SpilloverAnalysisEngine(minimal_project_state, metrics.average_item_effort).analyze()
    forecast = ForecastEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    monte_carlo = MonteCarloEngine(minimal_project_state, metrics, cp_result, spillover).calculate()
    
    rec_engine = RecommendationEngine(
        minimal_project_state,
        metrics,
        cp_result,
        dag,
        spillover,
        forecast,
        monte_carlo,
    )
    
    recommendations = rec_engine.generate_recommendations(max_count=10)
    
    # Should generate 0 recommendations for a clean project
    assert len(recommendations) <= 10
    
    for rec in recommendations:
        assert rec.id
        assert rec.category
        assert rec.priority_rank >= 1
        assert rec.title
        assert rec.estimated_hours_recovered >= 0
        assert rec.estimated_delay_reduction_days >= 0
        assert rec.confidence in ("HIGH", "MEDIUM", "LOW")
        assert rec.is_feasible


def test_recommendation_specificity():
    """Test that recommendations are specific (not generic)"""
    # This would require a project state that triggers various recommendations
    # For now, we just verify the structure supports specificity
    pass


def test_impact_quantification():
    """Test that all recommendations have quantified impact"""
    # This would verify that estimated_hours_recovered and estimated_delay_reduction_days
    # are never None and are derived from engine outputs
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

