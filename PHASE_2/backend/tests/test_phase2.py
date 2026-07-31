"""
Phase 2 Engine Tests

Unit tests for metrics, dependency, critical path, impact scoring, and spillover engines.
"""

import pytest
from datetime import datetime, timedelta

from app.domain.models import (
    ProjectInfo, Resource, Sprint, WorkItem, Dependency, Blocker, SprintActual, ProjectState,
    SkillLevel, WorkItemType, Priority, WorkItemStatus, SprintStatus, BlockerSeverity, BlockerStatus, BlockerCategory, DependencyType
)
from app.engines.metrics_engine import MetricsEngine, DeveloperMetrics
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.impact_scoring_engine import ImpactScoringEngine
from app.engines.spillover_engine import SpilloverAnalysisEngine


@pytest.fixture
def sample_project_state():
    """Create a sample ProjectState for testing."""
    
    # Project info
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
    
    # Team
    team = [
        Resource(
            resource_id="R1",
            name="Alice",
            role="Engineer",
            primary_skill="Python",
            secondary_skill="C++",
            skill_level=SkillLevel.SENIOR,
            allocation_pct=1.0,
            availability_pct=1.0,
        ),
        Resource(
            resource_id="R2",
            name="Bob",
            role="Engineer",
            primary_skill="Java",
            secondary_skill="JavaScript",
            skill_level=SkillLevel.MID,
            allocation_pct=0.8,
            availability_pct=0.9,
        ),
    ]
    
    # Sprints
    sprints = [
        Sprint(
            sprint_id="S1",
            sprint_name="Sprint 1",
            sprint_number=1,
            start_date=start_date,
            end_date=start_date + timedelta(days=14),
            working_days=10,
            sprint_goal="Initial setup",
            status=SprintStatus.COMPLETED,
            planned_velocity_hrs=160.0,
            carryover_count=2,
        ),
        Sprint(
            sprint_id="S2",
            sprint_name="Sprint 2",
            sprint_number=2,
            start_date=start_date + timedelta(days=14),
            end_date=start_date + timedelta(days=28),
            working_days=10,
            sprint_goal="Feature development",
            status=SprintStatus.IN_PROGRESS,
            planned_velocity_hrs=160.0,
            carryover_count=1,
        ),
    ]
    
    # Work items
    work_items = [
        WorkItem(
            item_id="WI-001",
            title="Task 1",
            work_type=WorkItemType.TASK,
            assigned_sprint="Sprint 1",
            original_sprint="Sprint 1",
            assigned_resource="R1",
            required_skill=SkillLevel.SENIOR,
            priority=Priority.HIGH,
            estimated_effort_hrs=40.0,
            current_estimate_hrs=40.0,
            actual_effort_hrs=40.0,
            remaining_effort_hrs=0.0,
            progress_pct=1.0,
            status=WorkItemStatus.COMPLETED,
            is_scope_changed=False,
            scope_change_reason=None,
        ),
        WorkItem(
            item_id="WI-002",
            title="Task 2",
            work_type=WorkItemType.TASK,
            assigned_sprint="Sprint 1",
            original_sprint="Sprint 1",
            assigned_resource="R2",
            required_skill=SkillLevel.MID,
            priority=Priority.MEDIUM,
            estimated_effort_hrs=50.0,
            current_estimate_hrs=50.0,
            actual_effort_hrs=30.0,
            remaining_effort_hrs=20.0,
            progress_pct=0.6,
            status=WorkItemStatus.IN_PROGRESS,
            is_scope_changed=False,
            scope_change_reason=None,
        ),
        WorkItem(
            item_id="WI-003",
            title="Task 3",
            work_type=WorkItemType.FEATURE,
            assigned_sprint="Sprint 2",
            original_sprint="Sprint 2",
            assigned_resource="R1",
            required_skill=SkillLevel.SENIOR,
            priority=Priority.HIGH,
            estimated_effort_hrs=60.0,
            current_estimate_hrs=60.0,
            actual_effort_hrs=0.0,
            remaining_effort_hrs=60.0,
            progress_pct=0.0,
            status=WorkItemStatus.NOT_STARTED,
            is_scope_changed=False,
            scope_change_reason=None,
        ),
        WorkItem(
            item_id="WI-004",
            title="Task 4 (Blocked)",
            work_type=WorkItemType.TASK,
            assigned_sprint="Sprint 2",
            original_sprint="Sprint 2",
            assigned_resource=None,
            required_skill=SkillLevel.MID,
            priority=Priority.MEDIUM,
            estimated_effort_hrs=30.0,
            current_estimate_hrs=30.0,
            actual_effort_hrs=0.0,
            remaining_effort_hrs=30.0,
            progress_pct=0.0,
            status=WorkItemStatus.BLOCKED,
            is_scope_changed=False,
            scope_change_reason=None,
        ),
    ]
    
    # Dependencies
    dependencies = [
        Dependency(
            dependency_id="D1",
            predecessor_item_id="WI-001",
            successor_item_id="WI-003",
            dependency_type=DependencyType.FINISH_TO_START,
            is_on_critical_path=True,
            lag_days=0,
            notes="WI-003 depends on WI-001",
        ),
        Dependency(
            dependency_id="D2",
            predecessor_item_id="WI-002",
            successor_item_id="WI-004",
            dependency_type=DependencyType.FINISH_TO_START,
            is_on_critical_path=False,
            lag_days=1,
            notes="WI-004 depends on WI-002",
        ),
    ]
    
    # Blockers
    blockers = [
        Blocker(
            blocker_id="BLK-001",
            related_item_id="WI-004",
            impacted_item_ids=["WI-004"],
            description="Waiting on external review",
            severity=BlockerSeverity.HIGH,
            status=BlockerStatus.OPEN,
            owner="External Team",
            raised_date=start_date,
            target_resolution_date=start_date + timedelta(days=7),
            category=BlockerCategory.EXTERNAL_TEAM_DEPENDENCY,
            notes="Awaiting approval",
        )
    ]
    
    # Sprint actuals
    actuals = [
        SprintActual(
            sprint_id="S1",
            sprint_number=1,
            planned_effort_hrs=160.0,
            actual_effort_hrs=140.0,
            variance_hrs=-20.0,
            tasks_planned=10,
            tasks_completed=8,
            completion_rate=0.8,
            carryover_count=2,
            carry_out_count=1,
            carry_in_count=1,
            carry_out_hours=10.0,
            carry_in_hours=10.0,
            scope_change_hours=5.0,
            blocker_impact_hrs=3.0,
            notes="Good progress",
        ),
    ]
    
    return ProjectState(
        project_id="TEST-001",
        project_info=project_info,
        team=team,
        sprints=sprints,
        work_items=work_items,
        dependencies=dependencies,
        blockers=blockers,
        actuals=actuals,
    )


class TestMetricsEngine:
    """Tests for MetricsEngine."""
    
    def test_calculate_metrics(self, sample_project_state):
        """Test metrics calculation."""
        engine = MetricsEngine(sample_project_state)
        metrics = engine.calculate()
        
        # Check completion
        assert metrics.total_items == 4
        assert metrics.completed_items == 1
        assert metrics.in_progress_items == 1
        assert metrics.blocked_items == 1
        assert metrics.not_started_items == 1
        assert metrics.completion_pct == 0.25
        
        # Check effort
        assert metrics.total_effort_hours == 180.0
        assert metrics.completed_effort_hours == 40.0
        assert metrics.remaining_effort_hours == 110.0
        
        # Check team
        assert metrics.team_size == 2
        assert metrics.active_blocker_count == 1
    
    def test_velocity_variance(self, sample_project_state):
        """Test velocity variance calculation."""
        engine = MetricsEngine(sample_project_state)
        metrics = engine.calculate()
        
        # With only 1 actual, variance should be 0
        assert metrics.velocity_variance == 0.0

    def test_enriched_metrics_are_exposed(self, sample_project_state):
        """Historical, resource, blocker, dependency, planning, and downstream-input metrics should be exposed deterministically."""
        metrics = MetricsEngine(sample_project_state).calculate()

        assert metrics.executive_metrics.total_items == 4
        assert metrics.executive_metrics.completion_pct == 0.25
        assert metrics.executive_metrics.current_sprint_number == 2

        assert metrics.work_metrics.total_effort_hours == 180.0
        assert metrics.work_metrics.remaining_effort_hours == 110.0
        assert metrics.work_metrics.completed_effort_hours == 40.0

        assert len(metrics.sprint_metrics) == 2
        assert metrics.sprint_metrics[0].planned_effort_hours == 160.0
        assert metrics.sprint_metrics[0].completion_pct == 0.8

        assert metrics.historical_metrics.planned_effort_hours == 160.0
        assert metrics.historical_metrics.actual_effort_hours == 140.0
        assert metrics.historical_metrics.effort_variance_hours == -20.0
        assert metrics.historical_metrics.completion_rate == 0.8
        assert metrics.historical_metrics.carry_in_count == 1
        assert metrics.historical_metrics.carry_out_count == 1
        assert metrics.historical_metrics.carryover_count == 2
        assert metrics.historical_metrics.velocity_by_sprint[0] == 140.0

        assert metrics.velocity_metrics.average_velocity == 140.0
        assert metrics.velocity_metrics.velocity_by_sprint[0] == 140.0
        assert metrics.velocity_metrics.velocity_stability_score >= 0.0

        assert metrics.resource_metrics.team_size == 2
        assert metrics.resource_metrics.estimation_accuracy_score >= 0.0
        assert metrics.resource_metrics.allocation_efficiency_pct >= 0.0
        assert len(metrics.resource_metrics.developer_metrics) == 2
        assert all(isinstance(item, DeveloperMetrics) for item in metrics.resource_metrics.developer_metrics)

        assert metrics.blocker_metrics.active_blocker_count == 1
        assert metrics.blocker_metrics.dependency_related_blocker_count == 1
        assert metrics.blocker_metrics.preventable_blocker_count == 0

        assert metrics.dependency_metrics.dependency_count == 2
        assert metrics.dependency_metrics.critical_dependency_density >= 0.0
        assert metrics.dependency_metrics.cross_team_dependency_count >= 0

        assert metrics.planning_metrics.planning_accuracy_score >= 0.0
        assert metrics.planning_metrics.scope_volatility_score >= 0.0
        assert metrics.planning_metrics.story_sizing_consistency_score >= 0.0

        assert metrics.quality_metrics.defect_density >= 0.0
        assert metrics.quality_metrics.rework_percentage >= 0.0

        assert metrics.risk_input_metrics.blocker_density >= 0.0
        assert metrics.risk_input_metrics.velocity_stability_score >= 0.0

        assert metrics.forecast_input_metrics.remaining_story_count == 3
        assert metrics.forecast_input_metrics.remaining_effort_hours == 110.0

        assert metrics.recommendation_input_metrics.recurring_blockers >= 0
        assert metrics.recommendation_input_metrics.critical_dependencies >= 0

    def test_executive_health_score_uses_schedule_signal(self, sample_project_state):
        """Critical schedule risk should pull the executive health score below the caution threshold."""
        engine = MetricsEngine(sample_project_state)

        executive_metrics = engine._build_executive_metrics(
            total_items=100,
            completed_items=70,
            blocked_items=0,
            remaining_effort_hours=734.0,
            current_sprint_number=2,
            completed_sprints=1,
            completion_pct=0.7042,
            on_time_probability=0.043,
        )

        health = executive_metrics.overall_health_score
        assert health < 0.55, f"Health should be <0.55 for a CRITICAL project, got {health:.3f}"

    def test_metrics_without_actuals_remain_deterministic(self, sample_project_state):
        """Missing historical actuals should not introduce fabricated values."""
        state = sample_project_state.model_copy(deep=True)
        state.actuals = []

        metrics = MetricsEngine(state).calculate()

        assert metrics.historical_metrics.actual_effort_hours == 0.0
        assert metrics.historical_metrics.velocity_by_sprint == []
        assert metrics.forecast_input_metrics.remaining_sprints == 1
        assert metrics.recommendation_input_metrics.recurring_blockers == 1

    def test_scope_changes_and_resolved_blockers_are_exposed(self, sample_project_state):
        """Scope changes and resolved blockers should be reflected as factual signals."""
        state = sample_project_state.model_copy(deep=True)
        state.work_items[2].is_scope_changed = True
        state.blockers[0].actual_resolution_date = datetime(2025, 1, 10)

        metrics = MetricsEngine(state).calculate()

        assert metrics.planning_metrics.scope_volatility_score > 0.0
        assert metrics.quality_metrics.requirement_volatility_score > 0.0
        assert metrics.blocker_metrics.active_blocker_count == 0

    def test_estimate_blocker_velocity_impact_single_blocker(self):
        """A single blocker should have its base impact."""
        blockers = [
            Blocker(
                blocker_id="BLK-SINGLE",
                related_item_id="WI-001",
                impacted_item_ids=["WI-001"],
                description="Single critical blocker",
                severity=BlockerSeverity.CRITICAL,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
        ]

        impact = MetricsEngine._estimate_blocker_velocity_impact(blockers)
        assert impact == 0.40

    def test_estimate_blocker_velocity_impact_multiple_blockers_diminishing_returns(self):
        """Multiple active blockers should increase impact with diminishing returns."""
        blockers = [
            Blocker(
                blocker_id="BLK-1",
                related_item_id="WI-001",
                impacted_item_ids=["WI-001"],
                description="Critical blocker",
                severity=BlockerSeverity.CRITICAL,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            ),
            Blocker(
                blocker_id="BLK-2",
                related_item_id="WI-002",
                impacted_item_ids=["WI-002"],
                description="High blocker",
                severity=BlockerSeverity.HIGH,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            ),
        ]

        impact_first = MetricsEngine._estimate_blocker_velocity_impact([blockers[0]])
        impact_second = MetricsEngine._estimate_blocker_velocity_impact(blockers)

        assert impact_second > impact_first
        assert impact_first == 0.40
        assert impact_second == pytest.approx(0.52, rel=1e-6)

    def test_zero_blockers(self):
        """No blockers should produce zero impact."""
        impact = MetricsEngine._estimate_blocker_velocity_impact([])
        assert impact == 0.0

    def test_single_critical(self):
        """Single critical blocker should match its base weight."""
        impact = MetricsEngine._estimate_blocker_velocity_impact([
            Blocker(
                blocker_id="BLK-CRIT",
                related_item_id="WI-001",
                impacted_item_ids=["WI-001"],
                description="Critical blocker",
                severity=BlockerSeverity.CRITICAL,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
        ])
        assert impact == pytest.approx(0.40, rel=1e-6)

    def test_single_high(self):
        """Single high blocker should match its base weight."""
        impact = MetricsEngine._estimate_blocker_velocity_impact([
            Blocker(
                blocker_id="BLK-HIGH",
                related_item_id="WI-001",
                impacted_item_ids=["WI-001"],
                description="High blocker",
                severity=BlockerSeverity.HIGH,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
        ])
        assert impact == pytest.approx(0.20, rel=1e-6)

    def test_single_medium(self):
        """Single medium blocker should match its base weight."""
        impact = MetricsEngine._estimate_blocker_velocity_impact([
            Blocker(
                blocker_id="BLK-MEDIUM",
                related_item_id="WI-001",
                impacted_item_ids=["WI-001"],
                description="Medium blocker",
                severity=BlockerSeverity.MEDIUM,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
        ])
        assert impact == pytest.approx(0.10, rel=1e-6)

    def test_single_low(self):
        """Single low blocker should match its base weight."""
        impact = MetricsEngine._estimate_blocker_velocity_impact([
            Blocker(
                blocker_id="BLK-LOW",
                related_item_id="WI-001",
                impacted_item_ids=["WI-001"],
                description="Low blocker",
                severity=BlockerSeverity.LOW,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
        ])
        assert impact == pytest.approx(0.05, rel=1e-6)

    def test_two_critical_blockers(self):
        """Two critical blockers should show diminishing returns relative to additive."""
        blockers = [
            Blocker(
                blocker_id=f"BLK-CRIT-{i}",
                related_item_id="WI-001",
                impacted_item_ids=["WI-001"],
                description="Critical blocker",
                severity=BlockerSeverity.CRITICAL,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
            for i in range(2)
        ]
        impact = MetricsEngine._estimate_blocker_velocity_impact(blockers)
        assert impact == pytest.approx(1 - (0.6 * 0.6), rel=1e-6)
        assert impact < 0.80

    def test_adding_blocker_increases_impact(self):
        """Adding an active blocker should always increase impact."""
        baseline = [
            Blocker(
                blocker_id="BLK-1",
                related_item_id="WI-001",
                impacted_item_ids=["WI-001"],
                description="Critical blocker",
                severity=BlockerSeverity.CRITICAL,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
        ]
        second = baseline + [
            Blocker(
                blocker_id="BLK-2",
                related_item_id="WI-002",
                impacted_item_ids=["WI-002"],
                description="High blocker",
                severity=BlockerSeverity.HIGH,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
        ]
        third = second + [
            Blocker(
                blocker_id="BLK-3",
                related_item_id="WI-003",
                impacted_item_ids=["WI-003"],
                description="Medium blocker",
                severity=BlockerSeverity.MEDIUM,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
        ]

        impact_baseline = MetricsEngine._estimate_blocker_velocity_impact(baseline)
        impact_second = MetricsEngine._estimate_blocker_velocity_impact(second)
        impact_third = MetricsEngine._estimate_blocker_velocity_impact(third)

        assert impact_second > impact_baseline
        assert impact_third > impact_second

    def test_result_non_negative(self):
        """Impact should never be negative."""
        blockers = [
            Blocker(
                blocker_id=f"BLK-{i}",
                related_item_id="WI-001",
                impacted_item_ids=["WI-001"],
                description="Critical blocker",
                severity=BlockerSeverity.CRITICAL,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
            for i in range(50)
        ]
        impact = MetricsEngine._estimate_blocker_velocity_impact(blockers)
        assert impact >= 0.0

    def test_result_below_one(self):
        """Impact should remain strictly below 1.0 for many blockers."""
        blockers = [
            Blocker(
                blocker_id=f"BLK-{i}",
                related_item_id="WI-001",
                impacted_item_ids=["WI-001"],
                description="High blocker",
                severity=BlockerSeverity.HIGH,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
            for i in range(100)
        ]
        impact = MetricsEngine._estimate_blocker_velocity_impact(blockers)
        assert impact < 1.0

    def test_resolved_blocker_excluded(self):
        """Resolved blockers must not contribute to impact."""
        active = Blocker(
            blocker_id="BLK-ACTIVE",
            related_item_id="WI-001",
            impacted_item_ids=["WI-001"],
            description="Active high blocker",
            severity=BlockerSeverity.HIGH,
            status=BlockerStatus.OPEN,
            owner="Owner",
            raised_date=datetime(2025, 1, 1),
            target_resolution_date=datetime(2025, 1, 8),
            category=BlockerCategory.OTHER,
            notes="",
        )
        resolved = Blocker(
            blocker_id="BLK-RESOLVED",
            related_item_id="WI-001",
            impacted_item_ids=["WI-001"],
            description="Resolved critical blocker",
            severity=BlockerSeverity.CRITICAL,
            status=BlockerStatus.RESOLVED,
            owner="Owner",
            raised_date=datetime(2025, 1, 1),
            target_resolution_date=datetime(2025, 1, 8),
            actual_resolution_date=datetime(2025, 1, 5),
            category=BlockerCategory.OTHER,
            notes="",
        )
        impact = MetricsEngine._estimate_blocker_velocity_impact([active, resolved])
        assert impact == pytest.approx(0.20, rel=1e-6)

    def test_unknown_severity_no_effect(self):
        """Unknown severities should not break the calculation."""
        active = Blocker(
            blocker_id="BLK-ACTIVE",
            related_item_id="WI-001",
            impacted_item_ids=["WI-001"],
            description="Active medium blocker",
            severity=BlockerSeverity.MEDIUM,
            status=BlockerStatus.OPEN,
            owner="Owner",
            raised_date=datetime(2025, 1, 1),
            target_resolution_date=datetime(2025, 1, 8),
            category=BlockerCategory.OTHER,
            notes="",
        )

        class UnknownSeverityBlocker:
            def __init__(self):
                self.severity = "UNKNOWN"
                self.actual_resolution_date = None

        impact = MetricsEngine._estimate_blocker_velocity_impact([active, UnknownSeverityBlocker()])
        assert impact == pytest.approx(0.10, rel=1e-6)

    @pytest.mark.parametrize(
        "severity,expected",
        [
            (BlockerSeverity.CRITICAL, 0.40),
            (BlockerSeverity.HIGH, 0.20),
            (BlockerSeverity.MEDIUM, 0.10),
            (BlockerSeverity.LOW, 0.05),
        ],
    )
    def test_single_blocker_equivalence(self, severity, expected):
        """A single blocker impact should exactly equal its severity weight."""
        impact = MetricsEngine._estimate_blocker_velocity_impact([
            Blocker(
                blocker_id="BLK-EQ",
                related_item_id="WI-001",
                impacted_item_ids=["WI-001"],
                description="Single blocker",
                severity=severity,
                status=BlockerStatus.OPEN,
                owner="Owner",
                raised_date=datetime(2025, 1, 1),
                target_resolution_date=datetime(2025, 1, 8),
                category=BlockerCategory.OTHER,
                notes="",
            )
        ])
        assert impact == pytest.approx(expected, rel=1e-6)


class TestDependencyGraphEngine:
    """Tests for DependencyGraphEngine."""
    
    def test_build_dag(self, sample_project_state):
        """Test DAG construction."""
        engine = DependencyGraphEngine(sample_project_state)
        dag = engine.build_dag()
        
        # Check graph structure
        assert len(dag.all_nodes) == 4
        assert "WI-001" in dag.graph
        assert "WI-003" in dag.graph["WI-001"]
        
        # Check no cycles
        assert not dag.has_cycles
        
        # Check degrees
        assert dag.in_degree["WI-001"] == 0
        assert dag.out_degree["WI-001"] == 1
        assert dag.in_degree["WI-003"] == 1
    
    def test_transitive_closure(self, sample_project_state):
        """Test transitive closure computation."""
        engine = DependencyGraphEngine(sample_project_state)
        dag = engine.build_dag()
        
        # WI-001 should reach WI-003
        assert "WI-003" in dag.transitive_closure["WI-001"]
        
        # WI-003 should reach nothing
        assert len(dag.transitive_closure["WI-003"]) == 0


class TestCriticalPathEngine:
    """Tests for CriticalPathEngine."""
    
    def test_analyze_critical_path(self, sample_project_state):
        """Test critical path analysis."""
        dep_engine = DependencyGraphEngine(sample_project_state)
        dag = dep_engine.build_dag()
        
        cp_engine = CriticalPathEngine(sample_project_state, dag)
        result = cp_engine.analyze()
        
        # Critical path should exist
        assert len(result.critical_path) > 0
        
        # Duration should be reasonable
        assert result.critical_path_duration_hours > 0
        assert result.critical_path_duration_days > 0

    def test_critical_path_growth_metrics(self):
        """Test original and current critical path duration aggregation."""
        start_date = datetime(2025, 1, 1)
        project_info = ProjectInfo(
            project_name="Growth Test",
            sponsor="Test Sponsor",
            business_unit="Engineering",
            project_manager="Test PM",
            customer="Test Customer",
            status="Active",
            start_date=start_date,
            target_end_date=start_date + timedelta(days=30),
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
                sprint_goal="Test sprint",
                status=SprintStatus.NOT_STARTED,
                planned_velocity_hrs=80.0,
                carryover_count=0,
            )
        ]

        work_items = [
            WorkItem(
                item_id="WI-001",
                title="First task",
                work_type=WorkItemType.TASK,
                assigned_sprint="S1",
                original_sprint="S1",
                assigned_resource="R1",
                required_skill=SkillLevel.SENIOR,
                priority=Priority.HIGH,
                estimated_effort_hrs=20.0,
                current_estimate_hrs=30.0,
                actual_effort_hrs=0.0,
                remaining_effort_hrs=30.0,
                progress_pct=0.0,
                status=WorkItemStatus.NOT_STARTED,
                is_scope_changed=False,
                scope_change_reason=None,
            ),
            WorkItem(
                item_id="WI-002",
                title="Second task",
                work_type=WorkItemType.TASK,
                assigned_sprint="S1",
                original_sprint="S1",
                assigned_resource="R1",
                required_skill=SkillLevel.SENIOR,
                priority=Priority.HIGH,
                estimated_effort_hrs=10.0,
                current_estimate_hrs=20.0,
                actual_effort_hrs=0.0,
                remaining_effort_hrs=20.0,
                progress_pct=0.0,
                status=WorkItemStatus.NOT_STARTED,
                is_scope_changed=False,
                scope_change_reason=None,
            ),
        ]

        dependencies = [
            Dependency(
                dependency_id="D1",
                predecessor_item_id="WI-001",
                successor_item_id="WI-002",
                dependency_type=DependencyType.FINISH_TO_START,
                is_on_critical_path=True,
                lag_days=0,
                notes="Chain dependency",
            )
        ]

        blockers = []
        actuals = []

        project_state = ProjectState(
            project_id="GROWTH-001",
            project_info=project_info,
            team=team,
            sprints=sprints,
            work_items=work_items,
            dependencies=dependencies,
            blockers=blockers,
            actuals=actuals,
        )

        dag = DependencyGraphEngine(project_state).build_dag()
        cp_result = CriticalPathEngine(project_state, dag).analyze()

        assert cp_result.critical_path == ["WI-001", "WI-002"]
        assert cp_result.critical_path_items == cp_result.critical_path
        assert cp_result.critical_path_duration_hours == 50.0
        assert cp_result.critical_path_duration_hours_original == 30.0
        assert cp_result.critical_path_growth_hours == 20.0
        assert cp_result.critical_path_growth_percent == pytest.approx(66.6666667, rel=1e-3)


class TestImpactScoringEngine:
    """Tests for ImpactScoringEngine."""
    
    def test_score_impacts(self, sample_project_state):
        """Test impact scoring."""
        dep_engine = DependencyGraphEngine(sample_project_state)
        dag = dep_engine.build_dag()
        
        impact_engine = ImpactScoringEngine(sample_project_state, dag)
        risks = impact_engine.score()
        
        # WI-004 should have high risk due to blocker
        assert risks.item_risk_scores["WI-004"] >= 0.5
        
        # Check risk categorization
        assert "WI-004" in risks.high_risk_items or "WI-004" in risks.medium_risk_items
        
        # Check blocker cascade
        assert "BLK-001" in risks.items_impacted_by_blockers


class TestSpilloverAnalysisEngine:
    """Tests for SpilloverAnalysisEngine."""
    
    def test_analyze_spillover(self, sample_project_state):
        """Test spillover analysis."""
        metrics = MetricsEngine(sample_project_state).calculate()
        engine = SpilloverAnalysisEngine(sample_project_state, metrics.average_item_effort)
        analysis = engine.analyze()
        
        # Check basic structure - only in-progress and not-started items are analyzed for spillover
        assert len(analysis.spillover_probability) >= 2  # At least WI-002 and WI-003 should be there
        assert len(analysis.predicted_spillover_by_sprint) >= 1
        
        # All probabilities should be between 0 and 1
        for prob in analysis.spillover_probability.values():
            assert 0.0 <= prob <= 1.0
    
    def test_sprint_utilization(self, sample_project_state):
        """Test sprint utilization calculation."""
        metrics = MetricsEngine(sample_project_state).calculate()
        engine = SpilloverAnalysisEngine(sample_project_state, metrics.average_item_effort)
        analysis = engine.analyze()
        
        # Utilization should be between 0 and 100%
        for sprint_num, util in analysis.sprint_utilization_pct.items():
            assert 0.0 <= util <= 100.0
