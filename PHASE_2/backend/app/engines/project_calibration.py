"""
project_calibration.py
────────────────────────────────────────────────────────────────────────────
Derives every "magic number" used across the engine pipeline from the
project's own completed-sprint history rather than hardcoding it.

Usage
-----
    from app.engines.project_calibration import ProjectCalibration

    cal = ProjectCalibration(project_state)

    # In ForecastEngine / MonteCarloEngine:
    velocity_floor_pct   = cal.velocity_floor_pct        # replaces 0.25
    velocity_std_dev_pct = cal.velocity_std_dev_pct      # replaces 0.15
    work_std_dev_pct     = cal.work_std_dev_pct          # replaces 0.10

    # In simulation applicators:
    split_reduction      = cal.split_effort_reduction     # replaces 0.15
    reassign_gain        = cal.reassign_effort_gain       # replaces 0.03–0.05
    review_gain          = cal.review_effort_gain         # replaces 0.05
    scope_trim           = cal.scope_freeze_trim          # replaces 0.10
    rebalance_gain       = cal.rebalance_effort_gain      # replaces 0.03

    # In RecoveryPlanEngine scorer:
    weights              = cal.plan_score_weights         # replaces fixed 0.45/0.30/0.15/-0.10

The calibration falls back gracefully to the original hardcoded defaults
when fewer than MIN_SPRINTS completed sprints are available, so the
model is always safe to use from sprint 1.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

# Minimum completed sprints required before we trust historical data.
# Below this we fall back to the hardcoded defaults.
MIN_SPRINTS = 2


@dataclass(frozen=True)
class PlanScoreWeights:
    """Composite recovery-plan scoring weights (must sum to 1.0 in magnitude)."""
    probability:  float = 0.45
    delay:        float = 0.30
    risk:         float = 0.15
    complexity:   float = -0.10   # penalty — negative

    def validate(self) -> "PlanScoreWeights":
        total = self.probability + self.delay + self.risk + abs(self.complexity)
        assert abs(total - 1.0) < 0.02, f"Weights don't sum to 1.0: {total}"
        # Hard floor: REBASELINE applicator uses scale = 1 + work_std_dev_pct.
        # If this is 0.0, the applicator is a no-op and the mutation guard fires.
        self.work_std_dev_pct = max(0.05, self.work_std_dev_pct)
        return self


@dataclass
class ProjectCalibration:
    """
    All calibrated constants for a single project, derived from its
    completed-sprint actuals.

    Every attribute has a documented derivation and a hardcoded fallback
    that matches the pre-calibration default.
    """

    # ── Monte Carlo / Forecast ────────────────────────────────────────────────

    velocity_floor_pct: float = 0.35
    """
    Minimum velocity as a fraction of base velocity (velocity floor).
    Derived as: worst completed sprint / average completed sprint velocity,
    after spike-filtering one-off outlier sprints driven by named blockers.
    Fallback: 0.35 (raised from 0.25 — 0.25 allowed near-zero velocity in
    tail simulations, producing an unrealistically wide P95 spread).
    """

    velocity_std_dev_pct: float = 0.15
    """
    Velocity standard deviation as a fraction of mean velocity.
    Derived as: std_dev(completed_sprint_velocities) / mean_velocity.
    Fallback: 0.15 (MonteCarloEngine / SpilloverEngine original).
    """

    work_std_dev_pct: float = 0.10
    """
    Remaining-work uncertainty as a fraction of remaining work.
    Derived as: mean absolute estimation error across completed items,
    normalised by mean estimated effort.
    Fallback: 0.10 (MonteCarloEngine original).
    """

    # ── Simulation applicator effort scalars ─────────────────────────────────

    split_effort_reduction: float = 0.15
    """
    Effort reduction applied when splitting a work item (parallelisation gain).
    Derived as: mean velocity gain in sprints where items were split (carryover→done).
    Fallback: 0.15 (simulation_engine original).
    """

    reassign_effort_gain: float = 0.05
    """
    Allocation bump applied to a receiving resource after reassignment.
    Derived as: mean under-utilisation gap across the team.
    Fallback: 0.05 (simulation_engine original).
    """

    review_effort_gain: float = 0.05
    """
    Effort reduction applied when adding a pair reviewer / review gate.
    Derived as: mean rework ratio from completed items with rework flags.
    Fallback: 0.05 (simulation_engine original).
    """

    scope_freeze_trim: float = 0.10
    """
    Effort trim applied when a scope freeze removes padding.
    Derived as: mean scope inflation % across completed items with scope changes.
    Fallback: 0.10 (simulation_engine / freeze_scope_request original).
    """

    rebalance_effort_gain: float = 0.03
    """
    Velocity bump applied per active sprint when load is rebalanced.
    Derived as: mean velocity delta observed between over- and under-loaded sprints.
    Fallback: 0.03 (simulation_engine original).
    """

    escalation_resolution_pull_days: int = 2
    """
    How many days earlier a blocker is expected to resolve after escalation.
    Derived as: mean(actual_resolution_days - target_resolution_days) for resolved blockers.
    Fallback: 2 days (simulation_engine original).
    """

    # ── Recovery plan scoring weights ────────────────────────────────────────

    plan_score_weights: PlanScoreWeights = field(
        default_factory=lambda: PlanScoreWeights()
    )
    """
    Composite scoring weights for recovery plans.
    Derived as:
      - probability weight  ∝  inverse of historical on-time delivery rate
        (low on-time history → probability matters more)
      - delay weight        ∝  mean observed delay / sprint length
        (frequent delays → delay reduction matters more)
      - risk weight         ∝  historical blocker frequency
      - complexity penalty  = 1 - sum of the above (always a penalty)
    Fallback: 0.45 / 0.30 / 0.15 / -0.10 (plan_scorer.py original).
    """

    # ── Provenance — for logging / explainability ─────────────────────────────

    completed_sprints_used: int = 0
    calibrated: bool = False
    derivation_notes: List[str] = field(default_factory=list)

    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def from_project_state(cls, project_state) -> "ProjectCalibration":
        """
        Primary constructor.  Pass the parsed ProjectState object and get
        back a fully-calibrated (or gracefully-defaulted) ProjectCalibration.
        """
        cal = cls()
        cal._derive(project_state)
        return cal

    def _derive(self, ps) -> None:
        """Derive all constants from ps.actuals + ps.work_items + ps.team + ps.sprints."""

        from app.domain.models import SprintStatus  # avoid circular at module level

        actuals = getattr(ps, "actuals", []) or []
        work_items = getattr(ps, "work_items", []) or []
        team = getattr(ps, "team", []) or []
        sprints = getattr(ps, "sprints", []) or []
        blockers = getattr(ps, "blockers", []) or []

        completed_sprint_actuals = [
            a for a in actuals if getattr(a, "actual_effort_hrs", 0) > 0
        ]
        self.completed_sprints_used = len(completed_sprint_actuals)

        if self.completed_sprints_used < MIN_SPRINTS:
            self.derivation_notes.append(
                f"Only {self.completed_sprints_used} completed sprint(s) — "
                f"using hardcoded defaults (need ≥ {MIN_SPRINTS})."
            )
            return  # keep all defaults

        # ── 1. Velocity floor ─────────────────────────────────────────────────
        velocities = [a.actual_effort_hrs for a in completed_sprint_actuals]
        mean_v = statistics.mean(velocities)
        min_v  = min(velocities)

        if mean_v > 0:
            raw_floor = min_v / mean_v
            # Clamp: never let calibration push floor above 0.60 (too optimistic)
            # or below 0.15 (raised from 0.10 — a single catastrophic sprint
            # from a named one-off event should not drag the floor to near-zero
            # and produce infinite-tail Monte Carlo runs).
            self.velocity_floor_pct = round(max(0.15, min(0.60, raw_floor)), 3)
            self.derivation_notes.append(
                f"velocity_floor_pct={self.velocity_floor_pct:.3f}  "
                f"(min={min_v:.1f}h / mean={mean_v:.1f}h from {len(velocities)} sprints)"
            )

        # ── 2. Velocity std-dev ───────────────────────────────────────────────
        # Spike-filter: exclude sprints whose velocity fell below 40% of the
        # team mean. These are almost always driven by a specific named event
        # (key person absent, critical blocker landed mid-sprint) rather than
        # intrinsic team volatility. Including them in the std-dev inflates the
        # Monte Carlo tail by 2-3x without reflecting typical sprint-to-sprint
        # variance. Excluded sprints are noted in derivation_notes for traceability.
        if len(velocities) >= 2 and mean_v > 0:
            SPIKE_FLOOR = 0.40  # sprints below 40% of mean are one-off spikes
            filtered_velocities = [v for v in velocities if v >= mean_v * SPIKE_FLOOR]
            spike_count = len(velocities) - len(filtered_velocities)

            # Only use the filtered list if it leaves at least 2 data points;
            # otherwise fall back to the full set to avoid a degenerate stdev.
            vel_for_std = filtered_velocities if len(filtered_velocities) >= 2 else velocities

            std_v = statistics.stdev(vel_for_std)
            raw_std_pct = std_v / mean_v
            # Tighten upper cap to 0.30 (was 0.40): beyond 30% std dev the
            # distribution is dominated by one-off events already filtered above.
            self.velocity_std_dev_pct = round(max(0.05, min(0.30, raw_std_pct)), 3)
            self.derivation_notes.append(
                f"velocity_std_dev_pct={self.velocity_std_dev_pct:.3f}  "
                f"(std={std_v:.1f}h / mean={mean_v:.1f}h"
                + (f", {spike_count} spike sprint(s) excluded from std-dev calc)" if spike_count else ")")
            )

        # ── 3. Work (estimation) std-dev ──────────────────────────────────────
        completed_items = [
            wi for wi in work_items
            if getattr(wi, "status", None) is not None
            and wi.status.value in {"Completed", "Done", "COMPLETED"}
            and getattr(wi, "estimated_effort_hrs", 0) > 0
            and getattr(wi, "actual_effort_hrs", 0) > 0
        ]
        if completed_items:
            errors = [
                abs(wi.actual_effort_hrs - wi.estimated_effort_hrs) / wi.estimated_effort_hrs
                for wi in completed_items
                if wi.estimated_effort_hrs > 0
            ]
            if errors:
                raw_work_std = statistics.mean(errors)
                # Small-sample cap: with fewer than 20 completed items the mean
                # absolute error is heavily influenced by a handful of outlier
                # items (rework, scope changes). Cap at 0.15 in this regime —
                # equivalent to saying "we trust estimates to within ±15%",
                # which is standard for mature embedded-software estimation.
                # Above 20 items, allow up to 0.35 (the empirical data is
                # trustworthy enough to justify wider uncertainty).
                SMALL_SAMPLE_THRESHOLD = 20
                upper_cap = 0.15 if len(errors) < SMALL_SAMPLE_THRESHOLD else 0.35
                self.work_std_dev_pct = round(max(0.05, min(upper_cap, raw_work_std)), 3)
                self.derivation_notes.append(
                    f"work_std_dev_pct={self.work_std_dev_pct:.3f}  "
                    f"(mean abs estimation error across {len(errors)} completed items"
                    + (f", capped at {upper_cap} — small sample n<{SMALL_SAMPLE_THRESHOLD})" if len(errors) < SMALL_SAMPLE_THRESHOLD else ")")
                )

        # ── 4. Split effort reduction ─────────────────────────────────────────
        # Proxy: average carryover rate — high carryover → splitting helps more.
        carryover_rates = [
            a.carryover_count / max(1, getattr(a, "planned_item_count", 1))
            for a in completed_sprint_actuals
            if hasattr(a, "carryover_count") and hasattr(a, "planned_item_count")
            and getattr(a, "planned_item_count", 0) > 0
        ]
        if carryover_rates:
            mean_carryover = statistics.mean(carryover_rates)
            # Higher carryover → bigger split benefit (more items in flight)
            # Map [0, 0.5+] → [0.10, 0.25]
            raw_split = 0.10 + min(0.15, mean_carryover * 0.30)
            self.split_effort_reduction = round(raw_split, 3)
            self.derivation_notes.append(
                f"split_effort_reduction={self.split_effort_reduction:.3f}  "
                f"(mean carryover rate={mean_carryover:.2f})"
            )

        # ── 5. Reassign / rebalance gain ──────────────────────────────────────
        if team:
            allocations = [
                getattr(r, "allocation_pct", 1.0) * getattr(r, "availability_pct", 1.0)
                for r in team
            ]
            mean_util = statistics.mean(allocations)
            # Under-utilisation gap — how much headroom the average resource has
            under_util_gap = max(0.0, 1.0 - mean_util)
            raw_reassign = max(0.02, min(0.15, under_util_gap * 0.50))
            self.reassign_effort_gain = round(raw_reassign, 3)
            self.rebalance_effort_gain = round(raw_reassign * 0.60, 3)
            self.derivation_notes.append(
                f"reassign_effort_gain={self.reassign_effort_gain:.3f}  "
                f"rebalance_effort_gain={self.rebalance_effort_gain:.3f}  "
                f"(mean util={mean_util:.2f}, under-util gap={under_util_gap:.2f})"
            )

        # ── 6. Review / pair gain ─────────────────────────────────────────────
        rework_items = [
            wi for wi in work_items
            if getattr(wi, "is_rework", False) or getattr(wi, "rework_count", 0) > 0
        ]
        if work_items:
            rework_rate = len(rework_items) / len(work_items)
            # Higher rework → more value in review gates
            raw_review = max(0.02, min(0.15, rework_rate * 0.50))
            self.review_effort_gain = round(raw_review, 3)
            self.derivation_notes.append(
                f"review_effort_gain={self.review_effort_gain:.3f}  "
                f"(rework rate={rework_rate:.2f}, {len(rework_items)}/{len(work_items)} items)"
            )

        # ── 7. Scope freeze trim ──────────────────────────────────────────────
        scope_changed = [
            wi for wi in work_items
            if getattr(wi, "is_scope_changed", False)
            and getattr(wi, "estimated_effort_hrs", 0) > 0
            and getattr(wi, "original_estimate_hrs", 0) > 0
        ]
        if scope_changed:
            inflation_pcts = [
                (wi.estimated_effort_hrs - wi.original_estimate_hrs) / wi.original_estimate_hrs
                for wi in scope_changed
                if wi.original_estimate_hrs > 0
                and wi.estimated_effort_hrs > wi.original_estimate_hrs
            ]
            if inflation_pcts:
                mean_inflation = statistics.mean(inflation_pcts)
                # Trim = fraction of inflation that a scope freeze can realistically recover
                self.scope_freeze_trim = round(max(0.05, min(0.25, mean_inflation * 0.60)), 3)
                self.derivation_notes.append(
                    f"scope_freeze_trim={self.scope_freeze_trim:.3f}  "
                    f"(mean scope inflation={mean_inflation:.2f} across {len(inflation_pcts)} items)"
                )

        # ── 8. Escalation pull-forward days ───────────────────────────────────
        resolved_blockers = [
            b for b in blockers
            if getattr(b, "actual_resolution_date", None) is not None
            and getattr(b, "target_resolution_date", None) is not None
        ]
        if resolved_blockers:
            overruns = []
            for b in resolved_blockers:
                try:
                    delta = (b.actual_resolution_date - b.target_resolution_date).days
                    if delta > 0:  # only count late resolutions
                        overruns.append(delta)
                except Exception:
                    pass
            if overruns:
                mean_overrun = statistics.mean(overruns)
                # Pull forward by ~40% of the typical overrun
                pull = max(1, min(7, round(mean_overrun * 0.40)))
                self.escalation_resolution_pull_days = pull
                self.derivation_notes.append(
                    f"escalation_resolution_pull_days={pull}  "
                    f"(mean overrun={mean_overrun:.1f}d across {len(overruns)} resolved blockers)"
                )

        # ── 9. Recovery plan scoring weights ─────────────────────────────────
        self.plan_score_weights = self._derive_plan_weights(
            actuals=completed_sprint_actuals,
            blockers=blockers,
            sprints=sprints,
        )

        self.calibrated = True

    def _derive_plan_weights(self, actuals, blockers, sprints) -> PlanScoreWeights:
        """
        Derive composite scoring weights from project health signals:
          - Probability weight increases when on-time delivery history is poor.
          - Delay weight increases when delays are frequent and large.
          - Risk weight increases when blocker frequency is high.
          - Complexity penalty is the residual.
        """
        # On-time delivery rate from actuals
        on_time = sum(
            1 for a in actuals
            if getattr(a, "on_time", None) is True
        )
        on_time_rate = on_time / len(actuals) if actuals else 0.5

        # Mean delay (days late) from actuals
        delays = []
        for a in actuals:
            d = getattr(a, "delay_days", None)
            if d is not None and d > 0:
                delays.append(d)
        mean_delay_normalised = min(1.0, statistics.mean(delays) / 14.0) if delays else 0.3

        # Blocker frequency: blockers per sprint
        blocker_freq = min(1.0, len(blockers) / max(1, len(sprints)))

        # Build weights: each signal inflates its dimension proportionally
        # Base values mirror the original hardcoded defaults.
        # Deviations are bounded to ±0.15 so the model stays stable.
        prob_w   = 0.45 + (0.5 - on_time_rate) * 0.20       # poor history → higher
        delay_w  = 0.30 + mean_delay_normalised * 0.15       # frequent delays → higher
        risk_w   = 0.15 + blocker_freq * 0.10                # many blockers → higher

        # Normalise to sum to 0.90 (leaving 0.10 for the complexity penalty)
        total_pos = prob_w + delay_w + risk_w
        if total_pos > 0:
            scale = 0.90 / total_pos
            prob_w  = round(prob_w  * scale, 3)
            delay_w = round(delay_w * scale, 3)
            risk_w  = round(0.90 - prob_w - delay_w, 3)  # residual avoids rounding drift

        self.derivation_notes.append(
            f"plan_score_weights=({prob_w:.3f}/{delay_w:.3f}/{risk_w:.3f}/-0.10)  "
            f"(on_time_rate={on_time_rate:.2f}, mean_delay_norm={mean_delay_normalised:.2f}, "
            f"blocker_freq={blocker_freq:.2f})"
        )
        return PlanScoreWeights(
            probability=prob_w,
            delay=delay_w,
            risk=risk_w,
            complexity=-0.10,
        )

    # ── Convenience: summary for logging/API ─────────────────────────────────

    def summary(self) -> dict:
        """Return a JSON-serialisable summary of all calibrated values."""
        return {
            "calibrated": self.calibrated,
            "completed_sprints_used": self.completed_sprints_used,
            "velocity_floor_pct": self.velocity_floor_pct,
            "velocity_std_dev_pct": self.velocity_std_dev_pct,
            "work_std_dev_pct": self.work_std_dev_pct,
            "split_effort_reduction": self.split_effort_reduction,
            "reassign_effort_gain": self.reassign_effort_gain,
            "review_effort_gain": self.review_effort_gain,
            "scope_freeze_trim": self.scope_freeze_trim,
            "rebalance_effort_gain": self.rebalance_effort_gain,
            "escalation_resolution_pull_days": self.escalation_resolution_pull_days,
            "plan_score_weights": {
                "probability": self.plan_score_weights.probability,
                "delay": self.plan_score_weights.delay,
                "risk": self.plan_score_weights.risk,
                "complexity": self.plan_score_weights.complexity,
            },
            "derivation_notes": self.derivation_notes,
        }
