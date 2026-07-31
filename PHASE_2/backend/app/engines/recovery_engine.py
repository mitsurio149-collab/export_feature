"""
EMIOS Stage 16 — RecoveryStateMachine (Phase 5).

A 6-state machine (HEALTHY / WATCH / WARNING / RECOVERY / CRITICAL /
RECOVERED) driven by Monte Carlo on-time probability. Tracks transition
history, surfaces the currently-recommended recovery plan as a short
actionable summary, generates exit KPIs, and states an explicit rollback
trigger.

Adapter note: the spec's pseudocode assumes a `RecoveryPlanResult` with a
`.plans` list of objects carrying a `.recommended` bool and `.actions` with
`.title`/owner fields. The actual Stage 15 adapter in this repo produces
`List[RecoveryPlan]` (dataclass, from app/engines/recovery_plan_engine/models.py)
where the winner is identified by `label == "Recommended"` and each action is
a `Recommendation` with `.title` and `.affected_resource_ids` (resource IDs,
not names). This engine's `evaluate()` accepts that real shape and resolves
owner names via `state.team` when a ProjectState is available.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from app.domain.emios_models import (
    ActiveRecoveryPlan,
    ExitKPI,
    RecoveryStateMachineResult,
    StateTransition,
)
from app.domain.models import BlockerStatus, ProjectState


_URGENCY_MAP = {
    "HEALTHY": "LOW",
    "WATCH": "LOW",
    "WARNING": "MEDIUM",
    "RECOVERY": "HIGH",
    "CRITICAL": "CRITICAL",
    "RECOVERED": "LOW",
}

_MONITORING_MAP = {
    "HEALTHY": "STANDARD",
    "WATCH": "STANDARD",
    "RECOVERED": "STANDARD",
    "WARNING": "ELEVATED",
    "RECOVERY": "INTENSIVE",
    "CRITICAL": "INTENSIVE",
}


def _narrative(state: str, prob: float) -> str:
    if state == "HEALTHY":
        return f"Project is on track ({prob:.0%} probability). Standard monitoring."
    if state == "WATCH":
        return f"Early warning: probability dropped to {prob:.0%}. Monitoring intensified."
    if state == "WARNING":
        return f"At risk ({prob:.0%}). Recovery plan activated — action required this sprint."
    if state == "RECOVERY":
        return f"Active recovery: {prob:.0%} probability. Executing plan — check progress daily."
    if state == "CRITICAL":
        return f"Emergency ({prob:.0%}). All recovery actions must execute immediately."
    if state == "RECOVERED":
        return f"Recovery successful. Probability restored to {prob:.0%}. Maintaining ELEVATED monitoring."
    return f"State {state} ({prob:.0%} probability)."


def _transition_reason(from_state: str, to_state: str, prob: float) -> str:
    return f"On-time probability moved to {prob:.0%}, crossing from {from_state} into {to_state}."


class RecoveryStateMachine:
    """Stage 16: stateful 6-state machine over Monte Carlo probability.
    A single instance persists state/history across calls to evaluate();
    a fresh instance always starts HEALTHY with empty history."""

    def __init__(self):
        self.current_state: str = "HEALTHY"
        self.history: List[StateTransition] = []
        self._consecutive_healthy: int = 0

    def evaluate(
        self,
        monte_carlo,
        risk_result=None,
        recovery_plan_result=None,
        previous_probability: Optional[float] = None,
        state: Optional[ProjectState] = None,
        metrics=None,
    ) -> RecoveryStateMachineResult:
        prob = float(getattr(monte_carlo, "on_time_probability", 0.0) or 0.0)
        prev_state = self.current_state

        new_state = self._next_state(prob, prev_state)

        transition_occurred = new_state != prev_state
        transition_reason = (
            _transition_reason(prev_state, new_state, prob) if transition_occurred else None
        )

        self.current_state = new_state
        if transition_occurred:
            self.history.append(
                StateTransition(
                    from_state=prev_state,
                    to_state=new_state,
                    trigger=transition_reason,
                    probability_at_transition=prob,
                    timestamp=datetime.now(timezone.utc),
                )
            )

        active_plan = self._build_active_plan(new_state, prob, recovery_plan_result, state)
        exit_kpis = self._build_exit_kpis(prob, state, metrics)
        rollback_trigger = self._rollback_trigger(prob, new_state)
        monitoring_intensity = _MONITORING_MAP[new_state]

        return RecoveryStateMachineResult(
            current_state=new_state,
            previous_state=prev_state,
            transition_occurred=transition_occurred,
            transition_reason=transition_reason,
            active_plan=active_plan,
            exit_kpis=exit_kpis,
            rollback_trigger=rollback_trigger,
            monitoring_intensity=monitoring_intensity,
        )

    # ------------------------------------------------------------------
    # State transition
    # ------------------------------------------------------------------

    def _next_state(self, prob: float, prev_state: str) -> str:
        if prob >= 0.65:
            self._consecutive_healthy += 1
            if self._consecutive_healthy >= 2 and prev_state in ("RECOVERY", "CRITICAL", "RECOVERED"):
                return "RECOVERED"
            elif self._consecutive_healthy >= 2:
                return "HEALTHY"
            else:
                return prev_state  # no transition yet — need 2 consecutive healthy reads
        elif prob >= 0.50:
            self._consecutive_healthy = 0
            return "WATCH"
        elif prob >= 0.30:
            self._consecutive_healthy = 0
            return "WARNING"
        elif prob >= 0.15:
            self._consecutive_healthy = 0
            return "RECOVERY"
        else:
            self._consecutive_healthy = 0
            return "CRITICAL"

    # ------------------------------------------------------------------
    # Active plan
    # ------------------------------------------------------------------

    def _build_active_plan(
        self,
        new_state: str,
        prob: float,
        recovery_plan_result,
        state: Optional[ProjectState],
    ) -> ActiveRecoveryPlan:
        recommended = None
        if recovery_plan_result:
            # Real shape: List[RecoveryPlan] (dataclass), label == "Recommended".
            for p in recovery_plan_result:
                if getattr(p, "label", None) == "Recommended":
                    recommended = p
                    break

        if recommended is not None:
            actions_list = list(getattr(recommended, "actions", []) or [])
            actions = [getattr(a, "title", str(a)) for a in actions_list[:3]]
            owner = self._first_owner(actions_list, state)
        else:
            actions = ["No plan available — run analysis first"]
            owner = "Project Manager"

        return ActiveRecoveryPlan(
            actions=actions,
            state_label=new_state,
            urgency=_URGENCY_MAP[new_state],
            owner=owner,
            narrative=_narrative(new_state, prob),
        )

    @staticmethod
    def _first_owner(actions: list, state: Optional[ProjectState]) -> str:
        if not actions:
            return "Project Manager"

        resource_ids = getattr(actions[0], "affected_resource_ids", None) or []
        if not resource_ids or state is None:
            return "Project Manager"

        first_id = resource_ids[0]
        for r in getattr(state, "team", []) or []:
            if getattr(r, "resource_id", None) == first_id:
                return getattr(r, "name", None) or "Project Manager"

        return "Project Manager"

    # ------------------------------------------------------------------
    # Exit KPIs
    # ------------------------------------------------------------------

    def _build_exit_kpis(
        self, prob: float, state: Optional[ProjectState], metrics
    ) -> List[ExitKPI]:
        open_blockers = 0
        if state is not None:
            open_blockers = len(
                [
                    b for b in (getattr(state, "blockers", []) or [])
                    if getattr(b, "status", None) == BlockerStatus.OPEN
                ]
            )

        velocity_trend = (
            getattr(getattr(metrics, "velocity_metrics", None), "velocity_trend_pct", 0.0)
            or 0.0
        )

        return [
            ExitKPI(
                metric="on_time_probability",
                current_value=round(prob, 4),
                target_value=0.65,
                target_by="Next sprint",
                status=(
                    "ON_TRACK" if prob >= 0.50 else "AT_RISK" if prob >= 0.30 else "BREACHED"
                ),
            ),
            ExitKPI(
                metric="open_blockers",
                current_value=float(open_blockers),
                target_value=0.0,
                target_by="Next sprint",
                status="ON_TRACK" if open_blockers == 0 else "AT_RISK",
            ),
            ExitKPI(
                metric="velocity_trend",
                current_value=float(velocity_trend),
                target_value=0.0,
                target_by="Next sprint",
                status="ON_TRACK" if velocity_trend >= 0 else "AT_RISK",
            ),
        ]

    # ------------------------------------------------------------------
    # Rollback trigger
    # ------------------------------------------------------------------

    @staticmethod
    def _rollback_trigger(prob: float, new_state: str) -> str:
        improvement_needed = max(0.05, 0.65 - prob)
        escalate_to = "CRITICAL" if new_state == "RECOVERY" else "WARNING"
        return (
            f"If on-time probability does not improve by "
            f"{improvement_needed:.0%} within 1 sprint, "
            f"escalate to {escalate_to} and re-evaluate the plan."
        )
