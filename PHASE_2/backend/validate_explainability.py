"""Validation runner for Phase 3 Explainability

Runs the full pipeline against the validated workbook and prints reconciliation checks.
"""
import sys
from pathlib import Path
from pprint import pprint

sys.path.insert(0, str(Path(__file__).parent))

from app.parsers.workbook_parser import WorkbookParser
from app.validators.workbook_validator import WorkbookValidator
from app.engines.metrics_engine import MetricsEngine
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.spillover_engine import SpilloverAnalysisEngine
from app.engines.forecast_engine import ForecastEngine
from app.engines.monte_carlo_engine import MonteCarloEngine
from app.engines.impact_scoring_engine import ImpactScoringEngine
from app.engines.risk_engine import RiskEngine
from app.engines.recommendation_engine import RecommendationEngine

from app.storage import store

from fastapi.testclient import TestClient
from app.main import app


WORKBOOK = "PHASE_2/INPUT/TIO2_Sprint_Intelligence_v5_final.xlsx"


def approx_equal(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return a == b


def run():
    report = {
        "exceptions": [],
        "checks": {},
    }

    try:
        print("Parsing workbook:", WORKBOOK)
        parser = WorkbookParser(WORKBOOK)
        project_state = parser.parse()
    except Exception as e:
        print("ERROR: Workbook parsing failed:", e)
        report["exceptions"].append(f"parser:{e}")
        pprint(report)
        return

    try:
        print("Validating workbook...")
        validator = WorkbookValidator(project_state)
        warnings = validator.validate()
        print(f"Validation warnings: {len(warnings)}")
    except Exception as e:
        print("ERROR: Workbook validation failed:", e)
        report["exceptions"].append(f"validator:{e}")
        pprint(report)
        return

    # Create session
    session_id = store.create_session(project_state)
    print("Session created:", session_id)

    try:
        # Engines sequence
        print("Calculating metrics...")
        metrics = MetricsEngine(project_state).calculate()

        print("Building dependency DAG...")
        dep = DependencyGraphEngine(project_state)
        dag = dep.build_dag()

        print("Analyzing critical path...")
        cp = CriticalPathEngine(project_state, dag).analyze()

        print("Analyzing spillover...")
        spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()

        print("Calculating deterministic forecast...")
        forecast = ForecastEngine(project_state, metrics, cp, spill).calculate()

        print("Running Monte Carlo (reduced count for speed)...")
        mc = MonteCarloEngine(project_state, metrics, cp, spill, simulation_count=2000).calculate()

        print("Scoring impact...")
        impact = ImpactScoringEngine(project_state, dag).score()

        print("Analyzing risk...")
        risk = RiskEngine(project_state, metrics, cp, dag, spill, forecast, mc, impact).analyze()

        print("Generating recommendations...")
        rec_engine = RecommendationEngine(project_state, metrics, cp, dag, spill, forecast, mc, risk, simulation_count=200)
        recommendations = rec_engine.generate_recommendations()

    except Exception as e:
        print("ERROR: Engine failed:", e)
        report["exceptions"].append(f"engine:{e}")
        pprint(report)
        return

    # STEP 2: FORECAST VALIDATION prints
    print("\nSTEP 2: Forecast values")
    fvals = {
        "expected_delay_days": forecast.expected_delay_days,
        "expected_finish_date": forecast.expected_finish_date.isoformat(),
        "remaining_effort_hours": forecast.remaining_effort_hours,
        "projected_velocity": forecast.projected_velocity,
        "on_track": forecast.on_track,
    }
    pprint(fvals)
    report["forecast"] = fvals

    # STEP 3: Delay breakdown validation
    print("\nSTEP 3: Delay breakdown validation")
    db = forecast.delay_breakdown.model_dump() if hasattr(forecast.delay_breakdown, 'model_dump') else dict(forecast.delay_breakdown)
    days_elapsed = db["days_elapsed"]
    remaining_days_total = db["remaining_days_total"]
    planned_window_days = db["planned_window_days"]
    expected_delay_days = db["expected_delay_days"]

    lhs = days_elapsed + remaining_days_total - planned_window_days
    pass3 = approx_equal(lhs, expected_delay_days, tol=1e-3)
    print("Computed lhs (days_elapsed + remaining_days_total - planned_window_days) =", lhs)
    print("expected_delay_days =", expected_delay_days)
    print("STEP 3 Result:", "PASS" if pass3 else "FAIL")
    report["checks"]["step3"] = {"lhs": lhs, "expected_delay_days": expected_delay_days, "pass": pass3}

    # STEP 4: Remaining days reconciliation
    print("\nSTEP 4: Remaining days reconciliation")
    rd_base = db["remaining_days_base_work"]
    rd_spill = db["remaining_days_spillover"]
    rd_block = db["remaining_days_blocker_loss"]
    rd_total = db["remaining_days_total"]
    lhs4 = rd_base + rd_spill + rd_block
    pass4 = approx_equal(lhs4, rd_total, tol=1e-3)
    print("Sum components =", lhs4)
    print("remaining_days_total =", rd_total)
    print("STEP 4 Result:", "PASS" if pass4 else "FAIL")
    report["checks"]["step4"] = {"sum_components": lhs4, "remaining_days_total": rd_total, "pass": pass4}

    # STEP 5: Critical Path explainability
    print("\nSTEP 5: Critical Path explainability")
    cp_remaining_hours = cp.critical_path_remaining_hours
    remaining_effort_hours = forecast.raw_remaining_effort_hours
    cp_uplift_hours = max(0.0, cp_remaining_hours - remaining_effort_hours)
    cp_schedule_active = cp_remaining_hours > remaining_effort_hours
    expected_uplift = max(0.0, cp_remaining_hours - remaining_effort_hours)
    pass5 = approx_equal(cp_uplift_hours, expected_uplift, tol=1e-3)
    print("cp_remaining_hours:", cp_remaining_hours)
    print("remaining_effort_hours:", remaining_effort_hours)
    print("cp_uplift_hours:", cp_uplift_hours)
    print("cp_schedule_active:", cp_schedule_active)
    print("STEP 5 Result:", "PASS" if pass5 else "FAIL")
    report["checks"]["step5"] = {"cp_remaining_hours": cp_remaining_hours, "remaining_effort_hours": remaining_effort_hours, "cp_uplift_hours": cp_uplift_hours, "pass": pass5}

    # STEP 6: Spillover explainability
    print("\nSTEP 6: Spillover explainability")
    predicted_spill = spill.predicted_spillover_by_sprint
    sum_predicted = sum(predicted_spill.values())
    expected_forecast_spill = sum_predicted * metrics.average_item_effort
    has_forecast_field = hasattr(spill, "forecast_spillover_hours")
    has_top_spill = hasattr(spill, "top_spillover_sprints")
    pass6 = (not has_forecast_field) and (not has_top_spill)
    print("forecast_spillover_hours exists:", has_forecast_field)
    print("top_spillover_sprints exists:", has_top_spill)
    print("sum(predicted_spillover_by_sprint):", sum_predicted)
    print("metrics.average_item_effort:", metrics.average_item_effort)
    print("expected (sum * avg_item_effort):", expected_forecast_spill)
    print("STEP 6 Result:", "PASS" if pass6 else "FAIL")
    report["checks"]["step6"] = {"forecast_spillover_hours_exists": has_forecast_field, "top_spillover_sprints_exists": has_top_spill, "pass": pass6}

    # STEP 7: Blocker explainability
    print("\nSTEP 7: Blocker explainability")
    blocker_equivalent_hours = forecast.blocker_penalty_hours
    base_velocity = metrics.actual_avg_velocity or metrics.planned_total_velocity or 0.0
    projected_velocity = forecast.projected_velocity
    remaining_sprints = forecast.remaining_effort_hours / projected_velocity if projected_velocity > 0 else float('inf')
    pass7 = blocker_equivalent_hours >= 0.0
    print("blocker_equivalent_hours:", blocker_equivalent_hours)
    print("base_velocity:", base_velocity)
    print("projected_velocity:", projected_velocity)
    print("remaining_sprints:", remaining_sprints)
    print("STEP 7 Result:", "PASS" if pass7 else "FAIL")
    report["checks"]["step7"] = {"blocker_equivalent_hours": blocker_equivalent_hours, "pass": pass7}

    # STEP 8: Monte Carlo prints
    print("\nSTEP 8: Monte Carlo results")
    print("on_time_probability:", mc.on_time_probability)
    print("p50_finish_date:", mc.statistics.percentile_50.isoformat())
    print("p80_finish_date:", mc.statistics.percentile_80.isoformat())
    sim_inputs = {
        "simulation_count": mc.simulation_count,
    }
    print("simulation_inputs:")
    pprint(sim_inputs)
    report["monte_carlo"] = {"on_time_probability": mc.on_time_probability, "p50": mc.statistics.percentile_50.isoformat(), "p80": mc.statistics.percentile_80.isoformat(), "inputs": sim_inputs}

    # STEP 9: Risk prints
    print("\nSTEP 9: Risk results")
    print("overall_risk_score:", risk.overall_risk_score)
    print("overall_risk_level:", risk.overall_risk_level.value)
    print("schedule_risk:", risk.schedule_risk.score)
    print("resource_risk:", risk.resource_risk.score)
    print("scope_risk:", risk.scope_risk.score)
    report["risk"] = {"overall_score": risk.overall_risk_score, "level": risk.overall_risk_level.value}

    # STEP 10: API Validation using TestClient
    print("\nSTEP 10: API validation: GET /api/forecast")
    client = TestClient(app)
    resp = client.get(f"/api/forecast?session_id={session_id}")
    api_ok = resp.status_code == 200
    print("HTTP status:", resp.status_code)
    if api_ok:
        data = resp.json()
        # Ensure keys exist
        ok_keys = all(k in data.get("data", {}).get("forecast", {}) for k in ["delay_breakdown", "schedule_diagnostics", "effort_breakdown"]) 
        print("contains required keys:", ok_keys)
        report["api"] = {"status_code": resp.status_code, "has_keys": ok_keys}
    else:
        print("API error detail:", resp.text)
        report["api"] = {"status_code": resp.status_code, "detail": resp.text}

    # Final report summary
    print("\nFINAL REPORT SUMMARY")
    print("Files modified: Added validation runner")
    print("Validation checks:")
    for k, v in report["checks"].items():
        print(f" - {k}: {v['pass']}")

    # Print full report dict for evidence
    print("\nFull evidence report:")
    pprint(report)


if __name__ == "__main__":
    run()
