"""VelocityBaseline: single source of truth for all velocity-related inputs.

All engines that need a sprint velocity (ForecastEngine, MonteCarloEngine,
ImpactEstimator) must read from this object. Do not re-derive velocity
independently in each engine.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class VelocityBaseline:
    """Computed once in MetricsEngine, consumed by all downstream engines."""

    # Primary figure: trimmed mean of completed sprint actuals.
    # Used by ForecastEngine and MonteCarloEngine as the base velocity.
    trimmed_avg_hrs: float

    # Secondary figure: simple mean of all completed sprint actuals.
    # Used for display and comparison only — not for forecast calculation.
    simple_avg_hrs: float

    # Number of sprints used to compute the above averages.
    sprint_count: int

    # Sprint length in working days (from project_info.sprint_duration_days).
    sprint_days: float

    # Calibrated floor: the lowest acceptable velocity, expressed as a fraction
    # of trimmed_avg_hrs. Computed from ProjectCalibration.velocity_floor_pct.
    floor_hrs: float

    # Human-readable description for display in evidence panels.
    data_source: str

    @property
    def floor_pct(self) -> float:
        return self.floor_hrs / max(self.trimmed_avg_hrs, 1.0)
