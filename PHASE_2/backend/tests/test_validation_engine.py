"""
Tests for the EMIOS ValidationEngine (Stage 2).

Each test builds a real Observation (via ObservationEngine._make so the shape is
authentic) plus a fake ProjectState, then asserts the right artifact is caught
or that a genuine signal passes through.
"""
from types import SimpleNamespace
from datetime import datetime, timedelta

import pytest

from app.engines.validation_engine import ValidationEngine
from app.engines.observation_engine import ObservationEngine
from app.domain.emios_models import ObservationCluster, ArtifactType
from app.domain.models import SprintStatus, WorkItemStatus, BlockerStatus, BlockerSeverity

_ENG = ObservationEngine()


def _velocity_obs(deviation_down=True):
    # current below baseline → negative deviation → DEGRADING velocity
    current, baseline = (60.0, 100.0) if deviation_down else (110.0, 100.0)
    return _ENG._make("velocity", current, baseline, higher_is_better=True)


def _carryover_obs():
    return _ENG._make("carryover_rate", 0.8, 0.20, higher_is_better=False)


def _probability_obs():
    return _ENG._make("on_time_probability", 0.18, 0.65,
                      higher_is_better=True, significance_override="HIGH")


def _blocker_obs(entity_id="BLK-1"):
    return _ENG._make("blocker_delay_days", 30.0, 14.0,
                      higher_is_better=False, entity_id=entity_id)


def _cluster(*observations):
    return ObservationCluster(cluster_id="c-test", observations=list(observations))


def _sprint(name, status, *, number=1, planned=0.0, working_days=10,
            start=None, breakdown=None):
    return SimpleNamespace(
        sprint_name=name, sprint_number=number, status=status,
        planned_velocity_hrs=planned, working_days=working_days,
        start_date=start, capacity_breakdown=breakdown or [],
    )


def _resource(rid, *, daily=8.0, avail=1.0, alloc=1.0):
    return SimpleNamespace(resource_id=rid, daily_capacity_hrs=daily,
                           availability_pct=avail, allocation_pct=alloc)


def _item(item_id, *, status=WorkItemStatus.SPILLOVER, remaining=10.0,
          original="Sprint 1", assigned="Sprint 2"):
    return SimpleNamespace(item_id=item_id, status=status,
                           remaining_effort_hrs=remaining,
                           original_sprint=original, assigned_sprint=assigned)


def _blocker(bid, *, raised, status=BlockerStatus.OPEN):
    return SimpleNamespace(blocker_id=bid, raised_date=raised, status=status,
                           severity=BlockerSeverity.CRITICAL,
                           actual_resolution_date=None)


def _state(*, sprints=None, team=None, work_items=None, blockers=None, sprint_days=14):
    return SimpleNamespace(
        project_info=SimpleNamespace(sprint_duration_days=sprint_days),
        sprints=sprints or [], team=team or [],
        work_items=work_items or [], blockers=blockers or [],
    )


# ---- Artifact 1: PTO capacity reduction suppresses velocity drop ---------
def test_pto_sprint_suppresses_velocity_drop():
    # Current sprint has ~40% of baseline capacity → velocity drop is an artifact.
    completed = _sprint("Sprint 1", SprintStatus.COMPLETED, number=1, planned=400.0)
    current = _sprint("Sprint 2", SprintStatus.IN_PROGRESS, number=2, planned=150.0)
    state = _state(sprints=[completed, current], team=[_resource("R1"), _resource("R2")])

    result = ValidationEngine().run(_cluster(_velocity_obs()), state)

    assert len(result.validated) == 0
    assert len(result.suppressed) == 1
    assert result.suppressed[0].artifact_type == ArtifactType.PLANNED_CAPACITY_REDUCTION
    assert result.data_confidence == 0.0


def test_normal_capacity_velocity_drop_passes_through():
    # Current sprint capacity ~ baseline → velocity drop is REAL, not suppressed.
    completed = _sprint("Sprint 1", SprintStatus.COMPLETED, number=1, planned=400.0)
    current = _sprint("Sprint 2", SprintStatus.IN_PROGRESS, number=2, planned=390.0)
    state = _state(sprints=[completed, current], team=[_resource("R1")])

    result = ValidationEngine().run(_cluster(_velocity_obs()), state)

    assert len(result.validated) == 1
    assert len(result.suppressed) == 0
    assert result.data_confidence == 1.0


# ---- Artifact 2: single outlier item suppresses carryover spike ----------
def test_estimate_outlier_suppresses_carryover():
    # One 300h item vs two 10h items → outlier dominates carryover effort.
    items = [
        _item("WI-BIG", remaining=300.0),
        _item("WI-1", remaining=10.0),
        _item("WI-2", remaining=10.0),
    ]
    state = _state(work_items=items,
                   sprints=[_sprint("S1", SprintStatus.COMPLETED),
                            _sprint("S2", SprintStatus.COMPLETED)])

    result = ValidationEngine().run(_cluster(_carryover_obs()), state)

    assert len(result.suppressed) == 1
    assert result.suppressed[0].artifact_type == ArtifactType.ESTIMATE_OUTLIER


# ---- Artifact 3: thin history suppresses on-time probability -------------
def test_insufficient_history_suppresses_probability():
    # Only 1 completed sprint → probability observation is low-confidence.
    state = _state(sprints=[_sprint("S1", SprintStatus.COMPLETED),
                            _sprint("S2", SprintStatus.IN_PROGRESS)])

    result = ValidationEngine().run(_cluster(_probability_obs()), state)

    assert len(result.suppressed) == 1
    assert result.suppressed[0].artifact_type == ArtifactType.INSUFFICIENT_HISTORY


def test_sufficient_history_keeps_probability():
    state = _state(sprints=[_sprint("S1", SprintStatus.COMPLETED),
                            _sprint("S2", SprintStatus.COMPLETED),
                            _sprint("S3", SprintStatus.IN_PROGRESS)])

    result = ValidationEngine().run(_cluster(_probability_obs()), state)

    assert len(result.validated) == 1
    assert len(result.suppressed) == 0


# ---- Artifact 4: blocker raised this sprint is too early -----------------
def test_early_blocker_suppressed():
    start = datetime(2026, 7, 1)
    current = _sprint("S2", SprintStatus.IN_PROGRESS, number=2, start=start)
    # raised AFTER sprint start → too young
    blk = _blocker("BLK-1", raised=start + timedelta(days=2))
    state = _state(sprints=[_sprint("S1", SprintStatus.COMPLETED), current], blockers=[blk])

    result = ValidationEngine().run(_cluster(_blocker_obs("BLK-1")), state)

    assert len(result.suppressed) == 1
    assert result.suppressed[0].artifact_type == ArtifactType.EARLY_BLOCKER


def test_aged_blocker_passes_through():
    start = datetime(2026, 7, 1)
    current = _sprint("S2", SprintStatus.IN_PROGRESS, number=2, start=start)
    # raised BEFORE sprint start → old enough to assess
    blk = _blocker("BLK-1", raised=start - timedelta(days=20))
    state = _state(sprints=[_sprint("S1", SprintStatus.COMPLETED), current], blockers=[blk])

    result = ValidationEngine().run(_cluster(_blocker_obs("BLK-1")), state)

    assert len(result.validated) == 1
    assert len(result.suppressed) == 0


# ---- data_confidence reflects the validated fraction ---------------------
def test_data_confidence_is_validated_fraction():
    # 1 real (aged blocker) + 1 artifact (thin-history probability).
    start = datetime(2026, 7, 1)
    current = _sprint("S2", SprintStatus.IN_PROGRESS, number=2, start=start)
    blk = _blocker("BLK-1", raised=start - timedelta(days=20))
    # only 1 completed sprint so the probability obs is suppressed
    state = _state(sprints=[_sprint("S1", SprintStatus.COMPLETED), current], blockers=[blk])

    cluster = _cluster(_blocker_obs("BLK-1"), _probability_obs())
    result = ValidationEngine().run(cluster, state)

    assert len(result.validated) == 1
    assert len(result.suppressed) == 1
    assert result.data_confidence == 0.5