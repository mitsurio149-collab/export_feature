"""Compare ForecastEngine.calculate() output vs API /api/forecast response for TIO2.

Prints days_elapsed, planned_window_days, remaining_days_total, expected_delay_days
from the engine result, then prints the same values from the API JSON, and reports
if they match exactly.
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
from app.storage import store
from fastapi.testclient import TestClient
from app.main import app

WORKBOOK = "PHASE_2/INPUT/TIO2_Sprint_Intelligence_v5_final.xlsx"


def run():
    parser = WorkbookParser(WORKBOOK)
    project_state = parser.parse()
    validator = WorkbookValidator(project_state)
    validator.validate()

    # create session
    session_id = store.create_session(project_state)

    # run engines
    metrics = MetricsEngine(project_state).calculate()
    dep = DependencyGraphEngine(project_state)
    dag = dep.build_dag()
    cp = CriticalPathEngine(project_state, dag).analyze()
    spill = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()

    # Forecast via engine
    forecast = ForecastEngine(project_state, metrics, cp, spill).calculate()

    # Extract fields from engine's ForecastResult
    db = forecast.delay_breakdown.model_dump() if hasattr(forecast.delay_breakdown, 'model_dump') else dict(forecast.delay_breakdown)
    engine_values = {
        'days_elapsed': db['days_elapsed'],
        'planned_window_days': db['planned_window_days'],
        'remaining_days_total': db['remaining_days_total'],
        'expected_delay_days': db['expected_delay_days'],
    }

    print("Engine Forecast values:")
    pprint(engine_values)

    # Call API
    client = TestClient(app)
    resp = client.get(f"/api/forecast?session_id={session_id}")
    print("API HTTP status:", resp.status_code)
    api_json = resp.json()

    api_forecast = api_json.get('data', {}).get('forecast', {})
    api_db = api_forecast.get('delay_breakdown', {})
    api_values = {
        'days_elapsed': api_db.get('days_elapsed'),
        'planned_window_days': api_db.get('planned_window_days'),
        'remaining_days_total': api_db.get('remaining_days_total'),
        'expected_delay_days': api_db.get('expected_delay_days'),
    }

    print("API Forecast values:")
    pprint(api_values)

    # Compare
    print('\nComparison:')
    for k in engine_values:
        ev = engine_values[k]
        av = api_values[k]
        same = ev == av
        print(f"- {k}: engine={ev} api={av} match={same}")

    # If mismatch, print locations of transformation
    if engine_values != api_values:
        print('\nMismatch detected. Inspecting transformation points...')
        print('Forecast engine returns Python types/rounded values; API serializes via Pydantic. Differences may be due to rounding or serialization of model fields.')
        print('Showing raw engine delay_breakdown and API delay_breakdown for inspection:')
        pprint({'engine_delay_breakdown': db, 'api_delay_breakdown': api_db})


if __name__ == '__main__':
    run()
