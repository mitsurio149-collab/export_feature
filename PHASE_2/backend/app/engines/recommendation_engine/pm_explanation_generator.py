"""pm_explanation_generator.py — Phase 2 PM Decision Intelligence Explanations.

Generates a structured PMExplanation for each Recommendation answering the
five questions a Project Manager needs before acting:

  1. Why am I seeing this?          (trigger_reason + trigger_detail)
  2. What objective does it serve?  (primary_objective)
  3. What value does it provide?    (strategic_benefits)
  4. What if I ignore it?           (ignore_consequence)
  5. How much effort?               (implementation_effort)
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.domain.models import ProjectState
from app.engines.recommendation_engine.models import (
    OpportunitySignal,
    Recommendation,
    RecommendationAction,
    RecommendationCandidate,
    SignalCategory,
    UpstreamEngineOutputs,
    SimulationResult,
    ImpactEstimate,
)
from app.engines.recommendation_engine.pm_decision_scorer import (
    effort_for,
    objective_for,
    trigger_for,
)
from app.engines.recommendation_engine.pm_models import (
    ConfidenceWithReason,
    EngineSource,
    ExecutionWindow,
    ImpactConfidence,
    ImpactDimension,
    ImpactDimensionType,
    ImplementationEffort,
    PMExplanation,
    RecommendationDecisionContext,
    RecommendationImpactMetrics,
    RecommendationImpactProfile,
    RecommendationIntent,
    RecommendationObjective,
    StructuredEvidence,
    TriggerReason,
)


# ---------------------------------------------------------------------------
# Strategic-benefit templates per action type
# ---------------------------------------------------------------------------

_STRATEGIC_BENEFITS: Dict[RecommendationAction, List[str]] = {
    RecommendationAction.RESOLVE_BLOCKER: [
        "Removes active impediment to team delivery",
        "Reduces execution risk on affected work items",
        "Restores delivery momentum",
    ],
    RecommendationAction.ESCALATE_BLOCKER_EARLY: [
        "Prevents compounding delay if blocker persists",
        "Reduces blocker exposure for future sprints",
        "Improves stakeholder visibility on delivery risk",
    ],
    RecommendationAction.CROSS_TRAIN_BACKUP: [
        "Removes Single Point of Failure from delivery chain",
        "Improves team resilience and bus-factor",
        "Reduces future sprint delivery risk",
    ],
    RecommendationAction.INSERT_REVIEW_GATE: [
        "Reduces rework and late-stage defect discovery",
        "Improves delivery quality and review coverage",
        "Protects acceptance criteria before handoff",
    ],
    RecommendationAction.FREEZE_SCOPE_REQUEST: [
        "Stabilises current sprint commitments",
        "Prevents scope creep from diluting velocity",
        "Improves forecast reliability for the sprint",
    ],
    RecommendationAction.REBASELINE_ESTIMATE: [
        "Increases forecast accuracy for remaining work",
        "Improves on-time delivery probability",
        "Reduces planning uncertainty for stakeholders",
    ],
    RecommendationAction.APPLY_RAMP_UP_DISCOUNT: [
        "Corrects optimistic velocity assumptions for new team members",
        "Improves sprint plan reliability",
        "Reduces surprise slippage late in the sprint",
    ],
    RecommendationAction.REASSIGN_ITEM: [
        "Improves workload balance across the team",
        "Reduces overload risk on the assigned resource",
        "Improves delivery confidence for the affected item",
    ],
    RecommendationAction.REBALANCE_SPRINT_LOAD: [
        "Distributes capacity risk across more resources",
        "Reduces risk of single resource becoming a bottleneck",
        "Improves team-level throughput",
    ],
    RecommendationAction.ADD_RESOURCE_SKILL: [
        "Closes skill gap blocking critical work",
        "Increases team capacity for the required skill area",
        "Reduces dependency on a single skilled resource",
    ],
    RecommendationAction.PARALLELIZE_ITEMS: [
        "Reduces total elapsed time for independent work",
        "Increases team utilisation",
        "Accelerates critical path completion",
    ],
    RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT: [
        "Pulls forward high-value delivery",
        "Reduces end-of-project schedule compression",
        "Improves team flow by surfacing blockers earlier",
    ],
    RecommendationAction.PULL_FORWARD_ITEM: [
        "Reduces idle capacity in the current sprint",
        "Improves sprint throughput",
        "Builds ahead of schedule buffer",
    ],
    RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK: [
        "Unblocks downstream work items in the dependency chain",
        "Reduces critical path length",
        "Improves delivery flow across teams or components",
    ],
    RecommendationAction.SPLIT_ITEM: [
        "Enables partial delivery and earlier feedback",
        "Reduces risk of single large item slipping the sprint",
        "Improves estimation accuracy on smaller units of work",
    ],
    RecommendationAction.SPLIT_AND_PAIR: [
        "Enables parallel execution of split work",
        "Spreads delivery risk across two resources",
        "Accelerates completion while improving review coverage",
    ],
    RecommendationAction.PAIR_REVIEWER: [
        "Improves review quality and reduces knowledge silos",
        "Reduces review cycle time through active pairing",
        "Builds cross-team knowledge for future resilience",
    ],
    RecommendationAction.ASSIGN_AS_SECOND_REVIEWER: [
        "Adds review redundancy to high-risk items",
        "Reduces single-reviewer bottleneck",
        "Improves defect detection before integration",
    ],
    RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM: [
        "Frees critical path capacity from lower-priority work",
        "Reduces competition for constrained resources",
        "Improves sprint execution focus",
    ],
    RecommendationAction.SWARM_ITEM: [
        "Accelerates a single blocked or at-risk item",
        "Reduces the risk of a single item blocking sprint close",
        "Demonstrates team-level commitment to the sprint goal",
    ],
}


# ---------------------------------------------------------------------------
# Ignore consequence templates per action type
# ---------------------------------------------------------------------------

_IGNORE_CONSEQUENCE: Dict[RecommendationAction, str] = {
    RecommendationAction.RESOLVE_BLOCKER: (
        "Active blocker continues to impact delivery. Blocked items will "
        "accumulate and may spill into the next sprint."
    ),
    RecommendationAction.ESCALATE_BLOCKER_EARLY: (
        "Blocker exposure compounds — later escalation is costlier and "
        "options narrow as the sprint end approaches."
    ),
    RecommendationAction.CROSS_TRAIN_BACKUP: (
        "Critical path remains concentrated on one resource. Any absence "
        "or overload event will have no mitigation path."
    ),
    RecommendationAction.INSERT_REVIEW_GATE: (
        "Review quality risk remains elevated. Defects discovered post-sprint "
        "create rework loops that erode future sprint capacity."
    ),
    RecommendationAction.FREEZE_SCOPE_REQUEST: (
        "Scope volatility continues to dilute team focus and increase "
        "sprint overcommitment risk."
    ),
    RecommendationAction.REBASELINE_ESTIMATE: (
        "Forecast uncertainty remains high. Stakeholders and planning cadence "
        "are working from potentially stale assumptions."
    ),
    RecommendationAction.APPLY_RAMP_UP_DISCOUNT: (
        "Sprint plan remains optimistic for new team members. Actual velocity "
        "shortfall will appear as late-sprint surprise."
    ),
    RecommendationAction.REASSIGN_ITEM: (
        "Resource overload continues, increasing burnout risk and delivery "
        "unreliability for the affected items."
    ),
    RecommendationAction.REBALANCE_SPRINT_LOAD: (
        "Capacity imbalance persists. Bottleneck resource remains a single "
        "point of delivery risk for the sprint."
    ),
    RecommendationAction.ADD_RESOURCE_SKILL: (
        "Skill gap remains open. Work requiring this skill will be delayed "
        "or delivered at lower quality."
    ),
    RecommendationAction.PARALLELIZE_ITEMS: (
        "Work is sequenced unnecessarily. Total elapsed time is longer than "
        "the team's actual capacity requires."
    ),
    RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT: (
        "High-value item remains queued late. Discovery of blockers is deferred "
        "and schedule buffer erodes."
    ),
    RecommendationAction.PULL_FORWARD_ITEM: (
        "Sprint capacity remains underutilised while future sprints are at risk "
        "of overcommitment."
    ),
    RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK: (
        "Dependency chain blocks downstream items. Critical path length "
        "grows and schedule risk compounds."
    ),
    RecommendationAction.SPLIT_ITEM: (
        "Large item remains a single delivery risk. If it slips, the entire "
        "sprint commitment is at risk."
    ),
    RecommendationAction.SPLIT_AND_PAIR: (
        "Item remains large and single-threaded. Parallelism opportunity is "
        "missed and review coverage stays low."
    ),
    RecommendationAction.PAIR_REVIEWER: (
        "Knowledge concentration on this work area increases. Future review "
        "capacity depends on a single team member."
    ),
    RecommendationAction.ASSIGN_AS_SECOND_REVIEWER: (
        "Single-reviewer bottleneck continues. Review latency may delay item "
        "completion at sprint close."
    ),
    RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM: (
        "Non-critical work competes with the critical path for shared resources. "
        "Focus and throughput on critical items is reduced."
    ),
    RecommendationAction.SWARM_ITEM: (
        "At-risk item continues on its current trajectory. If it misses the "
        "sprint, the team's committed scope is incomplete."
    ),
}


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class PMExplanationGenerator:
    """Generate a PMExplanation for a single Recommendation.

    signal_map: signal_id → OpportunitySignal, for trigger detail lookup.
    """

    def __init__(
        self,
        upstream: UpstreamEngineOutputs,
        project_state: Optional[ProjectState] = None,
        signal_map: Optional[Dict[str, OpportunitySignal]] = None,
    ) -> None:
        self.upstream = upstream
        self._project_state = project_state
        self.signal_map = signal_map or {}

    def explain(
        self,
        rec: Recommendation,
        impact: Optional[ImpactEstimate] = None,
        sim: Optional[SimulationResult] = None,
    ) -> PMExplanation:
        action = rec.action_type
        objective = objective_for(action)
        effort = effort_for(action)

        # Detect signal category from metadata or root-cause signal
        signal_category = self._detect_signal_category(rec)
        trigger_reason = trigger_for(signal_category)
        trigger_detail = self._trigger_detail(rec, signal_category, impact, sim)

        strategic_benefits = _STRATEGIC_BENEFITS.get(action, [
            "Reduces project execution risk",
            "Improves delivery predictability",
        ])

        ignore_consequence = _IGNORE_CONSEQUENCE.get(
            action,
            "Risk and uncertainty remain elevated for the affected delivery area.",
        )

        is_immediate = effort in (ImplementationEffort.LOW, ImplementationEffort.MEDIUM)
        if action in {
            RecommendationAction.CROSS_TRAIN_BACKUP,
            RecommendationAction.PAIR_REVIEWER,
            RecommendationAction.ASSIGN_AS_SECOND_REVIEWER,
            RecommendationAction.REBASELINE_ESTIMATE,
            RecommendationAction.APPLY_RAMP_UP_DISCOUNT,
            RecommendationAction.ADD_RESOURCE_SKILL,
        }:
            is_immediate = False

        if is_immediate:
            impact_horizon = "Immediate"
        elif effort == ImplementationEffort.MEDIUM:
            impact_horizon = "Next Sprint"
        else:
            impact_horizon = "Long Term"

        return PMExplanation(
            trigger_reason=trigger_reason,
            trigger_detail=trigger_detail,
            primary_objective=objective,
            strategic_benefits=strategic_benefits,
            ignore_consequence=ignore_consequence,
            implementation_effort=effort,
            is_immediate_impact=is_immediate,
            impact_horizon=impact_horizon,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_signal_category(self, rec: Recommendation) -> Optional[SignalCategory]:
        meta = rec.metadata or {}
        params = meta.get("simulation_params") or {}
        cat_val = params.get("signal_category")
        if cat_val:
            try:
                return SignalCategory(cat_val)
            except ValueError:
                pass
        # Fall back to root-cause signal lookup
        sig = self.signal_map.get(rec.root_cause_signal_id)
        if sig:
            return sig.category
        return None

    def _trigger_detail(
        self,
        rec: Recommendation,
        signal_category: Optional[SignalCategory],
        impact: Optional[ImpactEstimate],
        sim: Optional[SimulationResult],
    ) -> str:
        """Build a one-sentence, data-grounded trigger explanation."""
        action = rec.action_type
        n_items = len(rec.affected_item_ids or [])
        n_resources = len(rec.affected_resource_ids or [])
        n_blockers = len(rec.affected_blocker_ids or [])

        delay_days = 0.0
        if impact:
            delay_days = float(impact.estimated_delay_reduction_days or 0.0)
        otp_gain = 0.0
        if sim:
            otp_gain = float(getattr(sim, "delta_on_time_probability", 0.0) or 0.0)

        # Action-specific rich triggers
        if action == RecommendationAction.CROSS_TRAIN_BACKUP:
            cp_items = len(self.upstream.cp_result.items_on_critical_path or [])
            team_size = max(1, len(rec.affected_resource_ids or [1]))
            return (
                f"{cp_items} critical path items currently have no backup coverage. "
                f"A single resource absence would stall delivery with no mitigation."
            )
        if action == RecommendationAction.RESOLVE_BLOCKER:
            return (
                f"{n_blockers} active blocker(s) are impeding {n_items} work item(s). "
                + (f"Resolving this could save up to {delay_days:.1f} days." if delay_days > 0 else
                   "Resolving this removes the immediate impediment to team progress.")
            )
        if action == RecommendationAction.REBASELINE_ESTIMATE:
            return (
                "Current estimates show significant deviation from actuals. "
                "Rebaselining will improve forecast accuracy and stakeholder confidence."
            )
        if action == RecommendationAction.FREEZE_SCOPE_REQUEST:
            return (
                "Scope additions in recent sprints are increasing commitment risk. "
                "A scope freeze protects the current sprint plan."
            )
        if action in {RecommendationAction.INSERT_REVIEW_GATE, RecommendationAction.PAIR_REVIEWER,
                      RecommendationAction.ASSIGN_AS_SECOND_REVIEWER}:
            return (
                f"{n_items} item(s) are approaching completion without sufficient review coverage. "
                "Adding a review step reduces late-stage defect risk."
            )
        if action in {RecommendationAction.REASSIGN_ITEM, RecommendationAction.REBALANCE_SPRINT_LOAD}:
            return (
                f"{n_resources} resource(s) show capacity imbalance. "
                "Redistribution improves team-level throughput and reduces overload risk."
            )
        if action == RecommendationAction.ADD_RESOURCE_SKILL:
            return (
                f"A skill gap is blocking {n_items} item(s) from progressing. "
                "Adding the required capability removes the execution constraint."
            )
        if action in {RecommendationAction.PARALLELIZE_ITEMS, RecommendationAction.SPLIT_ITEM,
                      RecommendationAction.SPLIT_AND_PAIR}:
            return (
                f"{n_items} item(s) can be parallelised or split to reduce elapsed time. "
                + (f"Expected to save {delay_days:.1f} days of delivery time." if delay_days > 0 else
                   "Improves sprint throughput without adding scope.")
            )
        if action == RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK:
            return (
                "A dependency bottleneck is blocking downstream work in the critical chain. "
                "Removing it reduces schedule risk and unlocks parallel delivery."
            )
        # Generic fallback with OTP gain if available
        if otp_gain > 0:
            return (
                f"Project signals indicate a delivery risk that this action can reduce. "
                f"Estimated on-time probability improvement: +{otp_gain*100:.1f}%."
            )
        return (
            f"Project signals indicate elevated risk across {n_items} work item(s). "
            "This action directly addresses the identified risk pattern."
        )

    # ------------------------------------------------------------------
    # v3.2 — intent, execution window, dimensions, trade-offs, impact profile
    # ------------------------------------------------------------------

    def _infer_intent(
        self,
        action: RecommendationAction,
        candidate: RecommendationCandidate,
    ) -> RecommendationIntent:
        params = candidate.simulation_params or {}

        if action == RecommendationAction.RESOLVE_BLOCKER:
            return RecommendationIntent.RECOVER
        if action == RecommendationAction.ESCALATE_BLOCKER_EARLY:
            overdue = float(params.get("overdue_days", 0) or 0)
            return RecommendationIntent.RECOVER if overdue > 0 else RecommendationIntent.PROTECT
        if action == RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK:
            return RecommendationIntent.RECOVER
        if action == RecommendationAction.CROSS_TRAIN_BACKUP:
            on_cp = bool(params.get("on_critical_path", False))
            return RecommendationIntent.RECOVER if on_cp else RecommendationIntent.PROTECT
        if action in {
            RecommendationAction.REBALANCE_SPRINT_LOAD,
            RecommendationAction.FREEZE_SCOPE_REQUEST,
            RecommendationAction.PULL_FORWARD_ITEM,
        }:
            return RecommendationIntent.PROTECT
        if action in {
            RecommendationAction.ADD_RESOURCE_SKILL,
            RecommendationAction.SPLIT_ITEM,
            RecommendationAction.SPLIT_AND_PAIR,
        }:
            return RecommendationIntent.PREVENT
        if action in {
            RecommendationAction.INSERT_REVIEW_GATE,
            RecommendationAction.PAIR_REVIEWER,
            RecommendationAction.ASSIGN_AS_SECOND_REVIEWER,
        }:
            return RecommendationIntent.GOVERN
        if action in {
            RecommendationAction.REBASELINE_ESTIMATE,
            RecommendationAction.APPLY_RAMP_UP_DISCOUNT,
        }:
            return RecommendationIntent.PREPARE
        return RecommendationIntent.IMPROVE

    def _execution_window(
        self,
        action: RecommendationAction,
        intent: RecommendationIntent,
        candidate: RecommendationCandidate,
    ) -> ExecutionWindow:
        from datetime import datetime, timezone
        params = candidate.simulation_params or {}
        now = datetime.now(timezone.utc)

        days_to_sprint_end: float = 999.0
        if self._project_state:
            active_sprint = next(
                (s for s in self._project_state.sprints if s.status.value == "In Progress"), None
            )
            if active_sprint:
                end = active_sprint.end_date
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                days_to_sprint_end = max(0.0, (end - now).total_seconds() / 86400.0)

        days_to_release: float = 999.0
        if self._project_state and self._project_state.project_info.release_date:
            rel = self._project_state.project_info.release_date
            if rel.tzinfo is None:
                rel = rel.replace(tzinfo=timezone.utc)
            days_to_release = max(0.0, (rel - now).total_seconds() / 86400.0)

        overdue = float(params.get("overdue_days", 0) or 0)

        if action in {RecommendationAction.RESOLVE_BLOCKER, RecommendationAction.ESCALATE_BLOCKER_EARLY} \
                or (intent == RecommendationIntent.RECOVER and overdue > 0):
            return ExecutionWindow.IMMEDIATELY
        if action == RecommendationAction.CROSS_TRAIN_BACKUP and params.get("on_critical_path"):
            return ExecutionWindow.IMMEDIATELY
        if days_to_release <= 7 and action in {
            RecommendationAction.FREEZE_SCOPE_REQUEST,
            RecommendationAction.INSERT_REVIEW_GATE,
            RecommendationAction.REBASELINE_ESTIMATE,
        }:
            return ExecutionWindow.BEFORE_RELEASE
        if days_to_sprint_end <= 3 and action in {
            RecommendationAction.REBALANCE_SPRINT_LOAD,
            RecommendationAction.FREEZE_SCOPE_REQUEST,
            RecommendationAction.REASSIGN_ITEM,
        }:
            return ExecutionWindow.IMMEDIATELY
        if action in {
            RecommendationAction.CROSS_TRAIN_BACKUP,
            RecommendationAction.ADD_RESOURCE_SKILL,
            RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK,
        }:
            return ExecutionWindow.NEXT_SPRINT
        if action in {
            RecommendationAction.INSERT_REVIEW_GATE,
            RecommendationAction.PAIR_REVIEWER,
            RecommendationAction.ASSIGN_AS_SECOND_REVIEWER,
            RecommendationAction.FREEZE_SCOPE_REQUEST,
            RecommendationAction.REBASELINE_ESTIMATE,
            RecommendationAction.APPLY_RAMP_UP_DISCOUNT,
        }:
            return ExecutionWindow.CURRENT_SPRINT
        return ExecutionWindow.CURRENT_SPRINT

    def _build_dimensions(
        self,
        action: RecommendationAction,
        impact: ImpactEstimate,
        sim: Optional[SimulationResult],
        candidate: RecommendationCandidate,
    ) -> List[ImpactDimension]:
        params = candidate.simulation_params or {}

        # ── Schedule ──────────────────────────────────────────────────────
        delay = float(impact.estimated_delay_reduction_days or 0.0)
        otp_gain = float(getattr(sim, "delta_on_time_probability", 0.0) or 0.0) if sim else 0.0
        schedule_score = max(min(1.0, delay / 5.0), min(1.0, otp_gain / 0.10))
        schedule_conf_level = (
            ImpactConfidence.VERY_HIGH if (sim and getattr(sim, "is_positive_impact", False))
            else ImpactConfidence.HIGH if delay > 0
            else ImpactConfidence.MEDIUM
        )
        schedule_conf_reason = (
            "Simulation validated the delay reduction estimate."
            if sim and getattr(sim, "is_positive_impact", False)
            else f"Derived from {round(delay, 1)}d delay reduction on affected items."
            if delay > 0
            else "No direct schedule shortening; heuristic estimate."
        )

        # ── Risk ──────────────────────────────────────────────────────────
        risk_score = min(1.0, float(impact.estimated_risk_reduction or 0.0))
        if sim:
            sim_risk = min(1.0, abs(float(getattr(sim, "delta_risk_score", 0.0) or 0.0)))
            risk_score = max(risk_score, sim_risk)
        risk_conf_level = ImpactConfidence.HIGH if risk_score > 0.3 else ImpactConfidence.MEDIUM
        risk_conf_reason = (
            "Risk delta derived from Risk Engine composite score."
            if risk_score > 0 else
            "Heuristic estimate; limited signal for this action type."
        )

        # ── Resilience ────────────────────────────────────────────────────
        resilience_score = 0.0
        resilience_evidence_obj = StructuredEvidence(
            metric="bus_factor", value=1.0, target="", message="Not applicable for this action type."
        )
        resilience_explanation = "Not applicable for this action type."
        resilience_conf = ConfidenceWithReason(ImpactConfidence.LOW, "No resilience signal for this action.")

        if action == RecommendationAction.CROSS_TRAIN_BACKUP and self._project_state:
            skills = {
                wi.required_skill
                for wi in self._project_state.work_items
                if wi.item_id in (candidate.affected_item_ids or []) and wi.required_skill
            }
            total = len(self._project_state.team or [])

            def _covers(resource, sk: str) -> bool:
                if resource.primary_skill == sk or resource.secondary_skill == sk:
                    return True
                return any(sc.skill == sk for sc in (resource.skill_coverage or []))

            with_skill = sum(
                1 for r in (self._project_state.team or [])
                if any(_covers(r, sk) for sk in skills)
            ) if skills else 1
            bus_factor = with_skill / max(total, 1)
            resilience_score = min(1.0, 1.0 - bus_factor + 0.15)
            skill_label = ", ".join(skills) if skills else "required skill"
            resilience_evidence_obj = StructuredEvidence(
                metric="bus_factor",
                value=round(bus_factor, 2),
                target=skill_label,
                message=f"Only {with_skill} of {total} team members cover {skill_label}.",
            )
            resilience_explanation = (
                "Cross-training creates redundancy so delivery continues "
                "if the sole skill owner becomes unavailable."
            )
            resilience_conf = ConfidenceWithReason(
                ImpactConfidence.HIGH,
                f"Bus factor computed from team skill matrix across {total} resources.",
            )

        elif action == RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK:
            resilience_score = 0.55
            resilience_evidence_obj = StructuredEvidence(
                metric="dependency_bottleneck", value=1.0, target="affected_items",
                message="Dependency bottleneck detected on affected work items.",
            )
            resilience_explanation = (
                "Removing a dependency bottleneck reduces systemic fragility — "
                "multiple downstream items are unblocked simultaneously."
            )
            resilience_conf = ConfidenceWithReason(
                ImpactConfidence.MEDIUM, "Heuristic; bottleneck count from dependency graph."
            )

        # ── Quality ───────────────────────────────────────────────────────
        quality_score = 0.0
        quality_evidence_obj = StructuredEvidence(
            metric="rework_risk_reduction", value=0.0, target="",
            message="Not applicable for this action type.",
        )
        quality_explanation = "Not applicable for this action type."
        quality_conf = ConfidenceWithReason(ImpactConfidence.LOW, "No quality signal for this action.")

        if action in {
            RecommendationAction.PAIR_REVIEWER,
            RecommendationAction.ASSIGN_AS_SECOND_REVIEWER,
            RecommendationAction.INSERT_REVIEW_GATE,
        } and self._project_state:
            est_error = self._safe_est_error()
            item_count = len(candidate.affected_item_ids or [])
            total_items = max(len(self._project_state.work_items), 1)
            coverage = min(1.0, item_count / total_items * 5)
            quality_score = min(1.0, 0.30 + est_error * 1.2 + coverage * 0.25)
            quality_evidence_obj = StructuredEvidence(
                metric="estimation_error_pct",
                value=round(est_error, 4),
                target=f"{item_count}_items",
                message=f"Historical estimation error: {round(est_error * 100):.0f}%. Covering {item_count} item(s).",
            )
            quality_explanation = (
                "A second reviewer or review gate catches defects before they propagate, "
                f"reducing downstream rework risk by ~{round(quality_score * 100):.0f}%."
            )
            quality_conf = ConfidenceWithReason(
                ImpactConfidence.MEDIUM,
                "Heuristic derived from historical estimation error and item coverage ratio.",
            )

        # ── Forecast ──────────────────────────────────────────────────────
        forecast_score = 0.0
        forecast_evidence_obj = StructuredEvidence(
            metric="forecast_reliability_gain", value=0.0, target="",
            message="Not applicable for this action type.",
        )
        forecast_explanation = "Not applicable for this action type."
        forecast_conf = ConfidenceWithReason(ImpactConfidence.LOW, "No forecast signal for this action.")

        if action in {RecommendationAction.REBASELINE_ESTIMATE, RecommendationAction.APPLY_RAMP_UP_DISCOUNT}:
            est_error = self._safe_est_error()
            target_id = params.get("target_resource_id", "")
            load_factor = self._resource_load_factor(target_id)
            forecast_score = min(1.0, 0.35 + est_error * 1.5 + max(0.0, load_factor) * 0.20)
            forecast_evidence_obj = StructuredEvidence(
                metric="estimation_error_pct",
                value=round(est_error, 4),
                target=target_id or "project",
                message=(
                    f"Estimation error: {round(est_error * 100):.0f}%. "
                    + (f"Resource at {round((1 - load_factor) * 100):.0f}% effective capacity." if load_factor > 0 else "")
                ),
            )
            forecast_explanation = (
                "Correcting estimates aligns the plan with reality, "
                f"improving forecast reliability by ~{round(forecast_score * 100):.0f}%."
            )
            forecast_conf = ConfidenceWithReason(
                ImpactConfidence.HIGH if est_error > 0.2 else ImpactConfidence.MEDIUM,
                "Derived from Forecast Engine estimation error metric.",
            )

        # ── Governance ────────────────────────────────────────────────────
        _gov_map = {
            RecommendationAction.INSERT_REVIEW_GATE:        0.70,
            RecommendationAction.FREEZE_SCOPE_REQUEST:      0.65,
            RecommendationAction.ESCALATE_BLOCKER_EARLY:    0.50,
            RecommendationAction.PAIR_REVIEWER:             0.45,
            RecommendationAction.ASSIGN_AS_SECOND_REVIEWER: 0.40,
            RecommendationAction.REBASELINE_ESTIMATE:       0.35,
        }
        governance_score = _gov_map.get(action, 0.0)
        governance_evidence_obj = StructuredEvidence(
            metric="governance_control_added",
            value=governance_score,
            target=action.value,
            message=(
                "Process control mechanism added to the delivery flow."
                if governance_score > 0 else "Not applicable for this action type."
            ),
        )
        governance_explanation = (
            "Governance actions reduce variance in delivery outcomes and create audit-ready process records."
            if governance_score > 0 else "Not applicable for this action type."
        )
        governance_conf = ConfidenceWithReason(
            ImpactConfidence.HIGH if governance_score > 0.5 else ImpactConfidence.MEDIUM if governance_score > 0 else ImpactConfidence.LOW,
            "Heuristic score from action-type governance mapping." if governance_score > 0 else "No governance signal.",
        )

        # ── Resource ──────────────────────────────────────────────────────
        resource_score = 0.0
        n = len(candidate.affected_resource_ids or [])
        resource_evidence_obj = StructuredEvidence(
            metric="resources_rebalanced", value=0.0, target="",
            message="Not applicable for this action type.",
        )
        resource_explanation = "Not applicable for this action type."
        resource_conf = ConfidenceWithReason(ImpactConfidence.LOW, "No resource signal for this action.")

        if action in {
            RecommendationAction.REASSIGN_ITEM,
            RecommendationAction.REBALANCE_SPRINT_LOAD,
            RecommendationAction.ADD_RESOURCE_SKILL,
        }:
            resource_score = min(1.0, 0.40 + 0.10 * n)
            resource_evidence_obj = StructuredEvidence(
                metric="resources_rebalanced",
                value=float(n),
                target=",".join(candidate.affected_resource_ids or []),
                message=f"Workload rebalanced across {n} resource(s).",
            )
            resource_explanation = (
                "Reducing overload on critical resources improves throughput "
                "and decreases the probability of burnout-driven delays."
            )
            resource_conf = ConfidenceWithReason(
                ImpactConfidence.MEDIUM, "Heuristic derived from resource count and allocation data."
            )

        return [
            ImpactDimension(
                type=ImpactDimensionType.SCHEDULE,
                score=schedule_score,
                confidence=ConfidenceWithReason(schedule_conf_level, schedule_conf_reason),
                evidence=StructuredEvidence(
                    metric="delay_reduction_days",
                    value=round(delay, 2),
                    target="affected_items",
                    message=(
                        f"{round(delay, 1)}d delay reduction detected on affected work items."
                        if delay > 0 else "No direct schedule shortening measured."
                    ),
                ),
                explanation=(
                    "Recovering time on the critical path directly improves on-time delivery probability."
                    if delay > 0 else
                    "Value is strategic; schedule impact manifests through downstream dimensions."
                ),
                source=EngineSource.FORECAST_ENGINE,
            ),
            ImpactDimension(
                type=ImpactDimensionType.RISK,
                score=risk_score,
                confidence=ConfidenceWithReason(risk_conf_level, risk_conf_reason),
                evidence=StructuredEvidence(
                    metric="risk_reduction_pct",
                    value=round(risk_score, 4),
                    target="overall_delivery_risk",
                    message=f"Overall delivery risk score reduced by ~{round(risk_score * 100):.0f}%.",
                ),
                explanation=(
                    "Lower delivery risk increases stakeholder confidence and reduces "
                    "the probability of late-stage escalations."
                ),
                source=EngineSource.RISK_ENGINE,
            ),
            ImpactDimension(
                type=ImpactDimensionType.RESILIENCE,
                score=resilience_score,
                confidence=resilience_conf,
                evidence=resilience_evidence_obj,
                explanation=resilience_explanation,
                source=EngineSource.RESOURCE_ENGINE,
            ),
            ImpactDimension(
                type=ImpactDimensionType.QUALITY,
                score=quality_score,
                confidence=quality_conf,
                evidence=quality_evidence_obj,
                explanation=quality_explanation,
                source=EngineSource.RISK_ENGINE,
            ),
            ImpactDimension(
                type=ImpactDimensionType.FORECAST,
                score=forecast_score,
                confidence=forecast_conf,
                evidence=forecast_evidence_obj,
                explanation=forecast_explanation,
                source=EngineSource.FORECAST_ENGINE,
            ),
            ImpactDimension(
                type=ImpactDimensionType.GOVERNANCE,
                score=governance_score,
                confidence=governance_conf,
                evidence=governance_evidence_obj,
                explanation=governance_explanation,
                source=EngineSource.RISK_ENGINE,
            ),
            ImpactDimension(
                type=ImpactDimensionType.RESOURCE,
                score=resource_score,
                confidence=resource_conf,
                evidence=resource_evidence_obj,
                explanation=resource_explanation,
                source=EngineSource.RESOURCE_ENGINE,
            ),
        ]

    def _safe_est_error(self) -> float:
        try:
            return float(self.upstream.metrics.historical_metrics.avg_estimation_error_pct or 0.15)
        except AttributeError:
            return 0.15

    def _resource_load_factor(self, resource_id: Optional[str]) -> float:
        if not self._project_state or not resource_id:
            return 0.0
        resource = next((r for r in self._project_state.team if r.resource_id == resource_id), None)
        if resource is None:
            return 0.0
        alloc = float(getattr(resource, "allocation_pct", 1.0))
        avail = float(getattr(resource, "availability_pct", 1.0))
        return 1.0 - (alloc * avail)

    def _build_trade_offs(
        self,
        action: RecommendationAction,
        candidate: RecommendationCandidate,
    ) -> List[str]:
        params = candidate.simulation_params or {}
        trade_offs: List[str] = []

        if action == RecommendationAction.CROSS_TRAIN_BACKUP:
            trainer_id = params.get("target_resource_id")
            allocation = 0.7
            if self._project_state and trainer_id:
                resource = next((r for r in self._project_state.team if r.resource_id == trainer_id), None)
                if resource:
                    allocation = float(getattr(resource, "allocation_pct", 0.7))
            if allocation >= 0.90:
                trade_offs.append(f"High disruption: trainer ({trainer_id or 'SPOF resource'}) is at {round(allocation * 100):.0f}% allocation — schedule impact is likely.")
            elif allocation >= 0.75:
                trade_offs.append(f"Moderate disruption: trainer ({trainer_id or 'SPOF resource'}) is at {round(allocation * 100):.0f}% allocation — some velocity reduction expected.")
            else:
                trade_offs.append("Low disruption: trainer has available capacity.")
        elif action in {RecommendationAction.PAIR_REVIEWER, RecommendationAction.ASSIGN_AS_SECOND_REVIEWER}:
            item_count = len(candidate.affected_item_ids or [])
            trade_offs.append(f"Adds review cycle time across {item_count} work item(s); net effect depends on current review throughput.")
        elif action == RecommendationAction.INSERT_REVIEW_GATE:
            trade_offs.append("Review gate adds process overhead; throughput may dip while gate is calibrated.")
            trade_offs.append("Requires a designated reviewer with available capacity.")
        elif action == RecommendationAction.REBASELINE_ESTIMATE:
            trade_offs.append("Schedule extends on paper (honest, not pessimistic); stakeholder re-alignment on delivery date may be required.")
        elif action == RecommendationAction.APPLY_RAMP_UP_DISCOUNT:
            trade_offs.append("Reduces apparent sprint capacity; may require scope negotiation with stakeholders.")
        elif action == RecommendationAction.FREEZE_SCOPE_REQUEST:
            trade_offs.append("Requires stakeholder agreement; requested features may be deferred.")
        elif action == RecommendationAction.RESOLVE_BLOCKER:
            trade_offs.append("Resolution effort competes with other sprint commitments.")
        elif action == RecommendationAction.REASSIGN_ITEM:
            receiver_id = params.get("target_resource_id", "receiving resource")
            trade_offs.append(f"Context handover required for {receiver_id}; ramp-up adds a small schedule cost.")
        elif action == RecommendationAction.PARALLELIZE_ITEMS:
            trade_offs.append("Coordination overhead between parallel streams; sync points must be planned.")
        elif action == RecommendationAction.SPLIT_ITEM:
            trade_offs.append("Splitting adds definition and refinement effort before execution can begin.")
        elif action == RecommendationAction.ADD_RESOURCE_SKILL:
            trade_offs.append("Training or hiring takes longer than the current sprint; benefit is future-sprint.")

        return trade_offs

    def build_impact_profile(
        self,
        rec: "Recommendation",
        candidate: RecommendationCandidate,
        impact: ImpactEstimate,
        explanation: PMExplanation,           # partially built by explain()
        sim: Optional[SimulationResult] = None,
    ) -> "RecommendationImpactProfile":

        action = rec.action_type
        intent = self._infer_intent(action, candidate)
        dims = self._build_dimensions(action, impact, sim, candidate)
        window = self._execution_window(action, intent, candidate)
        trade_offs = self._build_trade_offs(action, candidate)

        # Aggregate confidence (conservative minimum across dims)
        _order = [ImpactConfidence.VERY_HIGH, ImpactConfidence.HIGH, ImpactConfidence.MEDIUM, ImpactConfidence.LOW]
        worst_idx = max(_order.index(d.confidence.level) for d in dims)
        aggregate_conf = _order[worst_idx]
        if sim and getattr(sim, "is_positive_impact", False):
            _upgrade = {
                ImpactConfidence.HIGH: ImpactConfidence.VERY_HIGH,
                ImpactConfidence.MEDIUM: ImpactConfidence.HIGH,
                ImpactConfidence.LOW: ImpactConfidence.MEDIUM,
            }
            aggregate_conf = _upgrade.get(aggregate_conf, aggregate_conf)

        primary_type = max(dims, key=lambda d: d.score).type if dims else ImpactDimensionType.RISK
        primary_dim = next((d for d in dims if d.type == primary_type), None)

        _outcome_templates = {
            ImpactDimensionType.SCHEDULE:   f"Estimated {round(float(impact.estimated_delay_reduction_days or 0), 1)}d schedule recovery on affected work.",
            ImpactDimensionType.RISK:       f"Overall delivery risk reduced by ~{round((primary_dim.score if primary_dim else 0) * 100):.0f}%.",
            ImpactDimensionType.RESILIENCE: "Bus-factor risk reduced; backup coverage established for the affected skill area.",
            ImpactDimensionType.QUALITY:    f"Rework probability reduced by an estimated {round((primary_dim.score if primary_dim else 0) * 100):.0f}%.",
            ImpactDimensionType.FORECAST:   f"Forecast confidence improved; planning error impact reduced by ~{round((primary_dim.score if primary_dim else 0) * 100):.0f}%.",
            ImpactDimensionType.GOVERNANCE: "Governance control added; process compliance and delivery predictability improved.",
            ImpactDimensionType.RESOURCE:   "Workload rebalanced; overload risk and throughput bottleneck reduced.",
        }
        expected_outcome = _outcome_templates.get(primary_type, impact.calculation_notes or "Delivery risk reduced.")

        # Fill in the three new PMExplanation fields (mutating the passed object)
        explanation.expected_outcome = expected_outcome
        explanation.trade_offs = trade_offs
        explanation.evidence_narrative = impact.calculation_notes or ""

        return RecommendationImpactProfile(
            decision_context=RecommendationDecisionContext(intent=intent, execution_window=window),
            impact_metrics=RecommendationImpactMetrics(
                dimensions=dims,
                primary_dimension=primary_type,
                impact_tier=_impact_tier_from_dims(dims),
                aggregate_confidence=aggregate_conf,
            ),
            explanation=explanation,   # same reference as PMIntelligence.explanation
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _impact_tier_from_dims(dims: List[ImpactDimension]) -> str:
    if not dims:
        return "Low"
    best = max(d.score for d in dims)
    if best >= 0.65:
        return "High"
    if best >= 0.35:
        return "Medium"
    return "Low"

