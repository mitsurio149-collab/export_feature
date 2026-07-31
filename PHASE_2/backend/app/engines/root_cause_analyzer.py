"""
EMIOS RootCauseAnalyzer (Stage 6). Highest-posterior hypothesis becomes the root
cause with a 5-Whys chain from actual ProjectState data. confidence == root
posterior, so confidence + sum(alternatives) == 1.0.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import uuid4

from app.domain.models import ProjectState
from app.domain.emios_models import Hypothesis, Diagnosis
from app.engines import cognition_common as cc
from app.engines.hypothesis_generator import (
    hypothesis_category,
    BLOCKER, VELOCITY, SCOPE, CAPACITY, DEPENDENCY, QUALITY, NULL,
)

_FISHBONE = {
    BLOCKER: "ENVIRONMENT",
    VELOCITY: "PROCESS",
    SCOPE: "PROCESS",
    CAPACITY: "PEOPLE",
    DEPENDENCY: "ENVIRONMENT",
    QUALITY: "PROCESS",
    NULL: "MEASUREMENT",
}


def _scope_changed_items(state: ProjectState) -> List[str]:
    changed = [
        wi.item_id for wi in getattr(state, "work_items", []) or []
        if getattr(wi, "is_scope_changed", False)
    ]
    if not changed:
        changed = [
            wi.item_id for wi in getattr(state, "work_items", []) or []
            if getattr(wi, "original_sprint", None)
            and getattr(wi, "assigned_sprint", None)
            and wi.original_sprint != wi.assigned_sprint
        ]
    return changed[:3]


class RootCauseAnalyzer:
    """Stage 6: 5-Whys + Fishbone to the deepest actionable cause."""

    def run(
        self,
        survivors: List[Hypothesis],
        state: ProjectState,
        *,
        forecast=None,
        metrics=None,
        monte_carlo=None,
        critical_path=None,
    ) -> Optional[Diagnosis]:
        if not survivors:
            return None
        ordered = sorted(survivors, key=lambda h: h.posterior, reverse=True)
        root = ordered[0]
        alternatives = ordered[1:]
        cat = hypothesis_category(root)
        cp_ids = cc.critical_path_ids(critical_path)
        sprint_days = float(getattr(state.project_info, "sprint_duration_days", 14) or 14)

        chain = self._causal_chain(cat, state, cp_ids, sprint_days, forecast, metrics, monte_carlo)
        actionable = self._actionable(cat, state, cp_ids, forecast, metrics)

        conf = round(root.posterior, 4)
        interval = [round(max(0.01, conf - 0.1), 4), round(min(0.99, conf + 0.1), 4)]

        return Diagnosis(
            diagnosis_id=f"dx-{uuid4().hex[:10]}",
            root_cause=actionable,
            causal_chain=chain,
            confidence=conf,
            confidence_interval=interval,
            contributing_factors=[f"Fishbone category: {_FISHBONE.get(cat, 'PROCESS')}"]
            + [a.statement for a in alternatives if hypothesis_category(a) != NULL],
            alternative_diagnoses=[a.statement for a in alternatives],
            supporting_hypothesis_id=root.hypothesis_id,
        )

    def _causal_chain(self, cat, state, cp_ids, sprint_days, forecast, metrics, monte_carlo) -> List[str]:
        if cat == BLOCKER:
            on_cp = [b for b in cc.open_blockers(state) if cc.blocker_hits_critical_path(b, cp_ids)]
            blockers = on_cp or cc.open_blockers(state)
            b = max(blockers, key=cc.blocker_delay_days) if blockers else None
            if b is not None:
                bid = getattr(b, "blocker_id", "?")
                impacted_list = getattr(b, "impacted_item_ids", []) or [getattr(b, "related_item_id", "?")]
                impacted = ", ".join(impacted_list[:3])
                delay = cc.blocker_delay_days(b)
                return [
                    "Why is the project delayed? The forecast shows added delay-days.",
                    f"Why the added days? Blocker {bid} is unresolved (~{delay:.0f} delay-days).",
                    f"Why does it hurt the schedule? It impacts critical-path item(s): {impacted}.",
                    "Why not absorbed? Those items have zero slack on the critical path.",
                    f"Root: {bid} must be resolved/mitigated to recover the schedule.",
                ]
        if cat == VELOCITY:
            trend = cc.velocity_trend_pct(metrics)
            series = cc.velocity_series(metrics)
            last = series[-1] if series else 0.0
            return [
                "Why is the project delayed? Remaining work won't finish at the current pace.",
                f"Why won't it finish? Velocity trend is {trend:.0f}% (declining).",
                f"Why declining? Recent sprint throughput ({last:.0f} hrs) fell below the trailing mean.",
                "Why lower throughput? A sustained slowdown, not a one-off capacity dip.",
                "Root: recover per-sprint velocity (unblock, refocus, or rebalance load).",
            ]
        if cat == SCOPE:
            pct = cc.scope_growth_percent(forecast)
            changed = _scope_changed_items(state)
            return [
                "Why is the project delayed? Total effort exceeds the baseline plan.",
                f"Why more effort? Scope grew {pct:.0f}% over baseline.",
                f"Why did scope grow? Items expanded/added after baseline: {', '.join(changed) or 'multiple items'}.",
                "Why not re-planned? The added effort was not offset by scope cuts or added capacity.",
                "Root: re-baseline scope or add capacity to cover the growth.",
            ]
        if cat == CAPACITY:
            over = cc.overloaded_resource_ids(metrics, threshold=cc.OVERLOAD_THRESHOLD)
            names = ", ".join(over[:3])
            return [
                "Why is the project delayed? Some work streams are progressing slowly.",
                f"Why slowly? Resources are over-allocated: {names or 'one or more resources'}.",
                "Why over-allocated? Peak sprint load exceeds their available capacity.",
                "Why not rebalanced? Load was not redistributed to resources with slack.",
                "Root: rebalance load or add capacity for the overloaded resources.",
            ]
        if cat == DEPENDENCY:
            deps = cc.critical_path_dependencies_over_lag(state, cp_ids, sprint_days)
            dep = deps[0] if deps else None
            pair = (
                f"{getattr(dep, 'predecessor_item_id', '?')} -> {getattr(dep, 'successor_item_id', '?')}"
                if dep else "a critical-path dependency"
            )
            lag = getattr(dep, "lag_days", 0) if dep else 0
            return [
                "Why is the project delayed? Critical-path items can't start on time.",
                f"Why can't they start? Dependency {pair} carries {lag}-day lead time.",
                f"Why does that matter? The lead time exceeds a sprint ({sprint_days:.0f} days).",
                "Why not parallelized? The dependency is finish-to-start on the critical path.",
                "Root: shorten/parallelize the dependency or start the predecessor earlier.",
            ]
        if cat == QUALITY:
            rework = cc.rework_rate(metrics)
            reopened = cc.reopened_count(metrics)
            return [
                "Why is the project delayed? Completed work is being reopened.",
                f"Why reopened? Rework rate is {rework:.0%} ({reopened} items).",
                "Why rework? Quality shortcuts under schedule pressure or unclear acceptance criteria.",
                "Why not caught earlier? Review gates insufficient or rushed under velocity pressure.",
                "Root: add review checkpoints; address root acceptance-criteria gaps before sprint end.",
            ]
        otp = cc.on_time_probability(monte_carlo)
        otp_txt = ("%.0f%%" % (otp * 100)) if otp is not None else "healthy"
        return [
            "Why any concern? Some signals deviated from baseline.",
            f"Why not alarming? On-time probability remains {otp_txt}.",
            "Why noise? No single driver dominates the forecast delay.",
            "Why hold course? Deviations are within normal sprint-to-sprint variance.",
            "Root: no systemic cause; continue monitoring.",
        ]

    def _actionable(self, cat, state, cp_ids, forecast, metrics) -> str:
        if cat == BLOCKER:
            on_cp = [b for b in cc.open_blockers(state) if cc.blocker_hits_critical_path(b, cp_ids)]
            blockers = on_cp or cc.open_blockers(state)
            if blockers:
                b = max(blockers, key=cc.blocker_delay_days)
                return (f"Blocker {getattr(b, 'blocker_id', '?')} on the critical path is the root cause. "
                        f"Resolve or mitigate it to recover roughly {cc.blocker_delay_days(b):.0f} delay-days.")
        if cat == VELOCITY:
            return ("A systematic velocity slowdown is the root cause. "
                    "Restore per-sprint throughput before committing to the current date.")
        if cat == SCOPE:
            return (f"Scope growth of {cc.scope_growth_percent(forecast):.0f}% over baseline is the root cause. "
                    "Re-baseline scope or add capacity to cover it.")
        if cat == CAPACITY:
            over = cc.overloaded_resource_ids(metrics, threshold=cc.OVERLOAD_THRESHOLD)
            names = ", ".join(over[:3])
            return (f"Resource over-allocation ({names or 'one or more resources'}) is the root cause. "
                    "Rebalance load or add capacity.")
        if cat == DEPENDENCY:
            return ("A long-lead dependency on the critical path is the root cause. "
                    "Shorten, parallelize, or start the predecessor earlier.")
        if cat == QUALITY:
            rework = cc.rework_rate(metrics)
            reopened = cc.reopened_count(metrics)
            return (f"Rework is consuming capacity ({rework:.0%} rate, {reopened} reopened items). "
                    "Add review gates and clarify acceptance criteria to stop the leak.")
        return ("No systemic root cause found; the project is on track. "
                "Continue monitoring the deviating signals.")