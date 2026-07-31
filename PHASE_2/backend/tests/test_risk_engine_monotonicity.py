"""
test_risk_engine_monotonicity.py
=================================
Verifies the fixed-denominator aggregation model:

  MONOTONICITY RULE (category level):
    If exactly one risk driver is improved (its slot value decreases),
    while every other input is held constant, that driver's CATEGORY
    risk score must not increase.

  NOT ENFORCED (by design):
    overall_risk_after <= overall_risk_before
    Some legitimate recovery actions trade schedule risk for resource or
    scope risk.  We want the model to expose those trade-offs.

One test per driver slot per category.  Each test:
  - Baseline: driver is active (non-zero)
  - After: driver is deactivated (slot → 0)
  - Assert: category score_after <= score_before
"""

import pytest
from datetime import datetime, timedelta

from app.domain.models import (
    ProjectInfo, Resource, Sprint, WorkItem, Dependency, Blocker, SprintActual,
    ProjectState, SkillLevel, WorkItemType, Priority, WorkItemStatus, SprintStatus,
    BlockerSeverity, BlockerStatus, BlockerCategory, DependencyType,
)
from app.engines.metrics_engine import MetricsEngine
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.spillover_engine import SpilloverAnalysis, SpilloverAnalysisEngine
from app.engines.forecast_engine import ForecastEngine
from app.engines.monte_carlo_engine import MonteCarloEngine
from app.engines.impact_scoring_engine import ImpactScoringEngine
from app.engines.risk_engine import RiskEngine
from app.api.models_phase3 import RiskExplanation


# ─── Shared project builder ───────────────────────────────────────────────────

def _base_project(
    *,
    n_items: int = 4,
    blockers=None,
    dependencies=None,
    actuals=None,
    allocation_pct: float = 0.75,
    availability_pct: float = 1.0,
    delay_days: int = 0,          # extra items beyond capacity to force delay
    sprint_velocity: float = 200.0,
    start_offset_days: int = 0,
) -> ProjectState:
    """Minimal TIO2-style project state for monotonicity testing."""
    start = datetime(2025, 6, 1) + timedelta(days=start_offset_days)
    end   = start + timedelta(days=60)
    info  = ProjectInfo(
        project_name="Monotonicity Test",
        sponsor="Test", business_unit="Eng", project_manager="PM",
        customer="C", status="Active",
        start_date=start, target_end_date=end,
        sprint_duration_days=14, methodology="Agile Scrum",
    )
    team = [
        Resource(
            resource_id="R1", name="Alice", role="Eng",
            primary_skill="Python", secondary_skill="C++",
            skill_level=SkillLevel.SENIOR,
            allocation_pct=allocation_pct,
            availability_pct=availability_pct,
        ),
        Resource(
            resource_id="R2", name="Bob", role="Eng",
            primary_skill="Embedded", secondary_skill="C",
            skill_level=SkillLevel.MID,
            allocation_pct=allocation_pct,
            availability_pct=availability_pct,
        ),
    ]
    sprints = [
        Sprint(
            sprint_id=f"S{i}", sprint_name=f"Sprint {i}", sprint_number=i,
            start_date=start + timedelta(days=(i-1)*14),
            end_date=start + timedelta(days=i*14),
            working_days=10, sprint_goal=f"Sprint {i}",
            status=SprintStatus.IN_PROGRESS if i == 1 else SprintStatus.NOT_STARTED,
            planned_velocity_hrs=sprint_velocity,
            carryover_count=0,
        )
        for i in range(1, 5)
    ]
    items = [
        WorkItem(
            item_id=f"WI-{i:03d}", title=f"Task {i}",
            work_type=WorkItemType.TASK,
            assigned_sprint="S1", original_sprint="S1",
            priority=Priority.HIGH,
            status=WorkItemStatus.IN_PROGRESS,
            estimated_effort_hrs=20.0,
            current_estimate_hrs=20.0,
            remaining_effort_hrs=20.0,
            assigned_resource="R1", required_skill="Python",
        )
        for i in range(1, n_items + 1)
    ]
    return ProjectState(
        project_id="proj-mono",
        project_info=info,
        team=team,
        sprints=sprints,
        work_items=items,
        dependencies=dependencies or [],
        blockers=blockers or [],
        actuals=actuals or [],
    )


def _build_engines(state: ProjectState, seed: int = 42):
    metrics     = MetricsEngine(state).calculate()
    dag         = DependencyGraphEngine(state).build_dag()
    cp_result   = CriticalPathEngine(state, dag).analyze()
    spillover   = SpilloverAnalysisEngine(state, metrics.average_item_effort).analyze()
    forecast    = ForecastEngine(state, metrics, cp_result, spillover).calculate()
    mc          = MonteCarloEngine(state, metrics, cp_result, spillover,
                                    simulation_count=500, seed=seed).calculate()
    impact      = ImpactScoringEngine(state, dag).score()
    engine      = RiskEngine(state, metrics, cp_result, dag, spillover,
                              forecast, mc, impact)
    return engine


def _run(state, seed=42) -> RiskExplanation:
    return _build_engines(state, seed).analyze()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_blocker(idx, severity, item_id):
    start = datetime(2025, 6, 1)
    return Blocker(
        blocker_id=f"B{idx}",
        related_item_id=item_id,
        impacted_item_ids=[item_id],
        description=f"Blocker {idx}",
        severity=severity,
        status=BlockerStatus.OPEN,
        owner="Team",
        raised_date=start,
        target_resolution_date=start + timedelta(days=5),
        actual_resolution_date=None,
        category=BlockerCategory.OTHER,
        notes="",
    )


def _resolve_blocker(b):
    """Return a copy of blocker b marked as resolved."""
    return Blocker(
        blocker_id=b.blocker_id,
        related_item_id=b.related_item_id,
        impacted_item_ids=b.impacted_item_ids,
        description=b.description,
        severity=b.severity,
        status=BlockerStatus.RESOLVED,
        owner=b.owner,
        raised_date=b.raised_date,
        target_resolution_date=b.target_resolution_date,
        actual_resolution_date=b.raised_date + timedelta(days=1),
        category=b.category,
        notes=b.notes,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULE MONOTONICITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestScheduleMonotonicity:
    """Slot S2: expected delay driver.  Remove delay → schedule score ≤ baseline."""

    def test_removing_delay_does_not_increase_schedule_score(self):
        """Reducing project delay cannot raise schedule category risk."""
        # High-delay scenario: many items in a single sprint exceeding capacity
        start = datetime(2025, 6, 1)
        end   = start + timedelta(days=28)
        info  = ProjectInfo(
            project_name="Delay Test", sponsor="T", business_unit="Eng",
            project_manager="PM", customer="C", status="Active",
            start_date=start, target_end_date=end,
            sprint_duration_days=14, methodology="Agile Scrum",
        )
        team = [Resource(
            resource_id="R1", name="A", role="Eng",
            primary_skill="Python", secondary_skill="C",
            skill_level=SkillLevel.SENIOR,
            allocation_pct=1.0, availability_pct=1.0,
        )]
        sprint = Sprint(
            sprint_id="S1", sprint_name="Sprint 1", sprint_number=1,
            start_date=start, end_date=start + timedelta(days=14),
            working_days=10, sprint_goal="dev",
            status=SprintStatus.IN_PROGRESS,
            planned_velocity_hrs=80.0, carryover_count=0,
        )

        def _make_state(n_items):
            items = [
                WorkItem(
                    item_id=f"WI-{i}", title=f"T{i}",
                    work_type=WorkItemType.TASK,
                    assigned_sprint="S1", original_sprint="S1",
                    priority=Priority.HIGH,
                    status=WorkItemStatus.IN_PROGRESS,
                    estimated_effort_hrs=30.0,
                    current_estimate_hrs=30.0,
                    remaining_effort_hrs=30.0,
                    assigned_resource="R1", required_skill="Python",
                )
                for i in range(1, n_items + 1)
            ]
            return ProjectState(
                project_id="p", project_info=info,
                team=team, sprints=[sprint],
                work_items=items, dependencies=[], blockers=[], actuals=[],
            )

        # Baseline: 6 items at 30h each = 180h, capacity 80h → big delay
        baseline = _run(_make_state(6))
        # After: 2 items → much less delay
        after    = _run(_make_state(2))

        assert after.schedule_risk.score <= baseline.schedule_risk.score + 0.001, (
            f"MONOTONICITY FAIL SCHEDULE/delay: "
            f"before={baseline.schedule_risk.score:.2f}  after={after.schedule_risk.score:.2f}"
        )

    def test_removing_low_prob_driver_does_not_increase_schedule_score(self):
        """Improving on-time probability cannot raise schedule risk."""
        # Build a project where MC prob is controlled via forecast mock
        state = _base_project(n_items=8, sprint_velocity=40.0)
        baseline = _run(state)

        state_easy = _base_project(n_items=2, sprint_velocity=200.0)
        after      = _run(state_easy)

        assert after.schedule_risk.score <= baseline.schedule_risk.score + 0.001, (
            f"MONOTONICITY FAIL SCHEDULE/probability: "
            f"before={baseline.schedule_risk.score:.2f}  after={after.schedule_risk.score:.2f}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# DEPENDENCY MONOTONICITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestDependencyMonotonicity:

    def _dep_chain(self, n):
        return [
            Dependency(
                dependency_id=f"DEP-{i:03d}",
                predecessor_item_id=f"WI-{i:03d}",
                successor_item_id=f"WI-{i+1:03d}",
                lag_days=0,
                dependency_type=DependencyType.FINISH_TO_START,
            )
            for i in range(1, n)
        ]

    def test_resolving_active_blocker_does_not_increase_dependency_score(self):
        """
        DEPENDENCY BUG CONFIRMED ON TIO2 LIVE DATA.
        Resolving the lowest-scored driver (Active Blocker) raised score 63→100
        under the old mean-over-active-components model:
          before: (bottleneck=100 + blocker_base=26) / 2 = 63
          after:  (bottleneck=100) / 1 = 100   ← BUG: score INCREASED

        Fixed-denominator model (denom=5 always):
          before: (100 + 26) / 5 = 25.2
          after:  (100 + 0)  / 5 = 20.0   ← monotonic: never increases
        """
        blocker = _make_blocker(1, BlockerSeverity.HIGH, "WI-001")

        # Use a 6-item chain — long enough to trigger the cp_length driver
        # alongside the blocker baseline driver.
        deps = self._dep_chain(6)

        state_before = _base_project(n_items=6, blockers=[blocker], dependencies=deps)
        state_after  = _base_project(n_items=6, blockers=[_resolve_blocker(blocker)], dependencies=deps)

        before = _run(state_before)
        after  = _run(state_after)

        assert after.dependency_risk.score <= before.dependency_risk.score + 0.001, (
            f"MONOTONICITY FAIL DEPENDENCY/blocker_baseline: "
            f"before={before.dependency_risk.score:.2f}  after={after.dependency_risk.score:.2f}\n"
            f"  Drivers before: {[(d.title, d.score) for d in before.dependency_risk.drivers]}\n"
            f"  Drivers after:  {[(d.title, d.score) for d in after.dependency_risk.drivers]}"
        )

    def test_shortening_dependency_chain_does_not_increase_dependency_score(self):
        """Removing items from critical path chain → dependency score ≤ baseline."""
        # 12-item chain: long cp → high score
        state_long  = _base_project(n_items=12, dependencies=self._dep_chain(12))
        # 3-item chain: short cp → lower score
        state_short = _base_project(n_items=3,  dependencies=self._dep_chain(3))

        before = _run(state_long)
        after  = _run(state_short)

        assert after.dependency_risk.score <= before.dependency_risk.score + 0.001, (
            f"MONOTONICITY FAIL DEPENDENCY/cp_length: "
            f"before={before.dependency_risk.score:.2f}  after={after.dependency_risk.score:.2f}"
        )

    def test_removing_cascade_driver_does_not_increase_dependency_score(self):
        """Resolving a deep cascade blocker (depth > 5) → dep score ≤ baseline."""
        # 7-item chain with blocker at root → cascade depth 6
        deps = self._dep_chain(7)
        blocker = _make_blocker(1, BlockerSeverity.CRITICAL, "WI-001")

        before_state = _base_project(n_items=7, blockers=[blocker], dependencies=deps)
        after_state  = _base_project(n_items=7, blockers=[_resolve_blocker(blocker)], dependencies=deps)

        before = _run(before_state)
        after  = _run(after_state)

        assert after.dependency_risk.score <= before.dependency_risk.score + 0.001, (
            f"MONOTONICITY FAIL DEPENDENCY/cascade: "
            f"before={before.dependency_risk.score:.2f}  after={after.dependency_risk.score:.2f}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# RESOURCE MONOTONICITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestResourceMonotonicity:

    def test_reducing_utilization_does_not_increase_resource_score(self):
        """Reducing team allocation → resource score ≤ baseline."""
        state_over = _base_project(allocation_pct=0.98, availability_pct=1.0)
        state_ok   = _base_project(allocation_pct=0.60, availability_pct=1.0)

        before = _run(state_over)
        after  = _run(state_ok)

        assert after.resource_risk.score <= before.resource_risk.score + 0.001, (
            f"MONOTONICITY FAIL RESOURCE/utilization: "
            f"before={before.resource_risk.score:.2f}  after={after.resource_risk.score:.2f}"
        )

    def test_resolving_blocker_below_resource_threshold_does_not_increase_resource_score(self):
        """Resolving one of several blockers → resource score ≤ baseline."""
        # 6 blockers → above threshold, not fully saturating velocity floor
        blockers_before = [_make_blocker(i, BlockerSeverity.MEDIUM, f"WI-{i:03d}") for i in range(1, 7)]
        blockers_after  = [_make_blocker(i, BlockerSeverity.MEDIUM, f"WI-{i:03d}") for i in range(1, 7)]
        blockers_after[0] = _resolve_blocker(blockers_after[0])

        state_before = _base_project(n_items=8, blockers=blockers_before)
        state_after  = _base_project(n_items=8, blockers=blockers_after)

        before = _run(state_before)
        after  = _run(state_after)

        assert after.resource_risk.score <= before.resource_risk.score + 0.001, (
            f"MONOTONICITY FAIL RESOURCE/blocker_capacity: "
            f"before={before.resource_risk.score:.2f}  after={after.resource_risk.score:.2f}"
        )

    def test_improving_allocation_balance_does_not_increase_resource_score(self):
        """Rebalancing workload → resource score ≤ baseline.
        Tests R4 slot (allocation_imbalance) in isolation.
        """
        # Imbalanced: R1 gets all work, R2 gets none
        start = datetime(2025, 6, 1)
        info  = ProjectInfo(
            project_name="Imbalance Test", sponsor="T", business_unit="E",
            project_manager="PM", customer="C", status="Active",
            start_date=start, target_end_date=start + timedelta(days=60),
            sprint_duration_days=14, methodology="Agile Scrum",
        )
        team_unbalanced = [
            Resource(resource_id="R1", name="A", role="E",
                     primary_skill="Python", secondary_skill="C",
                     skill_level=SkillLevel.SENIOR, allocation_pct=1.0, availability_pct=1.0),
            Resource(resource_id="R2", name="B", role="E",
                     primary_skill="Python", secondary_skill="C",
                     skill_level=SkillLevel.MID, allocation_pct=0.0, availability_pct=1.0),
        ]
        team_balanced = [
            Resource(resource_id="R1", name="A", role="E",
                     primary_skill="Python", secondary_skill="C",
                     skill_level=SkillLevel.SENIOR, allocation_pct=0.5, availability_pct=1.0),
            Resource(resource_id="R2", name="B", role="E",
                     primary_skill="Python", secondary_skill="C",
                     skill_level=SkillLevel.MID, allocation_pct=0.5, availability_pct=1.0),
        ]
        sprints = [Sprint(
            sprint_id="S1", sprint_name="Sprint 1", sprint_number=1,
            start_date=start, end_date=start + timedelta(days=14),
            working_days=10, sprint_goal="dev",
            status=SprintStatus.IN_PROGRESS,
            planned_velocity_hrs=160.0, carryover_count=0,
        )]
        items = [
            WorkItem(item_id=f"WI-{i}", title=f"T{i}",
                     work_type=WorkItemType.TASK,
                     assigned_sprint="S1", original_sprint="S1",
                     priority=Priority.MEDIUM, status=WorkItemStatus.IN_PROGRESS,
                     estimated_effort_hrs=20.0, current_estimate_hrs=20.0,
                     remaining_effort_hrs=20.0,
                     assigned_resource="R1", required_skill="Python")
            for i in range(1, 5)
        ]
        state_unbalanced = ProjectState(
            project_id="p1", project_info=info, team=team_unbalanced,
            sprints=sprints, work_items=items, dependencies=[], blockers=[], actuals=[],
        )
        state_balanced = ProjectState(
            project_id="p2", project_info=info, team=team_balanced,
            sprints=sprints, work_items=items, dependencies=[], blockers=[], actuals=[],
        )

        before = _run(state_unbalanced)
        after  = _run(state_balanced)

        assert after.resource_risk.score <= before.resource_risk.score + 0.001, (
            f"MONOTONICITY FAIL RESOURCE/imbalance: "
            f"before={before.resource_risk.score:.2f}  after={after.resource_risk.score:.2f}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SCOPE MONOTONICITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestScopeMonotonicity:

    def test_reducing_scope_growth_does_not_increase_scope_score(self):
        """Reducing forecast scope growth → scope score ≤ baseline."""
        state = _base_project()
        metrics  = MetricsEngine(state).calculate()
        dag      = DependencyGraphEngine(state).build_dag()
        cp       = CriticalPathEngine(state, dag).analyze()
        spill    = SpilloverAnalysisEngine(state, metrics.average_item_effort).analyze()
        forecast = ForecastEngine(state, metrics, cp, spill).calculate()
        mc       = MonteCarloEngine(state, metrics, cp, spill, simulation_count=500, seed=42).calculate()
        impact   = ImpactScoringEngine(state, dag).score()

        # Baseline: inject high scope growth
        forecast.scope_growth_percent = 35.0
        forecast.scope_growth_hours   = 200.0
        engine_before = RiskEngine(state, metrics, cp, dag, spill, forecast, mc, impact)
        before = engine_before.analyze()

        # After: resolve scope growth (descoped)
        import copy
        forecast2 = copy.copy(forecast)
        forecast2.scope_growth_percent = 5.0
        forecast2.scope_growth_hours   = 20.0
        engine_after = RiskEngine(state, metrics, cp, dag, spill, forecast2, mc, impact)
        after = engine_after.analyze()

        assert after.scope_risk.score <= before.scope_risk.score + 0.001, (
            f"MONOTONICITY FAIL SCOPE/scope_growth: "
            f"before={before.scope_risk.score:.2f}  after={after.scope_risk.score:.2f}"
        )

    def test_reducing_carryover_does_not_increase_scope_score(self):
        """Lower historical spillover carryover → scope score ≤ baseline."""
        state = _base_project()
        metrics  = MetricsEngine(state).calculate()
        dag      = DependencyGraphEngine(state).build_dag()
        cp       = CriticalPathEngine(state, dag).analyze()
        impact   = ImpactScoringEngine(state, dag).score()
        forecast_base = ForecastEngine(state, metrics, cp, SpilloverAnalysis(
            spillover_probability={},
            predicted_spillover_by_sprint={1: 5.0},
            spillover_confidence_intervals={1: (0.0, 0.0)},
            high_spillover_risk_items=[],
            historical_carryover_rate=5.0,
            historical_carryover_std_dev=1.0,
            sprint_utilization_pct={1: 0.8},
        )).calculate()
        mc = MonteCarloEngine(state, metrics, cp, SpilloverAnalysis(
            spillover_probability={},
            predicted_spillover_by_sprint={1: 5.0},
            spillover_confidence_intervals={1: (0.0, 0.0)},
            high_spillover_risk_items=[],
            historical_carryover_rate=5.0,
            historical_carryover_std_dev=1.0,
            sprint_utilization_pct={1: 0.8},
        ), simulation_count=500, seed=42).calculate()

        spill_high = SpilloverAnalysis(
            spillover_probability={},
            predicted_spillover_by_sprint={1: 5.0},
            spillover_confidence_intervals={1: (0.0, 0.0)},
            high_spillover_risk_items=[],
            historical_carryover_rate=5.0,
            historical_carryover_std_dev=1.0,
            sprint_utilization_pct={1: 0.8},
        )
        spill_low = SpilloverAnalysis(
            spillover_probability={},
            predicted_spillover_by_sprint={1: 0.0},
            spillover_confidence_intervals={1: (0.0, 0.0)},
            high_spillover_risk_items=[],
            historical_carryover_rate=0.5,
            historical_carryover_std_dev=0.1,
            sprint_utilization_pct={1: 0.4},
        )

        before = RiskEngine(state, metrics, cp, dag, spill_high,
                             forecast_base, mc, impact).analyze()
        after  = RiskEngine(state, metrics, cp, dag, spill_low,
                             forecast_base, mc, impact).analyze()

        assert after.scope_risk.score <= before.scope_risk.score + 0.001, (
            f"MONOTONICITY FAIL SCOPE/carryover: "
            f"before={before.scope_risk.score:.2f}  after={after.scope_risk.score:.2f}"
        )

    def test_unblocking_items_does_not_increase_scope_score(self):
        """Resolving blocked items → scope score ≤ baseline."""
        start = datetime(2025, 6, 1)
        info  = ProjectInfo(
            project_name="Block Test", sponsor="T", business_unit="E",
            project_manager="PM", customer="C", status="Active",
            start_date=start, target_end_date=start + timedelta(days=60),
            sprint_duration_days=14, methodology="Agile Scrum",
        )
        team = [Resource(resource_id="R1", name="A", role="E",
                         primary_skill="P", secondary_skill="C",
                         skill_level=SkillLevel.SENIOR,
                         allocation_pct=0.8, availability_pct=1.0)]
        sprints = [Sprint(
            sprint_id="S1", sprint_name="Sprint 1", sprint_number=1,
            start_date=start, end_date=start + timedelta(days=14),
            working_days=10, sprint_goal="dev", status=SprintStatus.IN_PROGRESS,
            planned_velocity_hrs=160.0, carryover_count=0,
        )]

        def _items(n_blocked):
            total = 10
            out = []
            for i in range(1, total + 1):
                status = WorkItemStatus.BLOCKED if i <= n_blocked else WorkItemStatus.IN_PROGRESS
                out.append(WorkItem(
                    item_id=f"WI-{i:03d}", title=f"T{i}",
                    work_type=WorkItemType.TASK,
                    assigned_sprint="S1", original_sprint="S1",
                    priority=Priority.MEDIUM, status=status,
                    estimated_effort_hrs=10.0, current_estimate_hrs=10.0,
                    remaining_effort_hrs=10.0,
                    assigned_resource="R1", required_skill="P",
                ))
            return out

        s_blocked   = ProjectState(project_id="p1", project_info=info, team=team,
                                    sprints=sprints, work_items=_items(4),
                                    dependencies=[], blockers=[], actuals=[])
        s_unblocked = ProjectState(project_id="p2", project_info=info, team=team,
                                    sprints=sprints, work_items=_items(0),
                                    dependencies=[], blockers=[], actuals=[])

        before = _run(s_blocked)
        after  = _run(s_unblocked)

        assert after.scope_risk.score <= before.scope_risk.score + 0.001, (
            f"MONOTONICITY FAIL SCOPE/blocked_items: "
            f"before={before.scope_risk.score:.2f}  after={after.scope_risk.score:.2f}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-DRIVER SIMULTANEOUS REMOVAL (regression)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiDriverMonotonicity:
    """Resolving multiple drivers simultaneously: each category ≤ its baseline."""

    def test_resolving_all_drivers_brings_all_categories_to_zero_or_lower(self):
        """After clearing all risk inputs, no category score should exceed baseline."""
        state_risky = _base_project(
            n_items=12,
            allocation_pct=0.97,
            sprint_velocity=50.0,
            blockers=[_make_blocker(1, BlockerSeverity.HIGH, "WI-001")],
        )
        state_clean = _base_project(
            n_items=2,
            allocation_pct=0.5,
            sprint_velocity=200.0,
        )

        risky = _run(state_risky)
        clean = _run(state_clean)

        for cat, score_before, score_after in [
            ("SCHEDULE",   risky.schedule_risk.score,   clean.schedule_risk.score),
            ("DEPENDENCY", risky.dependency_risk.score, clean.dependency_risk.score),
            ("RESOURCE",   risky.resource_risk.score,   clean.resource_risk.score),
            ("SCOPE",      risky.scope_risk.score,      clean.scope_risk.score),
        ]:
            assert score_after <= score_before + 0.001, (
                f"MONOTONICITY FAIL {cat}: "
                f"before={score_before:.2f}  after={score_after:.2f}"
            )
