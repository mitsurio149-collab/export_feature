"""
EvidenceMapper — projects Sprint Whisperer engine outputs into an EvidenceBundle
(EMIOS Stage 3: Evidence Collection).

Reads already-computed facts and copies them into immutable EvidenceItem records.
Computes nothing new — it only reshapes existing outputs into evidence the
hypothesis/diagnosis stages can consume. Every item is sourced, weighted, and
timestamped.

Weighting convention (0-1, higher = stronger evidence):
  - delay_breakdown components: weight scales with the share of total delay
    the component accounts for (a component causing most of the delay is
    stronger evidence than a marginal one).
  - risk drivers: weight = driver.score / 100 (RiskDriver.score is 0-100).
  - open blockers: weight scales with severity (Critical=1.0 down to Low=0.4).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from app.domain.models import ProjectState, BlockerStatus, BlockerSeverity
from app.domain.emios_models import EvidenceBundle, EvidenceItem
from app.pipeline.emios_pipeline import PipelineResult


_SEVERITY_WEIGHT = {
    BlockerSeverity.CRITICAL: 1.0,
    BlockerSeverity.HIGH: 0.8,
    BlockerSeverity.MEDIUM: 0.6,
    BlockerSeverity.LOW: 0.4,
}


class EvidenceMapper:
    """Projects PipelineResult (+ its ProjectState) into an EvidenceBundle."""

    def __init__(self, project_state: Optional[ProjectState] = None) -> None:
        # ProjectState is needed for the open-blocker evidence; if the caller
        # doesn't have it separately it can be attached to PipelineResult.
        self._project_state = project_state

    def map_sprint_whisperer_to_evidence(self, result: PipelineResult) -> EvidenceBundle:
        """Build an EvidenceBundle from a completed Sprint Whisperer pipeline run."""
        now = datetime.now(timezone.utc)
        items: List[EvidenceItem] = []

        items.extend(self._delay_breakdown_evidence(result, now))
        items.extend(self._scope_evidence(result, now))
        items.extend(self._risk_driver_evidence(result, now))
        items.extend(self._open_blocker_evidence(result, now))

        return EvidenceBundle(
            bundle_id=f"evb-{uuid4().hex[:10]}",
            triggered_by_observation_ids=[],
            items=items,
            collected_at=now,
        )

    # --- delay_breakdown: one item per component > 0 -----------------------
    def _delay_breakdown_evidence(self, result: PipelineResult, now: datetime) -> List[EvidenceItem]:
        forecast = result.forecast
        if forecast is None or getattr(forecast, "delay_breakdown", None) is None:
            return []

        db = forecast.delay_breakdown
        total = float(getattr(db, "expected_delay_days", 0.0) or 0.0)
        # Denominator for weight-share: use total delay, or the summed positive
        # components if total is non-positive (project on/ahead of schedule but
        # individual buckets still informative).
        components = {
            "base work": float(getattr(db, "remaining_days_base_work", 0.0) or 0.0),
            "blocker velocity loss": float(getattr(db, "remaining_days_blocker_loss", 0.0) or 0.0),
            "spillover": float(getattr(db, "remaining_days_spillover", 0.0) or 0.0),
        }
        positive = {name: v for name, v in components.items() if v > 0.0}
        if not positive:
            return []
        denom = total if total > 0 else sum(positive.values())
        denom = denom or 1.0

        items: List[EvidenceItem] = []
        for name, days in positive.items():
            share = max(0.0, min(1.0, days / denom))
            items.append(EvidenceItem(
                fact=f"{name.capitalize()} contributes {days:.1f} delay-days "
                     f"({share:.0%} of expected delay).",
                source="ForecastEngine.delay_breakdown",
                weight=round(share, 4),
                timestamp=now,
            ))
        return items

    # --- scope growth: one item when scope_impact_days > 0 -----------------
    def _scope_evidence(self, result: PipelineResult, now: datetime) -> List[EvidenceItem]:
        """Scope growth evidence. delay_breakdown has NO scope bucket, so this
        reads forecast.scope_impact_days directly. Without it, Phase 2's SCOPE
        hypothesis has no supporting evidence and gets eliminated prematurely
        even when scope creep is real."""
        forecast = result.forecast
        if forecast is None:
            return []
        scope_days = float(getattr(forecast, "scope_impact_days", 0.0) or 0.0)
        if scope_days <= 0:
            return []
        db = getattr(forecast, "delay_breakdown", None)
        total = float(getattr(db, "expected_delay_days", 0.0) or 0.0) if db else 0.0
        weight = round(max(0.0, min(1.0, scope_days / max(total, scope_days, 1.0))), 4)
        return [EvidenceItem(
            fact=f"Scope growth adds {scope_days:.1f} delay-days to the forecast.",
            source="ForecastEngine.scope_impact_days",
            weight=weight,
            timestamp=now,
        )]

    # --- top risk drivers: one item per driver -----------------------------
    def _risk_driver_evidence(self, result: PipelineResult, now: datetime) -> List[EvidenceItem]:
        risk = result.risk_result
        if risk is None:
            return []
        # RiskResult exposes top_risk_drivers: List[RiskDriver] (see NOTE 2).
        drivers = getattr(risk, "top_risk_drivers", None) or []
        items: List[EvidenceItem] = []
        for d in drivers:
            score = float(getattr(d, "score", 0.0) or 0.0)  # 0-100
            title = getattr(d, "title", None) or getattr(d, "category", "Risk")
            desc = getattr(d, "description", "") or ""
            items.append(EvidenceItem(
                fact=f"Risk driver '{title}' (score {score:.0f}/100): {desc}".strip(),
                source="RiskEngine.top_risk_drivers",
                weight=round(max(0.0, min(1.0, score / 100.0)), 4),
                timestamp=now,
            ))
        return items

    # --- open blockers: one item per open blocker in ProjectState ----------
    def _open_blocker_evidence(self, result: PipelineResult, now: datetime) -> List[EvidenceItem]:
        state = self._project_state or getattr(result, "project_state", None)
        if state is None:
            return []
        items: List[EvidenceItem] = []
        for b in getattr(state, "blockers", []) or []:
            # Open == no actual_resolution_date (matches MetricsEngine's own test),
            # also honor an explicit status field if present.
            status = getattr(b, "status", None)
            resolved = getattr(b, "actual_resolution_date", None) is not None
            is_open = (status == BlockerStatus.OPEN) or (status is None and not resolved)
            if not is_open:
                continue
            severity = getattr(b, "severity", BlockerSeverity.MEDIUM)
            weight = _SEVERITY_WEIGHT.get(severity, 0.6)
            desc = getattr(b, "description", None) or getattr(b, "blocker_id", "blocker")
            sev_label = getattr(severity, "value", str(severity))
            items.append(EvidenceItem(
                fact=f"Open {sev_label} blocker: {desc}",
                source="ProjectState.blockers",
                weight=round(weight, 4),
                timestamp=now,
            ))
        return items
