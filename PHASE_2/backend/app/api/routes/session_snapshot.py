"""
Session snapshot route.

Returns forecast + Monte Carlo + risk summary + reasoning trace keys in a
single call, so the Dashboard Overview tab doesn't need 4-5 separate requests.

GET /api/session-snapshot?session_id=<id>
"""
import logging
from datetime import datetime, timezone
from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict, Optional

from app.api.models import ApiResponse
from app.engines.emios_advisor_runtime import _upgrade_advisor_with_ai
from app.storage.session_store import get_or_build_pipeline_result, store
from app.engines.pmo_kpi_engine import PMOKpiEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Session Snapshot"])


def _safe_val(obj: Any, *attrs, default=None):
    """Safely chain attribute access."""
    for attr in attrs:
        if obj is None:
            return default
        obj = getattr(obj, attr, None)
    return obj if obj is not None else default


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)


def _derive_urgency_window(state: Any) -> Optional[str]:
    """Infer a decision urgency from the oldest blocker age relative to sprint length."""
    if state is None:
        return None

    sprint_days = _safe_val(state, "project_info", "sprint_duration_days") or 14
    blockers = getattr(state, "blockers", None) or []
    if not blockers:
        return "No immediate decision needed"

    oldest_raised = None
    for blocker in blockers:
        raised = getattr(blocker, "raised_date", None)
        if raised is None:
            continue
        if oldest_raised is None or raised < oldest_raised:
            oldest_raised = raised

    if oldest_raised is None:
        return "No immediate decision needed"

    if isinstance(oldest_raised, str):
        try:
            oldest_raised = datetime.fromisoformat(oldest_raised)
        except Exception:
            return "No immediate decision needed"

    if getattr(oldest_raised, "tzinfo", None) is None:
        oldest_raised = oldest_raised.replace(tzinfo=timezone.utc)

    try:
        age_days = (datetime.now(oldest_raised.tzinfo) - oldest_raised).days
    except Exception:
        age_days = 0

    if age_days >= sprint_days:
        return "Overdue — resolve immediately"
    if age_days >= sprint_days * 0.5:
        return "This sprint"
    return "Next sprint"


@router.get("/session-snapshot")
async def get_session_snapshot(session_id: str = Query(...)):
    """
    Single-call snapshot of forecast, Monte Carlo, risk, and project summary.

    Replaces the 4–5 parallel API calls the Dashboard Overview makes on load:
      - GET /api/forecast
      - GET /api/monte-carlo
      - GET /api/risk
      - GET /api/reasoning-trace  (for EMIOS strip)

    All data is read from the stored PipelineResult — zero engine re-runs.
    """
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        result = get_or_build_pipeline_result(session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await _upgrade_advisor_with_ai(result)

    # ── Monte Carlo ───────────────────────────────────────────────────────────
    mc = _safe_val(result, "monte_carlo")
    mc_data: Dict = {}
    if mc:
        mc_data = {
            "on_time_probability": _safe_val(mc, "on_time_probability"),
            "on_time_risk_level": (
                _safe_val(mc, "on_time_risk_level", "value")
                or str(_safe_val(mc, "on_time_risk_level") or "")
            ),
            "simulation_count": _safe_val(mc, "simulation_count"),
            "most_likely_finish_date": _iso(_safe_val(mc, "most_likely_finish_date")),
            "p80_finish_date": _iso(_safe_val(mc, "p80_finish_date")),
            "p90_finish_date": _iso(_safe_val(mc, "p90_finish_date")),
            "p95_finish_date": _iso(_safe_val(mc, "p95_finish_date")),
            "best_case_finish_date": _iso(_safe_val(mc, "best_case_finish_date")),
            "target_end_date": _iso(_safe_val(mc, "target_end_date")),
            "statistics": {
                "percentile_50": _iso(_safe_val(mc, "statistics", "percentile_50")
                                      if hasattr(mc, "statistics") else None),
                "percentile_80": _iso(_safe_val(mc, "statistics", "percentile_80")
                                      if hasattr(mc, "statistics") else None),
                "percentile_95": _iso(_safe_val(mc, "statistics", "percentile_95")
                                      if hasattr(mc, "statistics") else None),
            } if hasattr(mc, "statistics") and mc.statistics else {},
        }

    # ── Forecast ──────────────────────────────────────────────────────────────
    forecast = _safe_val(result, "forecast")
    forecast_data: Dict = {}
    if forecast:
        forecast_data = {
            "expected_delay_days": _safe_val(forecast, "expected_delay_days"),
            "expected_finish_date": _iso(_safe_val(forecast, "expected_finish_date")),
            "target_end_date": _iso(_safe_val(forecast, "target_end_date")),
            "scope_growth_percent": _safe_val(forecast, "scope_growth_percent"),
            "schedule_diagnostics": (
                {
                    "base_schedule_days": _safe_val(forecast.schedule_diagnostics, "base_schedule_days"),
                    "spillover_days": _safe_val(forecast.schedule_diagnostics, "spillover_days"),
                    "blocker_days": _safe_val(forecast.schedule_diagnostics, "blocker_days"),
                    "critical_path_days": _safe_val(forecast.schedule_diagnostics, "critical_path_days"),
                }
                if hasattr(forecast, "schedule_diagnostics") and forecast.schedule_diagnostics
                else None
            ),
        }

    # ── Risk summary ─────────────────────────────────────────────────────────
    risk = _safe_val(result, "risk_result")
    risk_data: Dict = {}
    if risk:
        risk_data = {
            "overall_risk_score": round(_safe_val(risk, "overall_risk_score") or 0),
            "overall_risk_level": (
                _safe_val(risk, "overall_risk_level", "value")
                or str(_safe_val(risk, "overall_risk_level") or "")
            ),
        }

    # ── EMIOS reasoning strip (lightweight — just the fields Overview needs) ─
    diagnosis = _safe_val(result, "diagnosis")
    decision = _safe_val(result, "decision")
    rsm = _safe_val(result, "recovery_state_machine")
    advisor = _safe_val(result, "advisor_output")

    emios_strip: Dict = {}
    if diagnosis:
        raw_root_cause = _safe_val(diagnosis, "root_cause")
        emios_strip["urgency_window"] = _derive_urgency_window(session.project_state)
        # diagnosis.root_cause is a 2-sentence narrative, e.g.
        # "Resource over-allocation (...) is the root cause. Rebalance load or add capacity."
        # The 2nd sentence is an action recommendation that can differ from (and visually
        # collide with) the separate `chosen_action` recommendation rendered below, so we
        # only surface the causal statement here and let `chosen_action` own "what to do".
        if raw_root_cause and ". " in raw_root_cause:
            emios_strip["root_cause"] = raw_root_cause.split(". ", 1)[0] + "."
        else:
            emios_strip["root_cause"] = raw_root_cause
        conf = _safe_val(diagnosis, "confidence")
        emios_strip["confidence_pct"] = round(conf * 100) if conf is not None else None

    if decision:
        chosen = _safe_val(decision, "chosen_option")
        emios_strip["chosen_action"] = (
            _safe_val(chosen, "label") or _safe_val(chosen, "name") if chosen else None
        )

    if rsm:
        emios_strip["recovery_state"] = _safe_val(rsm, "current_state")

    if advisor:
        # executive_summary restates root_cause + action (already shown above), so it's
        # dropped from the Overview strip to avoid a 3rd repetition. reasoning_explanation
        # ("what the engine ruled out") is genuinely new content, not shown elsewhere on
        # Overview, so that's what we surface instead.
        emios_strip["reasoning_explanation"] = _safe_val(advisor, "reasoning_explanation")

    blocker_metrics_data: Dict = {}
    blocker_metrics = None
    if getattr(result, "metrics", None) is not None:
        blocker_metrics = getattr(result.metrics, "blocker_metrics", None)
    if blocker_metrics is not None:
        blocker_metrics_data = blocker_metrics.model_dump() if hasattr(blocker_metrics, "model_dump") else {}

    # ── Baseline snapshot (stored on session at prewarm time) ─────────────────
    baseline = getattr(session, "baseline_snapshot", None) or {}

    # ── Historical analysis summary ───────────────────────────────────────────
    hist = _safe_val(result, "historical_analysis")
    hist_data: Dict = {}
    if hist:
        overbilling = getattr(hist, "overbilling", []) or []
        spillover = getattr(hist, "spillover", []) or []
        recurring = getattr(hist, "recurring_blockers", []) or []
        prevention = getattr(hist, "prevention_recommendations", []) or []

        hist_data = {
            "sprints_analysed": getattr(hist, "sprints_analysed", 0),
            "summary": getattr(hist, "summary", ""),
            "overbilling_count": len(overbilling),
            "spillover_count": len(spillover),
            "recurring_blocker_count": len(recurring),
            "top_overbilling": [
                {
                    "item_id": o.item_id,
                    "item_title": getattr(o, "item_title", ""),
                    "sprint_id": getattr(o, "sprint_id", ""),
                    "estimated_hrs": o.estimated_hrs,
                    "actual_hrs": o.actual_hrs,
                    "overrun_pct": round(o.overrun_pct * 100, 1),
                    "assigned_to": getattr(o, "assigned_to", ""),
                }
                for o in sorted(overbilling, key=lambda x: x.overrun_pct, reverse=True)[:5]
            ],
            "top_spillover": [
                {
                    "item_id": s.item_id,
                    "item_title": getattr(s, "item_title", ""),
                    "original_sprint": s.original_sprint,
                    "landed_sprint": s.landed_sprint,
                    "sprints_delayed": s.sprints_delayed,
                    "reason_category": s.reason_category,
                }
                for s in spillover[:5]
            ],
            "recurring_blockers": [
                {
                    "category": b.category,
                    "occurrences": b.occurrences,
                    "total_delay_days": b.total_delay_days,
                    "was_resolved_permanently": b.was_resolved_permanently,
                    "recurrence_verdict": b.recurrence_verdict,
                }
                for b in recurring
            ],
            "prevention_recommendations": [
                {
                    "trigger": r.trigger,
                    "action": r.action,
                    "sprint_to_apply": r.sprint_to_apply,
                    "confidence": r.confidence,
                    "evidence": r.evidence[:3] if r.evidence else [],
                }
                for r in prevention
            ],
        }

    # ── Learning calibration summary ──────────────────────────────────────────
    lr = _safe_val(result, "learning_record")
    learning_data: Dict = {}
    if lr:
        learning_data = {
            "forecast_probability": _safe_val(lr, "forecast_probability"),
            "actual_outcome": _safe_val(lr, "actual_outcome"),
            "brier_score": _safe_val(lr, "brier_score"),
            "velocity_estimate_bias": _safe_val(lr, "velocity_estimate_bias"),
            "calibration_note": _safe_val(lr, "calibration_note"),
            "diagnosis_accuracy": _safe_val(lr, "diagnosis_accuracy"),
        }

    # ── PMO KPI suite ─────────────────────────────────────────────────────────
    # Computed from ProjectAnalysis (the shared cached engine outputs), not from
    # PipelineResult, so it's always consistent with /forecast. Isolated
    # try/except: failure must never suppress the rest of the snapshot.
    pmo_kpi_data: Dict = {}
    try:
        analysis = store.get_analysis(session_id)
        if analysis:
            pmo_suite = PMOKpiEngine(
                project_state=analysis.project_state,
                metrics=analysis.metrics,
                forecast_result=analysis.forecast,
                cp_result=analysis.cp_result,
            ).calculate()
            pmo_kpi_data = pmo_suite.model_dump()
    except Exception as _pmo_exc:
        logger.warning(
            "PMOKpiEngine failed in session_snapshot for %s: %s",
            session_id,
            _pmo_exc,
            exc_info=True,
        )

    return ApiResponse(
        success=True,
        message="Session snapshot retrieved",
        data={
            "monte_carlo": mc_data,
            "forecast": forecast_data,
            "risk": risk_data,
            "blocker_metrics": blocker_metrics_data,
            "emios_strip": emios_strip,
            "baseline_snapshot": baseline,
            "historical": hist_data,
            "learning": learning_data,
            "pmo_kpi": pmo_kpi_data,
        },
    )
