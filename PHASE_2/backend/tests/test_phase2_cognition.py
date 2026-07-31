"""
Tests for EMIOS Phase 2 (Stages 3-6): Evidence, Hypotheses, Elimination, RCA.

Uses SimpleNamespace fakes so the suite is fast and hermetic. Real domain enums
(BlockerStatus/BlockerSeverity) are used so cognition_common's helpers behave
exactly as in production.
"""
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta

import pytest

from app.domain.models import BlockerStatus, BlockerSeverity
from app.domain.emios_models import ValidationResult, HypothesisStatus
from app.engines.evidence_collector import EvidenceCollector
from app.engines.hypothesis_generator import HypothesisGenerator, hypothesis_category, NULL, BLOCKER
from app.engines.hypothesis_eliminator import HypothesisEliminator
from app.engines.root_cause_analyzer import RootCauseAnalyzer


# ---- fakes ---------------------------------------------------------------
def _delay_breakdown(base=5.0, blocker=8.0, spill=2.0, total=15.0):
    return SimpleNamespace(
        remaining_days_base_work=base,
        remaining_days_blocker_loss=blocker,
        remaining_days_spillover=spill,
        expected_delay_days=total,
    )


def _forecast(scope_pct=0.0, scope_days=0.0, delay=None):
    return SimpleNamespace(
        scope_growth_percent=scope_pct,
        scope_impact_days=scope_days,
        delay_breakdown=delay or _delay_breakdown(),
    )


def _dev(rid, *, remaining=0.0, capacity=0.0, alloc=0.0, avail=1.0):
    return SimpleNamespace(
        resource_id=rid, name=rid,
        remaining_effort_hours=remaining, available_capacity_hours=capacity,
        allocation_pct=alloc, availability_pct=avail,
    )


def _metrics(*, trend=0.0, series=None, devs=None):
    return SimpleNamespace(
        velocity_metrics=SimpleNamespace(
            velocity_trend_pct=trend, velocity_by_sprint=series or [],
        ),
        resource_metrics=SimpleNamespace(developer_metrics=devs or []),
    )


def _mc(otp):
    return SimpleNamespace(on_time_probability=otp)


def _risk(drivers=None):
    return SimpleNamespace(top_risk_drivers=drivers or [])


def _driver(category, score, title="Driver", desc="detail"):
    return SimpleNamespace(category=category, score=score, title=title, description=desc)


def _blocker(bid, *, severity=BlockerSeverity.CRITICAL, impacted=None, raised=None, target=None):
    return SimpleNamespace(
        blocker_id=bid, severity=severity, status=BlockerStatus.OPEN,
        related_item_id=(impacted or ["WI-1"])[0],
        impacted_item_ids=impacted or ["WI-1"],
        description=f"{bid} description",
        raised_date=raised, target_resolution_date=target,
        actual_resolution_date=None,
    )


def _dep(pred, succ, lag=0):
    return SimpleNamespace(predecessor_item_id=pred, successor_item_id=succ, lag_days=lag)


def _cp(items):
    return SimpleNamespace(critical_path=items, critical_path_items=items)


def _state(*, blockers=None, deps=None, work_items=None, sprint_days=14):
    return SimpleNamespace(
        project_info=SimpleNamespace(sprint_duration_days=sprint_days),
        blockers=blockers or [],
        dependencies=deps or [],
        work_items=work_items or [],
    )


def _validation(confidence=1.0):
    return ValidationResult(validated=[], suppressed=[], data_confidence=confidence, warnings=[])


# ---- Stage 3: Evidence Collection ----------------------------------------
def test_evidence_collected_from_multiple_sources():
    raised = datetime(2026, 6, 1, tzinfo=timezone.utc)
    state = _state(blockers=[_blocker("BLK-1", impacted=["WI-1"], raised=raised,
                                      target=raised + timedelta(days=20))])
    bundle = EvidenceCollector().run(
        _validation(), state,
        forecast=_forecast(scope_pct=20.0, scope_days=6.0),
        risk_result=_risk([_driver("BLOCKER", 70)]),
        metrics=_metrics(trend=-20.0, series=[100, 80, 60], devs=[_dev("R1", remaining=200, capacity=100)]),
        monte_carlo=_mc(0.2),
        critical_path=_cp(["WI-1"]),
    )
    assert bundle.items, "expected evidence items"
    sources = {i.source.split("::")[0] for i in bundle.items}
    assert "ProjectState.blockers" in sources
    assert "ForecastEngine.scope_impact_days" in sources
    assert bundle.low_confidence_flag is False


def test_low_confidence_flag_set_and_caps_priors():
    state = _state(blockers=[_blocker("BLK-1", impacted=["WI-1"])])
    bundle = EvidenceCollector().run(
        _validation(confidence=0.4), state,
        forecast=_forecast(), risk_result=_risk(), metrics=_metrics(), monte_carlo=_mc(0.5),
        critical_path=_cp(["WI-1"]),
    )
    assert bundle.low_confidence_flag is True
    hyps = HypothesisGenerator().run(bundle, state, forecast=_forecast(),
                                     metrics=_metrics(), monte_carlo=_mc(0.5), critical_path=_cp(["WI-1"]))
    assert all(h.prior <= 0.5 for h in hyps)


# ---- Stage 4: Hypothesis Generation --------------------------------------
def test_null_hypothesis_always_generated():
    state = _state()
    bundle = EvidenceCollector().run(_validation(), state, forecast=_forecast(),
                                     risk_result=_risk(), metrics=_metrics(), monte_carlo=_mc(0.9))
    hyps = HypothesisGenerator().run(bundle, state, forecast=_forecast(),
                                     metrics=_metrics(), monte_carlo=_mc(0.9))
    cats = [hypothesis_category(h) for h in hyps]
    assert NULL in cats


def test_blocker_hypothesis_when_strong_blocker_on_cp():
    raised = datetime(2026, 6, 1, tzinfo=timezone.utc)
    state = _state(blockers=[_blocker("BLK-1", impacted=["WI-1"], raised=raised,
                                      target=raised + timedelta(days=20))])
    cp = _cp(["WI-1"])
    bundle = EvidenceCollector().run(_validation(), state, forecast=_forecast(),
                                     risk_result=_risk(), metrics=_metrics(), monte_carlo=_mc(0.2),
                                     critical_path=cp)
    hyps = HypothesisGenerator().run(bundle, state, forecast=_forecast(),
                                     metrics=_metrics(), monte_carlo=_mc(0.2), critical_path=cp)
    assert BLOCKER in [hypothesis_category(h) for h in hyps]


# ---- Stage 5: Elimination + posterior normalization (THE GATE) -----------
def test_survivor_posteriors_sum_to_one():
    raised = datetime(2026, 6, 1, tzinfo=timezone.utc)
    state = _state(blockers=[_blocker("BLK-1", impacted=["WI-1"], raised=raised,
                                      target=raised + timedelta(days=20))])
    cp = _cp(["WI-1"])
    forecast = _forecast(scope_pct=20.0, scope_days=6.0)
    metrics = _metrics(trend=-5.0, series=[100, 98, 97])
    mc = _mc(0.2)  # NULL will be eliminated (< 0.30)

    bundle = EvidenceCollector().run(_validation(), state, forecast=forecast,
                                     risk_result=_risk([_driver("SCOPE", 60)]),
                                     metrics=metrics, monte_carlo=mc, critical_path=cp)
    hyps = HypothesisGenerator().run(bundle, state, forecast=forecast,
                                     metrics=metrics, monte_carlo=mc, critical_path=cp)
    survivors = HypothesisEliminator().run(hyps, bundle, state, forecast=forecast,
                                           metrics=metrics, monte_carlo=mc, critical_path=cp)
    assert survivors, "expected at least one survivor"
    assert all(h.status == HypothesisStatus.SUPPORTED for h in survivors)
    assert NULL not in [hypothesis_category(h) for h in survivors]
    assert round(sum(h.posterior for h in survivors), 4) == 1.0


def test_velocity_hypothesis_killed_by_pto_artifact():
    state = _state()
    metrics = _metrics(trend=-25.0, series=[100, 70, 50])
    mc = _mc(0.6)
    bundle = EvidenceCollector().run(_validation(), state, forecast=_forecast(),
                                     risk_result=_risk(), metrics=metrics, monte_carlo=mc)
    hyps = HypothesisGenerator().run(bundle, state, forecast=_forecast(),
                                     metrics=metrics, monte_carlo=mc)
    survivors = HypothesisEliminator().run(
        hyps, bundle, state, forecast=_forecast(), metrics=metrics, monte_carlo=mc,
        velocity_artifact_suppressed=True,
    )
    from app.engines.hypothesis_generator import VELOCITY
    assert VELOCITY not in [hypothesis_category(h) for h in survivors]


def test_rejection_reasons_do_not_include_internal_eliminated_prefix():
    state = _state()
    metrics = _metrics(trend=0.0, series=[100, 98, 97])
    mc = _mc(0.2)
    bundle = EvidenceCollector().run(
        _validation(), state, forecast=_forecast(), risk_result=_risk(),
        metrics=metrics, monte_carlo=mc,
    )
    hyps = HypothesisGenerator().run(bundle, state, forecast=_forecast(),
                                     metrics=metrics, monte_carlo=mc)
    HypothesisEliminator().run(hyps, bundle, state, forecast=_forecast(),
                               metrics=metrics, monte_carlo=mc)

    rejected = [h for h in hyps if h.status == HypothesisStatus.REJECTED]
    assert rejected
    assert all(not (h.rejection_reason or "").startswith("Eliminated:") for h in rejected)


# ---- Stage 6: Root Cause Analysis ----------------------------------------
def test_diagnosis_confidence_matches_top_posterior():
    raised = datetime(2026, 6, 1, tzinfo=timezone.utc)
    state = _state(blockers=[_blocker("BLK-1", impacted=["WI-1"], raised=raised,
                                      target=raised + timedelta(days=25))])
    cp = _cp(["WI-1"])
    forecast = _forecast()
    metrics = _metrics()
    mc = _mc(0.2)
    bundle = EvidenceCollector().run(_validation(), state, forecast=forecast,
                                     risk_result=_risk([_driver("BLOCKER", 80)]),
                                     metrics=metrics, monte_carlo=mc, critical_path=cp)
    hyps = HypothesisGenerator().run(bundle, state, forecast=forecast,
                                     metrics=metrics, monte_carlo=mc, critical_path=cp)
    survivors = HypothesisEliminator().run(hyps, bundle, state, forecast=forecast,
                                           metrics=metrics, monte_carlo=mc, critical_path=cp)
    dx = RootCauseAnalyzer().run(survivors, state, forecast=forecast,
                                 metrics=metrics, monte_carlo=mc, critical_path=cp)
    assert dx is not None
    top = max(survivors, key=lambda h: h.posterior)
    assert dx.confidence == round(top.posterior, 4)
    assert dx.supporting_hypothesis_id == top.hypothesis_id
    assert len(dx.causal_chain) == 5  # 5-Whys
    # Gate: confidence + sum(other survivors) == 1.0
    others = sum(h.posterior for h in survivors if h.hypothesis_id != top.hypothesis_id)
    assert round(dx.confidence + others, 4) == 1.0


def test_no_survivors_returns_none():
    assert RootCauseAnalyzer().run([], _state()) is None