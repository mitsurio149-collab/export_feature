"""Compare TIO2 schedule metrics before and after the sprint-status fix.

This script:
- Parses the workbook
- Runs metrics, CP, and spillover analyses
- Obtains the deterministic forecast (after-fix)
- Emulates the "before-fix" schedule elapsed computation which used
  string comparisons on `sprint.status.value == 'Completed'` and
  `sprint.status.value == 'In Progress'`.
- Prints completed_sprints, current_sprint id, days_elapsed, planned_window_days,
  remaining_days_total, expected_delay_days for both cases.
"""
import sys
from pathlib import Path
from pprint import pprint

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.parsers.workbook_parser import WorkbookParser
from app.validators.workbook_validator import WorkbookValidator
from app.engines.metrics_engine import MetricsEngine
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.spillover_engine import SpilloverAnalysisEngine
from app.engines.forecast_engine import ForecastEngine

WORKBOOK = str(Path(__file__).parent.parent.parent / "reference" / "TIO2_Sprint_Intelligence_VALIDATED.xlsx")


def emulate_before_elapsed(sprints, sprint_days):
    """Emulate pre-fix logic that compared sprint.status.value to strings.
    Returns (completed_sprints, current_sprint, days_elapsed)
    """
    # completed using string equality on .value
    completed_sprints = sum(
        1 for sprint in sprints if getattr(sprint.status, 'value', sprint.status) == "Completed"
    )
    days_from_completed = completed_sprints * sprint_days

    current_sprint = next(
        (s for s in sprints if getattr(s.status, 'value', s.status) == "In Progress"),
        None,
    )
    if not current_sprint:
        return completed_sprints, None, float(days_from_completed)

    sprint_window_days = max(
        0.0,
        (current_sprint.end_date - current_sprint.start_date).total_seconds() / (24 * 3600),
    )
    return completed_sprints, current_sprint, float(days_from_completed + min(sprint_window_days, sprint_days))


def emulate_after_elapsed(sprints, sprint_days):
    """Use enum-aware logic (matches current code)."""
    from app.domain.models import SprintStatus

    completed_sprints = sum(
        1
        for sprint in sprints
        if (
            sprint.status == SprintStatus.COMPLETED
            or (isinstance(sprint.status, str) and sprint.status == SprintStatus.COMPLETED.value)
        )
    )

    days_from_completed = completed_sprints * sprint_days

    current_sprint = next(
        (
            sprint
            for sprint in sprints
            if (
                sprint.status == SprintStatus.IN_PROGRESS
                or (isinstance(sprint.status, str) and sprint.status == SprintStatus.IN_PROGRESS.value)
            )
        ),
        None,
    )
    if not current_sprint:
        return completed_sprints, None, float(days_from_completed)

    sprint_window_days = max(
        0.0,
        (current_sprint.end_date - current_sprint.start_date).total_seconds() / (24 * 3600),
    )
    return completed_sprints, current_sprint, float(days_from_completed + min(sprint_window_days, sprint_days))


def main():
    print("Parsing workbook:", WORKBOOK)
    parser = WorkbookParser(WORKBOOK)
    project_state = parser.parse()

    print("Calculating metrics and analyses...")
    metrics = MetricsEngine(project_state).calculate()
    dep = DependencyGraphEngine(project_state)
    dag = dep.build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()

    sprint_days = float(project_state.project_info.sprint_duration_days or 14)

    # After-fix: obtain ForecastEngine output
    forecast = ForecastEngine(project_state, metrics, cp, spill).calculate()

    # Get common values
    project_start = project_state.project_info.forecast_anchor_date()
    target_end_date = project_state.project_info.target_end_date

    planned_window_days = float((target_end_date - project_start).days)
    remaining_days_total = None
    try:
        db = forecast.delay_breakdown.model_dump() if hasattr(forecast.delay_breakdown, 'model_dump') else dict(forecast.delay_breakdown)
        remaining_days_total = db["remaining_days_total"]
    except Exception:
        remaining_days_total = None

    # BEFORE: emulate old behavior
    before_completed, before_current, before_days_elapsed = emulate_before_elapsed(project_state.sprints, sprint_days)
    before_expected_delay_days = None
    if remaining_days_total is not None:
        before_expected_delay_days = before_days_elapsed + remaining_days_total - planned_window_days

    # AFTER: use enum-aware computation and forecast values
    after_completed, after_current, after_days_elapsed = emulate_after_elapsed(project_state.sprints, sprint_days)
    # after_expected_delay_days from forecast
    after_expected_delay_days = float(forecast.expected_delay_days)

    print("\nRESULTS")
    print("-------")

    print("BEFORE FIX")
    print("completed_sprints:", before_completed)
    print("current_sprint:", getattr(before_current, 'sprint_id', None) if before_current else None)
    print("days_elapsed:", round(before_days_elapsed, 4))
    print("planned_window_days:", planned_window_days)
    print("remaining_days_total:", remaining_days_total)
    print("expected_delay_days:", round(before_expected_delay_days, 4) if before_expected_delay_days is not None else None)

    print("\nAFTER FIX")
    print("completed_sprints:", after_completed)
    print("current_sprint:", getattr(after_current, 'sprint_id', None) if after_current else None)
    print("days_elapsed:", round(after_days_elapsed, 4))
    print("planned_window_days:", planned_window_days)
    print("remaining_days_total:", remaining_days_total)
    print("expected_delay_days:", round(after_expected_delay_days, 4))


if __name__ == '__main__':
    main()
