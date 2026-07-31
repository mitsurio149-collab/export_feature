"""
EMIOS EvidenceCollector (Stage 3). Projects validated observations + Sprint
Whisperer outputs + ProjectState into an immutable EvidenceBundle. Facts only;
each source is tagged '<source>::<CATEGORY>' for routing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from app.domain.models import ProjectState
from app.domain.emios_models import ValidationResult, EvidenceBundle, EvidenceItem
from app.engines import cognition_common as cc

CAT_BLOCKER = cc.CAT_BLOCKER
CAT_VELOCITY = cc.CAT_VELOCITY
CAT_SCOPE = cc.CAT_SCOPE
CAT_CAPACITY = cc.CAT_CAPACITY
CAT_DEPENDENCY = cc.CAT_DEPENDENCY
CAT_QUALITY = cc.CAT_QUALITY
CAT_NEUTRAL = cc.CAT_NEUTRAL

RESOURCE_EVIDENCE_FLOOR = 0.9
AGED_BLOCKER_SPRINTS = 2.0


def _tag(source: str, category: str) -> str:
    return f"{source}::{category}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceCollector:
    """Stage 3: gather everything relevant before theorizing."""

    RISK_EVIDENCE_MIN_SCORE = 41.0

    def run(
        self,
        validation_result: Optional[ValidationResult],
        state: ProjectState,
        *,
        forecast=None,
        risk_result=None,
        metrics=None,
        monte_carlo=None,
        critical_path=None,
    ) -> EvidenceBundle:
        items: List[EvidenceItem] = []
        items.extend(self._delay_breakdown_evidence(forecast))
        items.extend(self._scope_evidence(forecast))
        items.extend(self._estimation_drift_evidence(state))
        items.extend(self._risk_driver_evidence(risk_result))
        items.extend(self._blocker_evidence(state))
        items.extend(self._critical_path_pressure_evidence(state, critical_path))
        items.extend(self._velocity_evidence(metrics))
        items.extend(self._resource_load_evidence(metrics))
        items.extend(self._load_concentration_evidence(metrics))
        items.extend(self._skill_mismatch_evidence(state))
        items.extend(self._rework_evidence(metrics))

        data_confidence = 1.0
        triggered_ids: List[str] = []
        if validation_result is not None:
            data_confidence = float(getattr(validation_result, "data_confidence", 1.0) or 1.0)
            triggered_ids = [
                getattr(o, "observation_id", "")
                for o in getattr(validation_result, "validated", []) or []
            ]

        return EvidenceBundle(
            bundle_id=f"evb-{uuid4().hex[:10]}",
            triggered_by_observation_ids=[i for i in triggered_ids if i],
            items=items,
            low_confidence_flag=data_confidence < 0.5,
            data_confidence=round(data_confidence, 4),
        )

    def _delay_breakdown_evidence(self, forecast) -> List[EvidenceItem]:
        if forecast is None:
            return []
        db = getattr(forecast, "delay_breakdown", None)
        if db is None:
            return []
        total = float(getattr(db, "expected_delay_days", 0.0) or 0.0)
        components = [
            ("Base remaining work", float(getattr(db, "remaining_days_base_work", 0.0) or 0.0), CAT_NEUTRAL),
            ("Blocker velocity loss", float(getattr(db, "remaining_days_blocker_loss", 0.0) or 0.0), CAT_BLOCKER),
            ("Spillover", float(getattr(db, "remaining_days_spillover", 0.0) or 0.0), CAT_VELOCITY),
        ]
        positive = [(n, v, c) for n, v, c in components if v > 0.0]
        if not positive:
            return []
        denom = total if total > 0 else sum(v for _, v, _ in positive)
        denom = denom or 1.0
        items = []
        for name, days, cat in positive:
            share = max(0.0, min(1.0, days / denom))
            items.append(EvidenceItem(
                fact=f"{name} contributes {days:.1f} delay-days ({share:.0%} of expected delay).",
                source=_tag("ForecastEngine.delay_breakdown", cat),
                weight=round(share, 4),
            ))
        return items

    def _scope_evidence(self, forecast) -> List[EvidenceItem]:
        if forecast is None:
            return []
        scope_days = float(getattr(forecast, "scope_impact_days", 0.0) or 0.0)
        scope_pct = float(getattr(forecast, "scope_growth_percent", 0.0) or 0.0)
        if scope_days <= 0 and scope_pct <= 0:
            return []
        db = getattr(forecast, "delay_breakdown", None)
        total = float(getattr(db, "expected_delay_days", 0.0) or 0.0) if db else 0.0
        weight = max(
            round(max(0.0, min(1.0, scope_days / max(total, scope_days, 1.0))), 4),
            round(min(1.0, scope_pct / 100.0), 4),
        )
        return [EvidenceItem(
            fact=f"Scope growth adds {scope_days:.1f} delay-days ({scope_pct:.0f}% over baseline).",
            source=_tag("ForecastEngine.scope_impact_days", CAT_SCOPE),
            weight=weight,
        )]

    def _estimation_drift_evidence(self, state) -> List[EvidenceItem]:
        from app.domain.models import WorkItemStatus
        done = {WorkItemStatus.DONE, WorkItemStatus.COMPLETED}
        items = []
        drifted = 0
        for wi in getattr(state, "work_items", []) or []:
            if getattr(wi, "status", None) in done:
                continue
            baseline = getattr(wi, "estimated_effort_hrs", None)
            current = getattr(wi, "current_estimate_hrs", None)
            if baseline is None or current is None or baseline <= 0:
                continue
            if float(current) <= float(baseline) * 1.2:
                continue
            drifted += 1
            pct = (float(current) - float(baseline)) / float(baseline) * 100.0
            items.append(EvidenceItem(
                fact=(f"Item {getattr(wi, 'item_id', '?')} re-estimated from "
                      f"{float(baseline):.0f}h to {float(current):.0f}h (+{pct:.0f}% drift)."),
                source=_tag("WorkItems.estimation_drift", CAT_SCOPE),
                weight=round(min(1.0, (float(current) - float(baseline)) / float(baseline)), 4),
            ))
        if drifted > 2:
            items.append(EvidenceItem(
                fact=f"{drifted} in-flight items have drifted >20% over their baseline estimate.",
                source=_tag("WorkItems.estimation_drift", CAT_SCOPE),
                weight=0.7,
            ))
        return items

    def _risk_driver_evidence(self, risk_result) -> List[EvidenceItem]:
        if risk_result is None:
            return []
        cat_map = {"BLOCKER": CAT_BLOCKER, "DEPENDENCY": CAT_DEPENDENCY,
                   "RESOURCE": CAT_CAPACITY, "SCOPE": CAT_SCOPE, "SCHEDULE": CAT_NEUTRAL}
        items = []
        for d in getattr(risk_result, "top_risk_drivers", None) or []:
            score = float(getattr(d, "score", 0.0) or 0.0)
            if score < self.RISK_EVIDENCE_MIN_SCORE:
                continue
            category = str(getattr(d, "category", "") or "").upper()
            title = getattr(d, "title", None) or category or "Risk"
            desc = getattr(d, "description", "") or ""
            items.append(EvidenceItem(
                fact=f"Risk driver '{title}' (score {score:.0f}/100): {desc}".strip(),
                source=_tag("RiskEngine.top_risk_drivers", cat_map.get(category, CAT_NEUTRAL)),
                weight=round(max(0.0, min(1.0, score / 100.0)), 4),
            ))
        return items

    def _blocker_evidence(self, state) -> List[EvidenceItem]:
        sprint_days = float(getattr(state.project_info, "sprint_duration_days", 14) or 14)
        now = _utcnow()
        items = []
        for b in cc.open_blockers(state):
            severity = getattr(b, "severity", None)
            base_weight = cc.SEVERITY_WEIGHT.get(severity, 0.6)
            raised = getattr(b, "raised_date", None)
            age_sprints = 0.0
            if raised is not None:
                r = raised.replace(tzinfo=None) if getattr(raised, "tzinfo", None) else raised
                age_sprints = ((now.replace(tzinfo=None) - r).days) / sprint_days if sprint_days else 0.0
            bid = getattr(b, "blocker_id", "?")
            if age_sprints > AGED_BLOCKER_SPRINTS:
                weight = min(1.0, base_weight * (age_sprints / 4.0))
                items.append(EvidenceItem(
                    fact=f"Blocker {bid} unresolved for {age_sprints:.1f} sprints (aging risk).",
                    source=_tag("ProjectState.blockers", CAT_BLOCKER),
                    weight=round(weight, 4),
                ))
            else:
                delay = cc.blocker_delay_days(b)
                sev_label = getattr(severity, "value", str(severity))
                desc = getattr(b, "description", None) or bid
                items.append(EvidenceItem(
                    fact=f"Open {sev_label} blocker {bid}: {desc} (~{delay:.0f} delay-days).",
                    source=_tag("ProjectState.blockers", CAT_BLOCKER),
                    weight=round(base_weight, 4),
                ))
        return items

    def _critical_path_pressure_evidence(self, state, critical_path) -> List[EvidenceItem]:
        cp_ids = cc.critical_path_ids(critical_path)
        if not cp_ids:
            return []
        blocked = cc.blocked_item_ids(state)
        ratio = len(blocked & cp_ids) / max(len(cp_ids), 1)
        if ratio <= 0.25:
            return []
        return [EvidenceItem(
            fact=f"{ratio:.0%} of critical-path items are blocked or at risk.",
            source=_tag("CriticalPathEngine.pressure", CAT_DEPENDENCY),
            weight=round(min(1.0, ratio * 1.5), 4),
        )]

    def _velocity_evidence(self, metrics) -> List[EvidenceItem]:
        if metrics is None:
            return []
        trend = cc.velocity_trend_pct(metrics)
        if trend >= -10.0:
            return []
        return [EvidenceItem(
            fact=f"Velocity trend is {trend:.0f}% (declining).",
            source=_tag("MetricsEngine.velocity_trend_pct", CAT_VELOCITY),
            weight=round(max(0.0, min(1.0, abs(trend) / 50.0)), 4),
        )]

    def _resource_load_evidence(self, metrics) -> List[EvidenceItem]:
        if metrics is None:
            return []
        items = []
        for name, load in cc.peak_resource_loads(metrics).items():
            if load <= RESOURCE_EVIDENCE_FLOOR:
                continue
            items.append(EvidenceItem(
                fact=f"Resource {name} peak load ratio {load:.2f} (over {RESOURCE_EVIDENCE_FLOOR}).",
                source=_tag("MetricsEngine.resource_sprint_loads", CAT_CAPACITY),
                weight=round(max(0.0, min(1.0, load / 2.0)), 4),
            ))
        return items

    def _load_concentration_evidence(self, metrics) -> List[EvidenceItem]:
        if metrics is None:
            return []
        devs = cc.developer_metrics(metrics)
        total = sum(float(getattr(d, "remaining_effort_hours", 0.0) or 0.0) for d in devs)
        if total <= 0:
            return []
        items = []
        for d in devs:
            share = float(getattr(d, "remaining_effort_hours", 0.0) or 0.0) / total
            if share <= 0.40:
                continue
            name = getattr(d, "resource_id", None) or getattr(d, "name", "resource")
            items.append(EvidenceItem(
                fact=f"Resource {name} carries {share:.0%} of remaining team effort (concentration risk).",
                source=_tag("MetricsEngine.load_concentration", CAT_CAPACITY),
                weight=round(min(1.0, share * 1.5), 4),
            ))
        return items

    def _skill_mismatch_evidence(self, state) -> List[EvidenceItem]:
        from app.domain.models import WorkItemStatus
        done = {WorkItemStatus.DONE, WorkItemStatus.COMPLETED}
        team = {getattr(r, "resource_id", None): r for r in getattr(state, "team", []) or []}
        by_name = {getattr(r, "name", None): r for r in getattr(state, "team", []) or []}
        count = 0
        for wi in getattr(state, "work_items", []) or []:
            if getattr(wi, "status", None) in done:
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
            if not covers:
                count += 1
        if count <= 0:
            return []
        return [EvidenceItem(
            fact=f"{count} work item(s) assigned to resources without the required skill.",
            source=_tag("WorkItems.skill_mismatch", CAT_CAPACITY),
            weight=round(min(1.0, count / 5.0), 4),
        )]

    def _rework_evidence(self, metrics) -> List[EvidenceItem]:
        if metrics is None:
            return []
        rate = cc.rework_rate(metrics)
        if rate <= 0.05:
            return []
        reopened = cc.reopened_count(metrics)
        return [EvidenceItem(
            fact=f"Rework rate {rate:.0%}: {reopened} item(s) reopened after completion.",
            source=_tag("MetricsEngine.quality_metrics", CAT_QUALITY),
            weight=round(min(1.0, rate * 4.0), 4),
        )]