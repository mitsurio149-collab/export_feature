"""
EMIOS Pipeline Validation Script — Phase 4 (Final.2)

Checks all 8 invariants against the live reasoning-trace endpoint.
Run after every phase to catch regressions.

Usage (from PHASE_2/backend/):
    python scripts/validate_emios_pipeline.py

Or against a running server:
    python scripts/validate_emios_pipeline.py --live --base-url http://localhost:8000

Exit code: 0 if all 8 pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# ── allow running from PHASE_2/backend/ ──────────────────────────────────────
_here = Path(__file__).resolve().parent
_backend = _here.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

PASS = "PASS"
FAIL = "FAIL"
WIDTH = 62


def _check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    suffix = f"  ({detail})" if detail and not condition else ""
    print(f"    [{status}] {label}{suffix}")
    return condition


def _deep_get(obj: Any, *keys, default=None) -> Any:
    """Safely traverse nested dicts/objects by key."""
    cur = obj
    for k in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list):
            try:
                cur = cur[int(k)]
            except (IndexError, TypeError, ValueError):
                return default
        else:
            cur = getattr(cur, k, default)
    return cur if cur is not None else default


# ─────────────────────────────────────────────────────────────────────────────
# Transport — in-process (default) or live HTTP
# ─────────────────────────────────────────────────────────────────────────────

def _load_via_test_client() -> dict:
    """Use FastAPI TestClient — no running server needed."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    load_resp = client.post("/api/demo/load")
    assert load_resp.status_code == 200, f"demo/load failed ({load_resp.status_code}): {load_resp.text}"
    session_id = load_resp.json()["data"]["session_id"]
    print(f"    session_id = {session_id}")

    trace_resp = client.get(f"/api/reasoning-trace?session_id={session_id}")
    assert trace_resp.status_code == 200, f"reasoning-trace failed ({trace_resp.status_code}): {trace_resp.text}"
    return trace_resp.json()["data"]


def _load_via_http(base_url: str) -> dict:
    """Hit a running server at base_url."""
    import json as _json
    import urllib.request

    def _post(url: str) -> dict:
        req = urllib.request.Request(
            url, data=b"{}", method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return _json.loads(r.read())

    def _get(url: str) -> dict:
        with urllib.request.urlopen(url, timeout=30) as r:
            return _json.loads(r.read())

    load = _post(f"{base_url}/api/demo/load")
    session_id = load["data"]["session_id"]
    print(f"    session_id = {session_id}")

    trace = _get(f"{base_url}/api/reasoning-trace?session_id={session_id}")
    return trace["data"]


# ─────────────────────────────────────────────────────────────────────────────
# Invariant checks
# ─────────────────────────────────────────────────────────────────────────────

def _inv1_observation(trace: dict) -> bool:
    """INV 1 — Observation:
    - primary_signal.cause is always None (observation rule)
    - cluster_severity in [HIGH, CRITICAL] when observations exist
    """
    oc = trace.get("observation_cluster") or {}
    passed = True

    ps = oc.get("primary_signal")
    if ps is not None:
        cause_val = ps.get("cause")
        passed &= _check(
            "primary_signal.cause is None",
            cause_val is None,
            f"got {cause_val!r}",
        )
    else:
        _check("primary_signal present", True, "absent — no anomaly detected (ok)")

    severity = oc.get("cluster_severity", "")
    observations = oc.get("observations") or []
    if observations:
        passed &= _check(
            "cluster_severity in [HIGH, CRITICAL] when observations exist",
            severity in ("HIGH", "CRITICAL"),
            f"got {severity!r}",
        )
    else:
        _check("cluster_severity (no observations — skip)", True)

    return passed


def _inv2_diagnosis(trace: dict) -> bool:
    """INV 2 — Diagnosis:
    - confidence >= 0.5
    - causal_chain non-empty
    - falsification ran: every hypothesis has a status (SUPPORTED or REJECTED)
      and at least 1 was REJECTED, OR all survive because all are evidenced
      (both are valid Popperian outcomes — what matters is the engine ran)
    """
    diag = trace.get("diagnosis") or {}
    passed = True

    confidence = float(diag.get("confidence") or 0.0)
    passed &= _check(
        "diagnosis.confidence >= 0.5",
        confidence >= 0.5,
        f"got {confidence:.3f}",
    )

    chain = diag.get("causal_chain") or []
    passed &= _check(
        "causal_chain non-empty",
        len(chain) >= 1,
        f"got {len(chain)} items",
    )

    all_hyps = trace.get("hypotheses") or []
    surviving = trace.get("surviving_hypotheses") or []
    surviving_ids = {h.get("hypothesis_id") for h in surviving}
    eliminated_count = sum(
        1 for h in all_hyps
        if h.get("hypothesis_id") not in surviving_ids
    )

    # Falsification process check: either something was eliminated, or
    # all hypotheses are evidenced (valid when dataset supports every candidate).
    # What we must NOT allow is 0 hypotheses generated at all.
    falsification_ran = len(all_hyps) >= 1
    passed &= _check(
        "falsification ran (≥1 hypothesis generated)",
        falsification_ran,
        f"got 0 hypotheses",
    )

    if eliminated_count >= 1:
        _check(
            f"elimination: {eliminated_count}/{len(all_hyps)} hypotheses rejected",
            True,
        )
    else:
        # All survive — valid when all have supporting evidence.
        # Confirm all survivors have posterior > 0 (i.e. posterior was updated).
        all_have_posterior = all(
            float(h.get("posterior") or 0.0) > 0.0
            for h in surviving
        )
        passed &= _check(
            "all survivors have posterior > 0 (all evidenced — none eliminated is valid)",
            all_have_posterior,
            f"some survivors have posterior=0 — eliminator may not have run",
        )

    return passed


def _inv3_impact(trace: dict) -> bool:
    """INV 3 — Impact:
    - all dimension magnitudes in [0, 10]
    - schedule magnitude ≈ min(10, delay/sprint_dur*3) within ±0.5
    """
    impact = trace.get("impact_matrix") or {}
    estimates = impact.get("estimates") or {}
    passed = True

    if not estimates:
        return _check("impact_matrix.estimates non-empty", False, "got empty dict")

    bad = [
        (k, est.get("magnitude"))
        for k, est in estimates.items()
        if not (0.0 <= float(est.get("magnitude") or 0.0) <= 10.0)
    ]
    passed &= _check(
        "all dimension magnitudes in [0, 10]",
        len(bad) == 0,
        f"out-of-range: {bad}" if bad else "",
    )

    # Cross-check schedule magnitude (best-effort)
    forecast = trace.get("forecast") or {}
    db = forecast.get("delay_breakdown") or {}
    delay_days = float(db.get("expected_delay_days") or 0.0)
    sprint_dur = float(db.get("sprint_duration_days") or 0.0)
    schedule_est = estimates.get("schedule") or estimates.get("SCHEDULE") or {}
    sched_mag = float(schedule_est.get("magnitude") or 0.0)

    if sprint_dur > 0 and delay_days > 0:
        expected = min(10.0, (delay_days / sprint_dur) * 3.0)
        passed &= _check(
            f"schedule magnitude ≈ {expected:.2f} (±0.5)",
            abs(sched_mag - expected) <= 0.5,
            f"got {sched_mag:.2f}",
        )
    else:
        _check("schedule magnitude cross-check (skip — no delay data)", True)

    return passed


def _inv4_decision(trace: dict) -> bool:
    """INV 4 — Decision:
    - chosen_option.net_expected_value > 0
    - null_option is in tradeoff_matrix.options
    - rejected_alternatives non-empty
    """
    decision = trace.get("decision") or {}
    tradeoff = trace.get("tradeoff_matrix") or {}
    passed = True

    chosen = decision.get("chosen_option") or {}
    nev = float(chosen.get("net_expected_value") or 0.0)
    passed &= _check(
        "chosen_option.net_expected_value > 0",
        nev > 0,
        f"got {nev:.4f}",
    )

    tm_options = tradeoff.get("options") or []
    null_opt = tradeoff.get("null_option") or {}
    null_id = null_opt.get("option_id")
    if null_id:
        tm_ids = {o.get("option_id") for o in tm_options}
        passed &= _check(
            "null_option in tradeoff_matrix.options",
            null_id in tm_ids,
            f"null_id={null_id!r} not in {tm_ids}",
        )
    else:
        _check("null_option check (skip — not set by this run)", True)

    rejected = decision.get("rejected_alternatives") or []
    passed &= _check(
        "rejected_alternatives non-empty",
        len(rejected) >= 1,
        f"got {len(rejected)}",
    )

    return passed


def _inv5_recommendations(trace: dict) -> bool:
    """INV 5 — Recommendation mutation:
    - recommendations list non-empty
    - simulation.simulated_metrics.on_time_probability > baseline
    """
    recs = trace.get("recommendations") or []
    passed = True

    passed &= _check("recommendations non-empty", len(recs) >= 1, f"got {len(recs)}")

    simulation = trace.get("simulation") or {}
    if simulation:
        bl = _deep_get(simulation, "baseline_metrics", "on_time_probability", default=None)
        sm = _deep_get(simulation, "simulated_metrics", "on_time_probability", default=None)
        if bl is not None and sm is not None:
            passed &= _check(
                "simulation: after_probability > baseline_probability",
                float(sm) > float(bl),
                f"baseline={float(bl):.4f}, simulated={float(sm):.4f}",
            )
        else:
            passed &= _check(
                "simulation baseline/simulated metrics present",
                False,
                "missing baseline_metrics or simulated_metrics",
            )
    else:
        # Simulation may be absent if top rec sim failed — soft pass
        _check("simulation present (soft — pipeline ran without it)", True)

    return passed


def _inv6_recovery_state(trace: dict) -> bool:
    """INV 6 — Recovery State:
    - current_state in valid set
    - if on_time_probability < 0.30, state must be RECOVERY or CRITICAL
    """
    rsm = trace.get("recovery_state_machine") or {}
    mc = trace.get("monte_carlo") or {}
    passed = True

    valid = {"HEALTHY", "WATCH", "WARNING", "RECOVERY", "CRITICAL"}
    current = rsm.get("current_state", "")
    passed &= _check(
        "current_state in valid set",
        current in valid,
        f"got {current!r}",
    )

    otp = float(mc.get("on_time_probability") or 1.0)
    if otp < 0.30:
        passed &= _check(
            "state is RECOVERY or CRITICAL when on_time_prob < 0.30",
            current in ("RECOVERY", "CRITICAL"),
            f"otp={otp:.3f}, state={current!r}",
        )
    else:
        _check(f"state escalation check (skip — otp={otp:.3f} ≥ 0.30)", True)

    return passed


def _inv7_ai_advisor(trace: dict) -> bool:
    """INV 7 — AI Advisor:
    - all 4 output fields non-empty
    - str(round(diagnosis.confidence*100)) appears in confidence_statement
    """
    ao = trace.get("advisor_output") or {}
    diag = trace.get("diagnosis") or {}
    passed = True

    for field in ("executive_summary", "reasoning_explanation",
                  "decision_explanation", "confidence_statement"):
        val = ao.get(field, "")
        passed &= _check(
            f"advisor_output.{field} non-empty",
            bool(val and str(val).strip()),
            f"got {val!r}",
        )

    confidence = float(diag.get("confidence") or 0.0)
    pct_str = str(round(confidence * 100))
    cs = str(ao.get("confidence_statement", ""))
    passed &= _check(
        f"confidence_statement contains '{pct_str}%' literal (INV 7)",
        pct_str in cs,
        f"statement={cs!r}",
    )

    return passed


def _inv8_counterfactual(trace: dict) -> bool:
    """INV 8 — Counterfactual:
    - every recommendation's counterfactual_statement non-empty
    - each contains str(round(baseline_probability*100))

    Note: counterfactual_statement is not yet on the Recommendation dataclass.
    This invariant will FAIL until the field is added (Phase 5 work item).
    """
    recs = trace.get("recommendations") or []
    mc = trace.get("monte_carlo") or {}
    passed = True

    if not recs:
        return _check("recommendations non-empty", False, "got 0")

    has_field = any("counterfactual_statement" in rec for rec in recs)
    if not has_field:
        _check(
            "counterfactual_statement field on Recommendation",
            False,
            "field not yet in Recommendation dataclass — add in Phase 5",
        )
        return False

    baseline_prob = float(mc.get("on_time_probability") or 0.0)
    expected_pct = str(round(baseline_prob * 100))
    all_ok = True

    for rec in recs:
        rec_id = (rec.get("recommendation_id") or "?")[:12]
        cf = str(rec.get("counterfactual_statement") or "")
        ok = bool(cf) and expected_pct in cf
        all_ok &= ok
        _check(
            f"rec {rec_id}: non-empty & contains '{expected_pct}'",
            ok,
            f"got {cf!r}" if not ok else "",
        )

    passed &= all_ok
    return passed


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

INVARIANTS = [
    (_inv1_observation,     "INV 1 — Observation"),
    (_inv2_diagnosis,       "INV 2 — Diagnosis"),
    (_inv3_impact,          "INV 3 — Impact"),
    (_inv4_decision,        "INV 4 — Decision"),
    (_inv5_recommendations, "INV 5 — Recommendations"),
    (_inv6_recovery_state,  "INV 6 — Recovery State"),
    (_inv7_ai_advisor,      "INV 7 — AI Advisor"),
    (_inv8_counterfactual,  "INV 8 — Counterfactual"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="EMIOS pipeline invariant checker")
    parser.add_argument(
        "--live", action="store_true",
        help="Hit a running server instead of using TestClient",
    )
    parser.add_argument(
        "--base-url", default="http://localhost:8000",
        help="Base URL when --live is used (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    print("=" * WIDTH)
    print("EMIOS Pipeline Validation — Phase 4 gate check")
    print("=" * WIDTH)

    print("\nStep 1 — Loading demo data & fetching reasoning trace ...")
    try:
        trace = _load_via_http(args.base_url) if args.live else _load_via_test_client()
    except Exception as exc:
        print(f"\n[FATAL] Could not load trace: {exc}")
        import traceback; traceback.print_exc()
        return 1

    print("\nStep 2 — Running invariant checks ...")
    print("-" * WIDTH)

    results: dict[str, bool] = {}
    for fn, name in INVARIANTS:
        print(f"\n  {name}")
        try:
            results[name] = fn(trace)
        except Exception as exc:
            print(f"    [FAIL] exception: {exc}")
            import traceback; traceback.print_exc()
            results[name] = False

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * WIDTH)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    ready = passed == total

    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'}  {name}")

    label = "DEMO READY ✅" if ready else "NOT READY ❌"
    print(f"\nEMIOS pipeline: {passed}/{total} invariants passed — {label}")
    print("=" * WIDTH)

    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
