"""
Reasoning trace route — Phase 3 / Final.1 + Phase 7 AI wiring.

Returns the full PipelineResult as JSON so the frontend ReasoningTrace
component (Phase 5) and the validate_emios_pipeline.py gate script (Phase 4)
can inspect the complete reasoning chain.

Phase 7 addition: after the sync pipeline runs, the advisor_output field is
upgraded from the deterministic template to a live Bosch LLM Farm response
via EMIOSAdvisor.run_with_ai(), using the AI credentials from .env.
Falls back to the template automatically on any network/parse failure.
"""
import asyncio
import dataclasses
import enum
import datetime as _dt
import logging

from fastapi import APIRouter, HTTPException, Query

from app.api.models import ApiResponse
from app.engines.emios_advisor_runtime import _upgrade_advisor_with_ai
from app.storage.session_store import get_or_build_pipeline_result, store as session_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Reasoning Trace"])


def _safe_serialize(obj, _seen=None):
    """
    Recursively convert a PipelineResult (and arbitrary nested objects) into
    a JSON-serialisable structure.

    Deliberately avoids dataclasses.asdict(), which internally deep-copies
    every field — if any nested object isn't copyable (e.g. holds a lock,
    generator, or other non-copyable attribute) asdict() raises and the
    whole endpoint 500s. Walking the structure by hand sidesteps that.
    """
    if _seen is None:
        _seen = set()

    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, enum.Enum):
        return obj.value

    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()

    obj_id = id(obj)
    if obj_id in _seen:
        return None  # break reference cycles
    _seen = _seen | {obj_id}

    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v, _seen) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_safe_serialize(v, _seen) for v in obj]

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out = {}
        for f in dataclasses.fields(obj):
            try:
                out[f.name] = _safe_serialize(getattr(obj, f.name), _seen)
            except Exception as exc:
                out[f.name] = f"<unserializable: {exc}>"
        return out

    if hasattr(obj, "model_dump"):
        try:
            return _safe_serialize(obj.model_dump(exclude_none=True), _seen)
        except Exception:
            pass

    if hasattr(obj, "__dict__"):
        out = {}
        for k, v in vars(obj).items():
            if k.startswith("_"):
                continue
            try:
                out[k] = _safe_serialize(v, _seen)
            except Exception as exc:
                out[k] = f"<unserializable: {exc}>"
        return out

    try:
        return str(obj)
    except Exception:
        return None


@router.get("/reasoning-trace")
async def get_reasoning_trace(session_id: str = Query(...)):
    """
    Return the complete PipelineResult for a session as a JSON dict,
    with advisor_output populated by the Bosch LLM Farm (GPT-4o Mini).

    Used by:
    - Frontend ReasoningTrace.jsx (Phase 5)
    - scripts/validate_emios_pipeline.py INV checks (Phase 4)
    """
    try:
        result = get_or_build_pipeline_result(session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to compute reasoning trace: {exc}",
        )

    # Phase 7: upgrade advisor_output with live Bosch LLM Farm response.
    # This runs every time so the advisor always reflects the latest state.
    # Falls back silently to the deterministic template on any failure.
    await _upgrade_advisor_with_ai(result)

    try:
        data = _safe_serialize(result)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to serialize pipeline result: {exc}",
        )

    return ApiResponse(
        success=True,
        message="Reasoning trace retrieved",
        data=data,
    )

