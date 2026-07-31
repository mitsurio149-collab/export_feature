from datetime import datetime, timedelta

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
from app.engines.metrics_engine import MetricsEngine
from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    Recommendation,
    RecommendationAction,
)
from app.engines.simulation_engine import (
    MONTE_CARLO_SEED,
    EngineRunner,
    SimulationEngineV2,
)


def make_project_state() -> ProjectState:
    start_date = datetime(2025, 1, 1)
    project_info = ProjectInfo(
        project_name="V2 Simulation",
        sponsor="Test Sponsor",
        business_unit="Engineering",
        project_manager="Test PM",
        customer="Test Customer",
        status="Active",
        start_date=start_date,
        target_end_date=start_date + timedelta(days=60),
        sprint_duration_days=14,
        methodology="Agile Scrum",
    )

    team = [
        Resource(
            resource_id="R1",
            name="Alice",
            role="Engineer",
            primary_skill="Python",
            secondary_skill="SQL",
            skill_level=SkillLevel.SENIOR,
            allocation_pct=0.8,
            availability_pct=0.8,
        )
    ]

    sprints = [
        Sprint(
            sprint_id="S1",
            sprint_name="Sprint 1",
            sprint_number=1,
            start_date=start_date,
            end_date=start_date + timedelta(days=13),
            working_days=10,
            sprint_goal="Build",
            status=SprintStatus.IN_PROGRESS,
            planned_velocity_hrs=160.0,
            carryover_count=1,
        ),
        Sprint(
            sprint_id="S2",
            sprint_name="Sprint 2",
            sprint_number=2,
            start_date=start_date + timedelta(days=14),
            end_date=start_date + timedelta(days=27),
            working_days=10,
            sprint_goal="Finish",
            status=SprintStatus.NOT_STARTED,
            planned_velocity_hrs=160.0,
            carryover_count=0,
        ),
    ]

    work_items = [
        WorkItem(
            item_id="WI-01",
            title="API work",
            work_type=WorkItemType.TASK,
            assigned_sprint="S1",
            original_sprint="S1",
            assigned_resource="R1",
            required_skill="Python",
            priority=Priority.HIGH,
            estimated_effort_hrs=80.0,
            current_estimate_hrs=80.0,
            actual_effort_hrs=20.0,
            remaining_effort_hrs=60.0,
            progress_pct=0.25,
            status=WorkItemStatus.IN_PROGRESS,
        ),
        WorkItem(
            item_id="WI-02",
            title="Blocked integration",
            work_type=WorkItemType.TASK,
            assigned_sprint="S1",
            original_sprint="S1",
            assigned_resource="R1",
            required_skill="Python",
            priority=Priority.MEDIUM,
            estimated_effort_hrs=40.0,
            current_estimate_hrs=40.0,
            actual_effort_hrs=0.0,
            remaining_effort_hrs=40.0,
            progress_pct=0.0,
            status=WorkItemStatus.BLOCKED,
        ),
    ]

    dependencies = [
        Dependency(
            dependency_id="DEP-01",
            predecessor_item_id="WI-02",
            successor_item_id="WI-01",
            dependency_type=DependencyType.FINISH_TO_START,
            is_on_critical_path=True,
            lag_days=0,
        )
    ]

    blockers = [
        Blocker(
            blocker_id="BLK-01",
            related_item_id="WI-02",
            impacted_item_ids=["WI-02", "WI-01"],
            description="Test blocker",
            severity=BlockerSeverity.HIGH,
            status=BlockerStatus.OPEN,
            owner="Ops",
            raised_date=start_date,
            target_resolution_date=start_date + timedelta(days=7),
            category=BlockerCategory.OTHER,
        )
    ]

    actuals = [
        SprintActual(
            sprint_id="SA-1",
            sprint_number=1,
            planned_effort_hrs=150.0,
            actual_effort_hrs=140.0,
            variance_hrs=10.0,
            tasks_planned=8,
            tasks_completed=7,
            completion_rate=0.875,
            carryover_count=1,
            scope_change_hours=0.0,
            blocker_impact_hrs=5.0,
        )
    ]

    return ProjectState(
        project_id="SIM-V2",
        project_info=project_info,
        team=team,
        sprints=sprints,
        work_items=work_items,
        dependencies=dependencies,
        blockers=blockers,
        actuals=actuals,
    )


def make_recommendation() -> Recommendation:
    return Recommendation(
        recommendation_id="REC-001",
        title="Resolve blocker",
        description="Resolve blocker on the critical path",
        action_type=RecommendationAction.RESOLVE_BLOCKER,
        priority_score=0.95,
        confidence=ConfidenceLevel.HIGH,
        estimated_hours_recovered=10.0,
        estimated_delay_reduction_days=3.0,
        estimated_risk_reduction=0.2,
        affected_item_ids=["WI-02"],
        affected_resource_ids=["R1"],
        affected_sprint_ids=["S1"],
        affected_blocker_ids=["BLK-01"],
        root_cause_signal_id="SIG-001",
    )


def test_simulation_engine_v2_is_deterministic_and_uses_seed_42():
    state = make_project_state()
    baseline = EngineRunner().run(state, simulation_count=100)
    engine = SimulationEngineV2(project_state=state, baseline=baseline, simulation_count=100)

    recommendation = make_recommendation()
    first = engine.simulate(recommendation)
    second = engine.simulate(recommendation)

    assert first == second
    assert first.seed_used == MONTE_CARLO_SEED
    assert state.blockers[0].status == BlockerStatus.OPEN


def test_simulation_engine_v2_uses_clone_before_mutation():
    state = make_project_state()
    baseline = EngineRunner().run(state, simulation_count=100)
    engine = SimulationEngineV2(project_state=state, baseline=baseline, simulation_count=100)

    recommendation = make_recommendation()
    result = engine.simulate(recommendation)

    assert result.recommendation_ids == [recommendation.recommendation_id]
    assert state.blockers[0].status == BlockerStatus.OPEN
    assert state.work_items[1].status == WorkItemStatus.BLOCKED


def test_simulation_engine_v2_resolve_blocker_unblocks_items():
    state = make_project_state()
    baseline = EngineRunner().run(state, simulation_count=100)
    engine = SimulationEngineV2(project_state=state, baseline=baseline, simulation_count=100)

    recommendation = make_recommendation()
    clone = state.model_copy(deep=True)
    engine.applicator.apply(clone, recommendation)

    assert clone.blockers[0].actual_resolution_date is not None
    assert clone.blockers[0].status == BlockerStatus.RESOLVED
    assert clone.work_items[1].status != WorkItemStatus.BLOCKED

    metrics_after = MetricsEngine(clone).calculate()
    assert metrics_after.blocked_items == 0
