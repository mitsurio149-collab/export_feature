from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.forecast_engine import ForecastEngine
from app.engines.metrics_engine import MetricsEngine
from app.engines.monte_carlo_engine import MonteCarloEngine
from app.engines.recommendation_engine.signal_detectors import ScheduleDetector
from app.engines.spillover_engine import SpilloverAnalysisEngine
from tests.test_recommendation_engine import make_recommendation_project_state


def test_scope_signal_uses_baseline_denominator():
    """Scope creep percentage should be based on original baseline estimate, not remaining effort."""
    project_state = make_recommendation_project_state()
    for work_item in project_state.work_items:
        if work_item.item_id == "WI-03":
            work_item.current_estimate_hrs = 180.0
            work_item.remaining_effort_hrs = 180.0
            break
    metrics = MetricsEngine(project_state).calculate()
    dag = DependencyGraphEngine(project_state).build_dag()
    cp_result = CriticalPathEngine(project_state, dag).analyze()
    spillover = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
    forecast = ForecastEngine(project_state, metrics, cp_result, spillover).calculate()
    monte_carlo = MonteCarloEngine(project_state, metrics, cp_result, spillover).calculate()

    detector = ScheduleDetector(project_state, forecast, monte_carlo, None, metrics)
    signals = detector.detect()
    scope_signal = next((signal for signal in signals if signal.context.get("flag") == "SCOPE_CREEP"), None)

    assert scope_signal is not None
    total_baseline = sum(float(wi.estimated_effort_hrs or 0.0) for wi in project_state.work_items)
    scope_growth_hours = float(getattr(forecast, "scope_growth_hours", 0.0) or 0.0)
    expected_pct = round((scope_growth_hours / total_baseline * 100.0) if total_baseline > 0 else 0.0, 2)

    assert scope_signal.context["scope_inflation_pct"] == expected_pct
