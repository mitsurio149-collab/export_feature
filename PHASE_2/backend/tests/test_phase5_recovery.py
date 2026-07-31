"""
tests/test_phase5_recovery.py

Integration tests for Phase 5 / Stage 16: RecoveryStateMachine.

Spec deviation note: the roadmap's TRANSITION LOGIC pseudocode only allows
RECOVERED when prev_state in ("RECOVERY", "RECOVERED"), but the STATE
THRESHOLDS table two paragraphs above it explicitly defines RECOVERED as
"was in RECOVERY/CRITICAL, now probability >= 0.65 for 2+ assessments" --
i.e. CRITICAL should also qualify. That's a genuine contradiction in the
spec, not a case where the pseudocode is more authoritative than the prose
definition. This implementation follows the definition (CRITICAL also
transitions to RECOVERED after recovering), and
test_recovered_requires_two_consecutive_healthy covers the CRITICAL path
to make that choice explicit and testable.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.engines.recovery_engine import RecoveryStateMachine


def _mc(prob: float) -> SimpleNamespace:
    return SimpleNamespace(on_time_probability=prob)


def _recommendation(title: str, resource_ids=None) -> SimpleNamespace:
    return SimpleNamespace(title=title, affected_resource_ids=resource_ids or [])


def _plan(label: str, actions: list) -> SimpleNamespace:
    return SimpleNamespace(label=label, actions=actions)


def _state_with_team(names_and_ids):
    team = [SimpleNamespace(resource_id=rid, name=name) for rid, name in names_and_ids]
    return SimpleNamespace(team=team, blockers=[])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_healthy_state_at_high_probability():
    """A single high-probability read stays in whatever state it started in
    (2 consecutive reads are required to confirm HEALTHY) -- the spec is
    explicit about this. So confirm HEALTHY is reachable with 2 reads."""
    machine = RecoveryStateMachine()
    machine.evaluate(monte_carlo=_mc(0.80))
    result = machine.evaluate(monte_carlo=_mc(0.80))
    assert result.current_state == "HEALTHY"


def test_watch_state_at_medium_probability():
    machine = RecoveryStateMachine()
    result = machine.evaluate(monte_carlo=_mc(0.55))
    assert result.current_state == "WATCH"


def test_warning_state_at_low_probability():
    machine = RecoveryStateMachine()
    result = machine.evaluate(monte_carlo=_mc(0.40))
    assert result.current_state == "WARNING"


def test_recovery_state_at_very_low_probability():
    machine = RecoveryStateMachine()
    result = machine.evaluate(monte_carlo=_mc(0.20))
    assert result.current_state == "RECOVERY"


def test_critical_state_below_015():
    machine = RecoveryStateMachine()
    result = machine.evaluate(monte_carlo=_mc(0.10))
    assert result.current_state == "CRITICAL"


def test_transition_recorded_in_history():
    machine = RecoveryStateMachine()
    machine.evaluate(monte_carlo=_mc(0.80))  # HEALTHY -> WATCH-ish read 1 (still needs 2)
    machine.evaluate(monte_carlo=_mc(0.20))  # -> RECOVERY (transition)
    assert len(machine.history) == 1
    assert machine.history[0].from_state == "HEALTHY"
    assert machine.history[0].to_state == "RECOVERY"
    assert machine.history[0].trigger != ""


def test_recovered_requires_two_consecutive_healthy():
    """From CRITICAL, a single high read must NOT flip straight to RECOVERED
    or HEALTHY -- only after 2 consecutive high reads does it resolve, and
    since prior state was CRITICAL it must resolve to RECOVERED (see module
    docstring for why CRITICAL, not just RECOVERY, qualifies)."""
    machine = RecoveryStateMachine()
    machine.evaluate(monte_carlo=_mc(0.10))  # -> CRITICAL
    mid = machine.evaluate(monte_carlo=_mc(0.80))  # 1st healthy read, no transition yet
    assert mid.current_state == "CRITICAL"
    final = machine.evaluate(monte_carlo=_mc(0.80))  # 2nd consecutive healthy read
    assert final.current_state == "RECOVERED"


def test_exit_kpis_always_three():
    machine = RecoveryStateMachine()
    result = machine.evaluate(monte_carlo=_mc(0.45))
    assert len(result.exit_kpis) == 3
    metrics = {k.metric for k in result.exit_kpis}
    assert metrics == {"on_time_probability", "open_blockers", "velocity_trend"}


def test_rollback_trigger_is_non_empty_string():
    machine = RecoveryStateMachine()
    result = machine.evaluate(monte_carlo=_mc(0.25))
    assert isinstance(result.rollback_trigger, str)
    assert result.rollback_trigger.strip() != ""
    assert any(c.isdigit() for c in result.rollback_trigger)


def test_monitoring_intensity_scales_with_state():
    cases = {
        0.80: "STANDARD",  # HEALTHY (after 2 reads, tested via helper below)
        0.55: "STANDARD",  # WATCH
        0.40: "ELEVATED",  # WARNING
        0.20: "INTENSIVE",  # RECOVERY
        0.10: "INTENSIVE",  # CRITICAL
    }
    for prob, expected in cases.items():
        machine = RecoveryStateMachine()
        if prob == 0.80:
            machine.evaluate(monte_carlo=_mc(prob))
        result = machine.evaluate(monte_carlo=_mc(prob))
        assert result.monitoring_intensity == expected, f"prob={prob}"


def test_null_recovery_plan_handled_gracefully():
    machine = RecoveryStateMachine()
    result = machine.evaluate(monte_carlo=_mc(0.40), recovery_plan_result=None)
    assert result.active_plan.actions == ["No plan available — run analysis first"]
    assert result.active_plan.owner == "Project Manager"


def test_active_plan_uses_recommended_plan_actions():
    state = _state_with_team([("R1", "Alice")])
    actions = [
        _recommendation("Resolve blocker X", resource_ids=["R1"]),
        _recommendation("Reassign item Y"),
    ]
    plans = [
        _plan("Alternative", [_recommendation("Ignore me")]),
        _plan("Recommended", actions),
    ]
    machine = RecoveryStateMachine()
    result = machine.evaluate(
        monte_carlo=_mc(0.40), recovery_plan_result=plans, state=state
    )
    assert result.active_plan.actions[0] == "Resolve blocker X"
    assert result.active_plan.owner == "Alice"


def test_active_plan_urgency_matches_state():
    machine = RecoveryStateMachine()
    result = machine.evaluate(monte_carlo=_mc(0.10))
    assert result.active_plan.urgency == "CRITICAL"
