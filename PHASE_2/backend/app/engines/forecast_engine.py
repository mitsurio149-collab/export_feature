"""
Forecast Engine (deterministic)

Produces a single-point forecast based on remaining effort, current velocity,
critical-path sequencing, spillover, and blocker impacts. No Monte Carlo,
no probabilities.
"""
from datetime import datetime, timedelta
import re
import difflib
from typing import Optional, List, Dict, Any

from app.domain.models import ProjectState, SprintStatus
from app.engines.metrics_engine import ProjectMetrics
from app.engines.critical_path_engine import CriticalPathResult
from app.engines.spillover_engine import SpilloverAnalysis
from app.api.models_phase3 import (
    ForecastResult,
    ForecastDelayBreakdown,
    ForecastScheduleDiagnostics,
    ForecastEffortBreakdown,
    ForecastConfidence,
    ForecastDriver,
    ForecastEvidence,
    ForecastAssumptions,
    ForecastExplanation,
    ForecastSteeringDriver,
    ForecastSteeringBlocker,
    ForecastSteeringOverload,
    ForecastSteeringBrief,
)


from app.engines.project_calibration import ProjectCalibration
from app.engines import cognition_common as cc
from app.core import working_calendar


def classify_schedule_variance(days: float) -> str:
    """Return the human-readable sign category for schedule variance.

    Backend convention: positive means late, negative means ahead, zero is on target.
    """
    if days > 0.05:
        return "late"
    if days < -0.05:
        return "ahead"
    return "on_target"


def _normalize_name(name: str) -> str:
    """Lowercase, strip punctuation/initials-dots, collapse whitespace, so
    'M. Balasubramanian' and 'Meena Balasubramanian' compare fairly."""
    if not name:
        return ""
    cleaned = re.sub(r"[.\-_]", " ", name.strip().lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _names_match(a: str, b: str) -> bool:
    """Owner names across sheets (Blockers vs Team) are free text and can differ
    in formatting even when they refer to the same person. Exact string
    equality silently fails on 'M. Balasubramanian' vs 'Meena Balasubramanian'
    or a stray trailing space -- this is what caused the blocker-owner /
    overloaded-resource cross-reference to be fragile. Match on: exact
    normalized string, one being a token-subset of the other (handles initials
    and missing middle names), or a high fuzzy-similarity ratio as a fallback."""
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    tokens_a, tokens_b = set(na.split()), set(nb.split())
    # Drop single-letter tokens (initials) from the subset check so "M" vs
    # "Meena" doesn't force a match on initials alone, but real name tokens do.
    real_a = {t for t in tokens_a if len(t) > 1}
    real_b = {t for t in tokens_b if len(t) > 1}
    if real_a and real_b and (real_a <= tokens_b or real_b <= tokens_a):
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.85


class ForecastEngine:
    """Deterministic forecast engine.

    High-level approach:
    - Use remaining effort (sum of remaining_effort_hrs) as the work to schedule.
    - Adjust for dependency sequencing by ensuring remaining work is at least
      the critical path duration (hours) — this captures serialisation delays.
    - Add spillover-induced extra work (predicted_spillover_count * avg_item_effort).
    - Project velocity = historical avg velocity per sprint adjusted for active
      blocker impact (velocity reduction factor). No randomness.
    - Compute remaining_sprints = adjusted_remaining_effort / projected_velocity
      and convert to days using project sprint length.
    - Return a single expected finish date (now + days) and derived fields.
    """

    def __init__(
        self,
        project_state: ProjectState,
        metrics: ProjectMetrics,
        cp_result: CriticalPathResult,
        spillover: Optional[SpilloverAnalysis] = None,
    ):
        self.project_state = project_state
        self.metrics = metrics
        self.cp_result = cp_result
        self.spillover = spillover

    def calculate(self) -> ForecastResult:
        _cal = ProjectCalibration.from_project_state(self.project_state)
        """Calculate deterministic forecast and return ForecastResult."""

        remaining_effort = float(self.metrics.remaining_effort_hours)
        cp_remaining_hours = float(getattr(self.cp_result, "critical_path_remaining_hours", 0.0) or 0.0)
        adjusted_remaining = max(remaining_effort, cp_remaining_hours)

        avg_item_effort = float(getattr(self.metrics, "average_item_effort", 20.0) or 20.0)
        spillover_hours = 0.0
        _vb = getattr(self.metrics, "velocity_baseline", None)
        base_velocity = float(_vb.trimmed_avg_hrs if _vb else self.metrics.actual_avg_velocity)
        predicted_spillover_items = 0.0
        if self.spillover:
            try:
                total_spill = sum(self.spillover.predicted_spillover_by_sprint.values())
                predicted_spillover_items = float(total_spill)
                spillover_hours = float(total_spill) * avg_item_effort
            except Exception:
                predicted_spillover_items = 0.0
                spillover_hours = 0.0

        # Prefer the canonical VelocityBaseline if available.
        # Fall back to actual_avg_velocity for backward compatibility.
        _vb = getattr(self.metrics, "velocity_baseline", None)
        base_velocity = float(_vb.trimmed_avg_hrs if _vb else self.metrics.actual_avg_velocity)
        if not base_velocity:
            base_velocity = float(
                getattr(self.metrics, "effective_project_velocity", 0.0)
                or self.metrics.planned_total_velocity
                or 1.0
            )
        # NOTE: actual_avg_velocity (empirical, from historical SprintActual records) is
        # preferred over effective_project_velocity (theoretical, capacity-based estimate)
        # so this deterministic forecast agrees with MonteCarloEngine, which uses the same
        # preference order. Do not swap this back without also updating monte_carlo_engine.py --
        # the two engines disagreeing on which velocity to trust is what caused expected_delay_days
        # and on_time_probability to contradict each other for projects where the two velocity
        # figures diverge significantly (e.g. team is not operating near theoretical capacity).
        # effective_project_velocity is still used as a fallback for brand-new projects with no
        # completed sprints yet, where there is no historical data to compute actual_avg_velocity from.
        blocker_impact = float(getattr(self.metrics, "estimated_blocker_velocity_impact", 0.0) or 0.0)

        sprint_days = float(self.project_state.project_info.sprint_duration_days or 14)
        # If future sprints have zero planned velocity (workbook leaves them empty),
        # substitute historical average velocity for those sprints when estimating
        # the effective remaining sprint capacity. Apply only to in-progress and
        # not-started sprints (do not alter completed sprints).
        try:
            remaining_sprints = [
                s for s in self.project_state.sprints
                if s.status in (SprintStatus.IN_PROGRESS, SprintStatus.NOT_STARTED)
            ]
            if remaining_sprints:
                per_sprint_caps = [
                    (
                        (s.planned_velocity_hrs if getattr(s, 'planned_velocity_hrs', 0.0) and s.planned_velocity_hrs > 0 else float(base_velocity or 0.0))
                        + s.simulation_capacity_hrs()  # cross_train_backup / swarm_item write capacity here — must be counted or those actions have no forecast effect
                    )
                    for s in remaining_sprints
                ]
                avg_remaining_planned_velocity = sum(per_sprint_caps) / len(per_sprint_caps) if per_sprint_caps else 0.0
                # Prefer a non-zero average remaining planned velocity when computing base velocity
                if avg_remaining_planned_velocity > 0:
                    base_velocity = max(base_velocity, avg_remaining_planned_velocity)
        except Exception:
            pass

        # ── Stall detection: apply velocity floor when in-progress sprint shows
        # no throughput yet. The historical actual_avg_velocity only reflects
        # COMPLETED sprints. An in-progress sprint with zero hours logged looks
        # identical to a healthy one — the stall is invisible to the average.
        #
        # Design principle (shared with MonteCarloEngine._compute_stall_factor):
        #   - When the in-progress sprint has recorded SOME work, we blend the
        #     current pace with historical to get a nuanced signal.
        #   - When the sprint has recorded ZERO work but >= 30% of its window
        #     has elapsed (including overrun), we DON'T blend 0×0.5 + hist×0.5
        #     because that gives 0.5× for a sprint that is merely late to log
        #     hours — an artefact of data entry, not necessarily zero delivery.
        #     Instead we apply the calibrated velocity_floor_pct directly.
        #     This is identical to what MonteCarloEngine does so both engines
        #     agree on the "stalled but logging lag" scenario.
        #   - We NEVER reduce below velocity_floor_pct — that is already priced
        #     into the risk model as the absolute worst case.
        #   - We NEVER inflate base_velocity from a fast current sprint, to
        #     avoid hiding structural risk behind one good week.
        #
        # SYNC CONTRACT: MonteCarloEngine._compute_stall_factor must mirror this
        # logic exactly. If you change the blend weight or floor here, update MC.
        try:
            as_of_stall = self.project_state.project_info.effective_as_of_date()
            in_progress_sprints = [
                s for s in self.project_state.sprints
                if s.status in (SprintStatus.IN_PROGRESS,)
            ]
            if in_progress_sprints and base_velocity > 0:
                ip_sprint = in_progress_sprints[0]
                sprint_start = ip_sprint.start_date
                sprint_end = ip_sprint.end_date
                sprint_window = max(1.0, (sprint_end - sprint_start).total_seconds() / 86400.0)
                elapsed_in_sprint = max(0.0, (as_of_stall - sprint_start).total_seconds() / 86400.0)
                fraction_elapsed = min(1.0, elapsed_in_sprint / sprint_window)

                if fraction_elapsed >= 0.30:
                    actuals_by_id = {a.sprint_id: a for a in self.project_state.actuals}
                    actual_rec = actuals_by_id.get(ip_sprint.sprint_id)
                    actual_so_far = float(actual_rec.actual_effort_hrs) if actual_rec else 0.0

                    if actual_so_far > 0:
                        # Some work logged — project current pace to full sprint length
                        # and blend 50/50 with historical (single sprint is noisy).
                        projected_full_sprint_velocity = actual_so_far / fraction_elapsed
                        if projected_full_sprint_velocity < base_velocity:
                            stall_adjusted = max(
                                0.5 * projected_full_sprint_velocity + 0.5 * base_velocity,
                                base_velocity * _cal.velocity_floor_pct,
                            )
                            base_velocity = stall_adjusted
                    else:
                        # Zero hours logged and sprint is >= 30% elapsed (or overrun).
                        # Could be a logging lag, a genuine blocker freeze, or both.
                        # We cannot distinguish, so apply the calibrated floor directly —
                        # this is the same signal MonteCarloEngine uses so the two
                        # engines agree rather than diverging by 1.86×.
                        base_velocity = base_velocity * _cal.velocity_floor_pct
        except Exception:
            pass  # stall detection is advisory — never crash the core forecast

        # Compute velocity_without_spillover AFTER the substitution above settles base_velocity --
        # otherwise this and base_schedule_days below are derived from two different base_velocity
        # values, and their difference gets mislabeled as blocker-caused delay when it is really
        # just the sprint-velocity-substitution effect (reproducible even when blocker_impact == 0).
        velocity_without_spillover = max(base_velocity * (1.0 - blocker_impact), base_velocity * _cal.velocity_floor_pct)
        base_schedule_days = (adjusted_remaining / base_velocity) * sprint_days if base_velocity > 0 else 0.0
        days_without_spillover = (
            (adjusted_remaining / velocity_without_spillover) * sprint_days
            if velocity_without_spillover > 0 else 0.0
        )

        spillover_penalty_days = (
            (spillover_hours / velocity_without_spillover) * sprint_days
            if velocity_without_spillover > 0 else 0.0
        )
        spillover_fraction = (
            min(0.4, spillover_penalty_days / max(1.0, days_without_spillover))
            if days_without_spillover > 0 else 0.0
        )
        projected_velocity = max(
            base_velocity * (1.0 - blocker_impact) * (1.0 - spillover_fraction * 0.5),
            base_velocity * _cal.velocity_floor_pct,
        )
        remaining_days_blocker_loss = max(0.0, days_without_spillover - base_schedule_days)
        raw_remaining_days = (adjusted_remaining / projected_velocity) * sprint_days if projected_velocity > 0 else 0.0
        spillover_delay_days = max(0.0, raw_remaining_days - days_without_spillover)
        remaining_days_base_work = base_schedule_days
        remaining_days_total = base_schedule_days + remaining_days_blocker_loss + spillover_delay_days
        velocity_floor = base_velocity * _cal.velocity_floor_pct
        velocity_floor_saturated_by_blockers = bool(velocity_without_spillover <= velocity_floor + 1e-6 and spillover_hours > 0.0)

        cp_remaining_days = 0.0
        if cp_remaining_hours > remaining_effort and base_velocity > 0:
            cp_remaining_days = ((cp_remaining_hours - remaining_effort) / base_velocity) * sprint_days
        spillover_days_diag = spillover_delay_days
        blocker_days_diag = remaining_days_blocker_loss
        diagnostic_total = base_schedule_days + cp_remaining_days + spillover_days_diag + blocker_days_diag

        project_start = self.project_state.project_info.forecast_anchor_date()
        as_of = self.project_state.project_info.effective_as_of_date()
        days_elapsed_raw = self._calculate_schedule_elapsed_days(sprint_days)

        # Diagnostic-only: what the OLD status-label-based method would have
        # said, and the gap between that and real elapsed time. This is the
        # "Calendar Variance" KPI -- it's what would have caught the Sprint
        # 6/7/8 stall immediately instead of relying on the effort/velocity
        # math to eventually notice. Always uses the TRUE (uncapped) elapsed
        # time -- see days_elapsed capping note below -- because this
        # diagnostic exists specifically to surface wall-clock/status drift
        # for in-progress projects and must not be masked by the completion
        # cap applied to the delay math.
        status_derived_elapsed_days = self._status_derived_elapsed_days(sprint_days)
        calendar_variance_days = float(round(days_elapsed_raw - status_derived_elapsed_days, 2))

        # National holidays (Republic Day, Independence Day, Gandhi Jayanti) are
        # irregular and can't already be priced into the velocity average the way
        # recurring weekly weekends are (see working_calendar module docstring),
        # so they're added as explicit extra non-working days on top of the
        # existing calendar-day math.
        #
        # IMPORTANT: pad only the REMAINING window (as_of -> finish), not the
        # whole project_start -> finish span. days_elapsed is now real elapsed
        # calendar time (see _calculate_schedule_elapsed_days), so any holidays
        # that already happened in the past are already correctly included in
        # that real day count -- re-padding them here would double-count them.
        # Only *future* holidays, between today and the projected finish, are
        # genuinely extra non-working time the remaining-effort math doesn't
        # already know about.
        #
        # Saturdays/Sundays are deliberately NOT added here even though the
        # user-facing ask is "treat weekends as non-working": remaining_days_total
        # is derived from a velocity computed as (daily_capacity_hrs * sprint.working_days),
        # then converted back to calendar days via sprint_days -- so the
        # calendar-day multiplier already spans the weekend days that sit
        # inside that ratio. Explicitly padding weekends on top of that would
        # double-count them and make the forecast unrealistically pessimistic
        # in the opposite direction. Weekend non-working time IS made explicit
        # and visible below via `non_working_days_in_remaining_window`, so
        # managers can see it -- it's just not added a second time into the
        # finish-date arithmetic where it's already priced in.
        holiday_padding_days = 0
        finish_candidate = as_of + timedelta(days=remaining_days_total)
        for _ in range(5):
            holidays_in_range = working_calendar.count_holidays_between(as_of, finish_candidate)
            new_finish = as_of + timedelta(days=remaining_days_total + holidays_in_range)
            if new_finish == finish_candidate:
                holiday_padding_days = holidays_in_range
                break
            finish_candidate = new_finish
            holiday_padding_days = holidays_in_range
        expected_finish = finish_candidate

        # Informational only (not added into expected_finish/expected_delay_days,
        # see note above) -- total non-working calendar days, weekends included,
        # sitting inside the remaining window. Lets a PM see "of the N remaining
        # calendar days, M are weekends/holidays" without corrupting the math.
        non_working_days_in_remaining_window = working_calendar.count_non_working_days_between(
            as_of, finish_candidate
        )

        target_end_date = self.project_state.project_info.target_end_date
        planned_window_days = float((target_end_date - project_start).days)

        # ── Completion-aware elapsed-time cap ──────────────────────────────
        # MODEL GAP: neither WorkItem nor ProjectState records the actual
        # calendar date remaining effort reached zero (no
        # `actual_completion_date` field exists anywhere in the domain
        # model -- see forensic audit). So when a project has no remaining
        # work (adjusted_remaining <= 0), days_elapsed_raw (real elapsed
        # calendar time to the wall-clock "today") is NOT a valid proxy for
        # "time actually consumed by this project" -- it just keeps growing
        # with however long ago the work happened to finish, indefinitely,
        # with no bound, for every day a report is run after the fact.
        #
        # We do not invent a completion date (e.g. guessing the last
        # sprint's end_date, which was explicitly rejected -- a sprint can
        # still be marked IN_PROGRESS in the workbook after all its items
        # are done, and using it would silently assert information we don't
        # have). Instead we bring days_elapsed into line with the rest of
        # this formula's own completed-project behavior: remaining_days_total,
        # spillover_delay_days, and remaining_days_blocker_loss are already
        # correctly 0 once nothing remains (they are all derived from
        # adjusted_remaining). days_elapsed is the one term in
        # expected_delay_raw that is NOT effort-derived -- it is a bare
        # wall-clock subtraction -- which is why it was the only term still
        # growing without bound. Capping it at planned_window_days makes it
        # consistent with those other terms: once nothing remains, we do not
        # manufacture additional schedule delay from calendar time we cannot
        # attribute to this project with the data actually available.
        #
        # Known, explicit limitation of this fallback: a project that
        # genuinely finished LATE (e.g. completed two sprints past its
        # target) will not show that historical lateness once
        # remaining_effort_hours reaches 0, because the model has no actual-
        # completion-date evidence to compute it from. Capturing that
        # correctly requires adding an actual-completion-date field to the
        # domain model -- out of scope for this fix, which only removes the
        # unbounded runaway growth, and does not claim to reconstruct
        # historical lateness that the data doesn't record.
        if adjusted_remaining <= 0.0:
            days_elapsed = min(days_elapsed_raw, planned_window_days)
        else:
            days_elapsed = days_elapsed_raw

        expected_delay_raw = days_elapsed + remaining_days_total + holiday_padding_days - planned_window_days
        expected_delay_days = float(round(expected_delay_raw, 2))
        on_track = expected_delay_days <= 0

        total_effort = float(getattr(self.metrics, "total_effort_hours", 0.0) or 0.0)
        completion_pct = (
            max(0.0, min(1.0, (total_effort - remaining_effort) / total_effort))
            if total_effort > 0 else 0.0
        )

        scope_growth_hours = float(
            sum(max(0.0, wi.current_estimate_hrs - wi.estimated_effort_hrs) for wi in self.project_state.work_items)
        )
        scope_growth_percent = float(round((scope_growth_hours / total_effort * 100.0) if total_effort > 0 else 0.0, 2))
        projected_velocity_per_day = float(projected_velocity / sprint_days if sprint_days > 0 else 0.0)
        scope_impact_days = float(round(scope_growth_hours / projected_velocity_per_day, 2)) if projected_velocity_per_day > 0 else 0.0

        blocker_penalty_hours_calc = (
            remaining_days_blocker_loss * (velocity_without_spillover / sprint_days)
            if sprint_days > 0 else 0.0
        )
        blocker_penalty_hours_final = min(float(adjusted_remaining), max(0.0, blocker_penalty_hours_calc))

        scope_growth_message = (
            f"Scope growth contributes {scope_impact_days:.1f} days to the forecast."
            if scope_growth_hours > 0 else "Scope growth is not material to the forecast."
        )
        if velocity_floor_saturated_by_blockers:
            spillover_message = (
                f"Spillover is present, but blockers already reduce velocity to the floor level."
            )
        elif spillover_delay_days > 0:
            spillover_message = f"Spillover adds approximately {spillover_delay_days:.1f} days to the forecast."
        else:
            spillover_message = "No material spillover delay is projected."

        delay_breakdown = ForecastDelayBreakdown(
            planned_window_days=float(round(planned_window_days, 2)),
            days_elapsed=float(round(days_elapsed, 2)),
            remaining_days_total=float(round(remaining_days_total, 2)),
            remaining_days_base_work=float(round(remaining_days_base_work, 2)),
            remaining_days_spillover=float(round(spillover_delay_days, 2)),
            remaining_days_blocker_loss=float(round(remaining_days_blocker_loss, 2)),
            remaining_days_holidays=float(round(holiday_padding_days, 2)),
            expected_delay_days=float(round(days_elapsed + remaining_days_total + holiday_padding_days - planned_window_days, 2)),
        )
        schedule_diagnostics = ForecastScheduleDiagnostics(
            is_additive=False,
            base_schedule_days=float(round(base_schedule_days, 2)),
            spillover_days=float(round(spillover_days_diag, 2)),
            blocker_days=float(round(blocker_days_diag, 2)),
            critical_path_days=float(round(cp_remaining_days, 2)),
            diagnostic_total_days=float(round(diagnostic_total, 2)),
            velocity_floor_saturated_by_blockers=velocity_floor_saturated_by_blockers,
            spillover_message=spillover_message,
            real_elapsed_days=float(round(days_elapsed_raw, 2)),
            status_derived_elapsed_days=float(round(status_derived_elapsed_days, 2)),
            calendar_variance_days=calendar_variance_days,
            non_working_days_in_remaining_window=int(non_working_days_in_remaining_window),
        )
        effort_breakdown = ForecastEffortBreakdown(
            raw_remaining_effort_hours=float(round(remaining_effort, 2)),
            critical_path_remaining_hours=float(round(cp_remaining_hours, 2)),
            spillover_penalty_hours=float(round(spillover_hours, 2)),
            blocker_penalty_hours=float(round(blocker_penalty_hours_final, 2)),
            forecast_adjusted_effort_hours=float(round(adjusted_remaining, 2)),
        )

        confidence = self._build_confidence()
        steering_brief = self._build_steering_brief(
            expected_delay_days=expected_delay_days,
            expected_finish=expected_finish,
            target_end_date=target_end_date,
            completion_pct=completion_pct,
            days_elapsed=days_elapsed,
            remaining_days_base_work=remaining_days_base_work,
            planned_window_days=planned_window_days,
            remaining_days_blocker_loss=remaining_days_blocker_loss,
            spillover_delay_days=spillover_delay_days,
            spillover_penalty_hours=spillover_hours,
            projected_velocity_per_day=projected_velocity_per_day,
            velocity_floor_saturated_by_blockers=velocity_floor_saturated_by_blockers,
            scope_growth_percent=scope_growth_percent,
            scope_impact_days=scope_impact_days,
            sprint_days=sprint_days,
            confidence_level=confidence.confidence_level,
            velocity_std_dev_pct=_cal.velocity_std_dev_pct,
            holiday_padding_days=holiday_padding_days,
        )
        forecast_drivers = self._build_forecast_drivers(
            scope_impact_days=scope_impact_days,
            remaining_days_blocker_loss=remaining_days_blocker_loss,
            cp_remaining_days=cp_remaining_days,
            spillover_delay_days=spillover_delay_days,
            remaining_days_base_work=remaining_days_base_work,
        )
        forecast_evidence = self._build_forecast_evidence()
        assumptions = self._build_assumptions()
        explanation = self._build_explanation(expected_delay_days, confidence, forecast_drivers)

        return ForecastResult(
            target_end_date=target_end_date,
            expected_finish_date=expected_finish,
            expected_delay_days=float(round(expected_delay_days, 2)),
            remaining_effort_hours=adjusted_remaining,
            completion_percentage=completion_pct,
            projected_velocity=projected_velocity,
            on_track=on_track,
            raw_remaining_effort_hours=remaining_effort,
            critical_path_remaining_hours=cp_remaining_hours,
            predicted_spillover_items=predicted_spillover_items,
            spillover_delay_days=float(round(spillover_delay_days, 2)),
            spillover_penalty_hours=spillover_hours,
            blocker_penalty_hours=float(round(blocker_penalty_hours_final, 2)),
            forecast_adjusted_effort_hours=adjusted_remaining,
            scope_growth_hours=float(round(scope_growth_hours, 2)),
            scope_growth_percent=scope_growth_percent,
            scope_impact_days=scope_impact_days,
            scope_growth_message=scope_growth_message,
            delay_breakdown=delay_breakdown,
            schedule_diagnostics=schedule_diagnostics,
            effort_breakdown=effort_breakdown,
            confidence=confidence,
            forecast_drivers=forecast_drivers,
            forecast_evidence=forecast_evidence,
            forecast_assumptions=assumptions,
            forecast_explanation=explanation,
            forecast_vs_montecarlo_note=(
                "You'll see two different numbers on this dashboard: an on-time probability "
                "and a delay estimate in days. They can look like they disagree, but they're "
                "answering two different questions. The delay estimate assumes a tougher, "
                "pessimistic scenario — that open blockers and predicted spillover hit at full "
                "strength. The on-time probability instead looks across a wide range of "
                "possible outcomes, including better-case ones, and reports how often the "
                "project finishes on time across that range. So it's normal for the delay "
                "figure to look worse than the probability suggests — one is a cautious "
                "worst-case estimate, the other is an overall likelihood."
            ),
            steering_brief=steering_brief,
        )

    def _build_confidence(self) -> ForecastConfidence:
        """Derive a deterministic forecast confidence score from measurable indicators."""
        velocity_stability = max(0.0, min(1.0, float(self.metrics.velocity_metrics.velocity_stability_score or 0.0)))
        planning_accuracy = max(0.0, min(1.0, float(self.metrics.planning_metrics.planning_accuracy_score or 0.0)))

        # estimation_variance: measures velocity stability as coefficient of variation.
        # Use std_dev / mean (not variance / mean) so units are consistent (h/h).
        _velocity_std_dev = float(self.metrics.velocity_variance ** 0.5) if self.metrics.velocity_variance >= 0 else 0.0
        _cv = _velocity_std_dev / max(self.metrics.actual_avg_velocity, 1.0)
        estimation_variance = max(0.0, min(1.0, 1.0 - min(1.0, _cv)))

        # carryover_consistency: measures how much carryover exists relative to sprint size.
        # Normalize by average sprint size so 1 item out of 10 = low carryover (good),
        # not "every sprint had carryover" = 100% bad.
        _total_sprints = max(1, len(self.project_state.sprints))
        _avg_sprint_size = max(1.0, self.metrics.total_items / _total_sprints)
        _normalized_carryover = self.metrics.historical_carryover_rate / _avg_sprint_size
        carryover_consistency = max(0.0, min(1.0, 1.0 - min(1.0, _normalized_carryover)))

        blocker_volatility = max(0.0, min(1.0, 1.0 - min(1.0, self.metrics.active_blocker_count / max(self.metrics.total_items, 1))))
        dependency_density = max(0.0, min(1.0, 1.0 - min(1.0, self.metrics.dependency_count / max(self.metrics.total_items, 1))))
        historical_stability = max(0.0, min(1.0, float(self.metrics.velocity_metrics.velocity_stability_score or 0.0)))

        confidence_score = (
            0.25 * velocity_stability
            + 0.2 * planning_accuracy
            + 0.15 * estimation_variance
            + 0.15 * carryover_consistency
            + 0.1 * blocker_volatility
            + 0.1 * dependency_density
            + 0.05 * historical_stability
        )
        confidence_score = max(0.0, min(1.0, confidence_score))
        if confidence_score >= 0.75:
            confidence_level = "HIGH"
            reason = "Historical delivery signals are stable and planning accuracy is strong."
        elif confidence_score >= 0.45:
            confidence_level = "MEDIUM"
            reason = "Forecast confidence is moderate because some planning and execution signals are mixed."
        else:
            confidence_level = "LOW"
            reason = "The forecast is highly sensitive to blockers, carryover, and unstable velocity."

        return ForecastConfidence(
            confidence_score=float(round(confidence_score, 4)),
            confidence_level=confidence_level,
            confidence_reason=reason,
            confidence_inputs={
                "velocity_stability": round(velocity_stability, 4),
                "planning_accuracy": round(planning_accuracy, 4),
                "estimation_variance": round(estimation_variance, 4),
                "carryover_consistency": round(carryover_consistency, 4),
                "blocker_volatility": round(blocker_volatility, 4),
                "dependency_density": round(dependency_density, 4),
                "historical_stability": round(historical_stability, 4),
            },
        )

    def _build_steering_brief(
        self,
        *,
        expected_delay_days: float,
        expected_finish: datetime,
        target_end_date: datetime,
        completion_pct: float,
        days_elapsed: float,
        remaining_days_base_work: float,
        planned_window_days: float,
        remaining_days_blocker_loss: float,
        spillover_delay_days: float,
        spillover_penalty_hours: float = 0.0,
        projected_velocity_per_day: float = 0.0,
        velocity_floor_saturated_by_blockers: bool = False,
        scope_growth_percent: float,
        scope_impact_days: float,
        sprint_days: float,
        confidence_level: str,
        velocity_std_dev_pct: float = 0.15,
        holiday_padding_days: float = 0.0,
    ) -> ForecastSteeringBrief:
        """Build the manager-facing steering-meeting summary.

        The waterfall here uses the SAME additive basis as `delay_breakdown`
        (not the diagnostic `schedule_diagnostics`, which is intentionally
        non-additive). This guarantees the bars always sum exactly to
        `expected_delay_days`, so the total never looks "made up" in a room
        full of stakeholders.

        pace_scope_days = (days_elapsed + remaining_days_base_work) - planned_window_days
            -> the gap between plan and "how long the remaining work takes at
               current pace", which bundles scope growth and any velocity
               shortfall against plan. scope_impact_days is surfaced
               separately as an informational split of this bucket (it can
               exceed the bucket itself if pace is otherwise ahead of plan,
               so it's clipped for display).
        blocker_days = remaining_days_blocker_loss  -> extra days from open blockers
        spillover_days = spillover_delay_days       -> extra days from predicted spillover
        """
        pace_scope_days = float(round((days_elapsed + remaining_days_base_work) - planned_window_days, 2))
        blocker_days = float(round(remaining_days_blocker_loss, 2))
        spillover_days = float(round(spillover_delay_days, 2))

        # Split the bundled pace/scope bucket into two named contributors
        # whenever scope growth is meaningful AND the project is behind plan.
        # This keeps the waterfall additive (scope_days_shown + velocity_days_shown
        # == pace_scope_days exactly) while surfacing "Scope growth" as its own
        # line item instead of hiding it inside "Pace vs. plan".
        split_scope_row = False
        scope_days_shown = 0.0
        velocity_days_shown = pace_scope_days
        scope_note = None
        if scope_growth_percent and scope_growth_percent > 0.5:
            if pace_scope_days > 0:
                # Behind plan overall: scope's share of that gap is bounded by the
                # gap itself (can't blame scope for more days than are actually late).
                scope_days_shown = float(round(max(0.0, min(scope_impact_days, pace_scope_days)), 2))
                velocity_days_shown = float(round(pace_scope_days - scope_days_shown, 2))
                split_scope_row = scope_days_shown > 0
                scope_note = (
                    f"Scope has grown {scope_growth_percent:.0f}% since baseline, contributing "
                    f"~{scope_days_shown:.1f} of the days above."
                )
            else:
                # Ahead of plan overall: scope growth still cost real days, it's just
                # being offset by the team running faster than planned elsewhere. Show
                # the true cost rather than clipping it to 0, which reads as "scope
                # growth was free" — it wasn't. Kept as a single bucket here (not
                # split) since the bucket as a whole is negative; the note below
                # still surfaces the true scope cost informationally.
                scope_note = (
                    f"Scope has grown {scope_growth_percent:.0f}% since baseline (~{scope_impact_days:.1f} days "
                    f"of added work), but the team is currently running ahead of plan by enough to absorb it."
                )

        overloaded_resources: List[ForecastSteeringOverload] = []
        total_overloaded_resources = 0
        try:
            loads = getattr(self.metrics, "resource_sprint_loads", None) or {}
            blocker_owner_names_early = [
                getattr(b, "owner", None)
                for b in cc.open_blockers(self.project_state)
                if getattr(b, "owner", None)
            ]
            sprint_by_id_early = {s.sprint_id: s for s in self.project_state.sprints}
            active_sprint_ids_early = {
                s.sprint_id for s in self.project_state.sprints
                if s.status in (SprintStatus.IN_PROGRESS, SprintStatus.NOT_STARTED)
            }
            rows_early = []
            for resource_name, per_sprint in loads.items():
                for sprint_id, ratio in (per_sprint or {}).items():
                    if ratio <= 1.0 or sprint_id not in active_sprint_ids_early:
                        continue
                    sprint = sprint_by_id_early.get(sprint_id)
                    rows_early.append(ForecastSteeringOverload(
                        resource_name=resource_name,
                        sprint_id=sprint_id,
                        sprint_name=getattr(sprint, "sprint_name", sprint_id),
                        load_pct=float(round(ratio * 100.0, 0)),
                        is_blocker_owner=any(_names_match(resource_name, o) for o in blocker_owner_names_early),
                    ))
            rows_early.sort(key=lambda r: (not r.is_blocker_owner, -r.load_pct))

            # Deduplicate: the same person can appear twice — once with their
            # username (underscores, all-lowercase from the workbook) and once
            # with their display name (spaces, mixed-case from a different sheet).
            # _normalize_name collapses both to the same key.  Keep whichever
            # version looks more like a display name (fewer underscores wins).
            seen_canonical: dict = {}  # canonical_key -> index in deduped list
            deduped: list = []
            for r in rows_early:
                key = _normalize_name(r.resource_name)
                if key not in seen_canonical:
                    seen_canonical[key] = len(deduped)
                    deduped.append(r)
                else:
                    # Prefer the version without underscores (display name)
                    existing_idx = seen_canonical[key]
                    existing = deduped[existing_idx]
                    if "_" in existing.resource_name and "_" not in r.resource_name:
                        # Replace with the display-name version
                        deduped[existing_idx] = r

            total_overloaded_resources = len(deduped)
            overloaded_resources = deduped  # full list — no cap; UI renders all rows
        except Exception:
            overloaded_resources = []
            total_overloaded_resources = 0

        # spillover_days now genuinely factors in per-resource overload (see
        # SpilloverAnalysisEngine._resource_overload_excess_hours), not just
        # team-wide sprint utilization. The caveat below is only for the residual
        # case where overload exists but is too small to move spillover_days at
        # the current item-size granularity.
        def _name_overloads(resources):
            # Name everyone, don't silently truncate -- a dropped name in a
            # steering-meeting caption reads as "not a risk" when it is one.
            parts = [f"{r.resource_name} ({r.load_pct:.0f}% in {r.sprint_name})" for r in resources]
            if len(parts) <= 3:
                return ", ".join(parts)
            return ", ".join(parts[:3]) + f", +{len(parts) - 3} more"

        if spillover_days > 0 and overloaded_resources:
            names = _name_overloads(overloaded_resources)
            spillover_detail = f"Includes overload from {names}, on top of standard sprint-capacity risk."
        elif spillover_days > 0:
            spillover_detail = "Extra days from items expected to carry over into future sprints."
        elif overloaded_resources:
            names = _name_overloads(overloaded_resources)
            if velocity_floor_saturated_by_blockers and spillover_penalty_hours > 0:
                conditional_spillover_days = round(spillover_penalty_hours / max(projected_velocity_per_day, 1.0), 1) if projected_velocity_per_day > 0 else 0.0
                spillover_detail = (
                    f"Spillover is currently absorbed within the blocker impact — net additional delay is 0 days. "
                    f"However, {spillover_penalty_hours:.0f}h of predicted spillover exists. "
                    f"If the top blocker is resolved without addressing overloaded resources, "
                    f"spillover could add approximately {conditional_spillover_days:.1f} additional days. "
                    f"Resolve overloads alongside the blocker."
                )
            else:
                spillover_detail = (
                    f"{names} " + ("are" if len(overloaded_resources) > 1 else "is")
                    + " over-allocated, but not by enough to move the day estimate yet — worth watching. See Resource overload below."
                )
        else:
            if velocity_floor_saturated_by_blockers and spillover_penalty_hours > 0:
                conditional_spillover_days = round(spillover_penalty_hours / max(projected_velocity_per_day, 1.0), 1) if projected_velocity_per_day > 0 else 0.0
                spillover_detail = (
                    f"Spillover is currently absorbed within the blocker impact — net additional delay is 0 days. "
                    f"However, {spillover_penalty_hours:.0f}h of predicted spillover exists. "
                    f"If the top blocker is resolved without addressing overloaded resources, "
                    f"spillover could add approximately {conditional_spillover_days:.1f} additional days. "
                    f"Resolve overloads alongside the blocker."
                )
            else:
                spillover_detail = "No material spillover is predicted, and no individual is over-allocated in upcoming sprints either."

        pace_detail = "Remaining work is exactly on pace with plan." if pace_scope_days == 0 else (
            f"Excluding blockers and spillover, team velocity alone would finish {abs(pace_scope_days):.1f} day(s) early — the delay below is what's pulling the date back." if pace_scope_days < 0 else
            "Remaining work is taking longer than planned at the team's current velocity, excluding the scope growth shown separately above."
            if split_scope_row else
            "Remaining work is taking longer than planned"
            + (f" — largely scope growth ({scope_growth_percent:.0f}%)." if scope_growth_percent and scope_growth_percent > 5 else " at the team's current velocity.")
        )
        holiday_days = float(round(holiday_padding_days, 2))

        if split_scope_row:
            pace_velocity_rows = [
                ForecastSteeringDriver(
                    key="scope_growth",
                    label="Scope growth",
                    days=scope_days_shown,
                    detail=f"Added work since baseline (scope grew {scope_growth_percent:.0f}%) is adding directly to the timeline.",
                    tone="risk",
                ),
                ForecastSteeringDriver(
                    key="velocity",
                    label="Velocity vs. plan",
                    days=velocity_days_shown,
                    detail=pace_detail,
                    tone="risk" if velocity_days_shown > 0 else "good",
                ),
            ]
        else:
            pace_velocity_rows = [
                ForecastSteeringDriver(
                    key="pace_scope",
                    label="Pace vs. plan",
                    days=pace_scope_days,
                    detail=pace_detail,
                    tone="risk" if pace_scope_days > 0 else "good",
                ),
            ]

        waterfall = pace_velocity_rows + [
            ForecastSteeringDriver(
                key="blockers",
                label="Open blockers",
                days=blocker_days,
                detail="Extra days from blockers currently reducing team velocity." if blocker_days > 0 else "No open blockers are dragging on velocity right now.",
                tone="risk" if blocker_days > 0 else "neutral",
            ),
            ForecastSteeringDriver(
                key="spillover",
                label="Predicted spillover",
                days=spillover_days,
                detail=spillover_detail,
                tone="risk" if (spillover_days > 0 or overloaded_resources) else "neutral",
            ),
            ForecastSteeringDriver(
                key="holidays",
                label="Public holidays",
                days=holiday_days,
                detail=(
                    f"{int(round(holiday_days))} mandatory national holiday(s) fall inside the remaining window."
                    if holiday_days > 0 else "No mandatory national holidays fall inside the remaining window."
                ),
                tone="risk" if holiday_days > 0 else "neutral",
            ),
        ]

        # Sort by descending impact so PMs see the biggest driver first (Overview
        # tab: "populate the waterfall using all contributors, sorted by descending
        # impact"). Zero-day rows keep their relative order at the end since the
        # frontend renders them separately as risk signals, not additive bars.
        waterfall.sort(key=lambda d: -d.days)

        # Named, owned blockers for the room to make a decision on.
        top_blockers: List[ForecastSteeringBlocker] = []
        total_open_blockers = 0
        try:
            cp_ids = cc.critical_path_ids(self.cp_result)
            open_blockers = cc.open_blockers(self.project_state)
            total_open_blockers = len(open_blockers)
            ranked = sorted(open_blockers, key=cc.blocker_delay_days, reverse=True)
            for b in ranked[:3]:
                top_blockers.append(ForecastSteeringBlocker(
                    blocker_id=getattr(b, "blocker_id", "?"),
                    description=getattr(b, "description", "") or "No description provided",
                    owner=getattr(b, "owner", None),
                    severity=str(getattr(getattr(b, "severity", None), "value", getattr(b, "severity", "Medium"))),
                    category=str(getattr(getattr(b, "category", None), "value", getattr(b, "category", "Other"))),
                    delay_days=float(round(cc.blocker_delay_days(b), 1)),
                    on_critical_path=cc.blocker_hits_critical_path(b, cp_ids),
                    target_resolution_date=getattr(b, "target_resolution_date", None),
                    raised_date=getattr(b, "raised_date", None),
                ))
        except Exception:
            top_blockers = []
            total_open_blockers = 0

        # Status thresholds, calibrated to this project's own velocity noise rather
        # than a flat "1 sprint" for every project: a project with more natural
        # sprint-to-sprint variance (higher velocity_std_dev_pct) should tolerate a
        # bit more slip before calling it LATE, since some of that slip is likely
        # just normal variance rather than a real trend.
        at_risk_threshold_days = max(sprint_days * (1.0 + velocity_std_dev_pct), 1.0)
        if expected_delay_days <= 0:
            status = "ON_TRACK"
        elif expected_delay_days <= at_risk_threshold_days:
            status = "AT_RISK"
        else:
            status = "LATE"

        finish_str = expected_finish.strftime("%d %b %Y")
        target_str = target_end_date.strftime("%d %b %Y")
        if status == "ON_TRACK":
            headline = f"On track — projected to finish {finish_str}, {abs(expected_delay_days):.0f} day(s) ahead of the {target_str} target."
        else:
            headline = f"Projected {expected_delay_days:.0f} day(s) late — {finish_str} vs. the {target_str} target."

        # "Biggest driver" should acknowledge a near-tie rather than confidently
        # naming a single winner that's barely ahead of the runner-up — e.g.
        # blockers +7.0 vs spillover +6.5 shouldn't read as "the" driver is blockers.
        positive_drivers = sorted([d for d in waterfall if d.days > 0], key=lambda d: d.days, reverse=True)
        dominant = positive_drivers[0] if positive_drivers else None
        near_tie = (
            len(positive_drivers) >= 2
            and dominant is not None
            and (dominant.days - positive_drivers[1].days) <= max(0.5, dominant.days * 0.15)
        )
        if not positive_drivers:
            driver_phrase = "No active driver is adding delay beyond plan."
        elif near_tie:
            driver_phrase = f"Driven jointly by {positive_drivers[0].label.lower()} and {positive_drivers[1].label.lower()}."
        else:
            driver_phrase = f"Biggest driver: {dominant.label}."
        subheadline = f"{completion_pct * 100:.0f}% complete. {driver_phrase}"

        compounding_owner_overload = next((r for r in overloaded_resources if r.is_blocker_owner), None)
        if status == "ON_TRACK":
            decision_ask = "No decision needed this cycle — hold current plan and re-check next steering meeting."
        elif compounding_owner_overload:
            decision_ask = (
                f"Needs a decision: {compounding_owner_overload.resource_name} owns the top blocker and is "
                f"{compounding_owner_overload.load_pct:.0f}% allocated in {compounding_owner_overload.sprint_name} — "
                "reassign the blocker, add support, or expect the blocker to slip further."
            )
        elif near_tie:
            decision_ask = (
                f"Needs a decision: {positive_drivers[0].label.lower()} and {positive_drivers[1].label.lower()} "
                "are contributing similar amounts — address both, or the untouched one will still cause the slip."
            )
        elif dominant and dominant.key == "blockers" and top_blockers:
            names = ", ".join(f"{b.blocker_id} ({b.owner or 'unassigned owner'})" for b in top_blockers[:2])
            more = f", +{total_open_blockers - len(top_blockers)} more open" if total_open_blockers > len(top_blockers) else ""
            decision_ask = f"Needs a decision: escalate/resource the open blockers ({names}{more}) or accept the schedule slip."
        elif dominant and dominant.key == "spillover":
            decision_ask = "Needs a decision: trim scope from upcoming sprints or accept the spillover-driven delay."
        elif dominant and dominant.key == "holidays":
            decision_ask = "No action needed — this is calendar-driven, not a team performance issue. Flag it to stakeholders so the target date reflects mandatory holidays."
        elif dominant and dominant.key in ("pace_scope", "scope_growth") and scope_growth_percent and scope_growth_percent > 5:
            decision_ask = "Needs a decision: approve the scope growth's schedule impact, or de-scope to protect the date."
        elif overloaded_resources:
            top = overloaded_resources[0]
            decision_ask = (
                f"Needs a decision: {top.resource_name} is {top.load_pct:.0f}% allocated in {top.sprint_name} — "
                "rebalance the load before that sprint starts."
            )
        else:
            decision_ask = "Needs a decision: add capacity, trim scope, or accept the revised finish date."

        return ForecastSteeringBrief(
            status=status,
            headline=headline,
            subheadline=subheadline,
            target_end_date=target_end_date,
            expected_finish_date=expected_finish,
            expected_delay_days=float(round(expected_delay_days, 2)),
            completion_percentage=completion_pct,
            waterfall=waterfall,
            scope_growth_percent=scope_growth_percent,
            scope_note=scope_note,
            top_blockers=top_blockers,
            total_open_blockers=total_open_blockers,
            overloaded_resources=overloaded_resources,
            total_overloaded_resources=total_overloaded_resources,
            decision_ask=decision_ask,
            confidence_level=confidence_level,
        )

    def _build_forecast_drivers(
        self,
        scope_impact_days: float,
        remaining_days_blocker_loss: float,
        cp_remaining_days: float,
        spillover_delay_days: float,
        remaining_days_base_work: float,
    ) -> List[ForecastDriver]:
        """Build ranked drivers from deterministic forecast components."""
        drivers: List[ForecastDriver] = []
        if scope_impact_days > 0:
            drivers.append(ForecastDriver(
                name="Scope Growth",
                impact=float(round(scope_impact_days, 2)),
                reason="Current estimates exceed the baseline estimate for one or more work items.",
                supporting_metrics={"scope_growth_hours": float(round(self._scope_growth_hours(), 2))},
            ))
        if remaining_days_blocker_loss > 0:
            drivers.append(ForecastDriver(
                name="Blockers",
                impact=float(round(remaining_days_blocker_loss, 2)),
                reason="Blockers reduce effective throughput relative to the base scheduled velocity.",
                supporting_metrics={"estimated_blocker_velocity_impact": float(round(self.metrics.estimated_blocker_velocity_impact, 4))},
            ))
        if cp_remaining_days > 0:
            drivers.append(ForecastDriver(
                name="Critical Path",
                impact=float(round(cp_remaining_days, 2)),
                reason="Dependency sequencing requires serial work that extends the schedule beyond raw remaining effort.",
                supporting_metrics={"critical_path_remaining_hours": float(round(self.cp_result.critical_path_remaining_hours, 2))},
            ))
        if spillover_delay_days > 0:
            drivers.append(ForecastDriver(
                name="Carryover",
                impact=float(round(spillover_delay_days, 2)),
                reason="Predicted spillover erodes effective velocity and adds schedule delay.",
                supporting_metrics={"predicted_spillover_items": float(round(self._predicted_spillover_items(), 2))},
            ))
        if remaining_days_base_work > 0:
            drivers.append(ForecastDriver(
                name="Base Workload",
                impact=float(round(remaining_days_base_work, 2)),
                reason="Remaining effort still requires schedule time even before secondary effects are applied.",
                supporting_metrics={"remaining_effort_hours": float(round(self.metrics.remaining_effort_hours, 2))},
            ))
        return sorted(drivers, key=lambda d: d.impact, reverse=True)

    def _build_forecast_evidence(self) -> List[ForecastEvidence]:
        """Expose structured evidence values already available through ProjectMetrics.

        NOTE: effective_project_velocity is intentionally excluded from this list.
        It is an internally-computed capacity estimate that diverges from observed
        sprint velocity when the team is not operating at theoretical capacity.
        Displaying it alongside historical velocity confuses readers. Use
        actual_avg_velocity (observed sprint actuals) as the canonical velocity signal.
        """
        return [
            ForecastEvidence(
                name="Historical sprint velocity",
                value=self.metrics.actual_avg_velocity,
                unit="hours/sprint",
                source="MetricsEngine",
            ),
            ForecastEvidence(name="Remaining effort", value=self.metrics.remaining_effort_hours, unit="hours", source="MetricsEngine"),
            ForecastEvidence(name="Critical path remaining effort", value=self.cp_result.critical_path_remaining_hours, unit="hours", source="CriticalPathEngine"),
            ForecastEvidence(name="Carryover history", value=self.metrics.historical_total_carryover_items, unit="items", source="MetricsEngine"),
            ForecastEvidence(name="Planning accuracy", value=self.metrics.planning_metrics.planning_accuracy_score, unit="score", source="MetricsEngine"),
            ForecastEvidence(name="Dependency density", value=self.metrics.dependency_metrics.critical_dependency_density, unit="ratio", source="MetricsEngine"),
            ForecastEvidence(name="Blocker counts", value=self.metrics.active_blocker_count, unit="count", source="MetricsEngine"),
            ForecastEvidence(name="Resource utilization", value=self.metrics.avg_allocation_pct, unit="ratio", source="MetricsEngine"),
        ]

    def _build_assumptions(self) -> ForecastAssumptions:
        """Document forecast assumptions in machine-readable form."""
        return ForecastAssumptions(
            velocity_calculation_method="projected_velocity = effective_project_velocity * (1 - blocker_impact) * (1 - spillover_fraction * 0.5), floored at 25% of effective project velocity",
            blocker_adjustment_method="blocker_impact is applied as a multiplicative velocity reduction factor from ProjectMetrics",
            spillover_adjustment_method="predicted spillover is converted to equivalent hours and reduces effective throughput rather than adding a separate additive delay bucket",
            critical_path_handling="critical_path_remaining_hours is used as a lower bound for remaining work so serial dependency effort cannot be under-counted",
            timeline_anchoring="forecast uses sprint-based elapsed days and project start anchor date rather than current wall-clock time",
            capacity_assumptions={"velocity_floor_ratio": 0.25, "spillover_damping_ratio": 0.5},
        )

    def _build_explanation(self, expected_delay_days: float, confidence: ForecastConfidence, forecast_drivers: List[ForecastDriver]) -> ForecastExplanation:
        """Create structured explanation payload for downstream consumers."""
        if expected_delay_days <= 0:
            delay_signal = "on track"
            summary = "The deterministic schedule remains within the planned window."
        elif expected_delay_days <= 7:
            delay_signal = "slightly late"
            summary = "The deterministic schedule is projected to slip slightly beyond the target window."
        else:
            delay_signal = "late"
            summary = "The deterministic schedule is projected to miss the target window materially."

        primary_driver = forecast_drivers[0].name if forecast_drivers else "Base Workload"
        return ForecastExplanation(
            summary=summary,
            primary_driver=primary_driver,
            driver_names=[driver.name for driver in forecast_drivers],
            confidence_note=confidence.confidence_reason,
            delay_signal=delay_signal,
        )

    def _scope_growth_hours(self) -> float:
        return float(sum(max(0.0, wi.current_estimate_hrs - wi.estimated_effort_hrs) for wi in self.project_state.work_items))

    def _predicted_spillover_items(self) -> float:
        if self.spillover is None:
            return 0.0
        try:
            return float(sum(self.spillover.predicted_spillover_by_sprint.values()))
        except Exception:
            return 0.0

    def _calculate_schedule_elapsed_days(self, sprint_days: float) -> float:
        """Real elapsed calendar days since project start, anchored to the
        actual current date (`ProjectInfo.effective_as_of_date()`, real
        wall-clock time unless a demo/backtest snapshot date is pinned).

        FIX (was `_status_derived_elapsed_days` below): the previous
        implementation inferred elapsed time purely from sprint status
        labels -- `completed_sprints * sprint_days` plus the in-progress
        sprint's window capped at exactly one sprint length. That meant:
          - an "In Progress" sprint running weeks past its planned end date
            was still only ever credited with one sprint-length of elapsed
            time -- the overrun vanished.
          - a "Not Started" sprint whose planned start date had already
            passed contributed ZERO elapsed days, no matter how overdue it
            was, because the function never looked at what today's date
            actually is.
        A project stalled mid-sprint (exactly this project's Sprint 6/7/8
        situation) therefore showed almost no schedule delay, because the
        model's internal clock only advanced when a sprint's status field
        changed -- not when actual calendar time passed. Anchoring to the
        real current date fixes this unconditionally: a stalled sprint or a
        late-starting one now shows up as delay immediately, with no
        dependency on anyone updating a status dropdown.
        """
        project_start = self.project_state.project_info.forecast_anchor_date()
        as_of = self.project_state.project_info.effective_as_of_date()
        real_elapsed_days = max(0.0, (as_of - project_start).total_seconds() / (24 * 3600))
        return real_elapsed_days

    def _status_derived_elapsed_days(self, sprint_days: float) -> float:
        """LEGACY method, retained only to compute `calendar_variance_days`
        (real elapsed vs. what the sprint-status labels alone would imply)
        as an explicit diagnostic -- see ForecastScheduleDiagnostics. Do NOT
        use this for the actual forecast; it is the method that caused the
        structural under-count described above."""
        completed_sprints = sum(
            1
            for sprint in self.project_state.sprints
            if (
                sprint.status == SprintStatus.COMPLETED
                or (isinstance(sprint.status, str) and sprint.status == SprintStatus.COMPLETED.value)
            )
        )

        days_from_completed = completed_sprints * sprint_days

        current_sprint = next(
            (
                sprint
                for sprint in self.project_state.sprints
                if (
                    sprint.status == SprintStatus.IN_PROGRESS
                    or (isinstance(sprint.status, str) and sprint.status == SprintStatus.IN_PROGRESS.value)
                )
            ),
            None,
        )
        if not current_sprint:
            return days_from_completed

        sprint_window_days = max(
            0.0,
            (current_sprint.end_date - current_sprint.start_date).total_seconds() / (24 * 3600),
        )
        return days_from_completed + min(sprint_window_days, sprint_days)