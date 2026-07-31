from app.engines.resource_intelligence import ResourceIntelligence
from app.engines.velocity_baseline import VelocityBaseline
"""
Project Metrics Engine

Calculates deterministic aggregate project health metrics from ProjectState.
The output is a factual foundation for downstream forecasting, recommendations,
and simulation engines.
"""

from datetime import datetime
from typing import List, Dict, Any
from pydantic import BaseModel, Field

from app.domain.models import (
    ProjectState,
    WorkItemStatus,
    SprintStatus,
    BlockerSeverity,
    BlockerCategory,
    DependencyType,
    WorkItemType,
)


HEALTH_SCORE_COMPLETION_WEIGHT = 0.4
HEALTH_SCORE_BLOCKER_WEIGHT = 0.2
HEALTH_SCORE_REMAINING_EFFORT_WEIGHT = 0.0
HEALTH_SCORE_SCHEDULE_WEIGHT = 0.4


class ExecutiveMetrics(BaseModel):
    """Current snapshot of project state and execution health."""

    total_items: int = Field(default=0)
    completed_items: int = Field(default=0)
    blocked_items: int = Field(default=0)
    completion_pct: float = Field(default=0.0)
    completion_pct_label: str = Field(default="Items complete (by count)")
    completion_pct_basis: str = Field(default="item_count")
    remaining_effort_hours: float = Field(default=0.0)
    current_sprint_number: int = Field(default=0)
    completed_sprints: int = Field(default=0)
    overall_health_score: float = Field(default=0.0)


class WorkMetrics(BaseModel):
    """Deterministic work breakdown metrics from the project backlog."""

    total_effort_hours: float = Field(default=0.0)
    remaining_effort_hours: float = Field(default=0.0)
    completed_effort_hours: float = Field(default=0.0)
    average_item_effort: float = Field(default=0.0)
    effort_by_sprint: Dict[str, float] = Field(default_factory=dict)
    effort_by_module: Dict[str, float] = Field(default_factory=dict)
    effort_by_developer: Dict[str, float] = Field(default_factory=dict)


class SprintMetrics(BaseModel):
    """Per-sprint execution facts derived from sprint and sprint-actual data."""

    sprint_id: str = Field(default="")
    sprint_number: int = Field(default=0)
    planned_items: int = Field(default=0)
    completed_items: int = Field(default=0)
    completion_pct: float = Field(default=0.0)
    planned_effort_hours: float = Field(default=0.0)
    actual_effort_hours: float = Field(default=0.0)
    variance_hours: float = Field(default=0.0)
    carry_in_count: int = Field(default=0)
    carry_out_count: int = Field(default=0)
    carry_in_hours: float = Field(default=0.0)
    carry_out_hours: float = Field(default=0.0)
    scope_change_hours: float = Field(default=0.0)
    blocker_impact_hours: float = Field(default=0.0)
    execution_efficiency_score: float = Field(default=0.0)
    planning_efficiency_score: float = Field(default=0.0)


class HistoricalMetrics(BaseModel):
    """Historical sprint performance facts derived from SprintActual data."""

    planned_effort_hours: float = Field(default=0.0)
    actual_effort_hours: float = Field(default=0.0)
    effort_variance_hours: float = Field(default=0.0)
    completion_rate: float = Field(default=0.0)
    carry_in_count: int = Field(default=0)
    carry_out_count: int = Field(default=0)
    carryover_count: int = Field(default=0)
    carry_in_hours: float = Field(default=0.0)
    carry_out_hours: float = Field(default=0.0)
    scope_change_hours: float = Field(default=0.0)
    blocker_impact_hours: float = Field(default=0.0)
    average_velocity_hours: float = Field(default=0.0)
    velocity_trend_pct: float = Field(default=0.0)
    velocity_by_sprint: List[float] = Field(default_factory=list)
    carryover_by_sprint: List[int] = Field(default_factory=list)
    completion_by_sprint: List[float] = Field(default_factory=list)
    effort_variance_by_sprint: List[float] = Field(default_factory=list)
    blocker_trend_by_sprint: List[float] = Field(default_factory=list)
    planning_trend_by_sprint: List[float] = Field(default_factory=list)


class VelocityMetrics(BaseModel):
    """Deterministic velocity analytics from sprint actuals."""

    average_velocity: float = Field(default=0.0)
    median_velocity: float = Field(default=0.0)
    velocity_variance: float = Field(default=0.0)
    velocity_std_dev: float = Field(default=0.0)
    velocity_by_sprint: List[float] = Field(default_factory=list)
    velocity_stability_score: float = Field(default=0.0)
    best_sprint_velocity: float = Field(default=0.0)
    worst_sprint_velocity: float = Field(default=0.0)
    velocity_trend_pct: float = Field(default=0.0)


class DeveloperMetrics(BaseModel):
    """Deterministic developer-level workload and delivery facts."""

    resource_id: str = Field(default="")
    name: str = Field(default="")
    allocation_pct: float = Field(default=0.0)
    availability_pct: float = Field(default=0.0)
    assigned_effort_hours: float = Field(default=0.0)
    completed_effort_hours: float = Field(default=0.0)
    remaining_effort_hours: float = Field(default=0.0)
    estimation_accuracy_score: float = Field(default=0.0)


class ResourceMetrics(BaseModel):
    """Deterministic resource analytics for team capacity and workload."""

    team_size: int = Field(default=0)
    avg_allocation_pct: float = Field(default=0.0)
    avg_availability_pct: float = Field(default=0.0)
    underutilized_resource_count: int = Field(default=0)
    estimation_accuracy_score: float = Field(default=0.0)
    workload_balance_score: float = Field(default=0.0)
    allocation_efficiency_pct: float = Field(default=0.0)
    knowledge_concentration_score: float = Field(default=0.0)
    critical_resource_dependency_count: int = Field(default=0)
    developer_metrics: List[DeveloperMetrics] = Field(default_factory=list)


class DependencyMetrics(BaseModel):
    """Structured dependency analytics for critical path and bottleneck analysis."""

    dependency_count: int = Field(default=0)
    critical_dependency_density: float = Field(default=0.0)
    cross_team_dependency_count: int = Field(default=0)
    cross_team_dependency_pct: float = Field(default=0.0)
    dependency_bottleneck_count: int = Field(default=0)
    critical_path_length: int = Field(default=0)
    blocked_dependency_chain_count: int = Field(default=0)
    dependency_clusters: int = Field(default=0)
    external_dependency_count: int = Field(default=0)


class BlockerMetrics(BaseModel):
    """Analytical blocker facts for recurring risk detection."""

    blocker_count_by_severity: Dict[str, int] = Field(default_factory=dict)
    total_blocker_count: int = Field(default=0)
    active_blocker_count: int = Field(default=0)
    resolved_blocker_count: int = Field(default=0)
    current_sprint_active_blocker_count: int = Field(default=0)
    estimated_blocker_velocity_impact: float = Field(default=0.0)
    recurring_blocker_categories: Dict[str, int] = Field(default_factory=dict)
    average_resolution_days: float = Field(default=0.0)
    dependency_related_blocker_count: int = Field(default=0)
    preventable_blocker_count: int = Field(default=0)
    blocker_trend_score: float = Field(default=0.0)
    blocker_severity_distribution: Dict[str, int] = Field(default_factory=dict)
    blocker_recurring_count: int = Field(default=0)
    environment_blocker_count: int = Field(default=0)
    requirement_blocker_count: int = Field(default=0)
    testing_blocker_count: int = Field(default=0)
    infrastructure_blocker_count: int = Field(default=0)


class PlanningMetrics(BaseModel):
    """Planning and predictability facts useful for AI and simulation inputs."""

    planning_accuracy_score: float = Field(default=0.0)
    story_sizing_consistency_score: float = Field(default=0.0)
    carryover_trend_score: float = Field(default=0.0)
    scope_volatility_score: float = Field(default=0.0)
    sprint_predictability_score: float = Field(default=0.0)
    schedule_confidence_score: float = Field(default=0.0)
    delivery_stability_score: float = Field(default=0.0)
    commitment_reliability_score: float = Field(default=0.0)
    backlog_churn_score: float = Field(default=0.0)


class QualityMetrics(BaseModel):
    """Quality and rework facts derived from available workbook fields."""

    defect_density: float = Field(default=0.0)
    reopened_work_count: int = Field(default=0)
    rework_percentage: float = Field(default=0.0)
    requirement_volatility_score: float = Field(default=0.0)
    scope_creep_score: float = Field(default=0.0)


class RiskInputMetrics(BaseModel):
    """Deterministic inputs for downstream risk scoring without performing risk logic."""

    blocker_density: float = Field(default=0.0)
    dependency_density: float = Field(default=0.0)
    resource_overload_score: float = Field(default=0.0)
    planning_accuracy_score: float = Field(default=0.0)
    velocity_stability_score: float = Field(default=0.0)
    carryover_rate: float = Field(default=0.0)
    scope_volatility_score: float = Field(default=0.0)


class ForecastInputMetrics(BaseModel):
    """Deterministic inputs for downstream forecast engines without forecasting."""

    remaining_effort_hours: float = Field(default=0.0)
    effective_project_velocity: float = Field(default=0.0)
    remaining_story_count: int = Field(default=0)
    historical_velocity_hours: float = Field(default=0.0)
    historical_carryover_rate: float = Field(default=0.0)
    completed_sprints: int = Field(default=0)
    remaining_sprints: int = Field(default=0)
    capacity_hours: float = Field(default=0.0)
    utilization_pct: float = Field(default=0.0)
    blocker_impact_hours: float = Field(default=0.0)
    dependency_density: float = Field(default=0.0)


class RecommendationInputMetrics(BaseModel):
    """Deterministic downstream-facing facts used by recommendation engines."""

    developer_allocation_pct: Dict[str, float] = Field(default_factory=dict)
    sprint_planned_velocity_hours: Dict[str, float] = Field(default_factory=dict)
    open_blocker_ids: List[str] = Field(default_factory=list)
    critical_dependency_ids: List[str] = Field(default_factory=list)
    carryover_signal_sprint_ids: List[str] = Field(default_factory=list)
    variance_signal_sprint_ids: List[str] = Field(default_factory=list)
    recurring_blockers: int = Field(default=0)
    critical_dependencies: int = Field(default=0)


class ProjectMetrics(BaseModel):
    """Aggregate project health metrics and richer analytics slices."""

    # Completion metrics
    total_items: int
    completed_items: int
    in_progress_items: int
    blocked_items: int
    not_started_items: int
    completion_pct: float

    # Work metrics
    total_effort_hours: float
    remaining_effort_hours: float
    completed_effort_hours: float
    average_item_effort: float

    # Velocity metrics
    planned_total_velocity: float
    actual_avg_velocity: float
    effective_project_velocity: float
    velocity_variance: float
    velocity_std_dev: float
    velocity_baseline: Any = Field(default=None)

    # Resource metrics
    team_size: int
    avg_allocation_pct: float
    avg_availability_pct: float
    underutilized_resource_count: int

    # Risk metrics
    blocker_count_by_severity: Dict[str, int]
    active_blocker_count: int
    estimated_blocker_velocity_impact: float  # 0.0-1.0, reduction factor

    # Schedule metrics
    project_start_date: datetime
    project_end_date: datetime
    current_sprint_number: int
    completed_sprints: int

    # Dependency metrics
    dependency_count: int
    critical_path_length: int

    # Spillover metrics
    #
    # NAMING CLARIFICATION (these two fields answer DIFFERENT questions and
    # are NOT alternative estimates of the same quantity — do not compare
    # them directly, and do not expect them to roughly agree):
    #
    # expected_spillover_items: despite the forward-looking name, this is
    # actually sum(a.carryover_count for a in actuals) — a HISTORICAL total
    # of how many items carried over across sprints that already have
    # recorded actuals (i.e. completed + current in-progress sprint). It is
    # backward-looking. Kept under its original name for backward
    # compatibility with existing callers; see historical_total_carryover_items
    # below for the same value under an accurate name.
    #
    # For the FORWARD-LOOKING prediction of how many items are expected to
    # spill across remaining/future sprints, use
    # SpilloverAnalysisEngine.predicted_spillover_by_sprint (summed) /
    # ForecastResult.predicted_spillover_items instead — that is a model
    # output over future sprints, not a historical tally.
    expected_spillover_items: int
    historical_total_carryover_items: int  # = expected_spillover_items, accurately named
    historical_carryover_rate: float

    # Structured analytics slices
    executive_metrics: ExecutiveMetrics
    work_metrics: WorkMetrics
    sprint_metrics: List[SprintMetrics]
    historical_metrics: HistoricalMetrics
    velocity_metrics: VelocityMetrics
    resource_metrics: ResourceMetrics
    resource_sprint_loads: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    # e.g. {"Meena Balasubramanian": {"Sprint 6": 1.21, "Sprint 7": 0.78}}
    per_resource_base_velocity: Dict[str, float] = Field(default_factory=dict)
    # e.g. {"Meena Balasubramanian": 48.0, "Ravi Chandran": 56.0}  (hrs/sprint, skill-adjusted)
    carryover_history: List[Dict[str, Any]] = Field(default_factory=list)
    # e.g. [{"item_id": "WI-047", "orig_sprint": "Sprint 5", "current_sprint": "Sprint 6"}]
    scope_inflation_by_reason: Dict[str, float] = Field(default_factory=dict)
    blocker_metrics: BlockerMetrics
    dependency_metrics: DependencyMetrics
    planning_metrics: PlanningMetrics
    quality_metrics: QualityMetrics
    risk_input_metrics: RiskInputMetrics
    forecast_input_metrics: ForecastInputMetrics
    recommendation_input_metrics: RecommendationInputMetrics


class MetricsEngine:
    """Calculates project metrics from ProjectState."""

    def __init__(self, project_state: ProjectState):
        self.project_state = project_state
        self.resource_intelligence = ResourceIntelligence(project_state)

    def calculate(self) -> ProjectMetrics:
        """Calculate all project metrics."""
        work_items = self.project_state.work_items
        sprints = self.project_state.sprints
        team = self.project_state.team
        blockers = self.project_state.blockers
        actuals = self.project_state.actuals
        dependencies = self.project_state.dependencies

        # Item counts by status
        completed = sum(1 for wi in work_items if wi.status == WorkItemStatus.COMPLETED)
        in_progress = sum(1 for wi in work_items if wi.status == WorkItemStatus.IN_PROGRESS)
        blocked = sum(1 for wi in work_items if wi.status == WorkItemStatus.BLOCKED)
        not_started = sum(1 for wi in work_items if wi.status == WorkItemStatus.NOT_STARTED)
        total = len(work_items)

        # Effort metrics
        total_effort = sum(wi.estimated_effort_hrs for wi in work_items)
        completed_effort = sum(
            wi.estimated_effort_hrs for wi in work_items
            if wi.status == WorkItemStatus.COMPLETED
        )
        remaining_effort = sum(wi.remaining_effort_hrs for wi in work_items)
        avg_item_effort = total_effort / total if total > 0 else 0.0

        # Velocity metrics
        planned_velocity = sum(s.planned_velocity_hrs for s in sprints if s.planned_velocity_hrs > 0)
        actual_velocities = [a.actual_effort_hrs for a in actuals if a.actual_effort_hrs > 0]
        actual_avg_velocity = self._trimmed_mean_velocity(actual_velocities)
        velocity_variance = self._calculate_variance(actual_velocities)
        velocity_std_dev = velocity_variance ** 0.5 if velocity_variance >= 0 else 0.0

        # Resource metrics
        team_size = len(team)
        avg_allocation = sum(r.allocation_pct for r in team) / team_size if team_size > 0 else 0.0
        avg_availability = sum(r.availability_pct for r in team) / team_size if team_size > 0 else 0.0
        underutilized = sum(1 for r in team if r.allocation_pct * r.availability_pct < 0.60)

        # Blocker metrics
        blocker_counts = self._count_blockers_by_severity(blockers)
        active_blockers = sum(1 for b in blockers if not b.actual_resolution_date)
        _as_of = self.project_state.project_info.effective_as_of_date()
        blocker_velocity_impact = self._estimate_blocker_velocity_impact(
            blockers, as_of_date=_as_of, work_items=work_items, team=team
        )

        # Schedule metrics
        completed_sprints = sum(1 for s in sprints if s.status == SprintStatus.COMPLETED)
        current_sprint_num = self._get_current_sprint_number(sprints)

        # Spillover metrics (HISTORICAL — from sprints with recorded actuals).
        # This is a backward-looking tally of items that have already carried
        # over historically. It is NOT a prediction of future spillover; for
        # that, see SpilloverAnalysisEngine.predicted_spillover_by_sprint,
        # which is a separate, forward-looking model over remaining sprints
        # and will not generally match this historical figure.
        expected_spillover = sum(a.carryover_count for a in actuals)
        historical_carryover_rate = (
            expected_spillover / len(actuals) if len(actuals) > 0 else 0.0
        )

        executive_metrics = self._build_executive_metrics(
            total,
            completed,
            blocked,
            remaining_effort,
            current_sprint_num,
            completed_sprints,
            completed / total if total > 0 else 0.0,
            on_time_probability=0.5,
        )
        work_metrics = self._build_work_metrics(total_effort, remaining_effort, completed_effort, avg_item_effort, work_items, sprints)
        sprint_metrics = self._build_sprint_metrics(sprints, actuals, work_items)
        historical_metrics = self._build_historical_metrics(actuals, actual_avg_velocity)
        velocity_metrics = self._build_velocity_metrics(actuals)
        resource_metrics = self._build_resource_metrics(team, work_items)
        resource_sprint_loads = self._build_resource_sprint_loads(team, sprints, work_items)
        per_resource_base_velocity = self._build_per_resource_base_velocity(team, work_items, sprints)
        effective_project_velocity = self._calculate_effective_project_velocity(
            team=team,
            work_items=work_items,
            actual_avg_velocity=actual_avg_velocity,
            planned_total_velocity=planned_velocity,
            sprints=sprints,
        )
        carryover_history = self._build_carryover_history(work_items)
        scope_inflation_by_reason = self._build_scope_inflation_by_reason(work_items)
        blocker_metrics = self._build_blocker_metrics(blockers)
        dependency_metrics = self._build_dependency_metrics(dependencies, work_items)
        planning_metrics = self._build_planning_metrics(actuals, work_items)
        quality_metrics = self._build_quality_metrics(work_items)
        from app.engines.project_calibration import ProjectCalibration

        _cal = ProjectCalibration.from_project_state(self.project_state)
        _sprint_days = float(self.project_state.project_info.sprint_duration_days or 14)
        _completed_sprint_count = len([a for a in actuals if a.actual_effort_hrs > 0])
        _floor_hrs = actual_avg_velocity * _cal.velocity_floor_pct
        velocity_baseline = VelocityBaseline(
            trimmed_avg_hrs=actual_avg_velocity,
            simple_avg_hrs=velocity_metrics.average_velocity,
            sprint_count=_completed_sprint_count,
            sprint_days=_sprint_days,
            floor_hrs=_floor_hrs,
            data_source=f"{_completed_sprint_count} completed sprint actuals",
        )

        risk_input_metrics = self._build_risk_input_metrics(blocker_metrics, dependency_metrics, resource_metrics, planning_metrics, velocity_metrics, historical_metrics)
        forecast_input_metrics = self._build_forecast_input_metrics(
            remaining_effort,
            actual_avg_velocity,
            planned_velocity,
            historical_carryover_rate,
            completed_sprints,
            current_sprint_num,
            len(sprints),
            team_size,
            avg_allocation,
            blocker_metrics,
            dependency_metrics,
            total - completed,
            team,
            sprints,
            effective_project_velocity,
        )
        recommendation_input_metrics = self._build_recommendation_input_metrics(team, sprints, work_items, blockers, dependencies, historical_metrics)

        return ProjectMetrics(
            total_items=total,
            completed_items=completed,
            in_progress_items=in_progress,
            blocked_items=blocked,
            not_started_items=not_started,
            completion_pct=completed / total if total > 0 else 0.0,
            total_effort_hours=total_effort,
            remaining_effort_hours=remaining_effort,
            completed_effort_hours=completed_effort,
            average_item_effort=avg_item_effort,
            planned_total_velocity=planned_velocity,
            actual_avg_velocity=actual_avg_velocity,
            velocity_variance=velocity_variance,
            velocity_std_dev=velocity_std_dev,
            velocity_baseline=velocity_baseline,
            team_size=team_size,
            avg_allocation_pct=avg_allocation,
            avg_availability_pct=avg_availability,
            underutilized_resource_count=underutilized,
            blocker_count_by_severity=blocker_counts,
            active_blocker_count=active_blockers,
            estimated_blocker_velocity_impact=blocker_velocity_impact,
            project_start_date=self.project_state.project_info.start_date,
            project_end_date=self.project_state.project_info.target_end_date,
            current_sprint_number=current_sprint_num,
            completed_sprints=completed_sprints,
            dependency_count=len(dependencies),
            critical_path_length=dependency_metrics.critical_path_length,
            expected_spillover_items=expected_spillover,
            historical_total_carryover_items=expected_spillover,
            historical_carryover_rate=historical_carryover_rate,
            executive_metrics=executive_metrics,
            work_metrics=work_metrics,
            sprint_metrics=sprint_metrics,
            historical_metrics=historical_metrics,
            velocity_metrics=velocity_metrics,
            resource_metrics=resource_metrics,
            resource_sprint_loads=resource_sprint_loads,
            per_resource_base_velocity=per_resource_base_velocity,
            carryover_history=carryover_history,
            scope_inflation_by_reason=scope_inflation_by_reason,
            blocker_metrics=blocker_metrics,
            dependency_metrics=dependency_metrics,
            planning_metrics=planning_metrics,
            quality_metrics=quality_metrics,
            risk_input_metrics=risk_input_metrics,
            forecast_input_metrics=forecast_input_metrics,
            recommendation_input_metrics=recommendation_input_metrics,
            effective_project_velocity=effective_project_velocity,
        )

    def _build_executive_metrics(
        self,
        total_items: int,
        completed_items: int,
        blocked_items: int,
        remaining_effort_hours: float,
        current_sprint_number: int,
        completed_sprints: int,
        completion_pct: float,
        on_time_probability: float = 0.5,
    ) -> ExecutiveMetrics:
        """Build the current snapshot metrics for the executive layer.

        Health score components:
          0.4 × completion_pct           — how much is done
          0.2 × (1 - blocker_rate)       — how many items are blocked
          0.4 × on_time_probability      — are we likely to hit the deadline
        """
        schedule_health = max(0.0, min(1.0, on_time_probability))
        overall_health_score = max(
            0.0,
            min(
                1.0,
                (completion_pct * HEALTH_SCORE_COMPLETION_WEIGHT)
                + (1.0 - min(1.0, blocked_items / max(total_items, 1))) * HEALTH_SCORE_BLOCKER_WEIGHT
                + schedule_health * HEALTH_SCORE_SCHEDULE_WEIGHT,
            ),
        )
        return ExecutiveMetrics(
            total_items=total_items,
            completed_items=completed_items,
            blocked_items=blocked_items,
            completion_pct=completion_pct,
            completion_pct_label="Items complete (by count)",
            completion_pct_basis="item_count",
            remaining_effort_hours=remaining_effort_hours,
            current_sprint_number=current_sprint_number,
            completed_sprints=completed_sprints,
            overall_health_score=overall_health_score,
        )

    def _build_work_metrics(self, total_effort_hours: float, remaining_effort_hours: float, completed_effort_hours: float, average_item_effort: float, work_items: List[Any], sprints: List[Any]) -> WorkMetrics:
        """Build deterministic work breakdown analytics from work items and sprint planning."""
        effort_by_sprint: Dict[str, float] = {}
        effort_by_module: Dict[str, float] = {}
        effort_by_developer: Dict[str, float] = {}
        for sprint in sprints:
            effort_by_sprint[sprint.sprint_name] = sum(
                wi.estimated_effort_hrs for wi in work_items if wi.assigned_sprint == sprint.sprint_name
            )
        for work_item in work_items:
            module_key = work_item.title.split()[0] if work_item.title else "Unknown"
            effort_by_module[module_key] = effort_by_module.get(module_key, 0.0) + work_item.estimated_effort_hrs
            if work_item.assigned_resource:
                effort_by_developer[work_item.assigned_resource] = effort_by_developer.get(work_item.assigned_resource, 0.0) + work_item.estimated_effort_hrs
        return WorkMetrics(
            total_effort_hours=total_effort_hours,
            remaining_effort_hours=remaining_effort_hours,
            completed_effort_hours=completed_effort_hours,
            average_item_effort=average_item_effort,
            effort_by_sprint=effort_by_sprint,
            effort_by_module=effort_by_module,
            effort_by_developer=effort_by_developer,
        )

    def _build_sprint_metrics(self, sprints: List[Any], actuals: List[Any], work_items: List[Any]) -> List[SprintMetrics]:
        """Build per-sprint facts for execution analysis."""
        sprint_metrics: List[SprintMetrics] = []
        actual_by_id = {actual.sprint_id: actual for actual in actuals}
        for sprint in sprints:
            actual = actual_by_id.get(sprint.sprint_id)
            planned_items = sum(1 for wi in work_items if wi.assigned_sprint == sprint.sprint_name)
            completed_items = sum(1 for wi in work_items if wi.assigned_sprint == sprint.sprint_name and wi.status == WorkItemStatus.COMPLETED)
            completion_pct = (actual.completion_rate if actual else 0.0) if actual else (completed_items / planned_items if planned_items else 0.0)
            planned_effort_hours = sprint.planned_velocity_hrs
            actual_effort_hours = actual.actual_effort_hrs if actual else 0.0
            variance_hours = (actual.variance_hrs if actual else 0.0)
            carry_in_count = actual.carry_in_count if actual else 0
            carry_out_count = actual.carry_out_count if actual else 0
            carry_in_hours = actual.carry_in_hours if actual else 0.0
            carry_out_hours = actual.carry_out_hours if actual else 0.0
            scope_change_hours = actual.scope_change_hours if actual else 0.0
            blocker_impact_hours = actual.blocker_impact_hrs if actual else 0.0
            execution_efficiency_score = max(0.0, min(1.0, actual_effort_hours / planned_effort_hours)) if planned_effort_hours else 0.0
            planning_efficiency_score = max(0.0, min(1.0, 1.0 - (abs(variance_hours) / max(planned_effort_hours, 1.0)))) if planned_effort_hours else 0.0
            sprint_metrics.append(
                SprintMetrics(
                    sprint_id=sprint.sprint_id,
                    sprint_number=sprint.sprint_number,
                    planned_items=planned_items,
                    completed_items=completed_items,
                    completion_pct=completion_pct,
                    planned_effort_hours=planned_effort_hours,
                    actual_effort_hours=actual_effort_hours,
                    variance_hours=variance_hours,
                    carry_in_count=carry_in_count,
                    carry_out_count=carry_out_count,
                    carry_in_hours=carry_in_hours,
                    carry_out_hours=carry_out_hours,
                    scope_change_hours=scope_change_hours,
                    blocker_impact_hours=blocker_impact_hours,
                    execution_efficiency_score=execution_efficiency_score,
                    planning_efficiency_score=planning_efficiency_score,
                )
            )
        return sprint_metrics

    def _build_historical_metrics(self, actuals: List[Any], average_velocity: float) -> HistoricalMetrics:
        """Build a structured historical slice from sprint actuals."""
        if not actuals:
            return HistoricalMetrics()

        planned_effort = sum(a.planned_effort_hrs for a in actuals if a.planned_effort_hrs > 0)
        actual_effort = sum(a.actual_effort_hrs for a in actuals if a.actual_effort_hrs > 0)
        effort_variance = sum(a.variance_hrs for a in actuals)
        completion_rate = sum(a.completion_rate for a in actuals) / len(actuals)
        carry_in_count = sum(a.carry_in_count for a in actuals)
        carry_out_count = sum(a.carry_out_count for a in actuals)
        carryover_count = sum(a.carryover_count for a in actuals)
        carry_in_hours = sum(a.carry_in_hours for a in actuals)
        carry_out_hours = sum(a.carry_out_hours for a in actuals)
        scope_change_hours = sum(a.scope_change_hours for a in actuals)
        blocker_impact_hours = sum(a.blocker_impact_hrs for a in actuals)
        velocity_trend_pct = 0.0
        if len(actuals) >= 2:
            first_velocity = actuals[0].actual_effort_hrs or 0.0
            last_velocity = actuals[-1].actual_effort_hrs or 0.0
            if first_velocity != 0.0:
                velocity_trend_pct = ((last_velocity - first_velocity) / first_velocity) * 100.0

        return HistoricalMetrics(
            planned_effort_hours=planned_effort,
            actual_effort_hours=actual_effort,
            effort_variance_hours=effort_variance,
            completion_rate=completion_rate,
            carry_in_count=carry_in_count,
            carry_out_count=carry_out_count,
            carryover_count=carryover_count,
            carry_in_hours=carry_in_hours,
            carry_out_hours=carry_out_hours,
            scope_change_hours=scope_change_hours,
            blocker_impact_hours=blocker_impact_hours,
            average_velocity_hours=average_velocity,
            velocity_trend_pct=velocity_trend_pct,
            velocity_by_sprint=[a.actual_effort_hrs for a in actuals if a.actual_effort_hrs > 0],
            carryover_by_sprint=[a.carryover_count for a in actuals],
            completion_by_sprint=[a.completion_rate for a in actuals],
            effort_variance_by_sprint=[a.variance_hrs for a in actuals],
            blocker_trend_by_sprint=[a.blocker_impact_hrs for a in actuals],
            planning_trend_by_sprint=[a.completion_rate for a in actuals],
        )

    def _build_velocity_metrics(self, actuals: List[Any]) -> VelocityMetrics:
        """Build deterministic velocity analytics from sprint actuals."""
        velocities = [a.actual_effort_hrs for a in actuals if a.actual_effort_hrs > 0]
        if not velocities:
            return VelocityMetrics()
        median_velocity = sorted(velocities)[len(velocities) // 2] if len(velocities) % 2 == 1 else (sorted(velocities)[len(velocities) // 2 - 1] + sorted(velocities)[len(velocities) // 2]) / 2.0
        velocity_variance = self._calculate_variance(velocities)
        velocity_std_dev = velocity_variance ** 0.5 if velocity_variance >= 0 else 0.0
        average_velocity = sum(velocities) / len(velocities)
        velocity_stability_score = max(0.0, 1.0 - (velocity_std_dev / max(average_velocity, 1.0)))
        velocity_trend_pct = 0.0
        if len(velocities) >= 2:
            first_velocity = velocities[0]
            last_velocity = velocities[-1]
            if first_velocity != 0.0:
                velocity_trend_pct = ((last_velocity - first_velocity) / first_velocity) * 100.0
        return VelocityMetrics(
            average_velocity=average_velocity,
            median_velocity=median_velocity,
            velocity_variance=velocity_variance,
            velocity_std_dev=velocity_std_dev,
            velocity_by_sprint=velocities,
            velocity_stability_score=velocity_stability_score,
            best_sprint_velocity=max(velocities),
            worst_sprint_velocity=min(velocities),
            velocity_trend_pct=velocity_trend_pct,
        )

    def _build_resource_metrics(self, team: List[Any], work_items: List[Any]) -> ResourceMetrics:
        """Build deterministic resource analytics from team and work-item assignments."""
        team_size = len(team)
        avg_allocation = sum(r.allocation_pct for r in team) / team_size if team_size > 0 else 0.0
        avg_availability = sum(r.availability_pct for r in team) / team_size if team_size > 0 else 0.0
        underutilized = sum(1 for r in team if r.allocation_pct * r.availability_pct < 0.60)

        completed_or_actual = [
            wi for wi in work_items if wi.status == WorkItemStatus.COMPLETED or wi.actual_effort_hrs > 0
        ]
        estimation_accuracy = 0.0
        if completed_or_actual:
            accuracy_scores = []
            for wi in completed_or_actual:
                baseline = max(wi.current_estimate_hrs or wi.estimated_effort_hrs, 1.0)
                delta = abs(baseline - wi.actual_effort_hrs) / baseline
                accuracy_scores.append(max(0.0, 1.0 - delta))
            estimation_accuracy = sum(accuracy_scores) / len(accuracy_scores)

        loads = []
        for resource in team:
            assigned_hours = sum(
                wi.estimated_effort_hrs
                for wi in work_items
                if wi.assigned_resource in {resource.resource_id, resource.name}
            )
            loads.append(assigned_hours)
        if len(loads) >= 2:
            mean_load = sum(loads) / len(loads)
            variance = sum((value - mean_load) ** 2 for value in loads) / len(loads)
            workload_balance_score = max(0.0, 1.0 - (variance ** 0.5 / max(mean_load, 1.0)))
        else:
            workload_balance_score = 1.0

        primary_skills = {r.primary_skill for r in team}
        knowledge_concentration_score = len(primary_skills) / max(team_size, 1)
        allocation_efficiency_pct = min(1.0, avg_allocation * avg_availability)
        critical_resource_dependency_count = sum(
            1 for wi in work_items if wi.assigned_resource and wi.priority.name in {"CRITICAL", "HIGH"}
        )

        developer_metrics: List[DeveloperMetrics] = []
        for resource in team:
            assigned_work = sum(
                wi.estimated_effort_hrs
                for wi in work_items
                if wi.assigned_resource in {resource.resource_id, resource.name}
            )
            completed_work = sum(
                wi.actual_effort_hrs
                for wi in work_items
                if wi.assigned_resource in {resource.resource_id, resource.name}
                and wi.status == WorkItemStatus.COMPLETED
            )
            remaining_work = sum(
                wi.remaining_effort_hrs
                for wi in work_items
                if wi.assigned_resource in {resource.resource_id, resource.name}
            )
            developer_metrics.append(
                DeveloperMetrics(
                    resource_id=resource.resource_id,
                    name=resource.name,
                    allocation_pct=resource.allocation_pct,
                    availability_pct=resource.availability_pct,
                    assigned_effort_hours=assigned_work,
                    completed_effort_hours=completed_work,
                    remaining_effort_hours=remaining_work,
                    estimation_accuracy_score=estimation_accuracy,
                )
            )

        return ResourceMetrics(
            team_size=team_size,
            avg_allocation_pct=avg_allocation,
            avg_availability_pct=avg_availability,
            underutilized_resource_count=underutilized,
            estimation_accuracy_score=estimation_accuracy,
            workload_balance_score=workload_balance_score,
            allocation_efficiency_pct=allocation_efficiency_pct,
            knowledge_concentration_score=knowledge_concentration_score,
            critical_resource_dependency_count=critical_resource_dependency_count,
            developer_metrics=developer_metrics,
        )

    def _build_resource_sprint_loads(self, team: List[Any], sprints: List[Any], work_items: List[Any]) -> Dict[str, Dict[str, float]]:
        """Canonical per-resource/per-sprint load ratio, keyed by resource_id."""
        result: Dict[str, Dict[str, float]] = {}
        for resource in team:
            per_sprint: Dict[str, float] = {}
            for sprint in sprints:
                capacity = self.resource_intelligence.effective_capacity_hours(resource, sprint.sprint_id)
                committed = self.resource_intelligence.committed_hours(resource, sprint.sprint_id)
                per_sprint[sprint.sprint_id] = committed / max(capacity, 1.0)
            result[resource.resource_id] = per_sprint
            if getattr(resource, "name", None):
                result[resource.name] = per_sprint
        return result

    def _build_per_resource_base_velocity(
        self, team: List[Any], work_items: List[Any], sprints: List[Any]
    ) -> Dict[str, float]:
        """Canonical resource velocity in hours/sprint, keyed by resource_id.

        Uses individual measured delivery history when available; otherwise the
        resource's own workbook capacity. No skill-level multiplier is applied.
        """
        result: Dict[str, float] = {}
        sprint_ref = sprints[0].sprint_id if sprints else None
        for resource in team:
            ev = self.resource_intelligence.evidence(resource, None, sprint_ref)
            result[resource.resource_id] = ev.daily_rate_hrs * self.resource_intelligence.sprint_days(sprint_ref)
        return result

    def _calculate_effective_project_velocity(
        self,
        team: List[Any],
        work_items: List[Any],
        actual_avg_velocity: float,
        planned_total_velocity: float,
        sprints: List[Any],
    ) -> float:
        """Calculate effective project velocity from team capacity, skills, and historical performance."""
        if not team:
            return max(actual_avg_velocity, planned_total_velocity, 1.0)

        sprint_days = float(self.project_state.project_info.sprint_duration_days or 10)
        total_sprints = len(sprints) if sprints else 1
        planned_avg_velocity = planned_total_velocity / max(total_sprints, 1)

        historical_perf_factor = 1.0
        if actual_avg_velocity > 0 and planned_avg_velocity > 0:
            historical_perf_factor = actual_avg_velocity / planned_avg_velocity
            historical_perf_factor = max(0.5, min(historical_perf_factor, 1.25))

        total_effective_capacity = 0.0
        for resource in team:
            total_effective_capacity += self._calculate_resource_effectiveness(
                resource=resource,
                work_items=work_items,
                sprint_days=sprint_days,
            )

        effective_velocity = total_effective_capacity * historical_perf_factor
        return max(1.0, effective_velocity)

    def _calculate_resource_effectiveness(self, resource: Any, work_items: List[Any], sprint_days: float) -> float:
        """Resource capacity from the canonical ResourceIntelligence model.

        Skill level is not converted to a generic productivity multiplier.
        """
        ev = self.resource_intelligence.evidence(resource, None, None)
        return ev.daily_rate_hrs * sprint_days


    def _build_carryover_history(self, work_items: List[Any]) -> List[Dict[str, Any]]:
        """Track work items that have moved between sprints (carryover/slippage)."""
        history = []
        for wi in work_items:
            orig = getattr(wi, "original_sprint", None) or getattr(wi, "assigned_sprint", None)
            current = getattr(wi, "assigned_sprint", None)
            if orig and current and orig != current:
                history.append({
                    "item_id": wi.item_id,
                    "orig_sprint": orig,
                    "current_sprint": current,
                })
        return history

    def _build_scope_inflation_by_reason(self, work_items: List[Any]) -> Dict[str, float]:
        """Aggregate scope growth (current_estimate - original estimate) by scope change reason."""
        by_reason: Dict[str, float] = {}
        for wi in work_items:
            if getattr(wi, "is_scope_changed", False):
                reason = getattr(wi, "scope_change_reason", None) or "Unspecified"
                growth = (wi.current_estimate_hrs or 0.0) - (wi.estimated_effort_hrs or 0.0)
                by_reason[reason] = by_reason.get(reason, 0.0) + max(0.0, growth)
        return by_reason

    def _build_blocker_metrics(self, blockers: List[Any]) -> BlockerMetrics:
        """Build deterministic blocker analytics from blocker records."""
        blocker_counts = self._count_blockers_by_severity(blockers)
        active_blockers = [b for b in blockers if not b.actual_resolution_date]
        resolved_blockers = [b for b in blockers if b.actual_resolution_date and b.raised_date]
        _as_of = self.project_state.project_info.effective_as_of_date()
        blocker_velocity_impact = self._estimate_blocker_velocity_impact(
            blockers,
            as_of_date=_as_of,
            work_items=getattr(self.project_state, "work_items", None),
            team=getattr(self.project_state, "team", None),
        )
        recurring_categories: Dict[str, int] = {}
        for blocker in blockers:
            recurring_categories[blocker.category.value] = recurring_categories.get(blocker.category.value, 0) + 1

        resolution_days = []
        for blocker in resolved_blockers:
            delta = blocker.actual_resolution_date - blocker.raised_date
            resolution_days.append(delta.days)
        average_resolution_days = sum(resolution_days)/len(resolution_days) if resolution_days else 0.0

        dependency_related = sum(
            1 for b in blockers if b.category in {
                BlockerCategory.EXTERNAL_TEAM_DEPENDENCY,
                BlockerCategory.PEOPLE_DEPENDENCY,
                BlockerCategory.APPROVAL_PENDING,
            }
        )
        preventable = sum(
            1 for b in blockers if b.category in {
                BlockerCategory.ENVIRONMENT,
                BlockerCategory.TOOL_ISSUE,
                BlockerCategory.LICENSE_UNAVAILABLE,
                BlockerCategory.RESOURCE,
                BlockerCategory.HARDWARE,
            }
        )
        blocker_trend_score = max(0.0, 1.0 - (len(active_blockers) / max(len(blockers), 1)))

        current_sprint_number = self._get_current_sprint_number(self.project_state.sprints)
        current_sprint = next(
            (s for s in self.project_state.sprints if s.sprint_number == current_sprint_number),
            None,
        )
        current_sprint_name = getattr(current_sprint, "sprint_name", None)
        work_items = getattr(self.project_state, "work_items", None) or []
        current_sprint_work_item_ids = {
            wi.item_id for wi in work_items if getattr(wi, "assigned_sprint", None) == current_sprint_name
        }
        current_sprint_active_blocker_count = sum(
            1
            for blocker in active_blockers
            if any(
                impacted_item_id in current_sprint_work_item_ids
                for impacted_item_id in getattr(blocker, "impacted_item_ids", []) or [getattr(blocker, "related_item_id", None)]
            )
        )

        return BlockerMetrics(
            blocker_count_by_severity=blocker_counts,
            total_blocker_count=len(blockers),
            active_blocker_count=len(active_blockers),
            resolved_blocker_count=len(resolved_blockers),
            current_sprint_active_blocker_count=current_sprint_active_blocker_count,
            estimated_blocker_velocity_impact=blocker_velocity_impact,
            recurring_blocker_categories=recurring_categories,
            average_resolution_days=average_resolution_days,
            dependency_related_blocker_count=dependency_related,
            preventable_blocker_count=preventable,
            blocker_trend_score=blocker_trend_score,
        )

    def _build_dependency_metrics(self, dependencies: List[Any], work_items: List[Any]) -> DependencyMetrics:
        """Build deterministic dependency analytics from dependency relationships."""
        dependency_count = len(dependencies)
        critical_dependency_density = dependency_count / max(len(work_items), 1)
        cross_team_dependency_count = sum(1 for dep in dependencies if dep.notes and "team" in dep.notes.lower())
        cross_team_dependency_pct = cross_team_dependency_count / dependency_count if dependency_count else 0.0
        dependency_bottleneck_count = sum(1 for dep in dependencies if dep.is_on_critical_path or dep.lag_days > 0)
        critical_path_length = self._calculate_critical_path_length(dependencies, work_items)
        dependency_clusters = self._calculate_dependency_clusters(dependencies, work_items)
        blocked_dependency_chain_count = sum(
            1 for dep in dependencies if any(
                wi.status in {WorkItemStatus.BLOCKED, WorkItemStatus.IN_PROGRESS}
                for wi in work_items
                if wi.item_id in {dep.predecessor_item_id, dep.successor_item_id}
            )
        )
        return DependencyMetrics(
            dependency_count=dependency_count,
            critical_dependency_density=critical_dependency_density,
            cross_team_dependency_count=cross_team_dependency_count,
            cross_team_dependency_pct=cross_team_dependency_pct,
            dependency_bottleneck_count=dependency_bottleneck_count,
            critical_path_length=critical_path_length,
            blocked_dependency_chain_count=blocked_dependency_chain_count,
            dependency_clusters=dependency_clusters,
            external_dependency_count=sum(1 for dep in dependencies if dep.notes and "external" in dep.notes.lower()),
        )

    def _build_planning_metrics(self, actuals: List[Any], work_items: List[Any]) -> PlanningMetrics:
        """Build deterministic planning and predictability analytics."""
        if actuals:
            planning_accuracy_score = 1.0 - min(1.0, sum(abs(a.variance_hrs) for a in actuals) / max(sum(a.planned_effort_hrs for a in actuals), 1.0))
            sprint_predictability_score = sum(a.completion_rate for a in actuals) / len(actuals)
        else:
            planning_accuracy_score = 0.0
            sprint_predictability_score = 0.0

        sizing_scores = []
        for wi in work_items:
            baseline = max(wi.current_estimate_hrs or wi.estimated_effort_hrs, 1.0)
            delta = abs(baseline - wi.estimated_effort_hrs) / baseline
            sizing_scores.append(max(0.0, 1.0 - delta))
        story_sizing_consistency_score = sum(sizing_scores) / len(sizing_scores) if sizing_scores else 0.0
        carryover_trend_score = 1.0 - min(1.0, sum(a.carryover_count for a in actuals) / max(len(actuals), 1)) if actuals else 1.0
        scope_volatility_score = sum(1 for wi in work_items if wi.is_scope_changed) / max(len(work_items), 1)
        schedule_confidence_score = max(0.0, min(1.0, (planning_accuracy_score + sprint_predictability_score) / 2.0))
        delivery_stability_score = max(0.0, 1.0 - min(1.0, abs(self._calculate_variance([a.actual_effort_hrs for a in actuals if a.actual_effort_hrs > 0]) / max(sum(a.actual_effort_hrs for a in actuals if a.actual_effort_hrs > 0), 1.0))) if actuals else 1.0)
        commitment_reliability_score = schedule_confidence_score
        backlog_churn_score = scope_volatility_score

        return PlanningMetrics(
            planning_accuracy_score=planning_accuracy_score,
            story_sizing_consistency_score=story_sizing_consistency_score,
            carryover_trend_score=carryover_trend_score,
            scope_volatility_score=scope_volatility_score,
            sprint_predictability_score=sprint_predictability_score,
            schedule_confidence_score=schedule_confidence_score,
            delivery_stability_score=delivery_stability_score,
            commitment_reliability_score=commitment_reliability_score,
            backlog_churn_score=backlog_churn_score,
        )

    def _build_quality_metrics(self, work_items: List[Any]) -> QualityMetrics:
        """Build quality and rework facts from work item data when supported."""
        defect_count = sum(1 for wi in work_items if wi.work_type in {WorkItemType.BUG, WorkItemType.DEFECT})
        reopened_work_count = sum(1 for wi in work_items if wi.status == WorkItemStatus.SPILLOVER)
        defect_density = defect_count / max(len(work_items), 1)
        rework_percentage = reopened_work_count / max(len(work_items), 1)
        requirement_volatility_score = sum(1 for wi in work_items if wi.is_scope_changed) / max(len(work_items), 1)
        scope_creep_score = requirement_volatility_score
        return QualityMetrics(
            defect_density=defect_density,
            reopened_work_count=reopened_work_count,
            rework_percentage=rework_percentage,
            requirement_volatility_score=requirement_volatility_score,
            scope_creep_score=scope_creep_score,
        )

    def _build_risk_input_metrics(self, blocker_metrics: BlockerMetrics, dependency_metrics: DependencyMetrics, resource_metrics: ResourceMetrics, planning_metrics: PlanningMetrics, velocity_metrics: VelocityMetrics, historical_metrics: HistoricalMetrics) -> RiskInputMetrics:
        """Expose deterministic inputs for downstream risk scoring."""
        return RiskInputMetrics(
            blocker_density=blocker_metrics.active_blocker_count / max(resource_metrics.team_size, 1),
            dependency_density=dependency_metrics.critical_dependency_density,
            resource_overload_score=max(0.0, resource_metrics.avg_allocation_pct - resource_metrics.avg_availability_pct),
            planning_accuracy_score=planning_metrics.planning_accuracy_score,
            velocity_stability_score=velocity_metrics.velocity_stability_score,
            carryover_rate=historical_metrics.carryover_count / max(len(historical_metrics.velocity_by_sprint), 1),
            scope_volatility_score=planning_metrics.scope_volatility_score,
        )

    def _build_forecast_input_metrics(
        self,
        remaining_effort_hours: float,
        average_velocity_hours: float,
        planned_velocity_hours: float,
        historical_carryover_rate: float,
        completed_sprints: int,
        current_sprint_number: int,
        total_sprints: int,
        team_size: int,
        avg_allocation: float,
        blocker_metrics: BlockerMetrics,
        dependency_metrics: DependencyMetrics,
        remaining_story_count: int,
        team: List[Any],
        sprints: List[Any],
        effective_project_velocity: float,
    ) -> ForecastInputMetrics:
        """Expose deterministic forecast inputs derived from workbook capacity and remaining workload."""
        remaining_sprints = sum(1 for sprint in sprints if sprint.sprint_number >= current_sprint_number)
        capacity_hours = sum(
            sum(resource.daily_capacity_hrs * sprint.working_days for resource in team)
            for sprint in sprints
            if sprint.sprint_number >= current_sprint_number
        )
        utilization_pct = remaining_effort_hours / max(capacity_hours, 1.0) if capacity_hours else 0.0
        return ForecastInputMetrics(
            remaining_effort_hours=remaining_effort_hours,
            effective_project_velocity=effective_project_velocity,
            remaining_story_count=remaining_story_count,
            historical_velocity_hours=average_velocity_hours,
            historical_carryover_rate=historical_carryover_rate,
            completed_sprints=completed_sprints,
            remaining_sprints=remaining_sprints,
            capacity_hours=capacity_hours,
            utilization_pct=utilization_pct,
            blocker_impact_hours=blocker_metrics.estimated_blocker_velocity_impact * remaining_effort_hours,
            dependency_density=dependency_metrics.critical_dependency_density,
        )

    def _build_recommendation_input_metrics(self, team: List[Any], sprints: List[Any], work_items: List[Any], blockers: List[Any], dependencies: List[Any], historical_metrics: HistoricalMetrics) -> RecommendationInputMetrics:
        """Expose deterministic factual inputs for downstream recommendation engines."""
        open_blockers = [blocker.blocker_id for blocker in blockers if blocker.actual_resolution_date is None]
        critical_dependencies = [dep.dependency_id for dep in dependencies if dep.is_on_critical_path]
        carryover_signal_sprint_ids = [sprint.sprint_name for sprint in sprints if sprint.sprint_number in {actual.sprint_number for actual in self.project_state.actuals if actual.carryover_count > 0}]
        variance_signal_sprint_ids = [sprint.sprint_name for sprint in sprints if sprint.sprint_number in {actual.sprint_number for actual in self.project_state.actuals if actual.variance_hrs != 0.0}]
        return RecommendationInputMetrics(
            developer_allocation_pct={resource.name: resource.allocation_pct for resource in team if resource.name},
            sprint_planned_velocity_hours={sprint.sprint_name: sprint.planned_velocity_hrs for sprint in sprints},
            open_blocker_ids=open_blockers,
            critical_dependency_ids=critical_dependencies,
            carryover_signal_sprint_ids=carryover_signal_sprint_ids,
            variance_signal_sprint_ids=variance_signal_sprint_ids,
            recurring_blockers=len(open_blockers),
            critical_dependencies=len(critical_dependencies),
        )

    @staticmethod
    def _calculate_variance(values: List[float]) -> float:
        """Calculate variance of a list of values."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance

    @staticmethod
    def _count_blockers_by_severity(blockers) -> Dict[str, int]:
        """Count blockers grouped by severity."""
        counts = {
            "Critical": sum(1 for b in blockers if b.severity == BlockerSeverity.CRITICAL),
            "High": sum(1 for b in blockers if b.severity == BlockerSeverity.HIGH),
            "Medium": sum(1 for b in blockers if b.severity == BlockerSeverity.MEDIUM),
            "Low": sum(1 for b in blockers if b.severity == BlockerSeverity.LOW),
        }
        return counts

    @staticmethod
    def _estimate_blocker_velocity_impact(
        blockers, as_of_date=None, work_items=None, team=None
    ) -> float:
        """Estimate velocity impact from active blockers (0.0-1.0).

        Canonical severity-weight model. Each unresolved blocker contributes
        a fixed weight based on its severity tier:

            Critical = 0.40
            High     = 0.20
            Medium   = 0.10
            Low      = 0.05
            Unknown  = 0.00 (does not affect the calculation)

        Independent blockers compound multiplicatively via survival-product
        aggregation so impact never exceeds 1.0 and multiple LOW blockers
        can't sum beyond it:

            impact = 1 - PRODUCT(1 - severity_weight_i)

        `as_of_date`, `work_items`, and `team` are accepted for call-site
        compatibility but are not used to scale the weight — age and
        team-size do not enter blocker probability.
        """
        base_weight_map = {
            BlockerSeverity.CRITICAL: 0.40,
            BlockerSeverity.HIGH: 0.20,
            BlockerSeverity.MEDIUM: 0.10,
            BlockerSeverity.LOW: 0.05,
        }

        active_blockers = [b for b in blockers if not b.actual_resolution_date]
        if not active_blockers:
            return 0.0

        survival = 1.0
        for blocker in active_blockers:
            base_w = base_weight_map.get(blocker.severity, 0.0)
            survival *= (1.0 - base_w)

        impact = 1.0 - survival
        return round(min(impact, 0.95), 4)

    @staticmethod
    def _calculate_critical_path_length(dependencies: List[Any], work_items: List[Any]) -> int:
        """Return a simple longest-path estimate over dependency chains."""
        if not dependencies:
            return 0

        item_ids = {wi.item_id for wi in work_items}
        adjacency = {item_id: [] for item_id in item_ids}
        for dependency in dependencies:
            if dependency.predecessor_item_id in adjacency and dependency.successor_item_id in adjacency:
                adjacency[dependency.predecessor_item_id].append(dependency.successor_item_id)

        memo: Dict[str, int] = {}

        def dfs(node_id: str) -> int:
            if node_id in memo:
                return memo[node_id]
            child_lengths = [dfs(child_id) for child_id in adjacency.get(node_id, [])]
            memo[node_id] = 1 + max(child_lengths, default=0)
            return memo[node_id]

        return max((dfs(item_id) for item_id in item_ids), default=0)

    @staticmethod
    def _calculate_dependency_clusters(dependencies: List[Any], work_items: List[Any]) -> int:
        """Count dependency-connected clusters directly from workbook dependency links."""
        if not dependencies:
            return 0

        item_ids = {wi.item_id for wi in work_items}
        adjacency = {item_id: set() for item_id in item_ids}
        for dependency in dependencies:
            if dependency.predecessor_item_id in adjacency and dependency.successor_item_id in adjacency:
                adjacency[dependency.predecessor_item_id].add(dependency.successor_item_id)
                adjacency[dependency.successor_item_id].add(dependency.predecessor_item_id)

        visited = set()
        clusters = 0
        for item_id in item_ids:
            if item_id in visited:
                continue
            stack = [item_id]
            visited.add(item_id)
            while stack:
                current_id = stack.pop()
                for child_id in adjacency[current_id]:
                    if child_id not in visited:
                        visited.add(child_id)
                        stack.append(child_id)
            clusters += 1
        return clusters

    def _trimmed_mean_velocity(self, velocities: List[float]) -> float:
        """Drop the highest and lowest sprint velocity before averaging,
        to prevent a single anomalous sprint (crunch, cybersec push, etc.)
        from inflating the forecast."""
        if len(velocities) <= 2:
            return sum(velocities) / len(velocities) if velocities else 0.0
        trimmed = sorted(velocities)[1:-1]
        return sum(trimmed) / len(trimmed) if trimmed else 0.0

    @staticmethod
    def _get_current_sprint_number(sprints) -> int:
        """Determine current sprint number based on sprint status."""
        # Find first in-progress or not-started sprint
        for sprint in sprints:
            if sprint.status == SprintStatus.IN_PROGRESS:
                return sprint.sprint_number
            if sprint.status == SprintStatus.NOT_STARTED:
                return sprint.sprint_number
        # If all completed, return last sprint + 1
        return max((s.sprint_number for s in sprints), default=1) + 1