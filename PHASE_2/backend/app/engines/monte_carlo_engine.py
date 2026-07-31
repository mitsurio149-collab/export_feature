"""
Monte Carlo Simulation Engine (Phase 3.2)

Performs probabilistic forecasting using Monte Carlo simulation.
Generates distribution of finish dates based on velocity and work variability.

Key principle: Target End Date is NEVER modified.
The target_end_date is a fixed business commitment used only for probability calculation.
All simulations hold target_end_date constant and generate variable finish_date outcomes.
"""
import random
from datetime import datetime, timedelta
from typing import List, Optional
import statistics

from pydantic import BaseModel

from app.domain.models import ProjectState, SprintStatus
from app.engines.metrics_engine import ProjectMetrics
from app.engines.critical_path_engine import CriticalPathResult
from app.engines.spillover_engine import SpilloverAnalysis
from app.api.models_phase3 import (
    MonteCarloResult,
    MonteCarloStatistics,
    OnTimeRisk,
)



from app.engines.project_calibration import ProjectCalibration
from app.storage.calibration_store import CalibrationStore, MIN_EPISODES_FOR_CORRECTION
from app.core import working_calendar

class MonteCarloEngine:
    """Monte Carlo simulation engine for probabilistic forecasting.

    Approach:
    1. For each simulation:
       a) Introduce variability into velocity (normal distribution)
       b) Introduce variability into remaining work (normal distribution)
       c) Apply random blocker impact
       d) Apply random spillover
       e) Calculate expected finish date using modified parameters
    2. Collect all finish dates
    3. Calculate statistics and percentiles
    4. Compute on-time probability (finish_date <= target_end_date)
    5. Assign risk level based on probability

    Important: target_end_date is CONSTANT across all simulations.
    It is a fixed business commitment, never modified by the engine.
    """

    def __init__(
        self,
        project_state: ProjectState,
        metrics: ProjectMetrics,
        cp_result: CriticalPathResult,
        spillover: Optional[SpilloverAnalysis] = None,
        simulation_count: int = 1000,
        velocity_std_dev_pct: float = 0.15,  # 15% std dev around velocity
        remaining_work_std_dev_pct: float = 0.10,  # 10% std dev around remaining work
        seed: int = None,
    ):
        """Initialize Monte Carlo engine.

        Args:
            project_state: Current project state
            metrics: Project metrics (velocity, effort, etc.)
            cp_result: Critical path analysis result
            spillover: Spillover analysis (optional)
            simulation_count: Number of simulations to run (default 10000)
            velocity_std_dev_pct: Standard deviation for velocity variation (0.0-1.0)
            remaining_work_std_dev_pct: Standard deviation for remaining work variation (0.0-1.0)
            seed: Random seed for reproducibility (optional)
        """
        self.project_state = project_state
        self.metrics = metrics
        self.cp_result = cp_result
        self.spillover = spillover
        self.simulation_count = simulation_count
        self.velocity_std_dev_pct = velocity_std_dev_pct
        self.remaining_work_std_dev_pct = remaining_work_std_dev_pct
        self.seed = 42 if seed is None else int(seed)

        # Use an instance-level RNG so multiple SimulationEngineV2 calls
        # in the same process don't share (and reset) the global random state.
        # This ensures baseline and simulated Monte Carlo draws are independent.
        self._rng = random.Random(self.seed)

    def calculate(self) -> MonteCarloResult:
        # Override hardcoded defaults with project-calibrated values
        _cal = ProjectCalibration.from_project_state(self.project_state)
        self.velocity_std_dev_pct = _cal.velocity_std_dev_pct
        self.remaining_work_std_dev_pct = _cal.work_std_dev_pct
        self._velocity_floor_pct = _cal.velocity_floor_pct

        # C1 fix: apply learned velocity bias from CalibrationStore.
        # If the model has over-estimated velocity in past sprints (positive bias →
        # team was slower than predicted), reduce base_velocity accordingly.
        # Only applied once MIN_EPISODES_FOR_CORRECTION episodes are available
        # so one bad sprint doesn't distort the whole forecast.
        self._velocity_bias_correction = 0.0
        try:
            team_id = getattr(self.project_state.project_info, "team_id", "default") or "default"
            profile = CalibrationStore.get(team_id)
            if profile and profile.episode_count >= MIN_EPISODES_FOR_CORRECTION:
                # velocity_bias = (actual - forecast) / forecast
                # Negative bias → model was over-optimistic → scale velocity down
                # Positive bias → model was pessimistic → scale velocity up
                # Clamp to ±20% to avoid over-correction from small samples
                self._velocity_bias_correction = max(-0.20, min(0.20, profile.velocity_bias))
        except Exception:
            self._velocity_bias_correction = 0.0

        """Run Monte Carlo simulation and return results."""

        # Target date is constant (business commitment)
        target_end_date = self.project_state.project_info.target_end_date

        # Build the national-holiday index once, sized generously around the
        # project's timeline, rather than per-simulation -- with 10,000 draws
        # a day-by-day holiday scan on every draw would be prohibitively slow.
        anchor = self.project_state.project_info.forecast_anchor_date()
        self._holiday_index = working_calendar.HolidayIndex.covering(anchor)

        # Pre-compute stall factor once for all simulations.
        # ForecastEngine applies the same logic deterministically; MC applies it
        # to the mean so the P50 output is coherent with the deterministic finish.
        # SYNC CONTRACT: mirrors forecast_engine.py stall detection exactly.
        self._stall_adjusted_base_velocity_factor = 1.0
        try:
            as_of_mc = self.project_state.project_info.effective_as_of_date()
            in_progress_sprints_mc = [
                s for s in self.project_state.sprints
                if s.status in (SprintStatus.IN_PROGRESS,)
            ]
            if in_progress_sprints_mc:
                ip = in_progress_sprints_mc[0]
                sprint_window = max(1.0, (ip.end_date - ip.start_date).total_seconds() / 86400.0)
                elapsed_in_sprint = max(0.0, (as_of_mc - ip.start_date).total_seconds() / 86400.0)
                fraction_elapsed = min(1.0, elapsed_in_sprint / sprint_window)
                if fraction_elapsed >= 0.30:
                    actuals_by_id = {a.sprint_id: a for a in self.project_state.actuals}
                    actual_rec = actuals_by_id.get(ip.sprint_id)
                    actual_so_far = float(actual_rec.actual_effort_hrs) if actual_rec else 0.0
                    if actual_so_far > 0:
                        raw_base_vel = float(self.metrics.actual_avg_velocity or 1.0)
                        projected_full = actual_so_far / fraction_elapsed
                        if projected_full < raw_base_vel:
                            blended = max(
                                0.5 * projected_full + 0.5 * raw_base_vel,
                                raw_base_vel * self._velocity_floor_pct,
                            )
                            self._stall_adjusted_base_velocity_factor = blended / raw_base_vel
                    else:
                        # Zero hours logged: apply floor (same as ForecastEngine)
                        self._stall_adjusted_base_velocity_factor = self._velocity_floor_pct
        except Exception:
            self._stall_adjusted_base_velocity_factor = 1.0

        # Collect finish dates from all simulations
        finish_dates: List[datetime] = []

        for _ in range(self.simulation_count):
            finish_date = self._run_simulation()
            finish_dates.append(finish_date)

        # Sort finish dates for percentile calculation
        finish_dates.sort()

        # Calculate statistics
        statistics_obj = self._calculate_statistics(finish_dates, target_end_date)

        # Calculate on-time probability
        on_time_count = sum(1 for fd in finish_dates if fd <= target_end_date)
        on_time_probability = on_time_count / self.simulation_count if self.simulation_count > 0 else 0.0

        # Assign risk level based on probability
        risk_level = self._calculate_risk_level(on_time_probability)

        # Build result (use percentiles from statistics for consistency)
        return MonteCarloResult(
            target_end_date=target_end_date,
            simulation_count=self.simulation_count,
            seed=self.seed,
            statistics=statistics_obj,
            on_time_probability=float(round(on_time_probability, 4)),
            on_time_risk_level=risk_level,
            simulations_on_time=on_time_count,
            simulations_late=self.simulation_count - on_time_count,
            most_likely_finish_date=statistics_obj.percentile_50,  # Use from statistics
            best_case_finish_date=statistics_obj.percentile_10,    # Use from statistics
            p80_finish_date=statistics_obj.percentile_80,          # 80% of outcomes ≤ this
            p90_finish_date=statistics_obj.percentile_90,          # 90% of outcomes ≤ this
            p95_finish_date=statistics_obj.percentile_95,          # 95% of outcomes ≤ this
        )

    def _run_simulation(self) -> datetime:
        """Run a single simulation and return the expected finish date."""

        # 1) Base remaining effort from metrics
        base_remaining = float(self.metrics.remaining_effort_hours)

        # 2) Add variation to remaining work (normal distribution)
        std_dev_remaining = base_remaining * self.remaining_work_std_dev_pct
        remaining_work = self._rng.gauss(base_remaining, std_dev_remaining)
        remaining_work = max(0.0, remaining_work)  # Clamp to non-negative

        # 3) Account for critical path sequencing using REMAINING effort
        cp_remaining_hours = float(getattr(self.cp_result, "critical_path_remaining_hours", 0.0) or 0.0)
        adjusted_remaining = max(remaining_work, cp_remaining_hours)

        # 4) Spillover: sample how much of the predicted spillover materializes
        # this trial, then fold it into THIS TRIAL'S velocity as a throughput
        # penalty — not as a separate additive days term.
        #
        # MODELING NOTE (mirrors ForecastEngine's fix — keep both in sync):
        # Spillover does not create a second, parallel block of work added on
        # top of the remaining-effort schedule; it represents capacity mismatch
        # (work re-entering the backlog instead of completing), which reduces
        # how much real progress the team makes per sprint. Previously this engine
        # computed `spillover_delay_days` independently (same units, same scale as
        # `remaining_days`) and added it on top — duplicating the same effort
        # against two convergent schedule terms, randomized fresh on every trial.
        # That widened the simulated spread and shifted the whole distribution
        # later on every run. We now apply the same velocity-erosion model the
        # deterministic ForecastEngine uses, sampled per-trial via spillover_factor
        # so Monte Carlo still captures spillover *variance* (0% to 100% of
        # predicted spillover materializing), just without double counting it.
        avg_item_effort = float(getattr(self.metrics, "average_item_effort", 20.0) or 20.0)
        spillover_hours = 0.0
        spillover_factor = 0.0
        if self.spillover:
            try:
                total_spill = sum(self.spillover.predicted_spillover_by_sprint.values())
                # Sample 0-100% random spillover materialization (sometimes items don't spill)
                spillover_factor = self._rng.uniform(0.0, 1.0)
                spillover_hours = float(total_spill) * avg_item_effort * spillover_factor
            except Exception:
                spillover_hours = 0.0
                spillover_factor = 0.0

        # 5) Base velocity with random variation (normal distribution)
        # Allow sprint-level planned velocities to fall back to historical
        # average for in-progress / not-started sprints when the workbook leaves
        # future sprints empty. Compute an average remaining planned velocity
        # and prefer it if non-zero.
        _vb = getattr(self.metrics, "velocity_baseline", None)
        base_velocity = float(_vb.trimmed_avg_hrs if _vb else self.metrics.actual_avg_velocity)
        if not base_velocity:
            base_velocity = float(self.metrics.planned_total_velocity or 1.0)
        try:
            remaining_sprints = [
                s for s in self.project_state.sprints
                if s.status in (SprintStatus.IN_PROGRESS, SprintStatus.NOT_STARTED)
            ]
            if remaining_sprints:
                per_sprint_caps = [
                    (
                        (s.planned_velocity_hrs if getattr(s, 'planned_velocity_hrs', 0.0) and s.planned_velocity_hrs > 0 else float(base_velocity or 0.0))
                        + s.simulation_capacity_hrs()  # cross_train_backup / swarm_item write capacity here — must be counted or those actions have no forecast effect
                    )
                    for s in remaining_sprints
                ]
                avg_remaining_planned_velocity = sum(per_sprint_caps) / len(per_sprint_caps) if per_sprint_caps else 0.0
                if avg_remaining_planned_velocity > 0:
                    base_velocity = max(base_velocity, avg_remaining_planned_velocity)
        except Exception:
            pass
        # Apply stall factor (computed once in calculate(), mirrors ForecastEngine stall logic).
        # This scales base_velocity DOWN when the in-progress sprint shows zero/low throughput,
        # ensuring MC's mean velocity matches ForecastEngine's deterministic velocity so their
        # outputs are coherent: FC should fall between MC P50 and P80, not beyond P95.
        stall_factor = getattr(self, "_stall_adjusted_base_velocity_factor", 1.0)
        if stall_factor < 1.0:
            base_velocity = base_velocity * stall_factor
        # C1 fix: apply learned velocity bias correction
        if self._velocity_bias_correction != 0.0:
            # bias < 0 means model over-estimated → team was slower → reduce velocity
            base_velocity = base_velocity * (1.0 + self._velocity_bias_correction)
            base_velocity = max(base_velocity, 1.0)  # never drive to zero

        # 6) Sample blocker impact — truncated normal centered at 80% of max
        # (blockers either fully bite or they're partially mitigated — uniform 0-max
        # underestimates the expected impact by 50%; this is more realistic)
        blocker_impact_max = float(getattr(self.metrics, "estimated_blocker_velocity_impact", 0.0) or 0.0)
        # S1 fix: truncated normal centered at 80% of max impact
        # (most of the time blockers do materially bite; occasionally they resolve early)
        if blocker_impact_max > 0.0:
            _mean_impact = blocker_impact_max * 0.80
            _std_impact = blocker_impact_max * 0.15
            blocker_impact_actual = max(0.0, min(blocker_impact_max,
                self._rng.gauss(_mean_impact, _std_impact)))
        else:
            blocker_impact_actual = 0.0
        sprint_days = float(self.project_state.project_info.sprint_duration_days or 14)

        # spillover_fraction: this trial's spillover-driven share of remaining
        # schedule delay, capped so a single trial's velocity can never be driven
        # to near-zero by spillover alone. Mirrors ForecastEngine's cap exactly.
        # M2 fix: apply floor only once — in mean_velocity below, not here
        # velocity_without_spillover is an intermediate term for spillover fraction calc only
        velocity_without_spillover = max(base_velocity * (1.0 - blocker_impact_actual), base_velocity * self._velocity_floor_pct * 0.5)
        spillover_penalty_days = (
            (spillover_hours / velocity_without_spillover) * sprint_days
            if velocity_without_spillover > 0 else 0.0
        )
        days_without_spillover = (
            (adjusted_remaining / velocity_without_spillover) * sprint_days
            if velocity_without_spillover > 0 else 0.0
        )
        spillover_fraction = (
            min(0.4, spillover_penalty_days / max(1.0, days_without_spillover))
            if days_without_spillover > 0 else 0.0
        )
        # Must match ForecastEngine.SPILLOVER_VELOCITY_DAMPING — keep these two
        # constants identical or the deterministic and probabilistic forecasts
        # will disagree on how hard spillover bites for the same input data.
        SPILLOVER_VELOCITY_DAMPING = 0.5

        # Blockers AND spillover both reduce MEAN velocity (consistent with the
        # deterministic forecast). Natural velocity fluctuation is layered on
        # top via the random.gauss draw below.
        mean_velocity = (
            base_velocity
            * (1.0 - blocker_impact_actual)
            * (1.0 - spillover_fraction * SPILLOVER_VELOCITY_DAMPING)
        )
        mean_velocity = max(mean_velocity, base_velocity * self._velocity_floor_pct)

        projected_velocity = max(
            self._rng.gauss(
                mean_velocity,
                mean_velocity * self.velocity_std_dev_pct,
            ),
            base_velocity * self._velocity_floor_pct,
        )

        # 7) Calculate remaining sprints and days. Spillover's effect is now
        # fully expressed through the eroded projected_velocity above — there
        # is no separate additive spillover_delay_days term added to the
        # schedule. spillover_hours/spillover_factor are retained only as
        # inputs to the erosion calculation, not as a standalone days figure.
        remaining_sprints = adjusted_remaining / projected_velocity if projected_velocity > 0 else float('inf')
        sprint_days = float(self.project_state.project_info.sprint_duration_days or 14)
        remaining_days = remaining_sprints * sprint_days

        # 8) Timeline anchoring (same as Phase 3.1 deterministic forecast)
        project_start = self.project_state.project_info.forecast_anchor_date()
        days_elapsed = self._calculate_schedule_elapsed_days(sprint_days)

        # Expected finish = project_start + elapsed + remaining
        # (spillover already baked into remaining_days via projected_velocity)
        # National holidays are added as explicit extra non-working days on top,
        # same reasoning as ForecastEngine: they're irregular and can't already
        # be priced into the velocity draw the way recurring weekly weekends
        # are. Uses the prebuilt HolidayIndex (bisect) rather than a day-by-day
        # scan since this runs once per simulation draw (~10,000x per call).
        holiday_index = getattr(self, "_holiday_index", None)
        finish_candidate = project_start + timedelta(days=days_elapsed + remaining_days)
        if holiday_index is not None:
            for _ in range(5):
                holidays_in_range = holiday_index.count_between(project_start, finish_candidate)
                new_finish = project_start + timedelta(days=days_elapsed + remaining_days + holidays_in_range)
                if new_finish == finish_candidate:
                    break
                finish_candidate = new_finish
        expected_finish = finish_candidate

        return expected_finish

    def _calculate_schedule_elapsed_days(self, sprint_days: float) -> float:
        """Real elapsed calendar days since project start, anchored to
        effective_as_of_date() (wall-clock time unless a demo snapshot is
        pinned via as_of_date).

        FIX: The previous implementation counted elapsed time purely from
        sprint status labels — completed_sprints * sprint_days + at most one
        sprint window for the in-progress sprint. That made the model's
        internal clock stop advancing once the current sprint started, no
        matter how many calendar days had passed. For this project, Sprint 6
        ended 2026-07-13 but is still marked In Progress with zero velocity —
        the old method credited only 14 days for Sprint 6 regardless of the
        actual overrun, making the project appear 11+ days younger than it is
        and producing an "ahead of schedule" result despite blockers,
        overloads, and zero throughput.

        Anchoring to the real date fixes this unconditionally: stalled sprints
        and overdue-but-not-started sprints immediately show up as elapsed
        schedule time, with no dependency on anyone updating a status field.

        Must stay in sync with ForecastEngine._calculate_schedule_elapsed_days,
        which uses the identical approach. If these two diverge, the
        deterministic and probabilistic elapsed-day figures will disagree and
        produce contradictory delay/probability signals.
        """
        project_start = self.project_state.project_info.forecast_anchor_date()
        as_of = self.project_state.project_info.effective_as_of_date()
        return max(0.0, (as_of - project_start).total_seconds() / (24 * 3600))

    def _calculate_statistics(
        self, finish_dates: List[datetime], target_end_date: datetime
    ) -> MonteCarloStatistics:
        """Calculate statistical summary of simulation results."""

        n = len(finish_dates)
        if n == 0:
            raise ValueError("No simulation results to analyze")

        # Calculate percentile indices using consistent method
        # For n items, kth percentile is at index: k * (n - 1)
        # But we'll use simpler approach: int(k * n) for closest element
        p10_idx = int(0.10 * (n - 1))
        p25_idx = int(0.25 * (n - 1))
        p50_idx = int(0.50 * (n - 1))
        p75_idx = int(0.75 * (n - 1))
        p80_idx = int(0.80 * (n - 1))
        p90_idx = int(0.90 * (n - 1))
        p95_idx = int(0.95 * (n - 1))

        p10 = finish_dates[p10_idx]
        p25 = finish_dates[p25_idx]
        p50 = finish_dates[p50_idx]
        p75 = finish_dates[p75_idx]
        p80 = finish_dates[p80_idx]
        p90 = finish_dates[p90_idx]
        p95 = finish_dates[p95_idx]

        # Mean finish date
        timestamps = [fd.timestamp() for fd in finish_dates]
        mean_timestamp = statistics.mean(timestamps)
        mean_finish_date = datetime.fromtimestamp(mean_timestamp)

        # Delay calculations
        mean_delay_days = (mean_finish_date - target_end_date).days
        median_delay_days = (p50 - target_end_date).days

        return MonteCarloStatistics(
            mean_finish_date=mean_finish_date,
            median_finish_date=p50,
            percentile_10=p10,
            percentile_25=p25,
            percentile_50=p50,
            percentile_75=p75,
            percentile_80=p80,
            percentile_90=p90,
            percentile_95=p95,
            mean_delay_days=float(mean_delay_days),
            median_delay_days=float(median_delay_days),
        )

    def _calculate_risk_level(self, on_time_probability: float) -> OnTimeRisk:
        """Determine risk level based on on-time probability.

        >80% = LOW risk (likely to deliver on time)
        60-79% = MEDIUM risk
        40-59% = HIGH risk
        <40% = CRITICAL risk
        """
        if on_time_probability > 0.80:
            return OnTimeRisk.LOW
        elif on_time_probability >= 0.60:
            return OnTimeRisk.MEDIUM
        elif on_time_probability >= 0.40:
            return OnTimeRisk.HIGH
        else:
            return OnTimeRisk.CRITICAL