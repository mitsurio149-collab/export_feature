#!/usr/bin/env python3
"""
Test script to run TIO2 workbook with Forecast Calibration Pass.

This script:
1. Loads the TIO2 workbook
2. Runs all engines with calibration parameters
3. Reports metrics: Delay, Risk, Probability, Spillover, Adjusted Effort
4. Analyzes which driver is dominating
"""

import sys
from pathlib import Path
from datetime import datetime

# Add backend directory to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.parsers import WorkbookParser
from app.validators import WorkbookValidator
from app.engines.metrics_engine import MetricsEngine
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.spillover_engine import SpilloverAnalysisEngine
from app.engines.forecast_engine import ForecastEngine
from app.engines.monte_carlo_engine import MonteCarloEngine
from app.engines.risk_engine import RiskEngine
from app.engines.impact_scoring_engine import ImpactScoringEngine
from app.core.config import settings


def print_section(title):
    """Print a formatted section header."""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")


def print_subsection(title):
    """Print a formatted subsection header."""
    print(f"\n  {title}:")
    print(f"  {'-'*76}")


def main():
    print_section("FORECAST CALIBRATION PASS - TIO2 WORKBOOK")
    
    # ─────────────────────────────────────────────────────────────────────────
    # 1. CALIBRATION PARAMETERS
    # ─────────────────────────────────────────────────────────────────────────
    print_subsection("Calibration Parameters")
    print(f"  • SPILLOVER_FORECAST_WEIGHT        : {settings.spillover_forecast_weight}")
    print(f"  • MIN_VELOCITY_FACTOR               : {settings.min_velocity_factor}")
    print(f"  • SPILLOVER_ITEM_CAP_PCT            : {settings.spillover_item_cap_pct * 100:.0f}%")
    print(f"  • UTILIZATION_PENALTY_GROWTH_CAP    : {settings.utilization_penalty_growth_cap}")
    
    # ─────────────────────────────────────────────────────────────────────────
    # 2. LOAD WORKBOOK
    # ─────────────────────────────────────────────────────────────────────────
    print_subsection("Loading TIO2 Workbook")
    try:
        parser = WorkbookParser(settings.demo_workbook_path)
        project_state = parser.parse()
        print(f"  ✓ Workbook loaded: {settings.demo_workbook_path}")
        print(f"  • Project: {project_state.project_info.project_name}")
        print(f"  • Work Items: {len(project_state.work_items)}")
        print(f"  • Sprints: {len(project_state.sprints)}")
        print(f"  • Resources: {len(project_state.team)}")
    except Exception as e:
        print(f"  ✗ Error loading workbook: {e}")
        sys.exit(1)
    
    # ─────────────────────────────────────────────────────────────────────────
    # 3. VALIDATE WORKBOOK
    # ─────────────────────────────────────────────────────────────────────────
    print_subsection("Validating Workbook")
    try:
        validator = WorkbookValidator(project_state)
        warnings = validator.validate()
        print(f"  ✓ Validation complete: {len(warnings)} warning(s)")
        for warning in warnings[:5]:  # Show first 5 warnings
            print(f"    - {warning.message}")
        if len(warnings) > 5:
            print(f"    ... and {len(warnings) - 5} more")
    except Exception as e:
        print(f"  ✗ Validation error: {e}")
        sys.exit(1)
    
    # ─────────────────────────────────────────────────────────────────────────
    # 4. METRICS ENGINE
    # ─────────────────────────────────────────────────────────────────────────
    print_subsection("Metrics Calculation")
    try:
        metrics_engine = MetricsEngine(project_state)
        metrics = metrics_engine.calculate()
        print(f"  ✓ Metrics calculated:")
        print(f"    • Total Effort (hours)              : {metrics.total_effort_hours:.1f}")
        print(f"    • Remaining Effort (hours)          : {metrics.remaining_effort_hours:.1f}")
        print(f"    • Completion %                      : {metrics.completed_effort_hours / metrics.total_effort_hours * 100:.1f}%")
        print(f"    • Actual Avg Velocity (hrs/sprint)  : {metrics.actual_avg_velocity:.1f}")
        print(f"    • Planned Total Velocity            : {metrics.planned_total_velocity:.1f}")
        print(f"    • Blocker Impact                    : {metrics.estimated_blocker_velocity_impact:.2f}")
        print(f"    • Average Item Effort (hours)       : {metrics.average_item_effort:.1f}")
    except Exception as e:
        print(f"  ✗ Error calculating metrics: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # ─────────────────────────────────────────────────────────────────────────
    # 5. CRITICAL PATH ENGINE
    # ─────────────────────────────────────────────────────────────────────────
    print_subsection("Critical Path Analysis")
    try:
        dep_engine = DependencyGraphEngine(project_state)
        dag = dep_engine.build_dag()
        cp_engine = CriticalPathEngine(project_state, dag)
        cp_result = cp_engine.analyze()
        print(f"  ✓ Critical path analyzed:")
        print(f"    • Critical Path Duration (hours)    : {cp_result.critical_path_duration_hours:.1f}")
        print(f"    • Remaining (hours)                 : {cp_result.critical_path_remaining_hours:.1f}")
        print(f"    • Items on Critical Path            : {len(cp_result.critical_path)}")
        print(f"    • High-Risk Items                   : {len(cp_result.high_risk_items)}")
    except Exception as e:
        print(f"  ✗ Error analyzing critical path: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # ─────────────────────────────────────────────────────────────────────────
    # 6. SPILLOVER ENGINE
    # ─────────────────────────────────────────────────────────────────────────
    print_subsection("Spillover Analysis")
    try:
        spillover_engine = SpilloverAnalysisEngine(project_state, metrics.average_item_effort)
        spillover = spillover_engine.analyze()
        total_predicted_spillover = sum(spillover.predicted_spillover_by_sprint.values())
        spillover_cap = max(1, int(len(project_state.work_items) * settings.spillover_item_cap_pct))
        print(f"  ✓ Spillover analyzed:")
        print(f"    • Predicted Total Spillover Items   : {total_predicted_spillover:.1f}")
        print(f"    • Spillover Item Cap (20%)          : {spillover_cap} items")
        print(f"    • Historical Carryover Rate         : {spillover.historical_carryover_rate:.2f}")
        print(f"    • High-Risk Items                   : {len(spillover.high_spillover_risk_items)}")
        print(f"    • Sprint Utilization (avg)          : {sum(spillover.sprint_utilization_pct.values()) / len(spillover.sprint_utilization_pct):.1f}%")
    except Exception as e:
        print(f"  ✗ Error analyzing spillover: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # ─────────────────────────────────────────────────────────────────────────
    # 7. DETERMINISTIC FORECAST ENGINE
    # ─────────────────────────────────────────────────────────────────────────
    print_subsection("Deterministic Forecast")
    try:
        forecast_engine = ForecastEngine(project_state, metrics, cp_result, spillover)
        forecast = forecast_engine.calculate()
        delay_days = forecast.expected_delay_days
        on_time = forecast.on_track
        
        print(f"  ✓ Forecast calculated:")
        print(f"    • Target End Date                   : {forecast.target_end_date.strftime('%Y-%m-%d')}")
        print(f"    • Expected Finish Date              : {forecast.expected_finish_date.strftime('%Y-%m-%d')}")
        print(f"    • Delay Days                        : {delay_days:.1f}")
        print(f"    • On Track                          : {'YES' if on_time else 'NO'}")
        print(f"    • Remaining Effort (hours)          : {forecast.remaining_effort_hours:.1f}")
        print(f"    • Projected Velocity (hrs/sprint)   : {forecast.projected_velocity:.1f}")
        print(f"    • Completion %                      : {forecast.completion_percentage * 100:.1f}%")
    except Exception as e:
        print(f"  ✗ Error in forecast: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # ─────────────────────────────────────────────────────────────────────────
    # 8. MONTE CARLO SIMULATION
    # ─────────────────────────────────────────────────────────────────────────
    print_subsection("Monte Carlo Simulation (10,000 iterations)")
    try:
        mc_engine = MonteCarloEngine(
            project_state,
            metrics,
            cp_result,
            spillover,
            simulation_count=10000,
            seed=42  # For reproducibility
        )
        mc_result = mc_engine.calculate()
        on_time_prob = mc_result.on_time_probability * 100
        
        print(f"  ✓ Monte Carlo simulation complete:")
        print(f"    • On-Time Probability               : {on_time_prob:.1f}%")
        print(f"    • Risk Level                        : {mc_result.on_time_risk_level.value}")
        print(f"    • Simulations On-Time               : {mc_result.simulations_on_time}")
        print(f"    • Simulations Late                  : {mc_result.simulations_late}")
        print(f"    • Most Likely Finish (P50)          : {mc_result.most_likely_finish_date.strftime('%Y-%m-%d')}")
        print(f"    • Best Case (P10)                   : {mc_result.best_case_finish_date.strftime('%Y-%m-%d')}")
        print(f"    • P80 Finish Date                   : {mc_result.p80_finish_date.strftime('%Y-%m-%d')}")
        print(f"    • P95 Finish Date                   : {mc_result.p95_finish_date.strftime('%Y-%m-%d')}")
        print(f"    • P90 Finish Date                   : {mc_result.p90_finish_date.strftime('%Y-%m-%d')}")
        print(f"    • Mean Delay (days)                 : {mc_result.statistics.mean_delay_days:.1f}")
        print(f"    • Median Delay (days)               : {mc_result.statistics.median_delay_days:.1f}")
    except Exception as e:
        print(f"  ✗ Error in Monte Carlo: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # ─────────────────────────────────────────────────────────────────────────
    # 9. RISK SCORING
    # ─────────────────────────────────────────────────────────────────────────
    print_subsection("Risk Scoring")
    try:
        # First calculate impact scores
        impact_engine = ImpactScoringEngine(project_state, dag)
        impact_scores = impact_engine.score()
        
        # Then calculate risk
        risk_engine = RiskEngine(project_state, metrics, cp_result, dag, spillover, forecast, mc_result, impact_scores)
        risk_result = risk_engine.analyze()
        
        print(f"  ✓ Risk assessment complete:")
        print(f"    • Overall Risk Score                : {risk_result.overall_risk_score:.1f}/100")
        print(f"    • Risk Level                        : {risk_result.overall_risk_level.value}")
        print(f"    • Schedule Risk                     : {risk_result.schedule_risk.score:.1f}")
        print(f"    • Dependency Risk                   : {risk_result.dependency_risk.score:.1f}")
        print(f"    • Resource Risk                     : {risk_result.resource_risk.score:.1f}")
        print(f"    • Scope Risk                        : {risk_result.scope_risk.score:.1f}")
    except Exception as e:
        print(f"  ✗ Error in risk scoring: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # ─────────────────────────────────────────────────────────────────────────
    # 10. TARGET VALIDATION
    # ─────────────────────────────────────────────────────────────────────────
    print_section("TARGET VALIDATION")
    
    print_subsection("Target Ranges vs. Actual Results")
    
    # Delay Days: 45-75 days
    delay_ok = 45 <= delay_days <= 75
    print(f"  Delay Days (Target: 45-75)")
    print(f"    • Actual: {delay_days:.1f} days", end="")
    print(f" ✓ IN RANGE" if delay_ok else f" ✗ OUT OF RANGE")
    
    # Risk remains HIGH
    risk_is_high = risk_result.overall_risk_level.value == "HIGH"
    print(f"\n  Risk Level (Target: HIGH)")
    print(f"    • Actual: {risk_result.overall_risk_level.value}", end="")
    print(f" ✓ CORRECT" if risk_is_high else f" ✗ INCORRECT")
    
    # Probability 30-50%
    prob_ok = 30 <= on_time_prob <= 50
    print(f"\n  On-Time Probability (Target: 30-50%)")
    print(f"    • Actual: {on_time_prob:.1f}%", end="")
    print(f" ✓ IN RANGE" if prob_ok else f" ✗ OUT OF RANGE")
    
    # ─────────────────────────────────────────────────────────────────────────
    # 11. DRIVER ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    print_section("DRIVER ANALYSIS")
    
    if not (delay_ok and risk_is_high and prob_ok):
        print_subsection("Out-of-Range Results - Analyzing Dominant Drivers")
        
        # Calculate impact of each factor
        spillover_impact = total_predicted_spillover * metrics.average_item_effort * settings.spillover_forecast_weight
        velocity_impact = metrics.actual_avg_velocity * settings.min_velocity_factor
        cp_impact = cp_result.critical_path_remaining_hours
        blocker_impact = metrics.estimated_blocker_velocity_impact
        
        drivers = {
            "Critical Path Duration": cp_impact,
            "Spillover Work": spillover_impact,
            "Blocker Impact": blocker_impact,
            "Velocity Reduction": velocity_impact,
        }
        
        sorted_drivers = sorted(drivers.items(), key=lambda x: x[1], reverse=True)
        
        print("\n  Ranked Drivers (by impact on delay):")
        for rank, (driver, impact) in enumerate(sorted_drivers, 1):
            pct = (impact / sum(drivers.values())) * 100 if sum(drivers.values()) > 0 else 0
            print(f"    {rank}. {driver:.<40} {impact:>8.1f} hrs ({pct:>5.1f}%)")
        
        print(f"\n  Recommendations:")
        top_driver = sorted_drivers[0][0]
        if "Critical Path" in top_driver:
            print(f"    → Focus on accelerating critical path items")
            print(f"    → Consider parallel execution of independent tasks")
        elif "Spillover" in top_driver:
            print(f"    → Increase sprint capacity to prevent spillover")
            print(f"    → Improve estimation accuracy")
        elif "Blocker" in top_driver:
            print(f"    → Prioritize blocker resolution")
            print(f"    → Establish blocker escalation process")
        elif "Velocity" in top_driver:
            print(f"    → Increase team capacity")
            print(f"    → Reduce context switching")
    else:
        print_subsection("All Targets Met ✓")
        print("\n  • Delay is within 45-75 day range")
        print("  • Risk remains HIGH")
        print("  • Probability is within 30-50% range")
        print("\n  Forecast is realistic and executive-friendly.")
    
    # ─────────────────────────────────────────────────────────────────────────
    # 12. FINAL SUMMARY
    # ─────────────────────────────────────────────────────────────────────────
    print_section("FORECAST CALIBRATION SUMMARY")
    
    print_subsection("Key Metrics")
    print(f"  • Delay Days                        : {delay_days:.1f} days")
    print(f"  • Risk Score                        : {risk_result.overall_risk_score:.1f}/100 ({risk_result.overall_risk_level.value})")
    print(f"  • On-Time Probability               : {on_time_prob:.1f}%")
    print(f"  • Total Spillover Items             : {total_predicted_spillover:.1f}")
    print(f"  • Forecast Adjusted Effort          : {forecast.remaining_effort_hours:.1f} hours")
    
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    main()
