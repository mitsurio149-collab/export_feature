"""
EMIOS Observation Engine (Stage 1) — full 17-detector signal layer.

Detects anomalies WITHOUT interpreting cause. An Observation NEVER contains a
cause (enforced by the _make() factory). run() takes critical_path (detectors
8/9/10 need it). Detector 3 reads resource_sprint_loads (capacity bug fixed).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from app.domain.models import (
    ProjectState, BlockerStatus, BlockerSeverity, SprintStatus, WorkItemStatus,
)
from app.domain.emios_models import Observation, ObservationCluster, ObservationDirection
from app.engines.metrics_engine import ProjectMetrics
from app.api.models_phase3 import ForecastResult, MonteCarloResult
from app.engines import cognition_common as cc

_DONE = {WorkItemStatus.DONE, WorkItemStatus.COMPLETED}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _significance_from_deviation(deviation_pct: float) -> str:
    d = abs(deviation_pct)
    if d > 30.0:
        return "HIGH"
    if d >= 15.0:
        return "MEDIUM"
    return "LOW"


class ObservationEngine:
    """Stage 1: emits a neutral ObservationCluster from deterministic outputs."""

    BASELINE_WINDOW: int = 6

    def run(
        self,
        state: ProjectState,
        metrics: ProjectMetrics,
        forecast: ForecastResult,
        monte_carlo: Optional[MonteCarloResult] = None,
        critical_path=None,
    ) -> ObservationCluster:
        observations: List[Observation] = []
        observations.extend(self._detect_velocity_anomaly(state, metrics))
        observations.extend(self._detect_probability_anomaly(monte_carlo))
        observations.extend(self._detect_resource_overload(metrics))
        observations.extend(self._detect_blocker_escalation(state))
        observations.extend(self._detect_carryover_anomaly(state, metrics))
        observations.extend(self._detect_scope_growth(forecast))
        observations.extend(self._detect_estimation_drift(state))
        observations.extend(self._detect_critical_path_pressure(state, critical_path))
        observations.extend(self._detect_dependency_chain_lag(state, critical_path))
        observations.extend(self._detect_skill_mismatch(state, critical_path))
        observations.extend(self._detect_sprint_completion_rate(state))
        observations.extend(self._detect_blocker_age(state))
        observations.extend(self._detect_load_concentration(metrics))
        observations.extend(self._detect_rework_signal(metrics))
        observations.extend(self._detect_scope_churn(state))
        observations.extend(self._detect_milestone_risk(state, monte_carlo))
        observations.extend(self._detect_velocity_variance(metrics))

        cluster_severity = self._worst_severity(observations)
        primary = self._primary_signal(observations)
        return ObservationCluster(
            cluster_id=f"obs-{uuid4().hex[:10]}",
            observations=observations,
            detected_at=_utcnow(),
            summary=self._summary(primary, observations),
            cluster_severity=cluster_severity,
            primary_signal=primary,
        )

    # --- factory (cause=None choke point) ---------------------------------
    def _make(self, metric, current, baseline, *, higher_is_better,
              entity_id=None, significance_override=None) -> Observation:
        deviation_pct = ((current - baseline) / abs(baseline) * 100.0) if baseline else 0.0
        significance = significance_override or _significance_from_deviation(deviation_pct)
        return Observation(
            observation_id=f"o-{uuid4().hex[:8]}",
            metric_ref=metric,
            magnitude=round(current - baseline, 4),
            direction=self._dir_enum(deviation_pct, higher_is_better),
            significance=significance,
            current_value=round(current, 4),
            baseline_value=round(baseline, 4),
            deviation_pct=round(deviation_pct, 4),
            entity_id=entity_id,
            detected_at=_utcnow(),
            source_engine="ObservationEngine",
            cause=None,
        )

    @staticmethod
    def _dir_enum(deviation_pct, higher_is_better) -> ObservationDirection:
        if abs(deviation_pct) < 5.0:
            return ObservationDirection.FLAT
        return ObservationDirection.UP if deviation_pct > 0 else ObservationDirection.DOWN

    def _band(self, obs) -> str:
        return obs.significance

    # --- 1 velocity -------------------------------------------------------
    def _detect_velocity_anomaly(self, state, metrics) -> List[Observation]:
        series = cc.velocity_series(metrics)
        if len(series) < 2:
            return []
        current = float(series[-1])
        prior = series[:-1][-self.BASELINE_WINDOW:]
        baseline = sum(prior) / len(prior) if prior else current
        if baseline <= 0:
            return []
        return [self._make("velocity", current, baseline, higher_is_better=True)]

    # --- 2 probability ----------------------------------------------------
    def _detect_probability_anomaly(self, monte_carlo) -> List[Observation]:
        if monte_carlo is None:
            return []
        otp = float(getattr(monte_carlo, "on_time_probability", 0.0) or 0.0)
        band = "HIGH" if otp < 0.30 else "MEDIUM" if otp < 0.50 else "LOW"
        return [self._make("on_time_probability", otp, 0.65,
                           higher_is_better=True, significance_override=band)]

    # --- 3 resource overload (FIXED) --------------------------------------
    def _detect_resource_overload(self, metrics) -> List[Observation]:
        out: List[Observation] = []
        peaks = cc.peak_resource_loads(metrics)
        if peaks:
            for name, load in peaks.items():
                if load <= 1.0:
                    continue
                out.append(self._make("resource_load_ratio", load, 1.0,
                                      higher_is_better=False, entity_id=name))
            return out
        for d in cc.developer_metrics(metrics):
            alloc = float(getattr(d, "allocation_pct", 0.0) or 0.0)
            avail = float(getattr(d, "availability_pct", 1.0) or 1.0)
            load = alloc * avail
            if load <= 1.0:
                continue
            out.append(self._make("resource_load_ratio", load, 1.0, higher_is_better=False,
                                  entity_id=getattr(d, "resource_id", None) or getattr(d, "name", None)))
        return out

    # --- 4 blocker escalation --------------------------------------------
    def _detect_blocker_escalation(self, state) -> List[Observation]:
        sprint_days = float(state.project_info.sprint_duration_days or 14)
        out: List[Observation] = []
        for b in cc.open_blockers(state):
            if cc.blocker_delay_days(b) <= sprint_days:
                continue
            out.append(self._make("blocker_delay_days", cc.blocker_delay_days(b), sprint_days,
                                  higher_is_better=False, entity_id=getattr(b, "blocker_id", None)))
        return out

    # --- 5 carryover ------------------------------------------------------
    def _detect_carryover_anomaly(self, state, metrics) -> List[Observation]:
        rate = getattr(metrics, "historical_carryover_rate", None)
        if rate is None:
            return []
        total_items = float(getattr(metrics, "total_items", 0) or 0)
        completed_sprints = float(getattr(metrics, "completed_sprints", 0) or 0)
        avg = (total_items / completed_sprints) if completed_sprints > 0 else 0.0
        frac = (float(rate) / avg) if avg > 0 else 0.0
        if frac <= 0.20:
            return []
        return [self._make("carryover_rate", frac, 0.20, higher_is_better=False)]

    # --- 6 scope growth ---------------------------------------------------
    def _detect_scope_growth(self, forecast) -> List[Observation]:
        pct = cc.scope_growth_percent(forecast)
        if pct <= 10.0:
            return []
        return [self._make("scope_growth_pct", pct, 10.0, higher_is_better=False)]

    # --- 7 estimation drift ----------------------------------------------
    def _detect_estimation_drift(self, state) -> List[Observation]:
        out: List[Observation] = []
        drifted = 0
        for wi in getattr(state, "work_items", []) or []:
            if getattr(wi, "status", None) in _DONE:
                continue
            baseline = getattr(wi, "estimated_effort_hrs", None)
            current = getattr(wi, "current_estimate_hrs", None)
            if baseline is None or current is None or baseline <= 0:
                continue
            if float(current) > float(baseline) * 1.2:
                drifted += 1
                out.append(self._make("estimation_drift", float(current), float(baseline),
                                      higher_is_better=False, entity_id=getattr(wi, "item_id", None)))
        if drifted > 2:
            out.append(self._make("estimation_drift_cluster", float(drifted), 2.0, higher_is_better=False))
        return out

    # --- 8 critical-path pressure ----------------------------------------
    def _detect_critical_path_pressure(self, state, critical_path) -> List[Observation]:
        cp_ids = cc.critical_path_ids(critical_path)
        if not cp_ids:
            return []
        blocked = cc.blocked_item_ids(state)
        ratio = len(blocked & cp_ids) / max(len(cp_ids), 1)
        if ratio <= 0.25:
            return []
        band = "HIGH" if ratio > 0.5 else "MEDIUM"
        return [self._make("critical_path_pressure", ratio, 0.0,
                           higher_is_better=False, significance_override=band)]

    # --- 9 dependency chain lag ------------------------------------------
    def _detect_dependency_chain_lag(self, state, critical_path) -> List[Observation]:
        cp_ids = cc.critical_path_ids(critical_path)
        sprint_days = float(state.project_info.sprint_duration_days or 14)
        out: List[Observation] = []
        for dep in getattr(state, "dependencies", []) or []:
            pred = getattr(dep, "predecessor_item_id", None)
            succ = getattr(dep, "successor_item_id", None)
            if (pred not in cp_ids) and (succ not in cp_ids):
                continue
            lag = float(getattr(dep, "lag_days", 0) or 0)
            if lag <= sprint_days:
                continue
            out.append(self._make("dependency_lag_days", lag, sprint_days,
                                  higher_is_better=False, entity_id=f"{pred}->{succ}"))
        return out

    # --- 10 skill mismatch -----------------------------------------------
    def _detect_skill_mismatch(self, state, critical_path) -> List[Observation]:
        cp_ids = cc.critical_path_ids(critical_path)
        team = {getattr(r, "resource_id", None): r for r in getattr(state, "team", []) or []}
        by_name = {getattr(r, "name", None): r for r in getattr(state, "team", []) or []}
        out: List[Observation] = []
        count = 0
        for wi in getattr(state, "work_items", []) or []:
            if getattr(wi, "status", None) in _DONE:
                continue
            req = getattr(wi, "required_skill", None)
            rid = getattr(wi, "assigned_resource", None)
            if not req or not rid:
                continue
            resource = team.get(rid) or by_name.get(rid)
            if resource is None:
                continue
            covers = resource.covers_skill(req) if hasattr(resource, "covers_skill") else (
                getattr(resource, "primary_skill", None) == req
                or getattr(resource, "secondary_skill", None) == req
            )
            if covers:
                continue
            count += 1
            item_id = getattr(wi, "item_id", None)
            band = "HIGH" if item_id in cp_ids else "MEDIUM"
            out.append(self._make("skill_mismatch", 1.0, 0.0, higher_is_better=False,
                                  entity_id=item_id, significance_override=band))
        if count > 3:
            out.append(self._make("skill_mismatch_cluster", float(count), 3.0, higher_is_better=False))
        return out

    # --- 11 sprint completion rate ---------------------------------------
    def _detect_sprint_completion_rate(self, state) -> List[Observation]:
        actuals = {getattr(a, "sprint_id", None): a for a in getattr(state, "actuals", []) or []}
        out: List[Observation] = []
        for s in getattr(state, "sprints", []) or []:
            if getattr(s, "status", None) != SprintStatus.COMPLETED:
                continue
            planned = float(getattr(s, "planned_velocity_hrs", 0.0) or 0.0)
            a = actuals.get(getattr(s, "sprint_id", None))
            if a is None:
                continue
            if planned <= 0:
                planned = float(getattr(a, "planned_effort_hrs", 0.0) or 0.0)
            actual = float(getattr(a, "actual_effort_hrs", 0.0) or 0.0)
            if planned <= 0:
                continue
            rate = actual / planned
            if rate >= 0.70:
                continue
            out.append(self._make("sprint_completion_rate", rate, 1.0,
                                  higher_is_better=True, entity_id=getattr(s, "sprint_id", None)))
        return out

    # --- 12 blocker age --------------------------------------------------
    def _detect_blocker_age(self, state) -> List[Observation]:
        sprint_days = float(state.project_info.sprint_duration_days or 14)
        now = _utcnow()
        out: List[Observation] = []
        for b in cc.open_blockers(state):
            raised = getattr(b, "raised_date", None)
            if raised is None:
                continue
            r = raised.replace(tzinfo=None) if getattr(raised, "tzinfo", None) else raised
            age_days = (now.replace(tzinfo=None) - r).days
            age_sprints = age_days / sprint_days if sprint_days else 0.0
            if age_sprints <= 2.0:
                continue
            band = "HIGH" if age_sprints > 4.0 else "MEDIUM"
            out.append(self._make("blocker_age_sprints", age_sprints, 2.0,
                                  higher_is_better=False, entity_id=getattr(b, "blocker_id", None),
                                  significance_override=band))
        return out

    # --- 13 load concentration -------------------------------------------
    def _detect_load_concentration(self, metrics) -> List[Observation]:
        devs = cc.developer_metrics(metrics)
        total = sum(float(getattr(d, "remaining_effort_hours", 0.0) or 0.0) for d in devs)
        if total <= 0:
            return []
        out: List[Observation] = []
        for d in devs:
            share = float(getattr(d, "remaining_effort_hours", 0.0) or 0.0) / total
            if share <= 0.40:
                continue
            band = "HIGH" if share > 0.60 else "MEDIUM"
            out.append(self._make("load_concentration", share, 0.40, higher_is_better=False,
                                  entity_id=getattr(d, "resource_id", None) or getattr(d, "name", None),
                                  significance_override=band))
        return out

    # --- 14 rework signal -------------------------------------------------
    def _detect_rework_signal(self, metrics) -> List[Observation]:
        rate = cc.rework_rate(metrics)
        if rate <= 0.05:
            return []
        band = "HIGH" if rate > 0.15 else "MEDIUM"
        return [self._make("rework_rate", rate, 0.05, higher_is_better=False,
                           significance_override=band)]

    # --- 15 scope churn (optional fields; degrades to []) ----------------
    def _detect_scope_churn(self, state) -> List[Observation]:
        current_sprint = None
        for s in getattr(state, "sprints", []) or []:
            if getattr(s, "status", None) == SprintStatus.IN_PROGRESS:
                current_sprint = s
                break
        churn = 0
        for wi in getattr(state, "work_items", []) or []:
            if getattr(wi, "added_mid_sprint", False):
                churn += 1
                continue
            created = getattr(wi, "created_date", None)
            wi_sprint = getattr(wi, "sprint_id", None)
            if current_sprint is not None and created is not None:
                start = getattr(current_sprint, "start_date", None)
                if wi_sprint == getattr(current_sprint, "sprint_id", None) and start is not None:
                    c = created.replace(tzinfo=None) if getattr(created, "tzinfo", None) else created
                    st = start.replace(tzinfo=None) if getattr(start, "tzinfo", None) else start
                    if c > st:
                        churn += 1
        if churn <= 2:
            return []
        return [self._make("scope_churn", float(churn), 2.0, higher_is_better=False)]

    # --- 16 milestone risk (optional fields; degrades to []) -------------
    def _detect_milestone_risk(self, state, monte_carlo) -> List[Observation]:
        milestone = getattr(state.project_info, "next_milestone_date", None)
        if milestone is None or monte_carlo is None:
            return []
        p80 = getattr(monte_carlo, "p80_finish_date", None) or getattr(monte_carlo, "p80_completion_date", None)
        if p80 is None:
            return []
        m = milestone.replace(tzinfo=None) if getattr(milestone, "tzinfo", None) else milestone
        p = p80.replace(tzinfo=None) if getattr(p80, "tzinfo", None) else p80
        days_at_risk = (p - m).days
        if days_at_risk <= 0:
            return []
        sprint_days = float(state.project_info.sprint_duration_days or 14)
        band = "HIGH" if days_at_risk > sprint_days else "MEDIUM"
        return [self._make("milestone_risk_days", float(days_at_risk), 0.0,
                           higher_is_better=False, significance_override=band)]

    # --- 17 velocity variance (CV) ---------------------------------------
    def _detect_velocity_variance(self, metrics) -> List[Observation]:
        series = cc.velocity_series(metrics)
        if len(series) < 3:
            return []
        mean_v = sum(series) / len(series)
        if mean_v <= 0:
            return []
        variance = sum((v - mean_v) ** 2 for v in series) / len(series)
        cv = (variance ** 0.5) / mean_v
        if cv <= 0.25:
            return []
        band = "HIGH" if cv > 0.50 else "MEDIUM"
        return [self._make("velocity_variance_cv", cv, 0.25, higher_is_better=False,
                           significance_override=band)]

    # --- cluster aggregation ---------------------------------------------
    def _worst_severity(self, observations) -> str:
        order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        if not observations:
            return "LOW"
        worst = max(observations, key=lambda o: order.get(self._band(o), 0))
        band = self._band(worst)
        high_count = sum(1 for o in observations if self._band(o) == "HIGH")
        if band == "HIGH" and high_count >= 2:
            return "CRITICAL"
        return band

    def _primary_signal(self, observations) -> Optional[Observation]:
        if not observations:
            return None
        return max(observations, key=lambda o: (o.significance, abs(o.deviation_pct or 0.0)))

    def _summary(self, primary, observations) -> str:
        if primary is None:
            return "No anomalies detected; all signals within expected bands."
        return (
            f"{len(observations)} signal(s) detected. Primary: {primary.metric_ref} "
            f"at {primary.current_value} vs baseline {primary.baseline_value} "
            f"({primary.deviation_pct:+.0f}%)."
        )