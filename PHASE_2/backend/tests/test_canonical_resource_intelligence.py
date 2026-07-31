from types import SimpleNamespace
from datetime import datetime, timedelta

from app.domain.models import (
    Blocker,
    Dependency,
    ProjectInfo,
    ProjectState,
    Resource,
    SkillLevel,
    Sprint,
    SprintStatus,
    WorkItem,
    WorkItemStatus,
    WorkItemType,
    Priority,
    BlockerStatus,
    BlockerSeverity,
    BlockerCategory,
    DependencyType,
)
from app.engines.metrics_engine import MetricsEngine
from app.engines.recommendation_engine.impact_estimator import ImpactEstimator
from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    RecommendationAction,
    RecommendationCandidate,
    UpstreamEngineOutputs,
)
from app.engines.resource_intelligence import ResourceIntelligence


def _make_state() -> ProjectState:
    project_info = ProjectInfo(
        project_name="Demo",
        sponsor="Sponsor",
        business_unit="BU",
        project_manager="PM",
        start_date=datetime(2024, 1, 1),
        target_end_date=datetime(2024, 6, 30),
        sprint_duration_days=10,
        methodology="Agile",
        customer="Customer",
        status="Active",
    )
    start = datetime(2024, 1, 1)
    end = start + timedelta(days=10)
    sprint = Sprint(
        sprint_id="SPR-1",
        sprint_name="Sprint 1",
        sprint_number=1,
        start_date=start,
        end_date=end,
        working_days=10,
        sprint_goal="Build",
        status=SprintStatus.IN_PROGRESS,
        planned_velocity_hrs=80.0,
    )
    source = Resource(
        resource_id="R1",
        name="Alice",
        role="Engineer",
        primary_skill="Python",
        secondary_skill=None,
        skill_level=SkillLevel.MID,
        allocation_pct=1.0,
        availability_pct=1.0,
        daily_capacity_hrs=8.0,
    )
    receiver = Resource(
        resource_id="R2",
        name="Bob",
        role="Engineer",
        primary_skill="Python",
        secondary_skill=None,
        skill_level=SkillLevel.SENIOR,
        allocation_pct=1.0,
        availability_pct=1.0,
        daily_capacity_hrs=8.0,
    )
    item = WorkItem(
        item_id="WI-1",
        title="Build feature",
        work_type=WorkItemType.STORY,
        assigned_sprint="Sprint 1",
        original_sprint="Sprint 1",
        assigned_resource="R1",
        required_skill="Python",
        priority=Priority.HIGH,
        estimated_effort_hrs=20.0,
        current_estimate_hrs=20.0,
        actual_effort_hrs=10.0,
        remaining_effort_hrs=20.0,
        progress_pct=0.5,
        status=WorkItemStatus.IN_PROGRESS,
    )
    completed_item = WorkItem(
        item_id="WI-2",
        title="Previous feature",
        work_type=WorkItemType.STORY,
        assigned_sprint="Sprint 1",
        original_sprint="Sprint 1",
        assigned_resource="R1",
        required_skill="Python",
        priority=Priority.HIGH,
        estimated_effort_hrs=10.0,
        current_estimate_hrs=10.0,
        actual_effort_hrs=10.0,
        remaining_effort_hrs=0.0,
        progress_pct=1.0,
        status=WorkItemStatus.COMPLETED,
    )
    receiver_completed_item = WorkItem(
        item_id="WI-3",
        title="Receiver prior feature",
        work_type=WorkItemType.STORY,
        assigned_sprint="Sprint 1",
        original_sprint="Sprint 1",
        assigned_resource="R2",
        required_skill="Python",
        priority=Priority.HIGH,
        estimated_effort_hrs=20.0,
        current_estimate_hrs=20.0,
        actual_effort_hrs=20.0,
        remaining_effort_hrs=0.0,
        progress_pct=1.0,
        status=WorkItemStatus.COMPLETED,
    )
    return ProjectState(
        project_id="P1",
        project_info=project_info,
        team=[source, receiver],
        sprints=[sprint],
        work_items=[item, completed_item, receiver_completed_item],
        dependencies=[],
        blockers=[],
        actuals=[],
    )


def _make_upstream(state: ProjectState) -> UpstreamEngineOutputs:
    metrics = SimpleNamespace(
        average_item_effort=20.0,
        actual_avg_velocity=80.0,
        historical_metrics=SimpleNamespace(avg_estimation_error_pct=0.0),
        resource_metrics=SimpleNamespace(developer_metrics=[]),
    )
    return UpstreamEngineOutputs(
        metrics=metrics,
        dag=SimpleNamespace(),
        cp_result=SimpleNamespace(items_on_critical_path=[]),
        spillover=SimpleNamespace(),
        forecast=SimpleNamespace(remaining_effort_hours=100.0, expected_delay_days=0.0, scope_growth_hours=0.0),
        monte_carlo=SimpleNamespace(),
        impact_scores=SimpleNamespace(),
        risk_result=SimpleNamespace(resource_risk=SimpleNamespace(score=0.0)),
    )


def test_resource_rate_uses_one_canonical_model():
    state = _make_state()
    ri = ResourceIntelligence(state)
    resource = ri.resource("R1")
    item = next(wi for wi in state.work_items if wi.item_id == "WI-1")
    evidence = ri.evidence(resource, item, "Sprint 1")
    assert evidence.source == "individual_history"
    assert evidence.daily_rate_hrs == 10.0


def test_impact_estimator_and_metrics_engine_do_not_have_conflicting_skill_tables():
    state = _make_state()
    metrics_engine = MetricsEngine(state)
    metrics = metrics_engine.calculate()
    ri = ResourceIntelligence(state)
    resource = ri.resource("R1")
    item = next(wi for wi in state.work_items if wi.item_id == "WI-1")
    evidence = ri.evidence(resource, item, "Sprint 1")
    assert metrics.resource_metrics.developer_metrics[0].resource_id == "R1"
    assert metrics_engine._build_per_resource_base_velocity(state.team, state.work_items, state.sprints)["R1"] == evidence.daily_rate_hrs * ri.sprint_days("Sprint 1")


def test_reassign_to_faster_feasible_resource_improves_duration():
    state = _make_state()
    ri = ResourceIntelligence(state)
    item = next(wi for wi in state.work_items if wi.item_id == "WI-1")
    source = ri.resource("R1")
    receiver = ri.resource("R2")
    candidate = RecommendationCandidate(
        recommendation_id="rec-1",
        action_type=RecommendationAction.REASSIGN_ITEM,
        title="Reassign",
        description="Reassign",
        affected_item_ids=[item.item_id],
        affected_resource_ids=[source.resource_id, receiver.resource_id],
        affected_sprint_ids=["Sprint 1"],
        affected_blocker_ids=[],
        root_cause_signal_id="sig-1",
        simulation_params={"target_resource_id": receiver.resource_id},
    )
    estimator = ImpactEstimator(state, _make_upstream(state))
    estimate = estimator.estimate(candidate)
    assert estimate.estimated_delay_reduction_days > 0.0


def test_rebalance_checks_receiver_load():
    state = _make_state()
    source = next(r for r in state.team if r.resource_id == "R1")
    receiver = next(r for r in state.team if r.resource_id == "R2")
    state.work_items[0].remaining_effort_hrs = 100.0
    state.work_items[1].remaining_effort_hrs = 0.0
    # Make the receiver already overloaded after the move.
    candidate = RecommendationCandidate(
        recommendation_id="rec-rebalance",
        action_type=RecommendationAction.REBALANCE_SPRINT_LOAD,
        title="Rebalance",
        description="Rebalance",
        affected_item_ids=["WI-1"],
        affected_resource_ids=[receiver.resource_id],
        affected_sprint_ids=["Sprint 1"],
        affected_blocker_ids=[],
        root_cause_signal_id="sig-2",
        simulation_params={"target_resource_id": receiver.resource_id, "source_resource_id": source.resource_id},
    )
    estimator = ImpactEstimator(state, _make_upstream(state))
    estimate = estimator.estimate(candidate)
    assert estimate.estimated_delay_reduction_days == 0.0


def test_new_team_member_does_not_get_instant_full_productivity_without_evidence():
    state = _make_state()
    resource = Resource(
        resource_id="R3",
        name="Cara",
        role="Engineer",
        primary_skill="Python",
        secondary_skill=None,
        skill_level=SkillLevel.JUNIOR,
        allocation_pct=1.0,
        availability_pct=1.0,
        daily_capacity_hrs=8.0,
        notes="New team member, joining next sprint",
    )
    state.team.append(resource)
    ri = ResourceIntelligence(state)
    item = next(wi for wi in state.work_items if wi.item_id == "WI-1")
    evidence = ri.evidence(resource, item, "Sprint 1")
    assert evidence.source == "resource_capacity"
    assert evidence.daily_rate_hrs == 8.0
