from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage.session_store import store


WORKBOOK_PATH = Path(__file__).resolve().parents[1] / ".." / "INPUT" / "TIO2_Sprint_Intelligence_v5_final.xlsx"
WORKBOOK_PATH = WORKBOOK_PATH.resolve()


def _client() -> TestClient:
    store.clear_all()
    return TestClient(app)


def _upload_workbook(client: TestClient):
    with WORKBOOK_PATH.open("rb") as fh:
        response = client.post(
            "/api/upload",
            files={"file": (WORKBOOK_PATH.name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["data"]["session_id"]


def test_session_snapshot_works_after_normal_upload():
    client = _client()
    session_id = _upload_workbook(client)

    response = client.get(f"/api/session-snapshot?session_id={session_id}")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["forecast"]


def test_session_snapshot_exposes_blocker_metrics():
    client = _client()
    session_id = _upload_workbook(client)

    response = client.get(f"/api/session-snapshot?session_id={session_id}")

    assert response.status_code == 200, response.text
    payload = response.json()
    blocker_metrics = payload["data"]["blocker_metrics"]

    assert blocker_metrics["total_blocker_count"] >= 0
    assert blocker_metrics["active_blocker_count"] >= 0
    assert blocker_metrics["resolved_blocker_count"] >= 0
    assert blocker_metrics["current_sprint_active_blocker_count"] >= 0


def test_session_snapshot_exposes_urgency_window():
    client = _client()
    session_id = _upload_workbook(client)

    response = client.get(f"/api/session-snapshot?session_id={session_id}")

    assert response.status_code == 200, response.text
    payload = response.json()
    urgency_window = payload["data"]["emios_strip"].get("urgency_window")

    assert urgency_window is not None
    assert urgency_window in {
        "Overdue — resolve immediately",
        "This sprint",
        "Next sprint",
        "No immediate decision needed",
    }


def test_session_snapshot_frontend_contract_fields_exist():
    client = _client()
    session_id = _upload_workbook(client)

    response = client.get(f"/api/session-snapshot?session_id={session_id}")

    assert response.status_code == 200, response.text
    payload = response.json()["data"]

    monte_carlo = payload.get("monte_carlo", {})
    forecast = payload.get("forecast", {})
    emios_strip = payload.get("emios_strip", {})

    assert "on_time_probability" in monte_carlo
    assert "expected_delay_days" in forecast
    assert "urgency_window" in emios_strip
    assert "root_cause" in emios_strip
    assert "confidence_pct" in emios_strip
    assert "reasoning_explanation" in emios_strip


@pytest.mark.asyncio
async def test_session_snapshot_uses_shared_ai_upgrade_helper(monkeypatch):
    from app.api.routes import session_snapshot

    result = SimpleNamespace()
    seen = {}

    async def fake_upgrade(result_arg):
        seen["result"] = result_arg

    monkeypatch.setattr(session_snapshot, "get_or_build_pipeline_result", lambda session_id: result)
    monkeypatch.setattr(
        session_snapshot.store,
        "get_session",
        lambda session_id: SimpleNamespace(project_state=None, baseline_snapshot={}),
    )
    monkeypatch.setattr(session_snapshot, "_upgrade_advisor_with_ai", fake_upgrade)

    response = await session_snapshot.get_session_snapshot("abc")

    assert response.success is True
    assert seen["result"] is result


@pytest.mark.asyncio
async def test_upgrade_advisor_with_ai_uses_cache_for_repeated_inputs(monkeypatch):
    from app.engines import emios_advisor_runtime

    result = SimpleNamespace()
    captured = []

    async def fake_run_with_ai(*, inp, client, ai_advisor_enabled):
        captured.append((inp, client, ai_advisor_enabled))
        return {"executive_summary": "cached", "reasoning_explanation": "cached", "decision_explanation": "cached", "confidence_statement": "cached", "status": "ok"}

    class _FakeClient:
        async def aclose(self):
            return None

    monkeypatch.setattr(emios_advisor_runtime, "_advisor_cache", emios_advisor_runtime.InMemoryNarrativeCache())
    monkeypatch.setattr(emios_advisor_runtime, "BoschClient", lambda _settings: _FakeClient())
    monkeypatch.setattr(emios_advisor_runtime, "build_emios_advisor_input", lambda _result: SimpleNamespace(model_dump_json=lambda: "{}"))
    monkeypatch.setattr(emios_advisor_runtime, "EMIOSAdvisor", lambda: SimpleNamespace(run_with_ai=fake_run_with_ai))

    await emios_advisor_runtime.upgrade_advisor_with_ai(result)
    await emios_advisor_runtime.upgrade_advisor_with_ai(result)

    assert len(captured) == 1


def test_sprint_health_works_after_normal_upload():
    client = _client()
    session_id = _upload_workbook(client)

    response = client.get(f"/api/sprint-health?session_id={session_id}")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True


def test_recovery_plans_work_after_normal_upload():
    client = _client()
    session_id = _upload_workbook(client)

    response = client.get(f"/api/recovery-plans?session_id={session_id}")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["plans"]


def test_demo_and_upload_produce_equivalent_analysis():
    client = _client()

    demo_response = client.post("/api/demo/load")
    assert demo_response.status_code == 200, demo_response.text
    demo_session_id = demo_response.json()["data"]["session_id"]

    upload_session_id = _upload_workbook(client)

    demo_pipeline = store.get_or_build_pipeline_result(demo_session_id)
    upload_pipeline = store.get_or_build_pipeline_result(upload_session_id)

    assert demo_pipeline.forecast.expected_finish_date == upload_pipeline.forecast.expected_finish_date
    assert demo_pipeline.monte_carlo.on_time_probability == upload_pipeline.monte_carlo.on_time_probability
    assert demo_pipeline.risk_result.overall_risk_score == upload_pipeline.risk_result.overall_risk_score
