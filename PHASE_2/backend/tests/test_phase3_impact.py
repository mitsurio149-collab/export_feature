"""
Tests for EMIOS Phase 3 (Stages 7-11): ImpactAssessor.

SimpleNamespace fakes; real ImpactDimension enum. Verifies the full five-axis
matrix, 0-10 magnitude clamping, and that each axis reads the correct field.
"""
from types import SimpleNamespace

from app.domain.emios_models import ImpactDimension
from app.engines.impact_assessor import ImpactAssessor


# ---- fakes ---------------------------------------------------------------
def _forecast(delay=0.0):
    return SimpleNamespace(expected_delay_days=delay)


def _mc(otp):
    return SimpleNamespace(on_time_probability=otp)


def _cp(items):
    return SimpleNamespace(critical_path=items, critical_path_items=items)


def _quality(rework=0.0, defect=0.0, reopened=0):
    return SimpleNamespace(
        rework_percentage=rework, defect_density=defect, reopened_work_count=reopened
    )


def _metrics(*, rsl=None, quality=None, team=5, carry=0.0, trend=0.0):
    return SimpleNamespace(
        resource_sprint_loads=rsl or {},
        quality_metrics=quality or _quality(),
        resource_metrics=SimpleNamespace(team_size=team, developer_metrics=[]),
        velocity_metrics=SimpleNamespace(velocity_trend_pct=trend, velocity_by_sprint=[]),
        historical_carryover_rate=carry,
    )


def _info(release=False, sprint_days=14):
    return SimpleNamespace(
        release_date=(object() if release else None),
        sprint_duration_days=sprint_days,
    )


def _state(release=False, sprint_days=14):
    return SimpleNamespace(project_info=_info(release, sprint_days))


def _dx(did="dx-1"):
    return SimpleNamespace(diagnosis_id=did)


# ---- gate: all five dimensions always present ----------------------------
def test_matrix_has_all_five_dimensions():
    m = ImpactAssessor().run(_dx(), _state(), forecast=_forecast(), metrics=_metrics())
    keys = set(m.estimates.keys())
    assert keys == {d.value for d in ImpactDimension}
    assert m.diagnosis_id == "dx-1"
    for est in m.estimates.values():
        assert 0.0 <= est.magnitude <= 10.0
        assert 0.0 <= est.confidence <= 1.0
        assert est.unit == "score(0-10)"
        assert est.explanation


def test_none_diagnosis_still_produces_full_matrix():
    m = ImpactAssessor().run(None, _state(), forecast=_forecast(), metrics=_metrics())
    assert len(m.estimates) == 5
    assert m.diagnosis_id is None


# ---- SCHEDULE monotonic in delay -----------------------------------------
def test_schedule_severity_rises_with_delay():
    a = ImpactAssessor().run(_dx(), _state(sprint_days=14), forecast=_forecast(0.0),
                             monte_carlo=_mc(0.9), metrics=_metrics())
    b = ImpactAssessor().run(_dx(), _state(sprint_days=14), forecast=_forecast(28.0),
                             monte_carlo=_mc(0.2), metrics=_metrics(), critical_path=_cp(["WI-1"]))
    assert b.estimates["schedule"].magnitude > a.estimates["schedule"].magnitude


# ---- RESOURCE reads resource_sprint_loads --------------------------------
def test_resource_overload_from_sprint_loads():
    rsl = {"Meena": {"S6": 1.21, "S7": 0.9}, "Ravi": {"S6": 0.7}}
    m = ImpactAssessor().run(_dx(), _state(), forecast=_forecast(),
                             metrics=_metrics(rsl=rsl, team=2))
    res = m.estimates["resource"]
    assert res.magnitude > 0.0
    assert "Meena" in res.explanation  # the >1.2 resource is named


def test_resource_zero_when_no_overload():
    rsl = {"Meena": {"S6": 0.8}, "Ravi": {"S6": 0.6}}
    m = ImpactAssessor().run(_dx(), _state(), forecast=_forecast(),
                             metrics=_metrics(rsl=rsl, team=2))
    assert m.estimates["resource"].magnitude == 0.0


# ---- BUSINESS amplified by a committed release date ----------------------
def test_business_amplified_by_release_date():
    no_rel = ImpactAssessor().run(_dx(), _state(release=False), forecast=_forecast(20.0),
                                  monte_carlo=_mc(0.3), metrics=_metrics())
    with_rel = ImpactAssessor().run(_dx(), _state(release=True), forecast=_forecast(20.0),
                                    monte_carlo=_mc(0.3), metrics=_metrics())
    assert with_rel.estimates["business"].magnitude > no_rel.estimates["business"].magnitude
    assert "committed release" in with_rel.estimates["business"].explanation


# ---- QUALITY leans on quality_metrics ------------------------------------
def test_quality_rises_with_rework():
    low = ImpactAssessor().run(_dx(), _state(), forecast=_forecast(),
                               metrics=_metrics(quality=_quality(rework=0.0)))
    high = ImpactAssessor().run(_dx(), _state(), forecast=_forecast(),
                                metrics=_metrics(quality=_quality(rework=0.5, defect=2.0, reopened=4)))
    assert high.estimates["quality"].magnitude > low.estimates["quality"].magnitude


# ---- ORGANIZATIONAL rises with chronic carryover + decline ---------------
def test_organizational_rises_with_carryover_and_decline():
    calm = ImpactAssessor().run(_dx(), _state(), forecast=_forecast(),
                                metrics=_metrics(carry=0.0, trend=0.0))
    strained = ImpactAssessor().run(_dx(), _state(), forecast=_forecast(),
                                    metrics=_metrics(carry=3.0, trend=-20.0,
                                                     rsl={"Meena": {"S6": 1.4}}, team=2))
    assert strained.estimates["organizational"].magnitude > calm.estimates["organizational"].magnitude


# ---- no forecast => pipeline should skip (assessor still returns matrix) --
def test_assessor_handles_empty_metrics():
    m = ImpactAssessor().run(None, _state(), forecast=_forecast(), metrics=None)
    assert len(m.estimates) == 5
    for est in m.estimates.values():
        assert 0.0 <= est.magnitude <= 10.0