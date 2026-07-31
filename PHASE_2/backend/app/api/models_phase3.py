"""API models for Phase 3 (Forecasting)
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from app.api.models_pm_intelligence import PMIntelligenceResponse


class ForecastDelayBreakdown(BaseModel):
    """
    Additive decomposition of `expected_delay_days`.

    All components use the same `projected_velocity` basis as the forecast,
    so these fields sum exactly to `expected_delay_days`.

    expected_delay_days = days_elapsed + remaining_days_total + remaining_days_holidays - planned_window_days
    where remaining_days_total = adjusted_remaining / projected_velocity * sprint_days
    and remaining_days_holidays counts mandatory national holidays landing in
    the remaining window (see app.core.working_calendar) -- weekly weekends are
    NOT double-counted here since they're already implicit in the historical
    velocity rate.
    """

    planned_window_days: float = Field(
        ...,
        description="Planned project duration in days (target_end_date - project_start)",
    )
    days_elapsed: float = Field(
        ..., description="Schedule days already consumed by completed and in-progress sprints"
    )
    remaining_days_total: float = Field(
        ..., description="Forecasted remaining days = adjusted_remaining / projected_velocity * sprint_days"
    )
    # Additive breakdown of remaining_days_total
    remaining_days_base_work: float = Field(
        ..., description="Portion of delay driven by raw remaining effort at base velocity"
    )
    remaining_days_spillover: float = Field(
        ..., description="Portion of delay driven by spillover schedule impact at projected velocity"
    )
    remaining_days_blocker_loss: float = Field(
        ...,
        description=(
            "Extra days caused by blocker-reduced velocity: equivalent days compared against base velocity"
        ),
    )
    remaining_days_holidays: float = Field(
        0.0,
        description=(
            "Extra calendar days added for mandatory national holidays (Republic Day, "
            "Independence Day, Gandhi Jayanti) landing within the remaining window. "
            "Not part of remaining_days_total; added separately in expected_delay_days."
        ),
    )
    expected_delay_days: float = Field(
        ...,
        description=(
            "Days late vs target (mirrors ForecastResult.expected_delay_days). "
            "= days_elapsed + remaining_days_total + remaining_days_holidays - planned_window_days"
        ),
    )


class ForecastScheduleDiagnostics(BaseModel):
    """
    Diagnostic schedule components computed using `base_velocity` (not `projected_velocity`).
    These are driver magnitudes for human explanation and are NOT additive to
    `expected_delay_days`.
    """

    is_additive: bool = Field(
        False,
        description="Always False — these are diagnostic values, not an additive decomposition",
    )
    base_schedule_days: float = Field(
        ..., description="Days to complete raw remaining effort at base (unpenalised) velocity"
    )
    spillover_days: float = Field(..., description="Extra days from spillover penalty at base velocity")
    blocker_days: float = Field(..., description="Extra days from blocker velocity loss (projected vs base)")
    critical_path_days: float = Field(..., description="Extra days from critical path serialisation beyond remaining effort")
    diagnostic_total_days: float = Field(..., description="Sum of above components (does not equal expected_delay_days)")
    velocity_floor_saturated_by_blockers: Optional[bool] = Field(
        False,
        description="True when blockers reduce velocity to the floor value used by the forecast",
    )
    spillover_message: Optional[str] = Field(
        "",
        description="Narrative explanation of spillover impact on the forecast",
    )
    real_elapsed_days: float = Field(
        0.0,
        description="Actual calendar days elapsed since project start, anchored to today's real date (or a pinned as_of_date).",
    )
    status_derived_elapsed_days: float = Field(
        0.0,
        description=(
            "What elapsed days the old status-label-only method would report "
            "(completed sprint count + capped in-progress window). Diagnostic "
            "only -- no longer used to drive the forecast."
        ),
    )
    calendar_variance_days: float = Field(
        0.0,
        description=(
            "real_elapsed_days minus status_derived_elapsed_days. A large positive "
            "value means the calendar has moved further than sprint status labels "
            "suggest -- the signature of a stalled or late-starting sprint that "
            "hasn't been re-labeled yet."
        ),
    )
    non_working_days_in_remaining_window: int = Field(
        0,
        description=(
            "Weekends + national holidays falling within the remaining forecast "
            "window, for visibility only. Not added into expected_delay_days -- "
            "weekly weekends are already implicit in the velocity-to-calendar-day "
            "conversion (see forecast_engine docstring); adding them again here "
            "would double-count them."
        ),
    )


class ForecastEffortBreakdown(BaseModel):
    """Explainable breakdown of forecast effort components."""

    raw_remaining_effort_hours: float = Field(..., description="Remaining effort without spillover or critical path uplift")
    critical_path_remaining_hours: float = Field(..., description="Remaining critical path effort used by the forecast")
    spillover_penalty_hours: float = Field(..., description="Equivalent penalty hours from predicted spillover items used for schedule delay calculation")
    blocker_penalty_hours: float = Field(..., description="Effective velocity penalty converted to equivalent effort hours")
    forecast_adjusted_effort_hours: float = Field(..., description="Adjusted effort used by the forecast calculation (critical path uplift only)")


class ForecastConfidence(BaseModel):
    """Deterministic forecast confidence derived from measurable historical indicators."""

    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Deterministic confidence score from historical predictability signals")
    confidence_level: str = Field(..., description="HIGH, MEDIUM, or LOW")
    confidence_reason: str = Field(..., description="Short human-readable reason for the confidence level")
    confidence_inputs: Dict[str, float] = Field(default_factory=dict, description="Historical metrics used to calculate confidence")


class ForecastDriver(BaseModel):
    """A ranked deterministic contributor to forecast delay."""

    name: str = Field(..., description="Contributor name")
    impact: float = Field(..., description="Impact in forecast days")
    reason: str = Field(..., description="Deterministic reason for the impact")
    supporting_metrics: Dict[str, float] = Field(default_factory=dict, description="Metrics that support this driver")


class ForecastEvidence(BaseModel):
    """Structured evidence used to produce the deterministic forecast."""

    name: str = Field(..., description="Evidence name")
    value: Any = Field(..., description="Evidence value")
    unit: str = Field(..., description="Unit of the evidence value")
    source: str = Field(..., description="Source engine or metric set")


class ForecastAssumptions(BaseModel):
    """Machine-readable assumptions that govern the deterministic forecast."""

    velocity_calculation_method: str = Field(..., description="Formula used to derive projected velocity")
    blocker_adjustment_method: str = Field(..., description="Method used to model blocker impact on velocity")
    spillover_adjustment_method: str = Field(..., description="Method used to model spillover impact on throughput")
    critical_path_handling: str = Field(..., description="Method used to incorporate dependency sequencing")
    timeline_anchoring: str = Field(..., description="Method used to anchor the forecast to schedule dates")
    capacity_assumptions: Dict[str, float] = Field(default_factory=dict, description="Capacity-related assumption values")


class ForecastExplanation(BaseModel):
    """Structured explanation payload for downstream UI or AI layers."""

    summary: str = Field(..., description="Short summary of the forecast outcome")
    primary_driver: str = Field(..., description="Name of the largest forecast driver")
    driver_names: List[str] = Field(default_factory=list, description="Ordered driver names")
    confidence_note: str = Field(..., description="Confidence explanation derived from deterministic metrics")
    delay_signal: str = Field(..., description="Whether the project is projected to be early, on track, or late")


class ForecastSteeringDriver(BaseModel):
    """One bar in the manager-facing delay waterfall. These are additive —
    the full set of `days` values sums exactly to `expected_delay_days`,
    so the waterfall always reconciles with the headline number."""

    key: str = Field(..., description="Stable identifier, e.g. 'pace_scope', 'blockers', 'spillover'")
    label: str = Field(..., description="Short manager-facing label")
    days: float = Field(..., description="Signed days contributed to the delay by this driver")
    detail: str = Field(..., description="One-line explanation in plain language")
    tone: str = Field(..., description="'risk' | 'neutral' | 'good' — for UI coloring")


class ForecastSteeringBlocker(BaseModel):
    """A named, owned blocker surfaced for a steering-committee decision."""

    blocker_id: str
    description: str
    owner: Optional[str] = None
    severity: str
    category: str
    delay_days: float
    on_critical_path: bool
    target_resolution_date: Optional[datetime] = None
    raised_date: Optional[datetime] = None  # When the blocker was opened; used to compute age in UI


class ForecastSteeringOverload(BaseModel):
    """A resource over-allocated in a specific upcoming/in-progress sprint.
    Surfaced separately from spillover because sprint-level utilization is a
    team-wide average and can mask an individual running over 100% while the
    sprint total still looks fine."""

    resource_name: str
    sprint_id: str
    sprint_name: str
    load_pct: float = Field(..., description="Allocation as a percent, e.g. 129.0 for 129%")
    is_blocker_owner: bool = Field(
        False, description="True if this resource also owns an open blocker — compounding risk"
    )


class ForecastSteeringBrief(BaseModel):
    """Executive summary of the forecast, structured for a steering meeting:
    status, the one-line why, an exact waterfall reconciling to the delay
    figure, the named blockers driving it, and the decision being asked of
    management."""

    status: str = Field(..., description="'ON_TRACK' | 'AT_RISK' | 'LATE'")
    headline: str = Field(..., description="One-sentence bottom line for the room")
    subheadline: str = Field(..., description="Supporting context sentence")
    target_end_date: datetime
    expected_finish_date: datetime
    expected_delay_days: float
    completion_percentage: float
    waterfall: List[ForecastSteeringDriver] = Field(
        default_factory=list,
        description="Additive drivers; sum of `days` == expected_delay_days",
    )
    scope_growth_percent: float = 0.0
    scope_note: Optional[str] = None
    top_blockers: List[ForecastSteeringBlocker] = Field(default_factory=list)
    total_open_blockers: int = Field(
        0, description="Total open blockers, independent of how many are in top_blockers"
    )
    overloaded_resources: List[ForecastSteeringOverload] = Field(
        default_factory=list,
        description=(
            "Individuals over 100% allocation in an upcoming/in-progress sprint. "
            "A leading risk indicator that team-average spillover prediction can miss."
        ),
    )
    total_overloaded_resources: int = Field(
        0, description="Total resource-sprint overload rows, independent of how many are returned"
    )
    decision_ask: str = Field(..., description="What management is being asked to decide/unblock")
    confidence_level: str = Field(..., description="HIGH | MEDIUM | LOW")


class ForecastResult(BaseModel):
    """Deterministic single-point forecast result."""

    target_end_date: datetime = Field(..., description="Project target completion date")
    expected_finish_date: datetime = Field(..., description="Forecasted project completion date")
    expected_delay_days: float = Field(..., description="Days between expected finish and target end date (negative = early, positive = late)")
    remaining_effort_hours: float = Field(..., description="Remaining work to complete (hours)")
    completion_percentage: float = Field(..., ge=0.0, le=1.0, description="Project completion percentage (0.0-1.0)")
    projected_velocity: float = Field(..., description="Projected velocity in hours per sprint")
    on_track: bool = Field(..., description="True if expected_finish_date <= target_end_date, false otherwise")
    raw_remaining_effort_hours: float = Field(..., description="Remaining effort before forecast adjustments")
    critical_path_remaining_hours: float = Field(..., description="Remaining critical-path effort used by the forecast")
    predicted_spillover_items: float = Field(..., description="Expected number of spillover items predicted across remaining sprints")
    spillover_delay_days: float = Field(..., description="Schedule impact of predicted spillover items in days")
    spillover_penalty_hours: float = Field(..., description="Equivalent hours from predicted spillover items used for schedule delay calculation")
    blocker_penalty_hours: float = Field(..., description="Velocity penalty hours due to blockers")
    forecast_adjusted_effort_hours: float = Field(..., description="Adjusted effort used for the forecast calculation")
    scope_growth_hours: float = Field(..., description="Total additional effort hours added since baseline scope")
    scope_growth_percent: float = Field(..., description="Scope growth as a percentage of original project estimate hours")
    scope_impact_days: float = Field(..., description="Estimated days added by scope growth using projected velocity per day")
    scope_growth_message: str = Field(..., description="Narrative explaining the scope growth impact on the forecast")
    delay_breakdown: ForecastDelayBreakdown = Field(
        ...,
        description=(
            "Additive decomposition of expected_delay_days. "
            "days_elapsed + remaining_days_total - planned_window_days == expected_delay_days"
        ),
    )
    schedule_diagnostics: ForecastScheduleDiagnostics = Field(
        ...,
        description=(
            "Diagnostic driver magnitudes computed at base velocity. "
            "Not additive — use delay_breakdown for the exact decomposition."
        ),
    )
    effort_breakdown: ForecastEffortBreakdown = Field(..., description="Structured breakdown of forecast effort components")
    confidence: ForecastConfidence = Field(..., description="Deterministic confidence score and supporting inputs")
    forecast_drivers: List[ForecastDriver] = Field(default_factory=list, description="Ranked deterministic forecast contributors")
    forecast_evidence: List[ForecastEvidence] = Field(default_factory=list, description="Structured evidence used to create the forecast")
    forecast_assumptions: ForecastAssumptions = Field(..., description="Machine-readable assumptions used by the forecast")
    forecast_explanation: ForecastExplanation = Field(..., description="Structured forecast explanation for downstream UI or AI consumers")
    forecast_vs_montecarlo_note: str = Field(
        ...,
        description=(
            "Explains why the deterministic delay and Monte Carlo "
            "on-time probability can appear contradictory"
        ),
    )
    steering_brief: Optional[ForecastSteeringBrief] = Field(
        None,
        description="Manager-facing executive summary of the forecast for steering meetings",
    )


class ForecastResponse(BaseModel):
    session_id: str
    project_name: str
    forecast: ForecastResult
    pmo_kpi: Optional["PMOKpiSuite"] = Field(
        default=None,
        description=(
            "Executive PMO KPI suite — SPI, sprint adherence, milestone adherence, "
            "critical path drift, dependency pressure, forecast confidence decomposition, "
            "recovery feasibility, calendar variance, and release readiness. "
            "None only if computation fails (engine is always attempted)."
        ),
    )


class OnTimeRisk(str, Enum):
    """Risk level based on on-time delivery probability."""
    LOW = "LOW"              # >80% probability of on-time delivery
    MEDIUM = "MEDIUM"        # 60-79% probability
    HIGH = "HIGH"            # 40-59% probability
    CRITICAL = "CRITICAL"    # <40% probability


class MonteCarloStatistics(BaseModel):
    """Statistical distribution of simulation results."""

    mean_finish_date: datetime = Field(..., description="Mean expected finish date across all simulations")
    median_finish_date: datetime = Field(..., description="Median expected finish date")
    percentile_10: datetime = Field(..., description="10th percentile (optimistic scenario)")
    percentile_25: datetime = Field(..., description="25th percentile")
    percentile_50: datetime = Field(..., description="50th percentile (median)")
    percentile_75: datetime = Field(..., description="75th percentile")
    percentile_80: datetime = Field(..., description="80th percentile (for analysis)")
    percentile_90: datetime = Field(..., description="90th percentile (pessimistic scenario)")
    percentile_95: datetime = Field(..., description="95th percentile (extreme pessimistic)")
    
    mean_delay_days: float = Field(..., description="Mean delay vs. target end date (days)")
    median_delay_days: float = Field(..., description="Median delay vs. target end date (days)")


class MonteCarloResult(BaseModel):
    """Monte Carlo simulation result with probability distribution."""

    target_end_date: datetime = Field(..., description="Project target completion date (constant across all simulations)")
    simulation_count: int = Field(..., description="Number of simulations performed", ge=1)
    seed: int = Field(..., description="Random seed used for reproducibility", ge=0)
    
    # Statistics
    statistics: MonteCarloStatistics
    
    # On-time delivery probability
    on_time_probability: float = Field(..., description="Probability of finishing on or before target_end_date (0.0-1.0)", ge=0.0, le=1.0)
    on_time_risk_level: OnTimeRisk = Field(..., description="Risk rating: LOW (>80%), MEDIUM (60-79%), HIGH (40-59%), CRITICAL (<40%)")
    
    # Counts
    simulations_on_time: int = Field(..., description="Number of simulations finishing on or before target_end_date")
    simulations_late: int = Field(..., description="Number of simulations finishing after target_end_date")
    
    # Additional context
    most_likely_finish_date: datetime = Field(..., description="Median finish date (most likely outcome)")
    best_case_finish_date: datetime = Field(..., description="10th percentile (best case)")
    p80_finish_date: datetime = Field(..., description="80th percentile (80% of outcomes complete by this date)")
    p90_finish_date: datetime = Field(..., description="90th percentile (90% of outcomes complete by this date)")
    p95_finish_date: datetime = Field(..., description="95th percentile (95% of outcomes complete by this date)")


class MonteCarloResponse(BaseModel):
    """API response for Monte Carlo analysis."""
    session_id: str
    project_name: str
    monte_carlo: MonteCarloResult


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 3.3 RISK ENGINE MODELS
# ──────────────────────────────────────────────────────────────────────────────


class RiskLevel(str, Enum):
    """Risk level classification (0-100 scale)."""
    LOW = "LOW"              # 0-20
    MODERATE = "MODERATE"    # 21-40
    HIGH = "HIGH"            # 41-60
    VERY_HIGH = "VERY_HIGH"  # 61-80
    CRITICAL = "CRITICAL"    # 81-100


class RiskDriver(BaseModel):
    """Single risk driver with explanation."""
    
    category: str = Field(
        ...,
        description="Risk category: SCHEDULE, DEPENDENCY, RESOURCE, SCOPE, or BLOCKER"
    )
    score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Risk contribution score (0-100)"
    )
    title: str = Field(..., description="Short title for risk driver")
    description: str = Field(..., description="Detailed explanation of the risk")
    recommendation_hint: str = Field(
        ...,
        description="Actionable recommendation to mitigate this risk"
    )


class SprintRisk(BaseModel):
    """Risk analysis at sprint level."""
    
    sprint_id: int = Field(..., description="Sprint number")
    risk_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Sprint-level risk score (0-100)"
    )
    risk_level: RiskLevel = Field(..., description="Risk level classification")
    blocked_items: int = Field(..., ge=0, description="Number of blocked items in sprint")
    spillover_items: int = Field(..., ge=0, description="Predicted spillover items from sprint")
    overload_pct: float = Field(
        ...,
        ge=0.0,
        le=300.0,
        description="Sprint overload percentage (planned effort / capacity)"
    )
    dependency_count: int = Field(..., ge=0, description="Number of dependencies in sprint")


class RiskExplanation(BaseModel):
    """Explainable breakdown of a risk score."""
    
    score: float = Field(..., ge=0.0, le=100.0, description="Risk score")
    reasons: List[str] = Field(default_factory=list, description="Human-readable reasons for the score")
    drivers: List[RiskDriver] = Field(
        default_factory=list,
        description="Contributing risk drivers"
    )


class RiskResult(BaseModel):
    """Comprehensive risk analysis result."""
    
    # Overall project risk
    overall_risk_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Overall project risk score (0-100)"
    )
    overall_risk_level: RiskLevel = Field(..., description="Overall risk classification")
    
    # Sub-score explanations
    schedule_risk: RiskExplanation = Field(
        ...,
        description="Schedule risk breakdown with reasons"
    )
    dependency_risk: RiskExplanation = Field(
        ...,
        description="Dependency risk breakdown with reasons"
    )
    resource_risk: RiskExplanation = Field(
        ...,
        description="Resource risk breakdown with reasons"
    )
    scope_risk: RiskExplanation = Field(
        ...,
        description="Scope risk breakdown with reasons"
    )
    
    # Top risk drivers
    top_risk_drivers: List[RiskDriver] = Field(
        max_items=10,
        description="Top 10 risk drivers, sorted by risk contribution (descending)"
    )
    
    # Sprint-level analysis
    sprint_risks: List[SprintRisk] = Field(
        default_factory=list,
        description="Per-sprint risk analysis"
    )
    
    # Scoring formula documentation
    weighting_formula: str = Field(
        default="overall = 0.40 * schedule + 0.25 * dependency + 0.20 * resource + 0.15 * scope",
        description="Weighted aggregation formula used to calculate overall_risk_score"
    )
    risk_vs_montecarlo_note: str = Field(
        default="",
        description=(
            "Explains why overall risk level and Monte Carlo "
            "on-time probability can appear contradictory"
        ),
    )
    blocker_risk_concentration: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of overall_risk_score attributable to active blocker root cause "
            "(range 0.0-1.0). Values above 0.60 indicate the score is dominated by a single "
            "factor. Informational only -- does not change the score."
        ),
    )


class RiskResponse(BaseModel):
    """API response for risk analysis."""
    
    session_id: str = Field(..., description="Session ID")
    project_name: str = Field(..., description="Project name")
    risk_analysis: RiskResult = Field(..., description="Risk analysis result")


class RecommendationType(str, Enum):
    RESOLVE_BLOCKER = "Resolve Blocker"
    ADD_RESOURCE = "Add Resource"
    REASSIGN_WORK = "Reassign Work"
    REDUCE_ITEM_SCOPE = "Reduce Item Scope"
    PARALLELIZE_TASKS = "Parallelize Tasks"
    MOVE_BLOCKER_ITEMS = "Move Blocked Items Forward"
    SPLIT_TASK = "Split Task"
    CRITICAL_PATH_OPTIMIZATION = "Critical Path Optimization"


class TradeOffResponse(BaseModel):
    description: str = Field(..., description="Trade-off description")
    severity: str = Field(..., description="Trade-off severity")


class RecommendationValidationResponse(BaseModel):
    why_selected: List[str] = Field(default_factory=list, description="Why this recommendation was selected")
    why_better_than_alternatives: List[str] = Field(default_factory=list, description="How this recommendation compares to alternatives")
    rejected_alternatives: List[str] = Field(default_factory=list, description="Alternatives that were rejected")
    delay_reduction_summary: str = Field(default="", description="Expected delay before and after")
    probability_improvement_summary: str = Field(default="", description="On-time probability before and after")
    confidence_label: str = Field(default="MEDIUM", description="Human-readable confidence label")
    confidence_reasoning: str = Field(default="", description="Why this confidence level was assigned")
    trade_offs: List[TradeOffResponse] = Field(default_factory=list, description="Trade-offs introduced by this recommendation")
    one_line_pitch: str = Field(default="", description="One-line pitch for the recommendation")


class RecommendationSimulationMetricSnapshot(BaseModel):
    on_time_probability: float = Field(..., ge=0.0, le=1.0, description="On-time delivery probability")
    expected_delay_days: float = Field(..., description="Expected delay in days")
    overall_risk_score: float = Field(..., description="Overall risk score")
    schedule_risk: Optional[float] = Field(None, description="Schedule risk score")
    resource_risk: Optional[float] = Field(None, description="Resource risk score")
    projected_velocity: Optional[float] = Field(None, description="Projected forecast velocity in hours per sprint")


class RecommendationSimulationDeltaMetricSnapshot(BaseModel):
    on_time_probability: float = Field(..., description="Change in on-time delivery probability (positive improvement, negative deterioration)")
    expected_delay_days: float = Field(..., description="Change in expected delay in days (positive reduction, negative worsening)")
    overall_risk_score: float = Field(..., description="Change in overall risk score")
    schedule_risk: Optional[float] = Field(None, description="Change in schedule risk score")
    resource_risk: Optional[float] = Field(None, description="Change in resource risk score")
    projected_velocity: Optional[float] = Field(None, description="Change in projected velocity in hours per sprint")


class RecommendationSimulationEvidence(BaseModel):
    baseline: RecommendationSimulationMetricSnapshot = Field(..., description="Baseline forecast and risk metrics before applying the recommendation")
    simulated: RecommendationSimulationMetricSnapshot = Field(..., description="Forecast and risk metrics after applying the recommendation")
    delta: RecommendationSimulationDeltaMetricSnapshot = Field(..., description="Change in forecast and risk metrics attributable to the recommendation")
    forecast_lever_names: List[str] = Field(default_factory=list, description="Forecast levers expected to change as a result of the recommendation")


class RecommendationSummary(BaseModel):
    recommendation_id: str = Field(..., description="Unique recommendation identifier")
    type: RecommendationType = Field(..., description="Recommendation type")
    action: str = Field(..., description="Action text for the recommendation")
    target_ids: List[str] = Field(default_factory=list, description="Target entity IDs")
    details: Dict[str, Any] = Field(default_factory=dict, description="Structured recommendation details")
    reason: str = Field(..., description="Why this recommendation was generated")
    implementation_effort: str = Field(..., description="Estimated implementation effort")
    confidence: str = Field(..., description="Confidence level")
    priority_score: float = Field(..., ge=0.0, le=100.0, description="Recommendation effectiveness score")
    baseline_probability: float = Field(..., ge=0.0, le=1.0, description="Baseline on-time probability")
    after_probability: float = Field(..., ge=0.0, le=1.0, description="On-time probability after applying recommendation")
    expected_probability_gain: float = Field(..., description="Probability gain from recommendation")
    baseline_delay_days: float = Field(..., description="Baseline expected delay in days")
    after_delay_days: float = Field(..., description="Expected delay after recommendation")
    expected_delay_gain_days: float = Field(..., description="Delay reduction in days")
    baseline_risk_score: float = Field(..., description="Baseline overall risk score")
    after_risk_score: float = Field(..., description="Overall risk score after recommendation")
    expected_risk_reduction: float = Field(..., description="Risk score reduction")
    impact_level: str = Field(..., description="High/Medium/Low impact level for the recommendation")
    impact_confidence: str = Field(..., description="High/Medium/Low impact confidence relative to Monte Carlo noise")
    impact_classification: str = Field(..., description="Impact classification such as Positive Impact, Negative Impact, or Negligible Impact")
    business_impact: str = Field(..., description="Business impact summary for the recommendation")
    impact_summary: str = Field(..., description="Summary of the recommendation's expected impact")
    category: Optional[str] = Field(None, description="Category of the blocker if applicable")
    recommended_actions: List[str] = Field(default_factory=list, description="Category-aware recommended actions")
    action_summary: Optional[str] = Field(None, description="One-line human-readable action summary, e.g. 'Move WI-059 from Meena to Ravi'")
    resource_load_impact: Optional[Dict[str, Dict[str, float]]] = Field(None, description="Before/after load ratio per affected resource, e.g. {'Meena': {'before': 1.21, 'after': 1.07}}")
    dependency_consequence: Optional[str] = Field(None, description="Named downstream chain this recommendation protects")
    urgency: Optional[str] = Field(None, description="TODAY, THIS_SPRINT, NEXT_SPRINT, or LATER")
    blocker_overdue_days: Optional[int] = Field(None, description="Days the targeted blocker is past its target resolution date, if applicable")
    simulation_evidence: Optional[RecommendationSimulationEvidence] = Field(None, description="Baseline/simulated/delta metrics plus forecast levers changed by the recommendation")
    validation: Optional[RecommendationValidationResponse] = Field(None, description="Why this recommendation was selected and how it compares to alternatives")
    counterfactual_statement: Optional[str] = Field(None, description="What happens if this action is NOT taken, e.g. 'Without this action, on-time probability stays at 34%'")
    pm_intelligence: Optional[PMIntelligenceResponse] = Field(
        None,
        description="Full PM Decision Intelligence (classification, pm_decision_score, explanation, impact_profile). "
                    "None for recommendations generated before this was attached. "
                    "`details.impact_profile` is retained alongside this for backward compatibility.",
    )


class RecommendationSimulationRequest(BaseModel):
    recommendation_id: str = Field(..., description="Recommendation ID to simulate")


class RecommendationScenarioRequest(BaseModel):
    recommendation_ids: List[str] = Field(..., description="List of recommendation IDs to simulate as a scenario")


class ScopeChangeRequest(BaseModel):
    item_ids: List[str] = Field(..., min_items=1, description="Work item IDs to descoped")
    reason: Optional[str] = Field(None, description="Reason for the scope change")


class RecommendationSimulationResult(BaseModel):
    session_id: str = Field(..., description="Session ID")
    project_name: str = Field(..., description="Project name")
    recommendation_id: Optional[str] = Field(None, description="Recommendation ID if single recommendation simulated")
    baseline_probability: float = Field(..., ge=0.0, le=1.0)
    after_probability: float = Field(..., ge=0.0, le=1.0)
    probability_gain: float = Field(..., description="Gain in on-time probability")
    baseline_delay_days: float = Field(..., description="Baseline delay days")
    after_delay_days: float = Field(..., description="Delay days after simulation")
    delay_reduction_days: float = Field(..., description="Delay reduction in days")
    baseline_risk_score: float = Field(..., description="Baseline overall risk score")
    after_risk_score: float = Field(..., description="Overall risk score after simulation")
    risk_reduction: float = Field(..., description="Risk score reduction")
    baseline_schedule_risk: Optional[float] = Field(None, description="Baseline schedule risk score")
    after_schedule_risk: Optional[float] = Field(None, description="Schedule risk score after simulation")
    baseline_resource_risk: Optional[float] = Field(None, description="Baseline resource risk score")
    after_resource_risk: Optional[float] = Field(None, description="Resource risk score after simulation")
    delta_spillover_risk: Optional[float] = Field(None, description="Change in total predicted spillover items (baseline - after)")
    delta_projected_velocity: Optional[float] = Field(None, description="Change in projected velocity (hours per sprint): after - baseline")
    seed_used: int = Field(..., description="Monte Carlo seed used for reproducibility")
    is_positive_impact: bool = Field(..., description="True if recommendation improves at least one key metric")
    summary: str = Field(..., description="Human-readable summary of simulation result")
    scenario_recommendation_ids: Optional[List[str]] = Field(None, description="List of recommendation IDs simulated")


class AdvisorExplanation(BaseModel):
    status: str = Field(..., description="AI advisor explanation status: ok, partial, or fallback")
    executive_summary: Optional[Dict[str, Any]] = Field(
        None,
        description="Project-level executive summary produced by the AI advisor",
    )
    recommendation_explanations: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Structured recommendation explanations produced by the AI advisor",
    )
    scenario_explanation: Optional[Dict[str, Any]] = Field(
        None,
        description="Structured scenario explanation produced by the AI advisor",
    )


class RecommendationResponse(BaseModel):
    session_id: str = Field(..., description="Session ID")
    project_name: str = Field(..., description="Project name")
    recommendations: List[RecommendationSummary] = Field(default_factory=list, description="Ranked recommendation list")
    advisor_explanation: Optional[AdvisorExplanation] = Field(
        None,
        description="AI advisor narrative payload for the request",
    )


class RecommendationSimulationResponse(BaseModel):
    session_id: str = Field(..., description="Session ID")
    project_name: str = Field(..., description="Project name")
    simulation_result: RecommendationSimulationResult = Field(..., description="Simulation result")
    advisor_explanation: Optional[AdvisorExplanation] = Field(
        None,
        description="AI advisor narrative payload for the simulation result",
    )


class ScopeChangeResponse(BaseModel):
    session_id: str = Field(..., description="Session ID")
    project_name: str = Field(..., description="Project name")
    dry_run: bool = Field(False, description="Whether this was a preview (dry_run=true) or actual change (dry_run=false)")
    descoped_item_ids: List[str] = Field(default_factory=list, description="Work items removed from scope")
    changed_item_count: int = Field(..., ge=0, description="Number of work items updated")
    updated_remaining_effort_hours: float = Field(..., ge=0.0, description="Remaining effort after scope change")
    forecast: ForecastResult = Field(..., description="Updated deterministic forecast")
    risk_analysis: RiskResult = Field(..., description="Updated risk analysis")


# ---------------------------------------------------------------------------
# PMO executive KPI suite (see app.engines.pmo_kpi_engine.PMOKpiEngine)
#
# These are diagnostic/explanatory KPIs for a PMO dashboard -- deliberately
# separate from ForecastResult's single-point date forecast. They exist
# because remaining-effort-over-velocity alone cannot answer "are we behind
# plan RIGHT NOW" (SPI, sprint/milestone adherence), "is lateness spreading"
# (critical path drift, dependency pressure), or "can we still recover"
# (recovery feasibility) -- see the forecasting audit for the full rationale.
# ---------------------------------------------------------------------------


class ForecastConfidenceDecomposition(BaseModel):
    """Confidence broken into independent components instead of one scalar.
    A forecast can be effort-confident but calendar-unreliable (status labels
    disagreeing with real dates) -- collapsing those into a single number
    hides which lever a PM should actually pull to raise confidence."""

    effort_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in remaining-effort sizing (lower when scope growth is high)")
    velocity_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in projected velocity (lower when historical velocity is volatile)")
    calendar_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence that sprint status labels reflect real calendar position (lower when calendar_variance_days is large)")
    weakest_component: str = Field(..., description="Name of the lowest-scoring component -- the thing most worth fixing first")
    overall_confidence_score: float = Field(..., ge=0.0, le=1.0, description="Existing ForecastConfidence.confidence_score, included for side-by-side comparison")


class PMOKpiSuite(BaseModel):
    """Executive PMO KPI suite. Computed from ProjectMetrics, ForecastResult,
    and CriticalPathResult -- does not re-derive raw project data."""

    # Schedule Performance Index: actual completion % vs. planned completion %
    # for time elapsed so far. SPI < 1.0 = behind plan, > 1.0 = ahead.
    schedule_performance_index: float = Field(..., description="actual_completion_pct / planned_completion_pct as of today")
    planned_completion_pct: float = Field(..., ge=0.0, le=1.0, description="Fraction of the planned calendar window elapsed as of today")
    actual_completion_pct: float = Field(..., ge=0.0, le=1.0, description="Fraction of total effort actually completed")

    # Sprint / milestone adherence
    sprint_adherence_index: float = Field(..., ge=0.0, le=1.0, description="Fraction of sprints already due (end_date <= today) that closed Completed")
    sprints_due_count: int = Field(..., ge=0, description="Number of sprints whose planned end date has passed")
    sprints_on_time_count: int = Field(..., ge=0, description="Number of due sprints that closed Completed")
    milestone_adherence_score: float = Field(..., ge=0.0, le=1.0, description="Partial-credit average across due sprints (1.0 if closed, else avg item progress_pct)")

    # Critical path drift
    critical_path_drift_days: float = Field(..., description="Calendar days the critical path network was pushed forward by the real-time floor (see CriticalPathResult.calendar_shift_hours)")
    critical_path_scope_growth_percent: float = Field(..., description="Growth in critical path duration vs. original estimates (passthrough of CriticalPathResult.critical_path_growth_percent)")
    critical_path_floored_item_count: int = Field(..., ge=0, description="Items ON the critical path whose earliest start was forced to today — these directly cause the calendar shift")
    critical_path_floored_item_ids: List[str] = Field(default_factory=list, description="IDs of critical-path items that are stalled — subset of all floored items in the network")
    network_stalled_item_count: int = Field(default=0, ge=0, description="Total project-wide count of items floored to today across ALL chains, not just the critical path")

    # Dependency pressure
    dependency_pressure_item_count: int = Field(..., ge=0, description="Distinct downstream items whose predecessor is currently stalled/late")
    dependency_pressure_hours: float = Field(..., ge=0.0, description="Remaining effort hours sitting behind a stalled/late predecessor")

    # Forecast confidence decomposition
    confidence_decomposition: ForecastConfidenceDecomposition = Field(..., description="Confidence broken into effort / velocity / calendar components")

    # Recovery feasibility
    recovery_feasible: bool = Field(..., description="True if remaining effort can plausibly still fit inside the remaining planned window at max-observed sustainable velocity")
    recovery_feasibility_margin_days: float = Field(..., description="Spare days if recoverable (positive) or shortfall days if not (negative), at max sustainable velocity")
    max_sustainable_velocity: float = Field(..., description="Velocity used for the recovery feasibility test (avg + 1 std dev of historical velocity, i.e. best plausible sustained pace, not a one-off spike)")

    # Calendar variance (passthrough from ForecastScheduleDiagnostics for convenience)
    calendar_variance_days: float = Field(..., description="real_elapsed_days minus status-label-derived elapsed days -- large values mean sprint statuses are stale relative to the real calendar")

    # Release readiness
    release_readiness_index: float = Field(..., ge=0.0, le=1.0, description="Fraction of active blockers resolved -- a proxy for how close the project is to a clean release gate, independent of hours remaining")
    open_blocker_count: int = Field(..., ge=0)
    resolved_blocker_count: int = Field(..., ge=0)

    # Cumulative schedule drift ledger (Gap 3)
    # Per-sprint record of actual vs. planned close date so the *history* of drift
    # is visible, not just the current snapshot. A single cross-sectional KPI like
    # SPI or calendar_variance_days cannot show whether drift is accelerating,
    # stable, or recovering — this ledger can.
    cumulative_drift_days: float = Field(
        ...,
        description=(
            "Sum of per-sprint lateness across all sprints that have already passed "
            "their planned end date. Zero if all due sprints closed on time. "
            "Grows each time a sprint misses its window; represents total accumulated "
            "schedule debt as of today."
        ),
    )
    sprint_drift_ledger: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Per-sprint breakdown of planned end date vs. actual outcome. "
            "Each entry: {sprint_name, planned_end, status, drift_days}. "
            "drift_days > 0 means the sprint is late or still open past its window; "
            "0 means on-time. Ordered by sprint_number ascending."
        ),
    )
