from datetime import datetime, timedelta

from app.api.models_phase3 import MonteCarloResult, MonteCarloStatistics, OnTimeRisk


def test_monte_carlo_result_includes_seed_and_simulation_count():
    base = datetime(2025, 1, 1, 12, 0, 0)
    statistics = MonteCarloStatistics(
        mean_finish_date=base + timedelta(days=10),
        median_finish_date=base + timedelta(days=9),
        percentile_10=base + timedelta(days=7),
        percentile_25=base + timedelta(days=8),
        percentile_50=base + timedelta(days=9),
        percentile_75=base + timedelta(days=10),
        percentile_80=base + timedelta(days=11),
        percentile_90=base + timedelta(days=12),
        percentile_95=base + timedelta(days=13),
        mean_delay_days=2.0,
        median_delay_days=1.5,
    )

    result = MonteCarloResult(
        target_end_date=base + timedelta(days=14),
        simulation_count=1000,
        seed=42,
        statistics=statistics,
        on_time_probability=0.72,
        on_time_risk_level=OnTimeRisk.MEDIUM,
        simulations_on_time=720,
        simulations_late=280,
        most_likely_finish_date=base + timedelta(days=9),
        best_case_finish_date=base + timedelta(days=7),
        p80_finish_date=base + timedelta(days=11),
        p90_finish_date=base + timedelta(days=12),
        p95_finish_date=base + timedelta(days=13),
    )

    assert result.simulation_count == 1000
    assert result.seed == 42
