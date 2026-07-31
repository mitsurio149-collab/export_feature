"""
Forecast Trend Route.

GET /api/forecast-trend?session_id=<id>

Returns the time-series of forecast snapshots captured on every fresh
analysis build for this session (upload, scope change, recovery plan apply).
Each entry carries timestamped P50 / P80 / P95 dates and on-time probability
so the UI can show direction-of-travel: is the project getting better or worse?
"""
from fastapi import APIRouter, HTTPException, Query

from app.api.models import ApiResponse, ErrorCodes
from app.storage.session_store import store

router = APIRouter(prefix="/api", tags=["Forecast Trend"])


@router.get("/forecast-trend")
async def get_forecast_trend(
    session_id: str = Query(..., description="Session ID"),
) -> dict:
    """
    Time-series of forecast snapshots for this session.

    Each snapshot is recorded whenever a fresh analysis is built — typically
    once per sprint close when a new workbook is uploaded. Returns up to 12
    entries (12 sprints of history), oldest first.

    Fields per entry:
        recorded_at          ISO-8601 timestamp
        label                Sprint label derived from current_sprint_number ("Sprint 6", etc.)
        completed_sprints    How many sprints were closed at time of this run
        current_sprint_num   The in-progress sprint number at time of this run
        p50_date             Median finish date (ISO)
        p80_date             80th-percentile finish date (ISO)
        p95_date             95th-percentile finish date (ISO)
        on_time_probability  Fraction 0–1
        expected_delay_days  Deterministic delay
        target_end_date      Project target (ISO) — same across all entries
    """
    session_id = session_id.strip()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.SESSION_NOT_FOUND,
                message=f"Session {session_id} not found",
            ).model_dump(mode="json"),
        )

    history = store.get_forecast_history(session_id)

    # Compute deltas between consecutive entries so the UI gets
    # pre-computed direction arrows without doing date arithmetic in JS.
    enriched = []
    for i, entry in enumerate(history):
        e = dict(entry)
        if i > 0:
            prev = history[i - 1]
            e["p80_delta_days"] = _date_delta_days(e.get("p80_date"), prev.get("p80_date"))
            e["p50_delta_days"] = _date_delta_days(e.get("p50_date"), prev.get("p50_date"))
            e["on_time_delta"]  = _round(
                (e.get("on_time_probability") or 0) - (prev.get("on_time_probability") or 0)
            )
        else:
            e["p80_delta_days"] = None
            e["p50_delta_days"] = None
            e["on_time_delta"]  = None
        enriched.append(e)

    return ApiResponse(
        success=True,
        message="Forecast trend retrieved",
        data={
            "entries": enriched,
            "entry_count": len(enriched),
        },
    ).model_dump()


def _date_delta_days(current_iso, previous_iso) -> float | None:
    """
    Positive = finish date moved later (worse).
    Negative = finish date moved earlier (better).
    """
    if not current_iso or not previous_iso:
        return None
    try:
        from datetime import datetime, timezone
        fmt = "%Y-%m-%dT%H:%M:%S%z" if "T" in current_iso else "%Y-%m-%d"
        def _parse(s):
            try:
                return datetime.fromisoformat(s)
            except Exception:
                return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        delta = (_parse(current_iso) - _parse(previous_iso)).total_seconds() / 86400
        return round(delta, 1)
    except Exception:
        return None


def _round(v) -> float | None:
    try:
        return round(float(v), 4)
    except Exception:
        return None
