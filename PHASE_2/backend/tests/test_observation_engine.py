"""
Tests for the EMIOS ObservationEngine (Stage 1).

Builds minimal fake metrics/forecast/state objects with SimpleNamespace so the
tests are fast and hermetic (no workbook, no engine pipeline). Covers the three
gate scenarios from the roadmap plus the hard cause=None invariant.
"""
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta

import pytest

from app.engines.observation_engine import ObservationEngine
from app.domain.models import BlockerStatus, BlockerSeverity


# ---- fakes ---------------------------------------------------------------
def _metrics(*, velocity_series=None, devs=None, carryover_rate=0.0,
             total_items=0, completed_sprints=0):
    return SimpleNamespace(
        velocity_metrics=SimpleNamespace(velocity_by_sprint=velocity_series or []),
        resource_metrics=SimpleNamespace(developer_metrics=devs or []),
        historical_carryover_rate=carryover_rate,
        total_items=total_items,
        completed_sprints=completed_sprints,
    )


def _forecast(*, scope_growth_percent=0.0):
    return SimpleNamespace(scope_growth_percent=scope_growth_percent)


def _mc(on_time_probability):
    return SimpleNamespace(on_time_probability=on_time_probability)


def _dev(resource_id, *, remaining=0.0, capacity=0.0, alloc=0.0, avail=1.0, name=None):
    return SimpleNamespace(
        resource_id=resource_id, name=name or resource_id,
        remaining_effort_hours=remaining, available_capacity_hours=capacity,
        allocation_pct=alloc, availability_pct=avail,
    )


def _blocker(blocker_id, *, severity=BlockerSeverity.HIGH, status=BlockerStatus.OPEN,
             raised=None, target=None, resolved=None):
    return SimpleNamespace(
        blocker_id=blocker_id, severity=severity, status=status,
        raised_date=raised, target_resolution_date=target,
        actual_resolution_date=resolved,
    )


def _state(*, blockers=None, sprint_days=14):
    return SimpleNamespace(
        project_info=SimpleNamespace(sprint_duration_days=sprint_days),
        blockers=blockers or [],
    )


# ---- 1. healthy project emits LOW or no observations ---------------------
def test_healthy_project_is_quiet():
    state = _state(blockers=[])
    metrics = _metrics(
        velocity_series=[100.0, 102.0, 101.0, 100.5],  # flat, healthy
        devs=[_dev("R1", alloc=0.6, avail=1.0)],        # load 0.6, not overloaded
        carryover_rate=0.0, total_items=40, completed_sprints=4,
    )
    forecast = _forecast(scope_growth_percent=2.0)      # under 10%
    mc = _mc(0.72)                                       # healthy probability

    cluster = ObservationEngine().run(state, metrics, forecast, mc)

    assert cluster.cluster_severity in ("LOW",)
    # every observation, if any, is LOW band
    eng = ObservationEngine()
    assert all(eng._band(o) == "LOW" for o in cluster.observations)


# ---- 2. critical blocker → at least one HIGH observation -----------------
def test_critical_blocker_emits_high():
    # blocker with a 30-day window on a 14-day sprint → escalation fires
    raised = datetime(2026, 6, 1, tzinfo=timezone.utc)
    target = raised + timedelta(days=30)
    state = _state(
        blockers=[_blocker("BLK-1", severity=BlockerSeverity.CRITICAL,
                           raised=raised, target=target)],
        sprint_days=14,
    )
    metrics = _metrics(velocity_series=[100.0, 100.0], devs=[], total_items=20, completed_sprints=2)
    forecast = _forecast()
    mc = _mc(0.18)  # also drives a HIGH probability observation

    cluster = ObservationEngine().run(state, metrics, forecast, mc)
    eng = ObservationEngine()
    bands = [eng._band(o) for o in cluster.observations]

    assert "HIGH" in bands
    # two HIGH signals (blocker + probability) → cluster escalates to CRITICAL
    assert cluster.cluster_severity in ("HIGH", "CRITICAL")


# ---- 3. cause is ALWAYS None (the hard invariant) ------------------------
def test_no_observation_ever_has_a_cause():
    raised = datetime(2026, 6, 1, tzinfo=timezone.utc)
    state = _state(
        blockers=[_blocker("BLK-1", severity=BlockerSeverity.CRITICAL,
                           raised=raised, target=raised + timedelta(days=40))],
    )
    metrics = _metrics(
        velocity_series=[120.0, 60.0],                  # big drop → velocity anomaly
        devs=[_dev("R1", remaining=200.0, capacity=100.0)],  # load 2.0 → overload
        carryover_rate=8.0, total_items=20, completed_sprints=2,
        # 8 carried / (20/2=10 avg) = 0.8 fraction → carryover anomaly
    )
    forecast = _forecast(scope_growth_percent=25.0)     # scope anomaly
    mc = _mc(0.15)                                       # probability anomaly

    cluster = ObservationEngine().run(state, metrics, forecast, mc)

    assert len(cluster.observations) >= 4  # multiple detectors fired
    for o in cluster.observations:
        assert o.cause is None
    assert cluster.observations != []
    # primary_signal is derived from the cluster; it too must be causeless
    primary = ObservationEngine()._primary_signal(cluster.observations)
    assert primary is not None
    assert primary.cause is None


# ---- 4. probability thresholds map to the right band ---------------------
@pytest.mark.parametrize("otp,expected", [(0.20, "HIGH"), (0.40, "MEDIUM"), (0.70, "LOW")])
def test_probability_significance_bands(otp, expected):
    eng = ObservationEngine()
    obs = eng._detect_probability_anomaly(_mc(otp))
    assert obs, "probability detector should always emit when MC is present"
    assert eng._band(obs[0]) == expected
    assert obs[0].cause is None
