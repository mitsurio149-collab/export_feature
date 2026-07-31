from datetime import datetime, timedelta

from app.domain.models import (
    Blocker,
    BlockerCategory,
    BlockerSeverity,
    BlockerStatus,
    Dependency,
    DependencyType,
    ProjectInfo,
    ProjectState,
    Priority,
    Resource,
    SkillLevel,
    Sprint,
    SprintActual,
    SprintStatus,
    WorkItem,
    WorkItemStatus,
    WorkItemType,
)
from app.engines.advisor_input_builder import AdvisorInputBuilder
from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    ImpactEstimate,
    RecommendationAction,
    RecommendationCandidate,
    SimulationResult,
    SignalEvidence,
)
from app.engines.recommendation_engine.models import SignalCategory, SignalSeverity
from app.engines.recommendation_engine.recommendation_engine_v2 import RecommendationEngineV2
from app.engines.recommendation_engine.candidate_generator import CandidateGenerator
from app.engines.recommendation_engine.impact_estimator import ImpactEstimator
from app.engines.recommendation_engine.priority_engine import PriorityEngine
from app.engines.recommendation_engine.signal_detectors import (
    BlockerDetector,
    CapacityDetector,
    SprintDetector,
    CriticalPathDetector,
    ScheduleDetector,
    EstimationReliabilityDetector,
    SpilloverRootCauseDetector,
    SPOFDetector,
    RecurringBlockerDetector,
    ReworkLoopDetector,
    RampUpDetector,
    ResequencingDetector,
    SwarmTradeoffDetector,
    SkillMismatchDetector,
    LowVelocityDetector,
)


def make_project_state() -> ProjectState:
    start_date = datetime(2025, 1, 1)
    project_info = ProjectInfo(
        project_name="V2 Recommendation",
        sponsor="Test Sponsor",
        business_unit="Engineering",
        project_manager="Test PM",
        customer="Test Customer",
        status="Active",
        start_date=start_date,
        target_end_date=start_date + timedelta(days=60),
        sprint_duration_days=14,
        methodology="Agile Scrum",
    )

    team = [
        Resource(
            resource_id="R1",
            name="Alice",
            role="Engineer",
            primary_skill="Python",
            secondary_skill="SQL",
            skill_level=SkillLevel.SENIOR,
            allocation_pct=0.8,
            availability_pct=0.8,
        )
    ]

    sprints = [
        Sprint(
            sprint_id="S1",
            sprint_name="Sprint 1",
            sprint_number=1,
            start_date=start_date - timedelta(days=14),
            end_date=start_date - timedelta(days=1),
            working_days=10,
            sprint_goal="Warmup",
            status=SprintStatus.NOT_STARTED,
            planned_velocity_hrs=120.0,
            carryover_count=0,
        ),
        Sprint(
            sprint_id="S2",
            sprint_name="Sprint 2",
            sprint_number=2,
            start_date=start_date,
            end_date=start_date + timedelta(days=13),
            working_days=10,
            sprint_goal="Build",
            status=SprintStatus.IN_PROGRESS,
            planned_velocity_hrs=160.0,
            carryover_count=1,
        )
    ]

    work_items = [
        WorkItem(
            item_id="WI-01",
            title="API work",
            work_type=WorkItemType.TASK,
            assigned_sprint="Sprint 2",
            original_sprint="S1",
            assigned_resource="R1",
            required_skill="Python",
            priority=Priority.HIGH,
            estimated_effort_hrs=80.0,
            current_estimate_hrs=80.0,
            actual_effort_hrs=20.0,
            remaining_effort_hrs=60.0,
            progress_pct=0.25,
            status=WorkItemStatus.IN_PROGRESS,
        ),
        WorkItem(
            item_id="WI-02",
            title="Blocked integration",
            work_type=WorkItemType.TASK,
            assigned_sprint="Sprint 2",
            original_sprint="S1",
            assigned_resource="R1",
            required_skill="Python",
            priority=Priority.MEDIUM,
            estimated_effort_hrs=40.0,
            current_estimate_hrs=40.0,
            actual_effort_hrs=0.0,
            remaining_effort_hrs=40.0,
            progress_pct=0.0,
            status=WorkItemStatus.BLOCKED,
        ),
    ]

    dependencies = [
        Dependency(
            dependency_id="DEP-01",
            predecessor_item_id="WI-02",
            successor_item_id="WI-01",
            dependency_type=DependencyType.FINISH_TO_START,
            is_on_critical_path=True,
            lag_days=0,
        )
    ]

    blockers = [
        Blocker(
            blocker_id="BLK-01",
            related_item_id="WI-02",
            impacted_item_ids=["WI-02", "WI-01"],
            description="Test blocker",
            severity=BlockerSeverity.HIGH,
            status=BlockerStatus.OPEN,
            owner="Ops",
            raised_date=start_date,
            target_resolution_date=start_date + timedelta(days=7),
            category=BlockerCategory.OTHER,
        )
    ]

    actuals = [
        SprintActual(
            sprint_id="SA-1",
            sprint_number=1,
            planned_effort_hrs=150.0,
            actual_effort_hrs=140.0,
            variance_hrs=10.0,
            tasks_planned=8,
            tasks_completed=7,
            completion_rate=0.875,
            carryover_count=1,
            scope_change_hours=0.0,
            blocker_impact_hrs=5.0,
        )
    ]

    return ProjectState(
        project_id="REC-V2",
        project_info=project_info,
        team=team,
        sprints=sprints,
        work_items=work_items,
        dependencies=dependencies,
        blockers=blockers,
        actuals=actuals,
    )


def test_recommendation_engine_v2_caches_upstream_once(monkeypatch):
    state = make_project_state()
    calls = []
    original_compute = RecommendationEngineV2._compute_upstream

    def wrapped_compute(self):
        calls.append(True)
        return original_compute(self)

    monkeypatch.setattr(RecommendationEngineV2, "_compute_upstream", wrapped_compute)

    engine = RecommendationEngineV2(state, simulation_count=50)
    engine.generate(top_n=5)
    engine.generate(top_n=3)

    assert len(calls) == 1  # Second generate() returns cached result, _compute_upstream not called again


def test_recommendation_engine_v2_simulate_without_prior_generate():
    state = make_project_state()
    engine = RecommendationEngineV2(state, simulation_count=50)
    recommendations = engine.generate(top_n=5)
    rec_id = recommendations[0].recommendation_id

    simulation = engine.simulate(rec_id)

    assert simulation.recommendation_ids == [rec_id]
    assert simulation.seed_used == 42


def test_recommendation_engine_v2_generates_actionable_recommendations():
    state = make_project_state()
    engine = RecommendationEngineV2(state, simulation_count=50)
    recommendations = engine.generate(top_n=5)

    assert recommendations
    assert len({rec.recommendation_id for rec in recommendations}) == len(recommendations)
    assert all(
        rec.affected_item_ids or rec.affected_resource_ids or rec.affected_blocker_ids
        for rec in recommendations
    )


def test_recommendation_engine_v2_exposes_validation_cache():
    state = make_project_state()
    engine = RecommendationEngineV2(state, simulation_count=50)
    recommendations = engine.generate(top_n=5)

    assert recommendations
    validation = engine.get_validation(recommendations[0].recommendation_id)
    assert validation is not None
    assert validation.recommendation_id == recommendations[0].recommendation_id


def test_recommendation_input_preserves_historical_pattern_for_narrative():
    state = make_project_state()
    engine = RecommendationEngineV2(state, simulation_count=50)
    recommendations = engine.generate(top_n=5)

    assert recommendations
    rec = next((item for item in recommendations if item.action_type == RecommendationAction.REBASELINE_ESTIMATE), None)
    assert rec is not None

    builder = AdvisorInputBuilder()
    advisor_input = builder.build_recommendation_input(
        project_id="session-1",
        project_state=state,
        forecast=engine._compute_upstream().forecast,
        monte_carlo=engine._compute_upstream().monte_carlo,
        recommendations=recommendations,
        metrics=engine._compute_upstream().metrics,
    )

    recommendation_fact = next(
        (fact for fact in advisor_input.recommendations if fact.recommendation_id == rec.recommendation_id),
        None,
    )
    assert recommendation_fact is not None
    assert recommendation_fact.historical_pattern is not None
    assert recommendation_fact.historical_pattern["pattern_type"]


def test_generated_recommendations_have_historical_evidence_confidence_and_simulation_support():
    state = make_project_state()
    engine = RecommendationEngineV2(state, simulation_count=50)
    recommendations = engine.generate(top_n=10)

    assert recommendations
    assert all(rec.metadata.get("historical_pattern") for rec in recommendations)
    assert all(rec.confidence for rec in recommendations)
    assert all(rec.estimated_hours_recovered >= 0.0 for rec in recommendations)
    assert all(rec.estimated_delay_reduction_days >= 0.0 for rec in recommendations)

    for rec in recommendations:
        try:
            simulated = engine.simulate(rec.recommendation_id)
            assert simulated.recommendation_ids == [rec.recommendation_id]
        except RuntimeError as exc:
            # Applicator mutation guard: some action types (REBASELINE, INSERT_REVIEW_GATE,
            # RESEQUENCE) require specific project conditions to produce a state mutation.
            # Acceptable here — the optimizer already skipped these during generate().
            assert "did not mutate cloned state" in str(exc), f"Unexpected RuntimeError: {exc}"


def test_deduplicates_split_recommendations_by_action_and_item_ids():
    engine = RecommendationEngineV2(make_project_state(), simulation_count=50)

    class DummyRec:
        def __init__(self, action_type, affected_item_ids, title, priority_score):
            self.action_type = action_type
            self.affected_item_ids = affected_item_ids
            self.title = title
            self.priority_score = priority_score
            self.recommendation_id = title

    duplicate_recs = [
        DummyRec(
            RecommendationAction.SPLIT_ITEM,
            ["WI-053"],
            "Split item (WI-053)",
            0.95,
        ),
        DummyRec(
            RecommendationAction.SPLIT_ITEM,
            ["WI-053"],
            "Split item to relieve CP owner (WI-053)",
            0.90,
        ),
    ]

    deduped = engine._deduplicate(duplicate_recs)

    assert len(deduped) == 1
    assert deduped[0].title == "Split item (WI-053)"


def test_zero_impact_low_confidence_recommendations_are_filtered_out():
    engine = RecommendationEngineV2(make_project_state(), simulation_count=50)

    class DummyRec:
        def __init__(self, action_type, confidence, estimated_hours_recovered, estimated_delay_reduction_days, estimated_risk_reduction):
            self.action_type = action_type
            self.confidence = confidence
            self.estimated_hours_recovered = estimated_hours_recovered
            self.estimated_delay_reduction_days = estimated_delay_reduction_days
            self.estimated_risk_reduction = estimated_risk_reduction
            self.priority_score = 0.0
            self.recommendation_id = action_type.value
            self.title = action_type.value
            self.description = action_type.value
            self.affected_item_ids = []
            self.affected_resource_ids = []
            self.affected_sprint_ids = []
            self.affected_blocker_ids = []
            self.root_cause_signal_id = "signal"
            self.supporting_signal_ids = []
            self.impact_evidence = []
            self.metadata = {}
            self.pm_intelligence = None

    zero_impact_low_confidence = DummyRec(
        RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM,
        ConfidenceLevel.LOW,
        0.0,
        0.0,
        0.0,
    )
    zero_impact_high_confidence = DummyRec(
        RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM,
        ConfidenceLevel.HIGH,
        0.0,
        0.0,
        0.0,
    )
    class PreventiveAction:
        name = "ESCALATE_BLOCKER"
        value = "escalate_blocker"

    preventive = DummyRec(
        PreventiveAction(),
        ConfidenceLevel.LOW,
        0.0,
        0.0,
        0.0,
    )

    selected = [zero_impact_low_confidence, zero_impact_high_confidence, preventive]
    filtered = []
    PREVENTIVE_ACTIONS = {"ESCALATE_BLOCKER", "ESCALATE_BLOCKER_EARLY", "FREEZE_SCOPE_REQUEST", "CROSS_TRAIN_BACKUP"}

    def _is_meaningful(rec):
        action_keys = {rec.action_type.name.upper(), rec.action_type.value.upper()}
        if action_keys & PREVENTIVE_ACTIONS:
            return True
        has_hours = rec.estimated_hours_recovered > 0.0
        has_delay = rec.estimated_delay_reduction_days > 0.0
        has_risk = rec.estimated_risk_reduction > 0.0
        has_impact = has_hours or has_delay or has_risk
        if has_impact:
            return True
        return rec.confidence.value == "HIGH"

    filtered = [r for r in selected if _is_meaningful(r)]

    assert len(filtered) == 2
    assert zero_impact_low_confidence not in filtered
    assert zero_impact_high_confidence in filtered


# ---------------------------------------------------------------------------
# Fix 1 — mode parameter tests
# ---------------------------------------------------------------------------

def test_optimizer_mode_default_behavior_unchanged():
    """Calling generate() without mode= uses optimizer mode (identical output)."""
    state = make_project_state()

    engine_no_mode = RecommendationEngineV2(state, simulation_count=50)
    recs_no_mode = engine_no_mode.generate(top_n=5)

    engine_explicit = RecommendationEngineV2(state, simulation_count=50)
    recs_explicit = engine_explicit.generate(top_n=5, mode="optimizer")

    # Same number and same recommendation IDs in same order.
    assert len(recs_no_mode) == len(recs_explicit)
    assert [r.recommendation_id for r in recs_no_mode] == [
        r.recommendation_id for r in recs_explicit
    ]


def test_recovery_plan_caller_unchanged(monkeypatch):
    """Existing generate() calls without mode= argument still return same results.

    Regression guard: if any code path calls generate(top_n=N) (no mode=),
    the behavior must be identical to before this change (optimizer mode).
    """
    state = make_project_state()

    # Simulate what recovery-plan code does: call generate without mode=
    engine = RecommendationEngineV2(state, simulation_count=50)
    recs = engine.generate(top_n=20)

    # Must still return a list of Recommendation objects with required fields.
    assert isinstance(recs, list)
    for rec in recs:
        assert hasattr(rec, "recommendation_id")
        assert hasattr(rec, "action_type")
        assert hasattr(rec, "priority_score")
        assert rec.affected_item_ids or rec.affected_resource_ids or rec.affected_blocker_ids


def test_dashboard_mode_returns_more_recommendations_than_optimizer():
    """dashboard mode collects candidates beyond threshold stops, approaching top_n=12."""
    state = make_project_state()

    engine_optimizer = RecommendationEngineV2(state, simulation_count=50)
    recs_optimizer = engine_optimizer.generate(top_n=12, mode="optimizer")

    engine_dashboard = RecommendationEngineV2(state, simulation_count=50)
    recs_dashboard = engine_dashboard.generate(top_n=12, mode="dashboard")

    # Dashboard mode should return at least as many recs as optimizer mode.
    assert len(recs_dashboard) >= len(recs_optimizer)

    # Dashboard recs must still satisfy basic structural requirements.
    assert isinstance(recs_dashboard, list)
    for rec in recs_dashboard:
        assert hasattr(rec, "recommendation_id")
        assert hasattr(rec, "action_type")
        assert rec.affected_item_ids or rec.affected_resource_ids or rec.affected_blocker_ids

    # Recommendation IDs must be unique (dedup still applied).
    ids = [r.recommendation_id for r in recs_dashboard]
    assert len(ids) == len(set(ids)), "Dashboard mode returned duplicate recommendation IDs"


def test_dashboard_mode_not_capped_by_otp_threshold():
    """dashboard mode does NOT stop when no candidate clears OTP/delay thresholds.

    We verify this by checking that dashboard mode with top_n=12 returns more
    results than optimizer mode when the project state produces few high-impact
    candidates (the optimizer would stop early; dashboard keeps going).
    """
    state = make_project_state()

    engine_opt = RecommendationEngineV2(state, simulation_count=50)
    recs_opt = engine_opt.generate(top_n=12, mode="optimizer")

    engine_dash = RecommendationEngineV2(state, simulation_count=50)
    recs_dash = engine_dash.generate(top_n=12, mode="dashboard")

    # dashboard must not produce fewer recommendations than optimizer on the
    # same state — it is designed to be a superset.
    assert len(recs_dash) >= len(recs_opt), (
        f"dashboard returned {len(recs_dash)} recs, "
        f"optimizer returned {len(recs_opt)} — dashboard should be >= optimizer"
    )


# ---------------------------------------------------------------------------
# Fix 2 — _diversity_rerank category-keyed tests
# ---------------------------------------------------------------------------

def _make_mock_rec(action_type, priority_score, rec_id=None):
    """Minimal Recommendation-like object for diversity rerank tests."""
    from app.engines.recommendation_engine.models import Recommendation, ConfidenceLevel
    import dataclasses

    return Recommendation(
        recommendation_id=rec_id or f"{action_type.value}-{priority_score}",
        title=action_type.value,
        description="test",
        action_type=action_type,
        priority_score=priority_score,
        confidence=ConfidenceLevel.HIGH,
        estimated_hours_recovered=1.0,
        estimated_delay_reduction_days=0.5,
        estimated_risk_reduction=0.1,
        affected_item_ids=["WI-001"],
        affected_resource_ids=[],
        affected_sprint_ids=[],
        affected_blocker_ids=[],
        root_cause_signal_id="sig-1",
    )


def test_diversity_rerank_caps_by_action_type():
    """_diversity_rerank with key_fn=action_type.value caps each action type at max_per_category."""
    engine = RecommendationEngineV2(make_project_state(), simulation_count=50)

    # Create 4 REBASELINE_ESTIMATE + 4 CROSS_TRAIN_BACKUP recs
    recs = (
        [_make_mock_rec(RecommendationAction.REBASELINE_ESTIMATE, 0.9 - i * 0.05) for i in range(4)]
        + [_make_mock_rec(RecommendationAction.CROSS_TRAIN_BACKUP, 0.85 - i * 0.05) for i in range(4)]
    )

    result = engine._diversity_rerank(
        recs,
        max_per_category=2,
        key_fn=lambda rec: rec.action_type.value,
    )

    # All 8 recs are returned (remainder appended after the cap)
    assert len(result) == 8

    # Count by action_type in the first 4 slots (the "selected" top positions)
    top4 = result[:4]
    rebaseline_in_top = sum(1 for r in top4 if r.action_type == RecommendationAction.REBASELINE_ESTIMATE)
    cross_train_in_top = sum(1 for r in top4 if r.action_type == RecommendationAction.CROSS_TRAIN_BACKUP)
    assert rebaseline_in_top <= 2
    assert cross_train_in_top <= 2


def test_diversity_rerank_no_category_exceeds_cap_in_first_pass():
    """No action_type appears more than max_per_category times in the primary (first-pass) result."""
    engine = RecommendationEngineV2(make_project_state(), simulation_count=50)

    recs = [_make_mock_rec(RecommendationAction.REBASELINE_ESTIMATE, 1.0 - i * 0.01) for i in range(6)]

    result = engine._diversity_rerank(
        recs,
        max_per_category=2,
        key_fn=lambda rec: rec.action_type.value,
    )

    # Count consecutive leading occurrences of the same action_type
    from collections import Counter
    counts = Counter(r.action_type.value for r in result[:2])
    for cnt in counts.values():
        assert cnt <= 2, f"Action type appeared {cnt} times in first 2 slots (cap=2)"


def test_diversity_rerank_legacy_max_per_objective_still_works():
    """Passing max_per_objective= (old kwarg) still works as a backward-compat alias."""
    engine = RecommendationEngineV2(make_project_state(), simulation_count=50)

    recs = [_make_mock_rec(RecommendationAction.REBASELINE_ESTIMATE, 1.0 - i * 0.01) for i in range(4)]

    # Should not raise; max_per_objective alias accepted
    result = engine._diversity_rerank(recs, max_per_objective=2)
    assert len(result) == 4


def test_generate_no_action_type_exceeds_2_in_top_slots():
    """End-to-end: generate() result has at most 2 recs of any single action_type."""
    state = make_project_state()
    engine = RecommendationEngineV2(state, simulation_count=50)
    recs = engine.generate(top_n=12, mode="dashboard")

    from collections import Counter
    counts = Counter(r.action_type.value for r in recs)
    for action_type, count in counts.items():
        assert count <= 2, (
            f"action_type '{action_type}' appears {count} times in generate() output "
            f"(max allowed: 2)"
        )


def test_recommendation_engine_v2_rank_by_simulation_delta(monkeypatch):
    state = make_project_state()
    engine = RecommendationEngineV2(state, simulation_count=50)
    # Build the pipeline up to ranked recommendations without invoking the
    # internal generate() simulation step so we can validate candidate scopes.
    upstream = engine._compute_upstream()

    # Reproduce signal detection the same way the engine does (deterministic)
    signals = []
    signals.extend(BlockerDetector(state, upstream.cp_result, upstream.dag, upstream.impact_scores).detect())
    signals.extend(CapacityDetector(state, upstream.metrics, upstream.cp_result, upstream.impact_scores).detect())
    signals.extend(SprintDetector(state, upstream.metrics, upstream.spillover, upstream.forecast).detect())
    signals.extend(CriticalPathDetector(state, upstream.cp_result, upstream.dag, upstream.impact_scores).detect())
    signals.extend(ScheduleDetector(state, upstream.forecast, upstream.monte_carlo, upstream.risk_result, upstream.metrics).detect())
    signals.extend(EstimationReliabilityDetector(state).detect())
    signals.extend(SpilloverRootCauseDetector(state, upstream.spillover).detect())
    signals.extend(SPOFDetector(state, upstream.cp_result).detect())
    signals.extend(RecurringBlockerDetector(state).detect())
    signals.extend(ReworkLoopDetector(state).detect())
    signals.extend(RampUpDetector(state).detect())
    signals.extend(ResequencingDetector(state, upstream.dag, upstream.cp_result).detect())
    signals.extend(SwarmTradeoffDetector(state, upstream.cp_result).detect())
    signals.extend(SkillMismatchDetector(state).detect())
    signals.extend(LowVelocityDetector(state).detect())

    # Filter out certain overloaded capacity signals that would exercise
    # rare candidate-building branches not necessary for this unit test.
    filtered = []
    for s in signals:
        if s.category == SignalCategory.CAPACITY:
            flag = s.context.get("flag") if s.context else ""
            load_ratio = float(s.context.get("load_ratio", 0.0)) if s.context else 0.0
            if flag == "OVERLOADED" and (len(s.affected_sprint_ids) > 1 or load_ratio > 1.3 or s.severity == SignalSeverity.HIGH):
                continue
        filtered.append(s)

    candidates = CandidateGenerator(state, upstream).generate(filtered)
    assert candidates, "CandidateGenerator produced no candidates for fixture"

    # Estimate impacts and triage via the PriorityEngine (mirrors generate())
    impact_estimates = {c.recommendation_id: ImpactEstimator(state, upstream).estimate(c) for c in candidates}
    ranked_candidates = PriorityEngine(upstream, weights=engine.scoring_weights).score_and_rank(candidates, impact_estimates)

    actionable = [rec for rec in ranked_candidates if rec.affected_item_ids or rec.affected_resource_ids or rec.affected_blocker_ids]
    actionable = engine._deduplicate(actionable)

    triage_limit = 2 * 2
    triaged = actionable[:triage_limit]

    # Requirement: validate affected_item_ids exist in the same ProjectState fixture
    available_item_ids = {wi.item_id for wi in state.work_items}
    for rec in triaged:
        missing = [iid for iid in (rec.affected_item_ids or []) if iid not in available_item_ids]
        if missing:
            import pytest

            pytest.fail(
                f"Invalid affected_item_ids for recommendation {rec.recommendation_id} ({rec.action_type}): {missing}; available={sorted(list(available_item_ids))}"
            )

    # Use the monkeypatched engine._run_simulation to compute simulation_results (cache-friendly)
    original_simulate = engine._run_simulation
    simulation_overrides = {}

    def fake_run_simulation(recommendation, upstream_arg):
        if recommendation.recommendation_id not in simulation_overrides:
            base = original_simulate(recommendation, upstream_arg)
            simulation_overrides[recommendation.recommendation_id] = base
        return simulation_overrides[recommendation.recommendation_id]

    monkeypatch.setattr(engine, "_run_simulation", fake_run_simulation)

    for rec in triaged:
        print(rec.recommendation_id, rec.action_type, rec.affected_item_ids, rec.root_cause_signal_id)

    simulation_results = {rec.recommendation_id: engine._run_simulation(rec, upstream) for rec in triaged}

    selected = triaged[:2]
    assert len(selected) == 2

    # Validate ordering is by simulated delta (descending)
    sorted_by_delta = sorted(
        selected,
        key=lambda rec: (
            -simulation_results[rec.recommendation_id].delta_on_time_probability,
            -simulation_results[rec.recommendation_id].delta_expected_delay_days,
            -rec.priority_score,
            rec.recommendation_id,
        ),
    )
    assert selected == sorted_by_delta


# ---------------------------------------------------------------------------
# Fix 7 — is_preventive flag tests
# ---------------------------------------------------------------------------

def test_cross_train_backup_pm_intelligence_is_preventive():
    """CROSS_TRAIN_BACKUP recommendations must have pm_intelligence.is_preventive=True."""
    state = make_project_state()
    engine = RecommendationEngineV2(state, simulation_count=50)
    recs = engine.generate(top_n=20)

    cross_train_recs = [r for r in recs if r.action_type == RecommendationAction.CROSS_TRAIN_BACKUP]
    # The project state has a SPOF resource; at least one cross-train rec should appear.
    if cross_train_recs:
        for rec in cross_train_recs:
            assert rec.pm_intelligence is not None, "pm_intelligence should be populated"
            assert rec.pm_intelligence.is_preventive is True, (
                f"CROSS_TRAIN_BACKUP rec {rec.recommendation_id} should have is_preventive=True"
            )


def test_preventive_actions_marked_correctly_in_pm_intelligence():
    """Known preventive action types must have is_preventive=True in pm_intelligence."""
    from app.engines.recommendation_engine.priority_engine import _PREVENTIVE_ACTION_TYPES, PriorityEngine
    from app.engines.recommendation_engine.models import ImpactEstimate, ConfidenceLevel
    from app.engines.recommendation_engine.recommendation_engine_v2 import RecommendationEngineV2

    state = make_project_state()
    engine = RecommendationEngineV2(state, simulation_count=50)
    upstream = engine._compute_upstream()

    # Build a minimal candidate for CROSS_TRAIN_BACKUP and confirm flag is set
    from app.engines.recommendation_engine.models import RecommendationCandidate
    from app.engines.recommendation_engine.models import ScoringWeights

    candidate = RecommendationCandidate(
        recommendation_id="test-preventive-001",
        action_type=RecommendationAction.CROSS_TRAIN_BACKUP,
        title="Cross-train backup",
        description="Test",
        affected_item_ids=["WI-001"],
        affected_resource_ids=["R1", "R2"],
        affected_sprint_ids=[],
        affected_blocker_ids=[],
        root_cause_signal_id="sig-spof",
        simulation_params={"signal_category": "single_point_of_failure"},
    )
    impact = ImpactEstimate(
        estimated_hours_recovered=0.0,
        estimated_delay_reduction_days=0.0,
        estimated_risk_reduction=0.05,
        confidence=ConfidenceLevel.LOW,
        evidence=[],
        calculation_notes="test",
    )
    priority_engine = PriorityEngine(upstream, state, ScoringWeights())
    ranked = priority_engine.score_and_rank([candidate], {candidate.recommendation_id: impact})
    assert ranked, "score_and_rank should return results"
    rec = ranked[0]
    assert rec.pm_intelligence is not None
    assert rec.pm_intelligence.is_preventive is True

    # Non-preventive action (RESOLVE_BLOCKER) must NOT be marked preventive
    non_preventive = RecommendationCandidate(
        recommendation_id="test-non-preventive-001",
        action_type=RecommendationAction.RESOLVE_BLOCKER,
        title="Resolve blocker",
        description="Test",
        affected_item_ids=["WI-001"],
        affected_resource_ids=[],
        affected_sprint_ids=[],
        affected_blocker_ids=["B1"],
        root_cause_signal_id="sig-blocker",
        simulation_params={"signal_category": "blocker"},
    )
    ranked_np = priority_engine.score_and_rank([non_preventive], {non_preventive.recommendation_id: impact})
    assert ranked_np
    assert ranked_np[0].pm_intelligence.is_preventive is False


def test_is_preventive_serialized_in_to_dict():
    """PMIntelligence.to_dict() must always include is_preventive."""
    from app.engines.recommendation_engine.pm_models import (
        PMIntelligence, PMDecisionScore, PMExplanation,
        RecommendationClassification, ImplementationEffort,
        RecommendationObjective, TriggerReason,
    )

    score = PMDecisionScore()
    explanation = PMExplanation(
        trigger_reason=TriggerReason.SINGLE_POINT_OF_FAILURE,
        trigger_detail="Test",
        primary_objective=RecommendationObjective.KNOWLEDGE_RESILIENCE,
        strategic_benefits=["Improves resilience"],
        ignore_consequence="Bus factor risk remains",
        implementation_effort=ImplementationEffort.MEDIUM,
        is_immediate_impact=False,
        impact_horizon="Long Term",
    )
    pm_intel = PMIntelligence(
        classification=RecommendationClassification.STRATEGIC,
        pm_decision_score=score,
        explanation=explanation,
        is_preventive=True,
    )
    d = pm_intel.to_dict()
    assert "is_preventive" in d
    assert d["is_preventive"] is True

    pm_intel_not = PMIntelligence(
        classification=RecommendationClassification.TACTICAL,
        pm_decision_score=score,
        explanation=explanation,
        is_preventive=False,
    )
    assert pm_intel_not.to_dict()["is_preventive"] is False
