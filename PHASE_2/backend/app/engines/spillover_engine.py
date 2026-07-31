"""
Spillover Analysis Engine

Predicts work items likely to carry over to next sprint.

KNOWN LIMITATIONS (documented, not fixed in this pass — see audit discussion):
1. predicted_spillover_by_sprint loops over every sprint in the project,
   including already-completed sprints with stray leftover NOT_STARTED/
   IN_PROGRESS items and not-yet-started future sprints. It does not
   distinguish "this sprint is closed, any remaining item here is a data
   hygiene issue" from "this sprint hasn't started, there's no track record
   to spill from yet" from "this sprint is in flight and at real risk."
2. avg_item_effort is a single project-wide average applied uniformly to
   every sprint's excess-hours figure to derive an item count. On a project
   with high item-size variance, this over/understates how many items will
   actually spill in any given sprint.
3. (FIXED below) avg_actual_velocity previously always took the lower of
   planned-vs-historical-average velocity for every sprint, one-directionally
   inflating predicted spillover on any deliberately over-planned sprint.
4. spillover_probability (per-item, normal-CDF-based) and
   predicted_spillover_by_sprint (per-sprint, flat threshold heuristic) are
   two independent models of the same underlying risk and are not reconciled
   against each other. They can disagree for the same sprint.
5. spillover_confidence_intervals derives its margin of error from velocity
   variance divided by an unexplained constant (5.0, "as sqrt(25)"), not from
   the actual variance of the spillover prediction itself. Treat these
   intervals as illustrative, not statistically rigorous.
"""

from typing import Dict, List, Tuple, Any
from pydantic import BaseModel
import statistics

from app.domain.models import ProjectState, WorkItemStatus, SprintStatus


class SpilloverAnalysis(BaseModel):
    """Spillover analysis results."""
    
    # Per-item spillover probability
    spillover_probability: Dict[str, float]  # item_id -> probability (0.0-1.0)
    
    # Per-sprint predictions
    predicted_spillover_by_sprint: Dict[int, float]  # sprint_num -> expected spillover count
    
    # Confidence intervals
    spillover_confidence_intervals: Dict[int, Tuple[float, float]]  # sprint_num -> (lower, upper)
    
    # High-risk items
    high_spillover_risk_items: List[str]  # Items with spillover probability > 0.6
    
    # Historical patterns
    historical_carryover_rate: float
    historical_carryover_std_dev: float
    
    # Capacity constraints
    sprint_utilization_pct: Dict[int, float]  # sprint_num -> % of capacity used by planned items

    # Forecast-aligned spillover (hours) that the ForecastEngine will consume
    # (Removed forecast_spillover_hours and top_spillover_sprints — forecast should
    # consume spillover via ForecastResult.effort_breakdown.spillover_penalty_hours)


class SpilloverAnalysisEngine:
    """Analyzes spillover risk using effort, velocity, and historical data."""
    
    def __init__(self, project_state: ProjectState, avg_item_effort: float = 20.0):
        self.project_state = project_state
        self.work_items = project_state.work_items
        self.sprints = {s.sprint_number: s for s in project_state.sprints}
        self.actuals = project_state.actuals
        
        # Velocity variance configuration
        self.velocity_std_dev_factor = 0.15  # 15% std dev of velocity

        # Average item effort (hours) — injected from MetricsEngine when available
        self.avg_item_effort: float = float(avg_item_effort or 20.0)
    
    def analyze(self) -> SpilloverAnalysis:
        """Analyze spillover risk for all work items."""
        
        # Get historical velocity stats
        actual_velocities = [a.actual_effort_hrs for a in self.actuals if a.actual_effort_hrs > 0]
        hist_carryover = [a.carryover_count for a in self.actuals]
        
        hist_carryover_rate = sum(hist_carryover) / len(hist_carryover) if hist_carryover else 0.0
        hist_carryover_std_dev = self._std_dev(hist_carryover) if len(hist_carryover) > 1 else 0.0
        
        # Compute per-item spillover probability
        spillover_prob = self._compute_item_spillover_probability()
        
        # Compute per-sprint predictions
        sprint_spillover = self._predict_sprint_spillover(actual_velocities)
        
        # Confidence intervals (using historical variance)
        confidence_intervals = self._compute_confidence_intervals(actual_velocities, sprint_spillover)
        
        # Categorize high-risk items
        high_risk = sorted(
            [item_id for item_id, prob in spillover_prob.items() if prob > 0.6]
        )
        
        # Sprint utilization
        sprint_util = self._compute_sprint_utilization()

        # NOTE: do not compute forecast_spillover_hours here. ForecastEngine
        # computes spillover_penalty_hours using `metrics.average_item_effort`.

        return SpilloverAnalysis(
            spillover_probability=spillover_prob,
            predicted_spillover_by_sprint=sprint_spillover,
            spillover_confidence_intervals=confidence_intervals,
            high_spillover_risk_items=high_risk,
            historical_carryover_rate=hist_carryover_rate,
            historical_carryover_std_dev=hist_carryover_std_dev,
            sprint_utilization_pct=sprint_util,
        )
    
    def _compute_item_spillover_probability(self) -> Dict[str, float]:
        """Compute spillover probability for each work item."""
        probabilities = {}
        
        # Group items by assigned sprint
        items_by_sprint = {}
        for item in self.work_items:
            sprint_num = self._get_sprint_number(item.assigned_sprint)
            if sprint_num not in items_by_sprint:
                items_by_sprint[sprint_num] = []
            items_by_sprint[sprint_num].append(item)
        
        # Compute probability per item
        # Compute historical avg velocity for fallback when sprints have zero planned capacity
        actual_velocities = [a.actual_effort_hrs for a in self.actuals if a.actual_effort_hrs > 0]
        avg_velocity = sum(actual_velocities) / len(actual_velocities) if actual_velocities else 100.0
        for sprint_num, items in items_by_sprint.items():
            sprint = self.sprints.get(sprint_num)
            if not sprint:
                continue
            
            available_capacity = self._effective_capacity(sprint, avg_velocity)
            
            # Filter to in-progress or not-started items (may spill)
            spillover_candidates = [
                i for i in items
                if i.status in (WorkItemStatus.IN_PROGRESS, WorkItemStatus.NOT_STARTED)
            ]
            
            # Sort by difficulty (effort * complexity heuristic)
            spillover_candidates.sort(
                key=lambda x: x.remaining_effort_hrs,
                reverse=True  # Hardest items first
            )
            
            # Compute capacity fill
            cumulative_effort = 0.0
            for item in spillover_candidates:
                cumulative_effort += item.remaining_effort_hrs
                
                # Probability that this item doesn't fit
                # = P(total effort > available capacity)
                # Use normal distribution approximation
                excess_effort = cumulative_effort - available_capacity
                variance = (available_capacity * self.velocity_std_dev_factor) ** 2
                std_dev = variance ** 0.5
                
                # Z-score
                if std_dev > 0:
                    z_score = excess_effort / std_dev
                    # Convert to probability (CDF of standard normal)
                    prob = self._normal_cdf(z_score)
                else:
                    prob = 1.0 if excess_effort > 0 else 0.0
                
                probabilities[item.item_id] = max(0.0, min(1.0, prob))
        
        return probabilities
    
    def _predict_sprint_spillover(self, actual_velocities: List[float]) -> Dict[int, float]:
        """Predict spillover count per sprint."""
        predictions = {}
        
        # Get average actual velocity
        avg_velocity = sum(actual_velocities) / len(actual_velocities) if actual_velocities else 100.0
        
        for sprint_num, sprint in self.sprints.items():
            # Skip completed sprints — they are done, their velocity already
            # appears in SprintActual records, and any stray NOT_STARTED /
            # IN_PROGRESS items left assigned to them are anomalies in the
            # workbook, not genuine future spillover risk.  Including completed
            # sprints here inflates predicted_spillover_by_sprint with work that
            # will never actually spill into future capacity, which in turn
            # causes ForecastEngine and MonteCarloEngine to under-count
            # effective velocity and report fictitious schedule delay.
            if getattr(sprint, 'status', None) in (SprintStatus.COMPLETED,) or (
                isinstance(getattr(sprint, 'status', None), str)
                and getattr(sprint, 'status', '') == SprintStatus.COMPLETED.value
            ):
                continue

            # Group items assigned to this sprint
            sprint_items = [
                i for i in self.work_items
                if self._get_sprint_number(i.assigned_sprint) == sprint_num
            ]
            
            # Filter to in-progress or not-started
            spillover_candidates = [
                i for i in sprint_items
                if i.status in (WorkItemStatus.IN_PROGRESS, WorkItemStatus.NOT_STARTED)
            ]
            
            # Calculate total effort
            total_effort = sum(i.remaining_effort_hrs for i in spillover_candidates)
            
            # FIX (was: avg_actual_velocity = min(sprint.planned_velocity_hrs, avg_velocity)):
            # min(planned, avg_velocity) ALWAYS returns whichever is lower, with no
            # exception — so a sprint deliberately planned ABOVE the historical
            # average (extra capacity allocated to absorb a known-heavy workload)
            # was always capped DOWN to the historical average, every time,
            # regardless of how much extra capacity was actually planned. That is
            # a one-directional bias that systematically overstates excess effort,
            # and therefore overstates predicted spillover, for every overplanned
            # sprint — including some of this dataset's later sprints.
            #
            # Correct comparison: trust the sprint's own planned capacity by
            # default. Only pull capacity down toward the historical average when
            # the plan is unrealistically optimistic relative to demonstrated
            # team output — defined here as planned capacity exceeding the
            # historical average by more than a documented tolerance band
            # (OVERPLAN_TOLERANCE), rather than capping at the historical average
            # the instant the plan exceeds it by even a single hour.
            # Use effective capacity (falls back to historical avg when planned_capacity==0)
            avg_actual_velocity = self._effective_capacity(sprint, avg_velocity)
            velocity_variance = avg_actual_velocity * self.velocity_std_dev_factor

            # Estimated spillover items (rough heuristic: items beyond capacity)
            expected_spillover = max(0.0, (total_effort - avg_actual_velocity) / self.avg_item_effort)

            # DEEPER FIX: the check above only compares team-wide effort against
            # team-wide capacity, so it can read "no spillover" even when a specific
            # resource is individually over 100% allocated in this sprint (other
            # resources being under-loaded masks it in the aggregate). Work assigned
            # to a specific resource can't be silently done by someone else in this
            # deterministic model, so that resource's own excess is a real spillover
            # risk this sprint even when the team total has headroom. Use whichever
            # is larger -- team-level or resource-level excess -- rather than only
            # ever looking at the team aggregate.
            resource_excess_hours = self._resource_overload_excess_hours(sprint_num, spillover_candidates)
            if resource_excess_hours > 0:
                resource_driven_spillover = resource_excess_hours / self.avg_item_effort
                expected_spillover = max(expected_spillover, resource_driven_spillover)

            predictions[sprint_num] = expected_spillover
        
        return predictions

    def _resource_overload_excess_hours(self, sprint_num: int, spillover_candidates: list) -> float:
        """Sum of (assigned remaining effort - individual capacity) across any
        resource individually over-allocated in this sprint. Mirrors the capacity
        formula MetricsEngine uses for resource_sprint_loads so the two numbers
        agree with each other."""
        team = getattr(self.project_state, "team", None) or []
        if not team:
            return 0.0
        sprint_days = float(self.project_state.project_info.sprint_duration_days or 10)
        total_excess = 0.0
        for resource in team:
            assigned_hrs = sum(
                i.remaining_effort_hrs for i in spillover_candidates
                if getattr(i, "assigned_resource", None) in {resource.resource_id, resource.name}
            )
            if assigned_hrs <= 0:
                continue
            capacity = (
                (resource.daily_capacity_hrs or 0.0)
                * sprint_days
                * (resource.availability_pct or 1.0)
                * (resource.allocation_pct or 1.0)
            )
            if capacity <= 0:
                continue
            total_excess += max(0.0, assigned_hrs - capacity)
        return total_excess

    def _effective_capacity(self, sprint, avg_velocity: float) -> float:
        """Return the sprint's usable capacity for spillover math.
        Falls back to historical average velocity when planned_velocity_hrs
        is zero (workbook leaves this blank for IN_PROGRESS/NOT_STARTED
        sprints). Otherwise applies the existing OVERPLAN_TOLERANCE cap.
        """
        OVERPLAN_TOLERANCE = 1.25
        planned_capacity = getattr(sprint, 'planned_velocity_hrs', 0.0) or 0.0
        if planned_capacity <= 0:
            return float(avg_velocity or 0.0)
        if avg_velocity > 0 and planned_capacity > avg_velocity * OVERPLAN_TOLERANCE:
            return float(avg_velocity * OVERPLAN_TOLERANCE)
        return float(planned_capacity)
    
    def _compute_confidence_intervals(
        self, 
        actual_velocities: List[float], 
        sprint_spillover: Dict[int, float]
    ) -> Dict[int, Tuple[float, float]]:
        """Compute 95% confidence intervals for spillover predictions."""
        intervals = {}
        
        # Compute velocity std dev
        velocity_std_dev = self._std_dev(actual_velocities) if len(actual_velocities) > 1 else 0.0
        
        for sprint_num, predicted in sprint_spillover.items():
            # Standard error (using z=1.96 for 95% confidence)
            z_score = 1.96
            margin_of_error = z_score * velocity_std_dev / 5.0  # Divide by sqrt(25) as rough estimate
            
            lower = max(0.0, predicted - margin_of_error)
            upper = predicted + margin_of_error
            
            intervals[sprint_num] = (lower, upper)
        
        return intervals
    
    def _compute_sprint_utilization(self) -> Dict[int, float]:
        """Compute % of planned capacity used by assigned items per sprint."""
        utilization = {}
        
        for sprint_num, sprint in self.sprints.items():
            # Get all items assigned to this sprint
            sprint_items = [
                i for i in self.work_items
                if self._get_sprint_number(i.assigned_sprint) == sprint_num
            ]
            
            # Sum effort of all items (completed + in-progress + not-started)
            total_effort = sum(i.current_estimate_hrs for i in sprint_items)
            
            # Compute utilization
            # Use effective capacity (fallback to historical avg when planned==0)
            actual_velocities = [a.actual_effort_hrs for a in self.actuals if a.actual_effort_hrs > 0]
            avg_velocity = sum(actual_velocities) / len(actual_velocities) if actual_velocities else 100.0
            planned_capacity = self._effective_capacity(sprint, avg_velocity)
            if planned_capacity > 0:
                pct = (total_effort / planned_capacity) * 100.0
                utilization[sprint_num] = min(100.0, pct)  # Cap at 100%
            else:
                utilization[sprint_num] = 0.0
        
        return utilization
    
    @staticmethod
    def _get_sprint_number(sprint_name: str) -> int:
        """Extract sprint number from sprint name (e.g., 'Sprint 5' -> 5)."""
        try:
            parts = sprint_name.split()
            return int(parts[-1])
        except (ValueError, IndexError):
            return 0
    
    @staticmethod
    def _std_dev(values: List[float]) -> float:
        """Compute standard deviation of values."""
        if len(values) < 2:
            return 0.0
        return statistics.stdev(values)
    
    @staticmethod
    def _normal_cdf(z: float) -> float:
        """Approximate CDF of standard normal distribution."""
        # Using Abramowitz and Stegun approximation
        a1 = 0.254829592
        a2 = -0.284496736
        a3 = 1.421413741
        a4 = -1.453152027
        a5 = 1.061405429
        p = 0.3275911
        
        sign = 1 if z >= 0 else -1
        z = abs(z) / (2 ** 0.5)
        
        t = 1.0 / (1.0 + p * z)
        t_approx = (
            a1 * t + a2 * t ** 2 + a3 * t ** 3 + a4 * t ** 4 + a5 * t ** 5
        )
        
        cdf = 0.5 + 0.5 * sign * (1.0 - t_approx * (2.71828 ** (-z ** 2)) / (3.14159 ** 0.5))
        return cdf