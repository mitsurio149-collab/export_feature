"""
EMIOS HypothesisEliminator (Stage 5). Popperian falsification; survivors get
Bayesian posteriors normalized to sum 1.0 (the gate).
"""
from __future__ import annotations

from typing import List, Optional

from app.domain.models import ProjectState
from app.domain.emios_models import EvidenceBundle, Hypothesis, HypothesisStatus
from app.engines import cognition_common as cc
from app.engines.hypothesis_generator import (
    hypothesis_category,
    BLOCKER, VELOCITY, SCOPE, CAPACITY, DEPENDENCY, QUALITY, NULL,
)


class HypothesisEliminator:
    """Stage 5: falsify aggressively, update posteriors, normalize survivors."""

    def run(
        self,
        hypotheses: List[Hypothesis],
        bundle: EvidenceBundle,
        state: ProjectState,
        *,
        forecast=None,
        metrics=None,
        monte_carlo=None,
        critical_path=None,
        velocity_artifact_suppressed: bool = False,
    ) -> List[Hypothesis]:
        cp_ids = cc.critical_path_ids(critical_path)
        sprint_days = float(getattr(state.project_info, "sprint_duration_days", 14) or 14)

        survivors: List[Hypothesis] = []
        for h in hypotheses:
            reason = self._elimination_reason(
                h, state, cp_ids, sprint_days,
                forecast=forecast, metrics=metrics, monte_carlo=monte_carlo,
                velocity_artifact_suppressed=velocity_artifact_suppressed,
            )
            if reason is not None:
                h.status = HypothesisStatus.REJECTED
                h.rejection_reason = reason
                h.posterior = 0.0
            else:
                survivors.append(h)

        self._update_posteriors(survivors, bundle)
        for h in survivors:
            h.status = HypothesisStatus.SUPPORTED
        return survivors

    def _elimination_reason(
        self, h, state, cp_ids, sprint_days, *, forecast, metrics, monte_carlo,
        velocity_artifact_suppressed,
    ) -> Optional[str]:
        cat = hypothesis_category(h)

        if cat == BLOCKER:
            blockers = cc.open_blockers(state)
            if not blockers:
                return "no open blockers remain."
            if all(cc.blocker_delay_days(b) < 2.0 for b in blockers):
                return "all open blockers have <2 estimated delay-days."
            if not any(cc.blocker_hits_critical_path(b, cp_ids) for b in blockers):
                return "no open blocker falls on the critical path."
            return None

        if cat == VELOCITY:
            trend = cc.velocity_trend_pct(metrics)
            if trend > 0:
                return f"velocity trend is improving ({trend:+.0f}%)."
            if velocity_artifact_suppressed:
                return "velocity drop was a validated capacity-reduction artifact (PTO)."
            return None

        if cat == SCOPE:
            if cc.scope_growth_percent(forecast) < 5.0:
                return "scope growth <5% of baseline."
            return None

        if cat == CAPACITY:
            if not cc.overloaded_resource_ids(metrics, threshold=cc.OVERLOAD_THRESHOLD):
                return f"no resource exceeds load ratio {cc.OVERLOAD_THRESHOLD}."
            return None

        if cat == DEPENDENCY:
            if not cc.critical_path_blocked_dependencies(state, cp_ids, sprint_days):
                return "no critical-path items have blocked/long-lead dependencies."
            return None

        if cat == QUALITY:
            rework = cc.rework_rate(metrics)
            reopened = cc.reopened_count(metrics)
            if rework < 0.05 and reopened < 2:
                return (f"rework rate {rework:.0%} and {reopened} reopened items "
                        "are below meaningful thresholds.")
            return None

        if cat == NULL:
            otp = cc.on_time_probability(monte_carlo)
            if otp is not None and otp < 0.30:
                return f"on-time probability {otp:.0%} shows the project is clearly at risk."
            return None

        return None

    def _update_posteriors(self, survivors: List[Hypothesis], bundle: EvidenceBundle) -> None:
        if not survivors:
            return
        for h in survivors:
            support = sum(
                (i.weight or 0.0) for i in bundle.items
                if h.hypothesis_id in (i.supports_hypothesis_ids or [])
            )
            contra = sum(
                (i.weight or 0.0) for i in bundle.items
                if h.hypothesis_id in (i.contradicts_hypothesis_ids or [])
            )
            raw = h.prior * (1.0 + support) * (1.0 - min(contra, 0.99))
            h.posterior = max(0.01, min(0.99, raw))

        total = sum(h.posterior for h in survivors)
        if total > 0:
            for h in survivors:
                h.posterior = round(h.posterior / total, 4)

        drift = round(1.0 - sum(h.posterior for h in survivors), 4)
        if abs(drift) >= 0.0001:
            top = max(survivors, key=lambda x: x.posterior)
            top.posterior = round(top.posterior + drift, 4)