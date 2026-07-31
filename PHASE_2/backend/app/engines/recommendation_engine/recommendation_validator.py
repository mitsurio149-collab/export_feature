from __future__ import annotations

from typing import Dict, List, Optional

from app.domain.models import ProjectState
from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    OpportunitySignal,
    Recommendation,
    RecommendationAction,
    RecommendationValidation,
    SimulationResult,
    TradeOff,
    UpstreamEngineOutputs,
)


class RecommendationValidator:
    """
    Runs after PriorityEngine. Produces a RecommendationValidation per recommendation
    by grounding the explanation in the available signal context and comparison data.

    Now accepts an optional simulation_results dict so delay/prob summaries are
    derived from measured simulation output rather than heuristic estimates.
    """

    def __init__(
        self,
        project_state: ProjectState,
        upstream: UpstreamEngineOutputs,
        signals_by_id: Dict[str, OpportunitySignal],
    ) -> None:
        self.project_state = project_state
        self.upstream = upstream
        self.signals_by_id = signals_by_id
        self._items = {wi.item_id: wi for wi in getattr(project_state, "work_items", [])}
        self._resources = self._build_resource_lookup(project_state)

    def validate_all(
        self,
        ranked: List[Recommendation],
        simulation_results: Optional[Dict[str, SimulationResult]] = None,
    ) -> Dict[str, RecommendationValidation]:
        sim = simulation_results or {}
        result: Dict[str, RecommendationValidation] = {}
        for rec in ranked:
            alternatives = self._find_alternatives(rec, ranked)
            result[rec.recommendation_id] = self._validate_one(
                rec, alternatives, sim.get(rec.recommendation_id)
            )
        return result

    def _find_alternatives(self, rec: Recommendation, ranked: List[Recommendation]) -> List[Recommendation]:
        rec_targets = set(rec.affected_item_ids) | set(rec.affected_resource_ids) | set(rec.affected_blocker_ids)
        if not rec_targets:
            return []
        alternatives = []
        for other in ranked:
            if other.recommendation_id == rec.recommendation_id:
                continue
            other_targets = set(other.affected_item_ids) | set(other.affected_resource_ids) | set(other.affected_blocker_ids)
            if rec_targets & other_targets:
                alternatives.append(other)
        return alternatives

    def _validate_one(
        self,
        rec: Recommendation,
        alternatives: List[Recommendation],
        sim: Optional[SimulationResult] = None,
    ) -> RecommendationValidation:
        why_selected = self._build_why_selected(rec)
        why_better, rejected = self._build_comparison(rec, alternatives)
        confidence_reasoning = self._build_confidence_reasoning(rec)
        trade_offs = self._build_trade_offs(rec)

        # Fix 2: prefer simulation results for delay and OTP summaries; fall back
        # to heuristic estimates only when simulation wasn't run for this rec.
        # Guard: some test mocks return a SimpleNamespace without baseline_metrics.
        if sim is not None and hasattr(sim, "baseline_metrics") and sim.baseline_metrics is not None:
            delay_before = round(sim.baseline_metrics.expected_delay_days, 1)
            delay_after  = round(sim.simulated_metrics.expected_delay_days, 1)
            prob_before  = round(sim.baseline_metrics.on_time_probability * 100)
            prob_after   = round(sim.simulated_metrics.on_time_probability * 100)
        else:
            sim = None  # fall through to heuristic path
            delay_before = round(getattr(self.upstream.forecast, "expected_delay_days", 0.0), 1)
            delay_after  = round(max(0.0, delay_before - rec.estimated_delay_reduction_days), 1)
            prob_before  = round(getattr(self.upstream.monte_carlo, "on_time_probability", 0.0) * 100)
            prob_gain    = round(rec.estimated_risk_reduction * 100)
            prob_after   = round(min(100.0, prob_before + prob_gain))

        delay_summary = f"{delay_before}d → {delay_after}d"
        prob_summary  = f"{prob_before}% → {prob_after}%"
        pitch = self._build_one_line_pitch(rec, delay_before, delay_after, sim)

        return RecommendationValidation(
            recommendation_id=rec.recommendation_id,
            why_selected=why_selected,
            why_better_than_alternatives=why_better,
            rejected_alternatives=rejected,
            delay_reduction_summary=delay_summary,
            probability_improvement_summary=prob_summary,
            confidence_label=rec.confidence,
            confidence_reasoning=confidence_reasoning,
            trade_offs=trade_offs,
            one_line_pitch=pitch,
        )

    # ------------------------------------------------------------------ #
    # Fix 4: why_selected handlers for all action types                   #
    # ------------------------------------------------------------------ #

    def _build_why_selected(self, rec: Recommendation) -> List[str]:
        signal = self.signals_by_id.get(rec.root_cause_signal_id)
        ctx = signal.context if signal else {}
        dispatch = {
            RecommendationAction.REASSIGN_ITEM:                  self._why_reassign,
            RecommendationAction.RESOLVE_BLOCKER:                self._why_resolve_blocker,
            RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT: self._why_advance_item,
            RecommendationAction.PARALLELIZE_ITEMS:              self._why_parallelize,
            RecommendationAction.SPLIT_ITEM:                     self._why_split_item,
            RecommendationAction.REBALANCE_SPRINT_LOAD:          self._why_rebalance_sprint_load,
            RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK:   self._why_remove_dep_bottleneck,
            RecommendationAction.ADD_RESOURCE_SKILL:             self._why_add_resource_skill,
            RecommendationAction.REBASELINE_ESTIMATE:            self._why_rebaseline_estimate,
            RecommendationAction.PAIR_REVIEWER:                  self._why_pair_reviewer,
            RecommendationAction.ESCALATE_BLOCKER_EARLY:         self._why_escalate_blocker_early,
            RecommendationAction.CROSS_TRAIN_BACKUP:             self._why_cross_train_backup,
            RecommendationAction.INSERT_REVIEW_GATE:             self._why_insert_review_gate,
            RecommendationAction.APPLY_RAMP_UP_DISCOUNT:         self._why_ramp_up_discount,
            RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM:   self._why_resequence,
            RecommendationAction.SWARM_ITEM:                     self._why_swarm_item,
            RecommendationAction.FREEZE_SCOPE_REQUEST:           self._why_freeze_scope,
        }
        handler = dispatch.get(rec.action_type)
        bullets = handler(rec, ctx) if handler else []
        return bullets or [rec.description]

    def _why_reassign(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        load_ratio = ctx.get("load_ratio")
        if load_ratio is not None:
            overload_pct = round((load_ratio - 1.0) * 100)
            source_name = self._resource_name((rec.affected_resource_ids or [None])[0])
            if overload_pct > 0:
                bullets.append(f"{source_name} is overloaded by {overload_pct}%")
            else:
                bullets.append(f"{source_name} has a load imbalance ({round(load_ratio * 100)}% of capacity)")
        receiver_id = rec.metadata.get("simulation_params", {}).get("receiving_resource_id") if rec.metadata else None
        if receiver_id:
            receiver = self._resources.get(receiver_id)
            receiver_name = receiver.name if receiver else receiver_id
            free_hours = self._free_hours(receiver_id)
            if free_hours is not None:
                bullets.append(f"{receiver_name} has {round(free_hours)} hours free")
            item_id = (rec.affected_item_ids or [None])[0]
            item = self._items.get(item_id) if item_id else None
            if item and receiver:
                req_skill = getattr(item, "required_skill", None)
                if req_skill and (receiver.primary_skill == req_skill or receiver.secondary_skill == req_skill):
                    bullets.append(f"Story requires {req_skill} skill, which {receiver_name} has")
        dep_conflict = self._has_dependency_conflict(rec.affected_item_ids)
        bullets.append("No dependency conflict" if not dep_conflict else f"Note: dependency conflict on {dep_conflict}")
        return bullets

    def _why_resolve_blocker(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        blocker_id = (rec.affected_blocker_ids or [None])[0]
        blocker = next((b for b in getattr(self.project_state, "blockers", []) if getattr(b, "blocker_id", None) == blocker_id), None)
        if blocker:
            severity = blocker.severity.value if hasattr(blocker.severity, "value") else str(blocker.severity)
            bullets.append(f"{severity} severity blocker, blocking {len(getattr(blocker, 'impacted_item_ids', []) or [])} item(s)")
        overdue = ctx.get("days_overdue", 0)
        if overdue and overdue > 0:
            bullets.append(f"{overdue} day(s) past target resolution date")
        if ctx.get("on_critical_path", False):
            bullets.append("Blocking items are on the critical path")
        return bullets

    def _why_advance_item(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        item_id = (rec.affected_item_ids or [None])[0]
        item = self._items.get(item_id) if item_id else None
        if item:
            downstream_count = sum(1 for dep in getattr(self.project_state, "dependencies", []) if getattr(dep, "predecessor_item_id", None) == item_id)
            if downstream_count > 0:
                bullets.append(f"Prerequisite for {downstream_count} downstream item(s)")
        spillover_days = ctx.get("delay_breakdown", {}).get("spillover_days") if isinstance(ctx.get("delay_breakdown"), dict) else None
        if spillover_days:
            bullets.append(f"Contributes to {round(spillover_days, 1)} days of predicted spillover")
        return bullets

    def _why_parallelize(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        cp_length = ctx.get("cp_remaining_hours")
        if cp_length:
            bullets.append(f"{round(cp_length)} hours remain on the critical path")
        bullets.append(f"Parallelising {len(rec.affected_item_ids)} items reduces sequential dependency drag")
        return bullets

    def _why_split_item(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        for item_id in rec.affected_item_ids[:1]:
            item = self._items.get(item_id)
            if item:
                bullets.append(f"Item has {round(float(getattr(item, 'current_estimate_hrs', 0.0)))}h estimate — splitting reduces batch size and improves predictability")
        cp_items = set(getattr(self.upstream.cp_result, "items_on_critical_path", []) or [])
        if any(iid in cp_items for iid in rec.affected_item_ids):
            bullets.append("Item is on the critical path — splitting allows the completed half to unblock successors earlier")
        return bullets

    def _why_rebalance_sprint_load(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        overloaded = [sm for sm in self.upstream.metrics.sprint_metrics if sm.completion_pct > 1.0]
        underloaded = [sm for sm in self.upstream.metrics.sprint_metrics if sm.completion_pct < 0.5]
        if overloaded:
            bullets.append(f"{len(overloaded)} sprint(s) are over-committed (>100% planned capacity)")
        if underloaded:
            bullets.append(f"{len(underloaded)} sprint(s) have capacity slack that can absorb rebalanced work")
        resource_id = (rec.affected_resource_ids or [None])[0]
        if resource_id:
            bullets.append(f"Rebalancing targets {self._resource_name(resource_id)} to absorb the moved work")
        return bullets

    def _why_remove_dep_bottleneck(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        cp_items = set(getattr(self.upstream.cp_result, "items_on_critical_path", []) or [])
        on_cp = any(iid in cp_items for iid in rec.affected_item_ids)
        if on_cp:
            bullets.append("Dependency bottleneck sits on the critical path — removing it shortens end-to-end duration")
        dep_count = sum(
            1 for dep in getattr(self.project_state, "dependencies", [])
            if dep.predecessor_item_id in rec.affected_item_ids or dep.successor_item_id in rec.affected_item_ids
        )
        if dep_count:
            bullets.append(f"Affects {dep_count} dependency edge(s) in the project graph")
        return bullets

    def _why_add_resource_skill(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        resource_id = (rec.affected_resource_ids or [None])[0]
        sim_params = rec.metadata.get("simulation_params", {}) if rec.metadata else {}
        req_skill = sim_params.get("required_skill")
        if resource_id and req_skill:
            bullets.append(f"{self._resource_name(resource_id)} lacks the required {req_skill} skill for affected items")
        resource_risk = float(getattr(getattr(self.upstream.risk_result, "resource_risk", None), "score", 0.0) or 0.0)
        if resource_risk > 0.4:
            bullets.append(f"Resource risk score is {round(resource_risk * 100)}% — skill coverage reduces single-point-of-failure exposure")
        return bullets

    def _why_rebaseline_estimate(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        for item_id in rec.affected_item_ids[:2]:
            item = self._items.get(item_id)
            if item:
                actual = float(getattr(item, "actual_effort_hrs", 0.0) or 0.0)
                estimated = float(getattr(item, "current_estimate_hrs", 1.0) or 1.0)
                if actual > 0 and estimated > 0:
                    overrun_pct = round((actual / estimated - 1.0) * 100)
                    if overrun_pct > 10:
                        bullets.append(f"Item is running {overrun_pct}% over its estimate ({round(actual)}h actual vs {round(estimated)}h planned)")
        if not bullets:
            bullets.append("Estimation patterns indicate the current baseline underestimates remaining work")
        return bullets

    def _why_pair_reviewer(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        rework_rate = ctx.get("rework_rate") or ctx.get("rework_loop_rate")
        if rework_rate:
            bullets.append(f"Detected rework rate of {round(float(rework_rate) * 100)}% on affected items")
        bullets.append("Pairing a reviewer reduces rework-driven delays from late-stage quality failures")
        return bullets

    def _why_escalate_blocker_early(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        blocker_id = (rec.affected_blocker_ids or [None])[0]
        blocker = next((b for b in getattr(self.project_state, "blockers", []) if getattr(b, "blocker_id", None) == blocker_id), None)
        if blocker:
            severity = blocker.severity.value if hasattr(blocker.severity, "value") else str(blocker.severity)
            bullets.append(f"Blocker is {severity} severity and has not been formally escalated")
            if getattr(blocker, "target_resolution_date", None):
                bullets.append(f"Target resolution date at risk — early escalation pulls the date forward")
        pattern = ctx.get("recurrence_count")
        if pattern and int(pattern) > 1:
            bullets.append(f"This blocker category has recurred {pattern} times — systemic escalation is warranted")
        return bullets

    def _why_cross_train_backup(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        spof_id = (rec.affected_resource_ids or [None])[0]
        backup_id = rec.affected_resource_ids[1] if len(rec.affected_resource_ids) > 1 else None
        cp_items = set(getattr(self.upstream.cp_result, "items_on_critical_path", []) or [])
        critical_count = sum(1 for iid in rec.affected_item_ids if iid in cp_items)
        if spof_id:
            bullets.append(f"{self._resource_name(spof_id)} is the sole owner of {critical_count} critical-path item(s)")
        if backup_id:
            free = self._free_hours(backup_id)
            if free is not None:
                bullets.append(f"{self._resource_name(backup_id)} has {round(free)}h available and is the proposed backup")
        resource_risk = float(getattr(getattr(self.upstream.risk_result, "resource_risk", None), "score", 0.0) or 0.0)
        if resource_risk > 0.3:
            bullets.append(f"Resource risk score is {round(resource_risk * 100)}% — backup coverage directly lowers this")
        return bullets

    def _why_insert_review_gate(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        cp_items = set(getattr(self.upstream.cp_result, "items_on_critical_path", []) or [])
        on_cp = any(iid in cp_items for iid in rec.affected_item_ids)
        if on_cp:
            bullets.append("Affected item(s) are on the critical path — a review gate catches defects before they propagate")
        rework = ctx.get("rework_loop_rate") or ctx.get("rework_rate")
        if rework:
            bullets.append(f"Rework rate of {round(float(rework) * 100)}% detected — inserting a gate breaks the loop earlier")
        return bullets

    def _why_ramp_up_discount(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        resource_id = (rec.affected_resource_ids or [None])[0]
        if resource_id:
            resource = self._resources.get(resource_id)
            join_date = ctx.get("join_date") or getattr(resource, "join_date", None)
            bullets.append(f"{self._resource_name(resource_id)} is recently ramped up — their forecast contribution is currently overstated")
            if join_date:
                bullets.append(f"Join date: {join_date} — applying a discount gives a more realistic velocity estimate")
        return bullets

    def _why_resequence(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        critical_item_id = ctx.get("critical_item_id")
        if critical_item_id:
            critical_item = self._items.get(critical_item_id)
            critical_name = getattr(critical_item, "title", critical_item_id) if critical_item else critical_item_id
            bullets.append(f"Non-critical work is competing for the same resource as '{critical_name}' on the critical path")
        for item_id in rec.affected_item_ids[:1]:
            item = self._items.get(item_id)
            if item:
                priority = getattr(item, "priority", None)
                pval = priority.value if hasattr(priority, "value") else str(priority)
                bullets.append(f"Item priority will be demoted ({pval} → lower) to yield capacity to critical-path work")
        return bullets

    def _why_swarm_item(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        swarm_resource_id = (rec.affected_resource_ids or [None])[0]
        cp_items = set(getattr(self.upstream.cp_result, "items_on_critical_path", []) or [])
        for item_id in rec.affected_item_ids[:1]:
            item = self._items.get(item_id)
            if item:
                hrs = round(float(getattr(item, "remaining_effort_hrs", 0.0) or 0.0))
                on_cp = item_id in cp_items
                bullets.append(
                    f"Item has {hrs}h remaining"
                    + (" and is on the critical path" if on_cp else "")
                    + " — a second resource accelerates completion"
                )
        if swarm_resource_id:
            free = self._free_hours(swarm_resource_id)
            if free is not None:
                bullets.append(f"{self._resource_name(swarm_resource_id)} has {round(free)}h available to swarm")
        days_saved = ctx.get("days_saved_on_critical_path")
        if days_saved:
            bullets.append(f"Estimated {round(float(days_saved), 1)} days saved on critical path from swarming")
        return bullets

    def _why_freeze_scope(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        scope_growth = float(getattr(self.upstream.forecast, "scope_growth_hours", 0.0) or 0.0)
        if scope_growth > 0:
            bullets.append(f"Scope has grown by {round(scope_growth)}h since baseline — freeze prevents further uncontrolled additions")
        bullets.append("Freezing scope protects the planned schedule from surprise work in the current sprint window")
        return bullets

    # ------------------------------------------------------------------ #
    # Comparison helpers                                                   #
    # ------------------------------------------------------------------ #

    def _build_comparison(self, rec: Recommendation, alternatives: List[Recommendation]) -> tuple[List[str], List[str]]:
        if not alternatives:
            return [], []
        why_better = []
        rejected = []
        for alt in alternatives:
            if alt.priority_score < rec.priority_score:
                reason = self._compare_one(rec, alt)
                if reason:
                    why_better.append(reason)
                rejected.append(f"{alt.title} (priority {round(alt.priority_score * 100)} vs {round(rec.priority_score * 100)})")
        return why_better, rejected

    def _compare_one(self, rec: Recommendation, alt: Recommendation) -> str:
        if rec.estimated_delay_reduction_days > alt.estimated_delay_reduction_days + 0.5:
            return f"Recovers {round(rec.estimated_delay_reduction_days - alt.estimated_delay_reduction_days, 1)} more days of delay than \"{alt.title}\""
        if rec.confidence == ConfidenceLevel.HIGH and alt.confidence != ConfidenceLevel.HIGH:
            return f"Higher confidence than \"{alt.title}\" ({rec.confidence.value} vs {alt.confidence.value})"
        if rec.estimated_risk_reduction > alt.estimated_risk_reduction + 0.05:
            return f"Larger risk reduction than \"{alt.title}\""
        return f"Ranked higher than \"{alt.title}\" on combined priority score"

    def _build_confidence_reasoning(self, rec: Recommendation) -> str:
        if rec.confidence == ConfidenceLevel.HIGH:
            return "Based on directly measured data (actual hours, actual load ratios, actual blocker status) with no estimation uncertainty."
        if rec.confidence == ConfidenceLevel.MEDIUM:
            return "Based on a mix of measured data and reasonable assumptions about how the team will respond to this change."
        return "Based on a coarse estimate — treat the impact numbers as directional, not precise."

    # ------------------------------------------------------------------ #
    # Fix 5: trade-off handlers for all action types                      #
    # ------------------------------------------------------------------ #

    def _build_trade_offs(self, rec: Recommendation) -> List[TradeOff]:
        dispatch = {
            RecommendationAction.REASSIGN_ITEM:                  self._tradeoff_reassign,
            RecommendationAction.RESOLVE_BLOCKER:                self._tradeoff_resolve_blocker,
            RecommendationAction.SPLIT_ITEM:                     self._tradeoff_split_item,
            RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT: self._tradeoff_advance_item,
            RecommendationAction.PARALLELIZE_ITEMS:              self._tradeoff_parallelize,
            RecommendationAction.REBALANCE_SPRINT_LOAD:          self._tradeoff_rebalance,
            RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK:   self._tradeoff_remove_dep,
            RecommendationAction.ADD_RESOURCE_SKILL:             self._tradeoff_add_skill,
            RecommendationAction.REBASELINE_ESTIMATE:            self._tradeoff_rebaseline,
            RecommendationAction.PAIR_REVIEWER:                  self._tradeoff_pair_reviewer,
            RecommendationAction.ESCALATE_BLOCKER_EARLY:         self._tradeoff_escalate,
            RecommendationAction.CROSS_TRAIN_BACKUP:             self._tradeoff_cross_train,
            RecommendationAction.INSERT_REVIEW_GATE:             self._tradeoff_review_gate,
            RecommendationAction.APPLY_RAMP_UP_DISCOUNT:         self._tradeoff_ramp_up,
            RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM:   self._tradeoff_resequence,
            RecommendationAction.SWARM_ITEM:                     self._tradeoff_swarm,
            RecommendationAction.FREEZE_SCOPE_REQUEST:           self._tradeoff_freeze_scope,
        }
        handler = dispatch.get(rec.action_type)
        trade_offs = handler(rec) if handler else []
        return trade_offs or [TradeOff(description="No significant trade-offs identified", severity="minor")]

    def _tradeoff_reassign(self, rec: Recommendation) -> List[TradeOff]:
        trade_offs = []
        receiver_id = rec.metadata.get("simulation_params", {}).get("receiving_resource_id") if rec.metadata else None
        if receiver_id:
            other_load = self._other_committed_hours(receiver_id, exclude_item_ids=rec.affected_item_ids)
            if other_load and other_load > 0:
                trade_offs.append(TradeOff(
                    description=f"Receiving resource already has {round(other_load)}h of other committed work this sprint",
                    severity="minor" if other_load < 20 else "moderate",
                ))
        trade_offs.append(TradeOff(
            description="Context-switching cost for the receiving resource — allow ramp-up time on the reassigned item",
            severity="minor",
        ))
        return trade_offs

    def _tradeoff_resolve_blocker(self, rec: Recommendation) -> List[TradeOff]:
        return [TradeOff(
            description="Requires external stakeholder action (escalation) — not fully within team control",
            severity="moderate",
        )]

    def _tradeoff_split_item(self, rec: Recommendation) -> List[TradeOff]:
        return [
            TradeOff(description="Split items require integration effort to recombine — adds coordination overhead", severity="minor"),
            TradeOff(description="Story splitting mid-sprint disrupts acceptance criteria and may require stakeholder re-approval", severity="minor"),
        ]

    def _tradeoff_advance_item(self, rec: Recommendation) -> List[TradeOff]:
        return [TradeOff(
            description="Moving an item earlier assumes the sprint has spare capacity — verify the target sprint is not already full",
            severity="moderate",
        )]

    def _tradeoff_parallelize(self, rec: Recommendation) -> List[TradeOff]:
        return [
            TradeOff(description="Parallel execution requires a second available resource — verify team capacity before committing", severity="moderate"),
            TradeOff(description="Parallel branches may need a merge/integration step not currently estimated", severity="minor"),
        ]

    def _tradeoff_rebalance(self, rec: Recommendation) -> List[TradeOff]:
        return [TradeOff(
            description="Rebalancing forces a resource context switch — moving work mid-sprint risks disrupting in-progress items",
            severity="moderate",
        )]

    def _tradeoff_remove_dep(self, rec: Recommendation) -> List[TradeOff]:
        return [TradeOff(
            description="Removing a dependency may relax a constraint that was protecting quality — confirm the successor item is truly ready to proceed in parallel",
            severity="moderate",
        )]

    def _tradeoff_add_skill(self, rec: Recommendation) -> List[TradeOff]:
        return [
            TradeOff(description="Skill acquisition takes time — the resource will be less productive on affected items during the learning curve", severity="moderate"),
            TradeOff(description="Training investment competes with delivery capacity this sprint", severity="minor"),
        ]

    def _tradeoff_rebaseline(self, rec: Recommendation) -> List[TradeOff]:
        return [TradeOff(
            description="Rebaselining increases the visible estimate — stakeholders may perceive this as a slip even if the project was always going to take this long",
            severity="moderate",
        )]

    def _tradeoff_pair_reviewer(self, rec: Recommendation) -> List[TradeOff]:
        return [TradeOff(
            description="Pairing costs reviewer hours now in exchange for reduced rework later — net benefit depends on actual rework rate",
            severity="minor",
        )]

    def _tradeoff_escalate(self, rec: Recommendation) -> List[TradeOff]:
        return [
            TradeOff(description="Escalation requires management attention and may damage stakeholder relationships if done prematurely", severity="moderate"),
            TradeOff(description="Resolution timeline after escalation is still uncertain — plan is improved, not guaranteed", severity="minor"),
        ]

    def _tradeoff_cross_train(self, rec: Recommendation) -> List[TradeOff]:
        backup_id = rec.affected_resource_ids[1] if len(rec.affected_resource_ids) > 1 else None
        description = (
            f"{self._resource_name(backup_id)} will spend time on cross-training rather than delivery tasks this sprint"
            if backup_id
            else "Cross-training investment reduces delivery capacity in the current sprint window"
        )
        return [
            TradeOff(description=description, severity="minor"),
            TradeOff(description="Backup coverage only materialises if the SPOF resource is actually unavailable — benefit is probabilistic", severity="minor"),
        ]

    def _tradeoff_review_gate(self, rec: Recommendation) -> List[TradeOff]:
        return [TradeOff(
            description="A review gate adds a handoff step that may slow throughput if reviewers are not promptly available",
            severity="minor",
        )]

    def _tradeoff_ramp_up(self, rec: Recommendation) -> List[TradeOff]:
        return [TradeOff(
            description="Applying a ramp-up discount lowers the near-term capacity estimate — the forecast will show more risk until the resource reaches full speed",
            severity="minor",
        )]

    def _tradeoff_resequence(self, rec: Recommendation) -> List[TradeOff]:
        return [
            TradeOff(description="Demoting item priority may delay it beyond the current sprint window — verify stakeholder alignment before changing sequence", severity="moderate"),
            TradeOff(description="Resequencing does not reduce overall scope — the work still needs to be done in a later sprint", severity="minor"),
        ]

    def _tradeoff_swarm(self, rec: Recommendation) -> List[TradeOff]:
        swarm_id = (rec.affected_resource_ids or [None])[0]
        displaced_hrs = self._other_committed_hours(swarm_id, exclude_item_ids=rec.affected_item_ids) if swarm_id else 0.0
        trade_offs = [TradeOff(
            description=(
                f"{self._resource_name(swarm_id)} is displaced from {round(displaced_hrs)}h of other committed work to swarm this item"
                if swarm_id and displaced_hrs > 0
                else "The swarming resource will defer other committed work — confirm the net schedule impact is positive"
            ),
            severity="moderate" if displaced_hrs > 16 else "minor",
        )]
        trade_offs.append(TradeOff(
            description="Coordination overhead between the two resources reduces the theoretical parallelism gain (Brook's Law applies at the extreme)",
            severity="minor",
        ))
        return trade_offs

    def _tradeoff_freeze_scope(self, rec: Recommendation) -> List[TradeOff]:
        return [
            TradeOff(description="Scope freeze requires explicit stakeholder sign-off — rejected requests may create friction with the product owner", severity="moderate"),
            TradeOff(description="Deferred scope items need to be triaged into a future sprint, adding backlog management overhead", severity="minor"),
        ]

    # ------------------------------------------------------------------ #
    # Pitch                                                                #
    # ------------------------------------------------------------------ #

    def _build_one_line_pitch(
        self,
        rec: Recommendation,
        delay_before: float,
        delay_after: float,
        sim: Optional[SimulationResult] = None,
    ) -> str:
        saved = round(delay_before - delay_after, 1)
        if sim is not None:
            otp_gain = round(sim.delta_on_time_probability * 100, 1)
            return (
                f"{rec.title} — saves {saved}d of delay, "
                f"+{otp_gain}% on-time probability, {rec.confidence.value.lower()} confidence."
            )
        return f"{rec.title} — recovers {saved} days, {rec.confidence.value.lower()} confidence."

    # ------------------------------------------------------------------ #
    # Shared utilities                                                     #
    # ------------------------------------------------------------------ #

    def _build_resource_lookup(self, project_state: ProjectState) -> Dict[str, object]:
        resources = getattr(project_state, "resources", None)
        if resources is not None:
            return {getattr(r, "resource_id", None): r for r in resources if getattr(r, "resource_id", None)}
        team = getattr(project_state, "team", None)
        if team is not None:
            return {getattr(r, "resource_id", None): r for r in team if getattr(r, "resource_id", None)}
        return {}

    def _resource_name(self, resource_id: Optional[str]) -> str:
        if not resource_id:
            return "Unknown"
        r = self._resources.get(resource_id)
        return getattr(r, "name", None) or resource_id

    def _free_hours(self, resource_id: str) -> Optional[float]:
        dev = next(
            (
                dm
                for dm in getattr(getattr(self.upstream, "metrics", None), "resource_metrics", None).developer_metrics
                if getattr(dm, "resource_id", None) == resource_id
            ),
            None,
        )
        if dev is None:
            return None
        resource = self._resources.get(resource_id)
        if not resource:
            return None
        capacity = (getattr(resource, "daily_capacity_hrs", 0.0) or 0.0) * (getattr(self.project_state.project_info, "sprint_duration_days", 10) or 10)
        return max(0.0, capacity - getattr(dev, "remaining_effort_hours", 0.0))

    def _has_dependency_conflict(self, item_ids: List[str]) -> Optional[str]:
        for item_id in item_ids:
            for dep in getattr(self.project_state, "dependencies", []) or []:
                if getattr(dep, "successor_item_id", None) == item_id:
                    pred = self._items.get(getattr(dep, "predecessor_item_id", None))
                    if pred and getattr(pred, "status", None) not in ("Completed", "Done"):
                        return getattr(dep, "predecessor_item_id", None)
        return None

    def _other_committed_hours(self, resource_id: Optional[str], exclude_item_ids: List[str]) -> float:
        if not resource_id:
            return 0.0
        return sum(
            float(getattr(wi, "remaining_effort_hrs", 0.0) or 0.0)
            for wi in getattr(self.project_state, "work_items", [])
            if getattr(wi, "assigned_resource", None) == resource_id
            and getattr(wi, "item_id", None) not in exclude_item_ids
        )