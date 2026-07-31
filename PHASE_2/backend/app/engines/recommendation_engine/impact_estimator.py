from __future__ import annotations

from typing import List, Optional

from app.domain.models import ProjectState, Resource, SkillLevel
from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    ImpactEstimate,
    RecommendationAction,
    RecommendationCandidate,
    SignalEvidence,
    UpstreamEngineOutputs,
)


from app.engines.resource_intelligence import ResourceIntelligence

# Severity mapping reused for recommendation impact estimation
SEVERITY_SCORES = {
    "Critical": 40.0,
    "High": 20.0,
    "Medium": 10.0,
    "Low": 5.0,
}


class ImpactEstimator:
    def __init__(self, project_state: ProjectState, upstream: UpstreamEngineOutputs) -> None:
        self.project_state = project_state
        self.upstream = upstream
        self.resource_intelligence = ResourceIntelligence(project_state)

    def estimate(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        Estimate impact of a recommendation candidate.
        
        This method consumes from upstream engines (ProjectMetrics, ForecastResult, RiskResult)
        rather than performing its own calculations. This ensures consistency with the
        single source of truth from upstream engines.
        """
        dispatch = {
            RecommendationAction.RESOLVE_BLOCKER: self._estimate_resolve_blocker,
            RecommendationAction.REASSIGN_ITEM: self._estimate_reassign_item,
            RecommendationAction.SPLIT_ITEM: self._estimate_split_item,
            RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT: self._estimate_advance_item,
            RecommendationAction.PARALLELIZE_ITEMS: self._estimate_parallelize_items,
            RecommendationAction.REBALANCE_SPRINT_LOAD: self._estimate_rebalance_sprint_load,
            RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK: self._estimate_remove_dependency_bottleneck,
            RecommendationAction.ADD_RESOURCE_SKILL: self._estimate_add_resource_skill,
            RecommendationAction.REBASELINE_ESTIMATE: self._estimate_rebaseline_estimate,
            RecommendationAction.PAIR_REVIEWER: self._estimate_pair_reviewer,
            RecommendationAction.ESCALATE_BLOCKER_EARLY: self._estimate_escalate_blocker_early,
            RecommendationAction.FREEZE_SCOPE_REQUEST: self._estimate_freeze_scope_request,
            RecommendationAction.PULL_FORWARD_ITEM: self._estimate_pull_forward_item,
            RecommendationAction.SPLIT_AND_PAIR: self._estimate_split_and_pair,
            RecommendationAction.ASSIGN_AS_SECOND_REVIEWER: self._estimate_assign_second_reviewer,
            RecommendationAction.CROSS_TRAIN_BACKUP: self._estimate_cross_train_backup,
            RecommendationAction.INSERT_REVIEW_GATE: self._estimate_insert_review_gate,
            RecommendationAction.APPLY_RAMP_UP_DISCOUNT: self._estimate_apply_ramp_up_discount,
            RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM: self._estimate_resequence_non_critical_item,
            RecommendationAction.SWARM_ITEM: self._estimate_swarm_item,
        }
        estimator = dispatch.get(candidate.action_type)
        if estimator is None:
            return self._default_estimate(candidate)
        return estimator(candidate)

    def _estimate_resolve_blocker(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        Estimate impact of resolving THIS SPECIFIC blocker, not a pro-rata
        share of all active blockers. Severity and overdue days come from
        the specific blocker this candidate targets.
        """
        blocker_id = (candidate.affected_blocker_ids or [None])[0]
        blocker = next((b for b in self.project_state.blockers if b.blocker_id == blocker_id), None)

        total_blocker_loss_days = 0.0
        if hasattr(self.upstream.forecast, "delay_breakdown") and self.upstream.forecast.delay_breakdown:
            total_blocker_loss_days = float(self.upstream.forecast.delay_breakdown.remaining_days_blocker_loss or 0.0)

        active_blockers = [b for b in self.project_state.blockers if not b.actual_resolution_date]

        severity_weight_map = {"Critical": 0.40, "High": 0.20, "Medium": 0.10, "Low": 0.05}
        this_blocker_weight = severity_weight_map.get(
            getattr(blocker, "severity", None).value if blocker and hasattr(getattr(blocker, "severity", None), "value") else "Medium",
            0.10,
        )
        total_weight = sum(
            severity_weight_map.get(b.severity.value if hasattr(b.severity, "value") else "Medium", 0.10)
            for b in active_blockers
        ) or 1.0
        this_blocker_share = this_blocker_weight / total_weight

        blocker_delay_days = total_blocker_loss_days * this_blocker_share

        overdue_days = 0
        if blocker and getattr(blocker, "target_resolution_date", None):
            from datetime import datetime, timezone
            target = blocker.target_resolution_date
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            overdue_days = max(0, (datetime.now(timezone.utc) - target).days)
            if overdue_days > 0:
                blocker_delay_days *= 1.0 + min(0.3, overdue_days * 0.05)

        impacted_count = len(getattr(blocker, "impacted_item_ids", []) or []) if blocker else 0
        blocked_hours = sum(
            next((wi.remaining_effort_hrs for wi in self.project_state.work_items if wi.item_id == iid), 0.0)
            for iid in (getattr(blocker, "impacted_item_ids", []) or [])
        ) if blocker else 0.0

        severity_label = blocker.severity.value if blocker and hasattr(blocker.severity, "value") else "Medium"

        # FIX-13: CP timing check — even if the blocker resolves on time, blocked
        # items may not have enough sprint time remaining to complete before sprint end.
        cp_timing_note = ""
        blocked_items_on_cp = self._is_on_critical_path(
            getattr(blocker, "impacted_item_ids", []) or []
        ) if blocker else False

        if blocked_items_on_cp and blocker and getattr(blocker, "target_resolution_date", None):
            from datetime import datetime, timezone
            resolution_date = blocker.target_resolution_date
            if resolution_date.tzinfo is None:
                resolution_date = resolution_date.replace(tzinfo=timezone.utc)

            # Find the sprint containing the blocked items to get its end date
            blocked_item_ids = getattr(blocker, "impacted_item_ids", []) or []
            sprint_end_date = None
            for iid in blocked_item_ids:
                wi = next((w for w in self.project_state.work_items if w.item_id == iid), None)
                if wi:
                    sprint = next((s for s in self.project_state.sprints if s.sprint_id == wi.assigned_sprint or s.sprint_name == wi.assigned_sprint), None)
                    if sprint:
                        sprint_end_date = sprint.end_date
                        if sprint_end_date.tzinfo is None:
                            sprint_end_date = sprint_end_date.replace(tzinfo=timezone.utc)
                        break

            if sprint_end_date and sprint_end_date > resolution_date:
                avg_daily_velocity = max(1.0, self.upstream.metrics.actual_avg_velocity / 8.0)
                remaining_sprint_days = max(0, (sprint_end_date - resolution_date).days)
                deliverable_hours = remaining_sprint_days * avg_daily_velocity
                completion_fraction = min(1.0, deliverable_hours / max(blocked_hours, 1.0))
                blocker_delay_days *= completion_fraction
                cp_timing_note = (
                    f" CP timing: {completion_fraction:.0%} of blocked work completable "
                    f"before sprint end ({remaining_sprint_days}d remaining after resolution)."
                )

        notes = (
            f"Resolving {blocker_id or 'this blocker'} ({severity_label} severity, blocking {impacted_count} item(s), "
            f"{round(blocked_hours, 0)}h of work)"
            + (f", {overdue_days} day(s) overdue" if overdue_days > 0 else "")
            + f" recovers an estimated {round(blocker_delay_days, 1)} days of the {round(total_blocker_loss_days, 1)} "
            f"total blocker-attributable delay."
            + cp_timing_note
        )

        return self._build_estimate(
            candidate,
            hours_recovered=min(blocked_hours, self.upstream.forecast.remaining_effort_hours),
            delay_days=blocker_delay_days,
            risk_reduction=min(0.15 + this_blocker_share * 0.4, 0.45),
            confidence=ConfidenceLevel.HIGH,
            evidence=[self._evidence(
                "ForecastEngine",
                "delay_breakdown.blocker_loss",
                blocker_delay_days,
                0.0,
                f"This blocker accounts for {round(blocker_delay_days, 1)} of {round(total_blocker_loss_days, 1)} total blocker-attributable delay days",
            )],
            notes=notes,
        )

    def _estimate_reassign_item(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """Compare source/receiver with the canonical item+sprint resource model."""
        item = next((w for w in self.project_state.work_items if w.item_id in candidate.affected_item_ids), None)
        item_hours = self._sum_item_remaining_effort(candidate.affected_item_ids)
        source_id = candidate.affected_resource_ids[0] if candidate.affected_resource_ids else (item.assigned_resource if item else None)
        receiver_id = candidate.affected_resource_ids[1] if len(candidate.affected_resource_ids) > 1 else (
            candidate.simulation_params.get("target_resource_id") if getattr(candidate, "simulation_params", None) else None
        )
        source = self.resource_intelligence.resource(source_id)
        receiver = self.resource_intelligence.resource(receiver_id)
        sprint_ref = (candidate.affected_sprint_ids[0] if candidate.affected_sprint_ids else
                      (item.assigned_sprint if item else None))

        if item is None or source is None or receiver is None:
            return self._build_estimate_signed(candidate, hours_recovered=0.0, delay_days=0.0,
                risk_reduction=0.0, confidence=ConfidenceLevel.LOW,
                evidence=[], notes="Cannot verify source, receiver and work item; zero direct schedule benefit.")

        src = self.resource_intelligence.evidence(source, item, sprint_ref)
        dst = self.resource_intelligence.evidence(receiver, item, sprint_ref)
        if not dst.skill_match:
            delay_days = 0.0
            note = f"{receiver.resource_id} does not cover required skill '{item.required_skill}'; reassignment is infeasible."
            confidence = ConfidenceLevel.HIGH
        elif dst.free_capacity_hrs < item_hours:
            delay_days = 0.0
            note = (f"{receiver.resource_id} has only {dst.free_capacity_hrs:.1f}h free in target sprint "
                    f"for {item_hours:.1f}h remaining work; full reassignment is infeasible.")
            confidence = ConfidenceLevel.HIGH
        else:
            # Guard: if the source has zero (or near-zero) daily rate due to a
            # skill mismatch that wasn't caught above (e.g. skill_match=True but
            # rate is still 0 from sparse history), we cannot compute a meaningful
            # before/after ratio. Return 0 delay reduction with LOW confidence.
            if src.daily_rate_hrs <= 0.0:
                delay_days = 0.0
                note = (
                    f"Source rate for {source.resource_id} is 0 h/day — "
                    f"insufficient history to compute delay comparison. "
                    f"Reassignment may still be beneficial; manual assessment required."
                )
                confidence = ConfidenceLevel.LOW
            else:
                before_days = item_hours / src.daily_rate_hrs
                after_days = item_hours / max(dst.daily_rate_hrs, 0.01)
                raw_delay_days = before_days - after_days
                # Hard clamp: delay recovery cannot exceed the project's remaining
                # window (approximately 107 days for this project) or be worse than
                # losing an entire sprint (roughly -14 days). Values outside this
                # range indicate a unit error in the rate calculation and must not
                # be displayed to users.
                delay_days = max(-14.0, min(raw_delay_days, 120.0))
                note = (
                    f"Source rate — {source.resource_id}: {src.daily_rate_hrs:.1f}h/day ({src.source}); "
                    f"Receiver rate — {receiver.resource_id}: {dst.daily_rate_hrs:.1f}h/day ({dst.source}), "
                    f"{dst.free_capacity_hrs:.1f}h free in target sprint; effort unchanged."
                )
                if abs(raw_delay_days) > 120.0:
                    note += (
                        f" [Raw computed value {raw_delay_days:.1f}d was clamped to {delay_days:.1f}d "
                        f"— rate data may be unreliable; treat as estimate only.]"
                    )
                confidence = ConfidenceLevel.HIGH if src.sample_size and dst.sample_size else ConfidenceLevel.MEDIUM

        return self._build_estimate_signed(candidate, hours_recovered=0.0, delay_days=delay_days,
            risk_reduction=0.0, confidence=confidence,
            evidence=[self._evidence("MetricsEngine","effective_delivery_rate",dst.daily_rate_hrs,0.0,note)],
            notes=note)

    def _sum_item_remaining_effort(self, item_ids: List[str]) -> float:
        return sum(
            next((wi.remaining_effort_hrs for wi in self.project_state.work_items if wi.item_id == iid), 0.0)
            for iid in item_ids
        )

    def _resource_metric(self, resource_id: str | None):
        if not resource_id:
            return None
        return next(
            (dm for dm in self.upstream.metrics.resource_metrics.developer_metrics if dm.resource_id == resource_id),
            None,
        )

    def _is_on_critical_path(self, item_ids: List[str]) -> bool:
        cp_items = set(self.upstream.cp_result.items_on_critical_path or [])
        return any(item_id in cp_items for item_id in item_ids)

    def _estimate_split_item(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        FIX-08: Split item only reduces duration when a second capable resource
        can run the sibling half in parallel.  Without a second resource, the
        only benefit is reduced batch size (flow improvement, no delay_days).

        Total remaining effort is conserved — only critical_path_delta changes.
        """
        item_hours = self._sum_item_remaining_effort(candidate.affected_item_ids)
        half_hours = item_hours / 2.0

        team_avg_daily_rate = max(1.0, self.upstream.metrics.actual_avg_velocity / 8.0)

        # Find the primary assignee and a second capable resource
        primary_resource_id = None
        required_skill = None
        for iid in candidate.affected_item_ids:
            wi = next((w for w in self.project_state.work_items if w.item_id == iid), None)
            if wi:
                primary_resource_id = wi.assigned_resource
                required_skill = wi.required_skill
                break

        primary_resource = next(
            (r for r in self.project_state.team if r.resource_id == primary_resource_id), None
        )
        second_resource = self._find_second_capable_resource(
            required_skill=required_skill,
            exclude_resource_id=primary_resource_id,
            sprint_ids=candidate.affected_sprint_ids,
            required_hours=half_hours,
        )

        if second_resource is None:
            delay_days = 0.0
            notes = (
                f"No second capable resource available for skill '{required_skill}'; "
                f"split reduces batch size only (no parallelism gain)."
            )
            confidence = ConfidenceLevel.LOW
        else:
            sprint_ref = candidate.affected_sprint_ids[0] if candidate.affected_sprint_ids else None
            primary_ev = self.resource_intelligence.evidence(primary_resource, None, sprint_ref)
            second_ev = self.resource_intelligence.evidence(second_resource, None, sprint_ref)
            r1_rate, r2_rate = primary_ev.daily_rate_hrs, second_ev.daily_rate_hrs
            parallel_hours = min(half_hours, second_ev.free_capacity_hrs)
            if parallel_hours <= 0:
                delay_days = 0.0
            else:
                # Only the portion the second resource can actually absorb runs concurrently.
                primary_hours = item_hours - parallel_hours
                t_sequential = item_hours / max(r1_rate, 0.01)
                t_parallel = max(primary_hours / max(r1_rate, 0.01), parallel_hours / max(r2_rate, 0.01))
                delay_days = max(0.0, t_sequential - t_parallel)
            notes = (
                f"Split with {second_resource.resource_id}: {second_ev.free_capacity_hrs:.1f}h target-sprint free capacity; "
                f"{parallel_hours:.1f}h can run in parallel. Total engineering effort unchanged."
            )
            confidence = ConfidenceLevel.MEDIUM

        return self._build_estimate(
            candidate,
            hours_recovered=0.0,   # FIX-08: total effort is conserved; no hours are recovered
            delay_days=delay_days,
            risk_reduction=0.04,
            confidence=confidence,
            evidence=[self._evidence(
                "MetricsEngine",
                "average_item_effort",
                self.upstream.metrics.average_item_effort,
                0.0,
                "Splitting enables parallelism when a second capable resource is available",
            )],
            notes=notes,
        )

    def _find_second_capable_resource(
        self, required_skill: Optional[str], exclude_resource_id: Optional[str], sprint_ids: List[str],
        required_hours: float = 0.0,
    ) -> Optional[Resource]:
        """Choose a capable receiver using actual target-sprint free capacity."""
        sprint_ref = sprint_ids[0] if sprint_ids else None
        ranked = []
        for resource in self.project_state.team:
            if resource.resource_id == exclude_resource_id:
                continue
            if required_skill and not resource.covers_skill(required_skill):
                continue
            free = self.resource_intelligence.free_capacity_hours(resource, sprint_ref)
            if free <= 0:
                continue
            measured, n = self.resource_intelligence.measured_daily_rate(resource, required_skill)
            rate = measured if measured is not None else (
                self.resource_intelligence.daily_rate_capacity_fallback(resource, sprint_ref)
            )
            ranked.append((min(free, required_hours) if required_hours > 0 else free, rate, n, resource.resource_id, resource))
        return max(ranked, default=(0,0,0,"",None))[-1]

    def _estimate_advance_item(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        BATCH A / FIX-P4: Moving an item to an earlier sprint does not make
        its remaining work vanish — a 40h item moved from Sprint 7 to
        Sprint 6 still requires 40h. hours_recovered is always 0.0 here.

        Any schedule benefit is conditional on feasibility that this
        estimator cannot verify on its own (target sprint has usable
        capacity, dependencies allow an earlier start, required skill is
        available in that sprint). Applicator does not check target-sprint
        capacity yet (that lands in Batch B), so until that check exists we
        report zero schedule benefit rather than fabricate one — this keeps
        the estimator honest about a known model gap instead of guessing.
        """
        is_on_cp = any(
            item_id in self.upstream.cp_result.items_on_critical_path
            for item_id in candidate.affected_item_ids
        )

        item_hours = self._sum_item_remaining_effort(candidate.affected_item_ids)

        # Minimal, verifiable feasibility gate: the item must actually have
        # an earlier sprint to move into. Beyond that (target-sprint capacity,
        # resource/skill availability) is not yet modelled -- Batch B.
        target_sprint_exists = False
        sprints_by_number = sorted(self.project_state.sprints, key=lambda s: s.sprint_number)
        sprint_by_name = {s.sprint_name: s for s in self.project_state.sprints}
        for iid in candidate.affected_item_ids:
            wi = next((w for w in self.project_state.work_items if w.item_id == iid), None)
            if wi is None:
                continue
            current_sprint = sprint_by_name.get(wi.assigned_sprint)
            if current_sprint and any(s.sprint_number < current_sprint.sprint_number for s in sprints_by_number):
                target_sprint_exists = True
                break

        if not target_sprint_exists:
            delay_days = 0.0
            notes = "No earlier sprint available to advance into; zero schedule benefit."
            confidence = ConfidenceLevel.LOW
        else:
            # Model gap: without target-sprint capacity/resource feasibility
            # (Batch B), we cannot verify the item can actually start earlier.
            # Report zero direct schedule benefit rather than fabricate one.
            delay_days = 0.0
            notes = (
                "Earlier sprint exists, but target-sprint capacity/resource "
                "feasibility is not yet modelled (Batch B). Reporting zero "
                "direct schedule benefit rather than assuming feasibility."
            )
            confidence = ConfidenceLevel.LOW

        return self._build_estimate(
            candidate,
            hours_recovered=0.0,  # FIX-P4: advancing never deletes/recovers effort
            delay_days=delay_days,
            risk_reduction=0.0,
            confidence=confidence,
            evidence=[self._evidence(
                "ForecastEngine",
                "expected_delay_days",
                self.upstream.forecast.expected_delay_days,
                0.0,
                f"Advancing item {'on critical path' if is_on_cp else ''} moves {round(item_hours, 0):.0f}h "
                f"of unchanged work earlier; no effort is recovered",
            )],
            notes=notes,
        )

    def _estimate_parallelize_items(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        BATCH A / FIX-P1: Parallelizing items conserves total engineering
        effort — 32h of work sequential is still 32h of work run side by
        side. Only serialization (dependency lag) can shrink, and only when
        a real dependency edge with lag exists between the affected items.

        hours_recovered is always 0.0. delay_days is derived directly from
        the actual lag_days on dependencies connecting the affected items,
        converted to calendar days at the team's measured daily rate — not
        from an arbitrary dependency-pressure percentage.
        """
        item_ids = set(candidate.affected_item_ids)
        avg_daily_velocity = max(1.0, self.upstream.metrics.actual_avg_velocity / 8.0)

        lag_days_removable = 0
        has_dependency_edge = False
        for dep in self.project_state.dependencies:
            if dep.predecessor_item_id in item_ids and dep.successor_item_id in item_ids:
                has_dependency_edge = True
                lag_days_removable += dep.lag_days

        if not has_dependency_edge:
            delay_days = 0.0
            confidence = ConfidenceLevel.LOW
            notes = (
                "No dependency edge found between the affected items; "
                "independence (and any schedule benefit) cannot be verified, "
                "so schedule gain is reported as zero."
            )
        elif lag_days_removable <= 0:
            delay_days = 0.0
            confidence = ConfidenceLevel.LOW
            notes = "Dependency edge exists but carries no lag to remove; zero schedule gain."
        else:
            # Convert removable lag (calendar days of waiting) into the
            # equivalent schedule benefit; capped by the item's own hours
            # so we never claim more benefit than the item's actual duration.
            item_hours = self._sum_item_remaining_effort(list(item_ids))
            max_possible_days = item_hours / avg_daily_velocity
            delay_days = min(float(lag_days_removable), max_possible_days)
            confidence = ConfidenceLevel.MEDIUM
            notes = f"Removes {lag_days_removable}d of dependency lag between the affected items."

        is_on_cp = self._is_on_critical_path(list(item_ids))

        return self._build_estimate(
            candidate,
            hours_recovered=0.0,  # FIX-P1: parallelizing never deletes effort
            delay_days=delay_days,
            risk_reduction=0.06 if (is_on_cp and delay_days > 0) else 0.0,
            confidence=confidence,
            evidence=[self._evidence(
                "DependencyGraphEngine",
                "lag_days",
                float(lag_days_removable),
                0.0,
                "Parallelizing independent items reduces serial dependency lag, not effort",
            )],
            notes=notes,
        )

    def _estimate_rebalance_sprint_load(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        FIX-10: Moving work across resources does not destroy effort.
        Delay impact comes from overload relief on the source resource — if the
        source was overloaded and moving items brings it to ≤ 100%, the excess
        queue is resolved earlier.

        hours_recovered stays 0.0 because no effort is deleted.
        """
        item_hours = self._sum_item_remaining_effort(candidate.affected_item_ids)
        avg_daily_velocity = max(1.0, self.upstream.metrics.actual_avg_velocity / 8.0)

        sprint_ref = candidate.affected_sprint_ids[0] if candidate.affected_sprint_ids else None
        receiver_id = candidate.affected_resource_ids[0] if candidate.affected_resource_ids else None
        source_id = candidate.simulation_params.get("source_resource_id") if getattr(candidate, "simulation_params", None) else None
        if not source_id:
            source_id = next(
                (
                    wi.assigned_resource
                    for wi in self.project_state.work_items
                    if wi.item_id in candidate.affected_item_ids and getattr(wi, "assigned_resource", None)
                ),
                None,
            )

        source_resource = next((r for r in self.project_state.team if r.resource_id == source_id), None)
        receiver_resource = next((r for r in self.project_state.team if r.resource_id == receiver_id), None)

        if source_resource is None or receiver_resource is None:
            delay_days = 0.0
            risk_reduction = 0.02
            notes = "Source or receiver resource metadata unavailable; structural rebalance only. No effort deleted."
            confidence = ConfidenceLevel.LOW
        else:
            src = self.resource_intelligence.evidence(source_resource, None, sprint_ref)
            dst = self.resource_intelligence.evidence(receiver_resource, None, sprint_ref)
            source_capacity = max(src.sprint_capacity_hrs, 1.0)
            receiver_capacity = max(dst.sprint_capacity_hrs, 1.0)
            source_load_before = src.committed_hrs / max(source_capacity, 1.0)
            source_load_after = max(0.0, src.committed_hrs - item_hours) / max(source_capacity, 1.0)
            receiver_load_before = dst.committed_hrs / max(receiver_capacity, 1.0)
            receiver_load_after = (dst.committed_hrs + item_hours) / max(receiver_capacity, 1.0)

            if receiver_load_after > 1.0:
                delay_days = 0.0
                risk_reduction = 0.0
                notes = (
                    f"Receiver {receiver_id} would be overloaded after the move: "
                    f"{receiver_load_before:.0%} → {receiver_load_after:.0%}; no rebalance benefit claimed."
                )
                confidence = ConfidenceLevel.MEDIUM
            elif source_load_before > 1.0 and source_load_after <= 1.0:
                overload_excess_hours = (source_load_before - 1.0) * source_capacity
                delay_days = overload_excess_hours / max(avg_daily_velocity, 0.01)
                spillover_risk_delta = -max(0.0, source_load_before - 1.0) * item_hours / max(source_capacity, 1.0)
                risk_reduction = min(0.10, max(0.0, abs(spillover_risk_delta)))
                notes = (
                    f"Source {source_id} load: {source_load_before:.0%} → {source_load_after:.0%}; "
                    f"receiver {receiver_id} load: {receiver_load_before:.0%} → {receiver_load_after:.0%}; "
                    f"overload relieved; delay saving: {delay_days:.1f}d. No effort deleted."
                )
                confidence = ConfidenceLevel.MEDIUM if source_load_before > 1.0 else ConfidenceLevel.LOW
            else:
                delay_days = 0.0
                risk_reduction = 0.0
                notes = (
                    f"Source {source_id} is not meaningfully overloaded after the move; "
                    f"receiver {receiver_id} remains feasible at {receiver_load_after:.0%} load."
                )
                confidence = ConfidenceLevel.LOW

        return self._build_estimate(
            candidate,
            hours_recovered=0.0,   # FIX-10: rebalancing never deletes effort
            delay_days=delay_days,
            risk_reduction=risk_reduction,
            confidence=confidence,
            evidence=[self._evidence(
                "MetricsEngine",
                "resource_sprint_loads",
                item_hours,
                0.0,
                "Rebalance delay benefit comes from overload relief, not effort reduction",
            )],
            notes=notes,
        )

    def _estimate_remove_dependency_bottleneck(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        BATCH A / FIX-P3: Removing a dependency bottleneck changes WAITING
        TIME (dependency lag/serialization), not the successor's engineering
        effort. hours_recovered is always 0.0. Schedule benefit is derived
        from the actual lag_days on dependencies touching the affected
        items — a dependency with zero lag genuinely has nothing to remove,
        and that must surface as zero benefit, not a fabricated percentage.
        """
        affected_ids = set(candidate.affected_item_ids)
        cp_items = self.upstream.cp_result.items_on_critical_path or []
        avg_daily_velocity = max(1.0, self.upstream.metrics.actual_avg_velocity / 8.0)

        touching_deps = [
            dep for dep in self.project_state.dependencies
            if dep.predecessor_item_id in affected_ids or dep.successor_item_id in affected_ids
        ]
        lag_days_removable = sum(dep.lag_days for dep in touching_deps)

        is_cp_bottleneck = any(item_id in cp_items for item_id in affected_ids)

        if not touching_deps:
            delay_days = 0.0
            confidence = ConfidenceLevel.LOW
            notes = "No dependency found touching the affected items; zero schedule benefit."
        elif lag_days_removable <= 0:
            delay_days = 0.0
            confidence = ConfidenceLevel.LOW
            notes = "Dependency touches the affected items but carries no lag; zero schedule benefit."
        else:
            item_hours = self._sum_item_remaining_effort(list(affected_ids))
            max_possible_days = item_hours / avg_daily_velocity
            delay_days = min(float(lag_days_removable), max_possible_days)
            confidence = ConfidenceLevel.MEDIUM if is_cp_bottleneck else ConfidenceLevel.LOW
            notes = f"Removes {lag_days_removable}d of dependency lag {'on the critical path' if is_cp_bottleneck else ''}."

        return self._build_estimate(
            candidate,
            hours_recovered=0.0,  # FIX-P3: removing a bottleneck never deletes effort
            delay_days=delay_days,
            risk_reduction=0.08 if (is_cp_bottleneck and delay_days > 0) else 0.0,
            confidence=confidence,
            evidence=[self._evidence(
                "DependencyGraphEngine",
                "lag_days",
                float(lag_days_removable),
                0.0,
                "Removing a dependency bottleneck eases waiting time, not effort",
            )],
            notes=notes,
        )

    def _estimate_rebaseline_estimate(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        FIX-07: Rebaselining makes the schedule longer (honest) while reducing
        planning surprise.  The OLD code returned a positive delay_reduction_days
        implying the action shortens the schedule — the opposite of what the
        applicator does (it increases remaining_effort_hrs).

        Two-sided profile:
          Cost:    schedule gets longer by the inflated hours / avg team rate
          Benefit: risk / estimation surprise decreases
        """
        item_hours = sum(
            next((wi.remaining_effort_hrs for wi in self.project_state.work_items if wi.item_id == iid), 0.0)
            for iid in candidate.affected_item_ids
        )
        avg_daily_velocity = max(1.0, self.upstream.metrics.actual_avg_velocity / 8.0)
        # How much extra effort rebaselining adds (mirrors applicator: scale by work_std_dev_pct)
        effort_increase = item_hours * self.upstream.metrics.historical_metrics.avg_estimation_error_pct \
            if hasattr(self.upstream.metrics, "historical_metrics") and \
               hasattr(self.upstream.metrics.historical_metrics, "avg_estimation_error_pct") \
            else item_hours * 0.15   # documented fallback: 15% estimation error
        delay_increase = effort_increase / avg_daily_velocity  # days schedule gets longer

        # Risk benefit: more honest estimate reduces late-stage planning surprises
        risk_reduction = min(0.12, 0.04 + (effort_increase / max(item_hours, 1.0)) * 0.40)

        notes = (
            f"Rebaselining {round(item_hours, 0)}h of work adds ~{round(effort_increase, 1)}h "
            f"to the plan ({round(delay_increase, 1)}d longer finish), but reduces estimation "
            f"surprise risk by {round(risk_reduction * 100, 0):.0f}pp."
        )

        return self._build_estimate_signed(
            candidate,
            hours_recovered=0.0,   # rebaseline does not recover hours; it adds them
            delay_days=-delay_increase,   # NEGATIVE: makes finish later (FIX-07 sign fix)
            risk_reduction=risk_reduction,
            confidence=ConfidenceLevel.MEDIUM,
            # Rebaselining directly improves forecast reliability: the more the estimate
            # was off, the more value an honest rebaseline provides (capped at 0.80).
            forecast_confidence_gain=min(0.80, risk_reduction * 4.0),
            evidence=[self._evidence(
                "ForecastEngine",
                "remaining_effort_hours",
                item_hours,
                0.0,
                "Historical overrun pattern justifies rebaselining; cost is longer schedule, benefit is less surprise",
            )],
            notes=notes,
        )

    def _estimate_pair_reviewer(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        FIX-16: Adding a reviewer costs review time (modelled as +effort by the applicator)
        and reduces rework risk.  No direct delay reduction is claimed without rework_risk data
        on WorkItem.  The benefit is risk-only.
        """
        return self._build_estimate(
            candidate,
            hours_recovered=0.0,   # FIX-16: review costs time; no hours recovered
            delay_days=0.0,         # FIX-16: no delay reduction without rework_risk data
            risk_reduction=0.06,
            confidence=ConfidenceLevel.MEDIUM,
            evidence=[self._evidence(
                "MetricsEngine", "review_pairing", 1.0, 0.0,
                "Pair reviewer reduces rework risk; schedule impact depends on rework rate (data unavailable)",
            )],
            notes=(
                "Adding a reviewer costs review time (modelled as +effort in simulation) "
                "and reduces rework risk. Schedule impact depends on rework rate; "
                "no direct delay reduction is claimed without rework_risk data."
            ),
        )

    def _estimate_escalate_blocker_early(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        FIX-14: Early escalation benefit depends on whether the blocker is on the
        critical path.  A flat 25% of total delay is disconnected from CP structure.

        On CP: benefit = cal.escalation_resolution_pull_days (direct CP save)
        Off CP: benefit = risk reduction only (no schedule shortening)
        """
        blocker_id = (candidate.affected_blocker_ids or [None])[0]
        blocker = next((b for b in self.project_state.blockers if b.blocker_id == blocker_id), None)

        impacted_ids = (getattr(blocker, "impacted_item_ids", []) or []) if blocker else []
        is_on_cp = self._is_on_critical_path(impacted_ids)

        # pull_days: how many days earlier the blocker resolves due to escalation
        pull_days = float(self.upstream.forecast.expected_delay_days * 0.1)   # fallback
        if hasattr(self, '_cal_pull_days'):
            pull_days = float(self._cal_pull_days)

        # Try to read from upstream calibration if available
        try:
            from app.engines.project_calibration import ProjectCalibration
            # We cannot access the calibration from the estimator directly, so use a safe default
            pull_days = 2.0   # documented default: escalation_resolution_pull_days = 2
        except Exception:
            pass

        if is_on_cp:
            delay_days = pull_days   # direct CP day save
            risk_delta = 0.10
            notes = (
                f"Blocker {blocker_id or ''} is on the critical path. "
                f"Escalating early pulls resolution by ~{pull_days:.0f}d → direct schedule save."
            )
            confidence = ConfidenceLevel.HIGH
        else:
            delay_days = 0.0   # no CP impact
            risk_delta = 0.12  # but reduces schedule risk tail
            notes = (
                f"Blocker {blocker_id or ''} is NOT on the critical path. "
                f"Benefit is risk reduction only; no direct delay saving is claimed."
            )
            confidence = ConfidenceLevel.MEDIUM

        return self._build_estimate(
            candidate,
            hours_recovered=0.0,
            delay_days=delay_days,
            risk_reduction=risk_delta,
            confidence=confidence,
            evidence=[self._evidence(
                "ForecastEngine",
                "expected_delay_days",
                self.upstream.forecast.expected_delay_days,
                0.0,
                "Early escalation benefit is CP-dependent (FIX-14)",
            )],
            notes=notes,
        )

    def _estimate_freeze_scope_request(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        scope_growth = max(0.0, self.upstream.forecast.scope_growth_hours or 0.0)
        # Conservative: assume 50% of scope growth is avoidable if scope is frozen now
        hours_recovered = min(scope_growth * 0.5, 40.0)
        avg_daily_velocity = max(1.0, self.upstream.metrics.actual_avg_velocity / 8.0)
        delay_days = round(hours_recovered / avg_daily_velocity, 2) if hours_recovered > 0 else 0.3
        return self._build_estimate(
            candidate,
            hours_recovered=round(hours_recovered, 1),
            delay_days=delay_days,
            risk_reduction=0.07,
            confidence=ConfidenceLevel.MEDIUM if scope_growth > 0 else ConfidenceLevel.LOW,
            evidence=[self._evidence("ForecastEngine", "scope_growth_hours", scope_growth, 0.0, "50% of scope growth assumed avoidable with a scope freeze")],
            notes=f"Freezing scope prevents ~{round(hours_recovered, 1)}h of unplanned work from entering the backlog.",
        )

    def _estimate_pull_forward_item(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        return self._build_estimate(
            candidate,
            hours_recovered=0.0,
            delay_days=0.3,
            risk_reduction=0.04,
            confidence=ConfidenceLevel.LOW,
            evidence=[self._evidence("ForecastEngine", "expected_delay_days", self.upstream.forecast.expected_delay_days, 0.0, "Pulling work forward reduces sequencing pressure")],
            notes="Pulling the item forward helps protect the critical path when sequencing pressure is present.",
        )

    def _estimate_split_and_pair(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        avg_effort = self.upstream.metrics.average_item_effort or 8.0
        # Splitting reduces rework overhead — estimate 30% of average item effort saved
        hours_recovered = round(min(avg_effort * 0.3, 20.0), 1)
        avg_daily_velocity = max(1.0, self.upstream.metrics.actual_avg_velocity / 8.0)
        delay_days = round(hours_recovered / avg_daily_velocity, 2) if hours_recovered > 0 else 0.4
        return self._build_estimate(
            candidate,
            hours_recovered=hours_recovered,
            delay_days=delay_days,
            risk_reduction=0.06,
            confidence=ConfidenceLevel.MEDIUM,
            evidence=[self._evidence("MetricsEngine", "average_item_effort", avg_effort, 0.0, f"30% of {round(avg_effort, 1)}h average item effort saved by splitting review contention")],
            notes=f"Splitting and pairing saves ~{hours_recovered}h of rework overhead by reducing review handoff friction.",
        )

    def _estimate_assign_second_reviewer(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        FIX-16: Risk-only benefit. No invented hours or delay without rework_risk data.
        """
        return self._build_estimate(
            candidate,
            hours_recovered=0.0,   # FIX-16: no hours recovered
            delay_days=0.0,         # FIX-16: no delay reduction without rework_risk data
            risk_reduction=0.06,
            confidence=ConfidenceLevel.MEDIUM,
            evidence=[self._evidence(
                "MetricsEngine", "review_pairing", 1.0, 0.0,
                "Second reviewer reduces rework risk; schedule impact requires rework_risk data",
            )],
            notes=(
                "Adding a second reviewer costs review time (modelled as +effort in simulation) "
                "and reduces rework risk. Schedule impact depends on rework rate; "
                "no direct delay reduction is claimed without rework_risk data."
            ),
        )

    def _estimate_cross_train_backup(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        target_resource_id = candidate.affected_resource_ids[0] if candidate.affected_resource_ids else None
        resource_risk_score = float(
            getattr(self.upstream.risk_result, "resource_risk", {}).score
            if hasattr(self.upstream.risk_result, "resource_risk") else 0.0
        )
        resource_metric = self._resource_metric(target_resource_id)
        load_factor = 0.0
        if resource_metric is not None:
            load_factor = 1.0 - (resource_metric.allocation_pct * resource_metric.availability_pct)
        risk_factor = min(0.08 + resource_risk_score * 0.2, 0.25)
        if resource_metric and resource_metric.allocation_pct * resource_metric.availability_pct > 0.8:
            risk_factor = min(risk_factor + 0.05, 0.30)

        notes = (
            "No current-window delay reduction is estimated for cross-training; "
            "the benefit is future sprint resilience from backup coverage."
        )
        if target_resource_id:
            notes += f" Target resource: {target_resource_id}."

        return self._build_estimate(
            candidate,
            hours_recovered=0.0,
            delay_days=0.0,
            risk_reduction=risk_factor,
            confidence=ConfidenceLevel.MEDIUM if resource_risk_score > 0.1 else ConfidenceLevel.LOW,
            # Cross-training benefit scales with how loaded the resource is —
            # higher load factor means more resilience value from backup coverage.
            forecast_confidence_gain=min(0.50, 0.10 + max(0.0, load_factor) * 0.40),
            evidence=[self._evidence(
                "RiskEngine",
                "resource_risk",
                resource_risk_score,
                0.0,
                "Cross-training backup coverage reduces single-resource dependency risk",
            )],
            notes=notes,
        )

    def _estimate_insert_review_gate(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        FIX-16: Review gate costs review time (applicator adds effort) and reduces
        rework risk.  No direct delay reduction is claimed without rework_risk data.
        Risk-only benefit, consistent with _estimate_pair_reviewer.
        """
        return self._build_estimate(
            candidate,
            hours_recovered=0.0,   # FIX-16: review costs time; no hours recovered
            delay_days=0.0,         # FIX-16: no delay reduction without rework_risk data
            risk_reduction=0.06,
            confidence=ConfidenceLevel.MEDIUM,
            evidence=[self._evidence(
                "ForecastEngine",
                "expected_delay_days",
                self.upstream.forecast.expected_delay_days,
                0.0,
                "Review gate reduces rework risk; schedule impact requires rework_risk data on WorkItem",
            )],
            notes=(
                "Inserting a review gate costs review time (modelled as +effort in simulation) "
                "and reduces rework risk. Schedule impact depends on rework rate; "
                "no direct delay reduction is claimed without rework_risk data."
            ),
        )

    def _estimate_apply_ramp_up_discount(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        target_resource_id = candidate.affected_resource_ids[0] if candidate.affected_resource_ids else None
        resource_metric = self._resource_metric(target_resource_id)
        load_factor = 0.0
        if resource_metric is not None:
            load_factor = 1.0 - (resource_metric.allocation_pct * resource_metric.availability_pct)
        risk_reduction = min(0.04 + max(0.0, load_factor) * 0.12, 0.12)
        confidence = ConfidenceLevel.MEDIUM if load_factor > 0.2 else ConfidenceLevel.LOW
        notes = (
            "Applying a ramp-up discount improves forecast realism for a newly ramped resource "
            "without claiming immediate current-window delay reduction."
        )
        if target_resource_id:
            notes += f" Target resource: {target_resource_id}."

        return self._build_estimate(
            candidate,
            hours_recovered=0.0,
            delay_days=0.0,
            risk_reduction=risk_reduction,
            confidence=confidence,
            evidence=[self._evidence(
                "ForecastEngine",
                "remaining_effort_hours",
                self.upstream.forecast.remaining_effort_hours,
                0.0,
                "A ramp-up discount reduces forecast error risk for new resources",
            )],
            notes=notes,
        )

    def _estimate_resequence_non_critical_item(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        FIX-11: Resequencing only changes execution order — it does NOT destroy or
        recover effort.  The real benefit is queue-pressure relief for CP resources,
        expressed as a spillover risk reduction, not delay_days.

        By construction, RESEQUENCE_NON_CRITICAL targets items NOT on the critical path,
        so delay_days is always 0.0.
        """
        item_hours = self._sum_item_remaining_effort(candidate.affected_item_ids)
        item_fraction = item_hours / max(self.upstream.forecast.remaining_effort_hours, 1.0)

        # Risk benefit: proportional to this item's share of total remaining work
        # (documented assumption: each 1% of work share reduces spillover risk by ~0.15pp)
        spillover_risk_delta = item_fraction * 0.15
        risk_reduction = min(0.08, spillover_risk_delta)

        return self._build_estimate(
            candidate,
            hours_recovered=0.0,   # FIX-11: resequencing does not delete or recover work
            delay_days=0.0,         # FIX-11: non-CP item; no direct CP impact
            risk_reduction=risk_reduction,
            confidence=ConfidenceLevel.MEDIUM,
            evidence=[self._evidence(
                "CriticalPathEngine",
                "critical_path_duration_hours",
                float(self.upstream.cp_result.critical_path_duration_hours or 0.0),
                0.0,
                "Resequencing non-critical work reduces queue pressure for CP resources",
            )],
            notes=(
                f"Resequencing {round(item_hours, 0):.0f}h of non-critical work relieves shared-resource "
                f"queue pressure. No effort is recovered or deleted; only execution order changes. "
                f"Estimated spillover risk reduction: {round(risk_reduction * 100, 1):.1f}pp."
            ),
        )

    def _estimate_swarm_item(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        FIX-15: Estimator must mirror the applicator's Brook's Law formula.
        The applicator computes:
            share = swarm_daily / (primary_daily + swarm_daily)
            parallelism_factor = max(1 - min(share, 0.40), 0.60)   # Brook's Law cap: max 40% reduction
            item.remaining_effort_hrs *= parallelism_factor

        The estimator mirrors this using resource_effective_rate for swarm and primary.
        delay_days = item_hours × (1 - parallelism_factor) / primary_rate
        """
        item_hours = self._sum_item_remaining_effort(candidate.affected_item_ids)
        is_on_cp = self._is_on_critical_path(candidate.affected_item_ids)
        team_avg_daily_rate = max(1.0, self.upstream.metrics.actual_avg_velocity / 8.0)

        # Identify primary and swarm resources
        primary_resource_id = None
        for iid in candidate.affected_item_ids:
            wi = next((w for w in self.project_state.work_items if w.item_id == iid), None)
            if wi:
                primary_resource_id = wi.assigned_resource
                break

        # Swarm resource is in affected_resource_ids[0] per candidate_generator convention
        swarm_resource_id = candidate.affected_resource_ids[0] if candidate.affected_resource_ids else None

        primary_resource = next((r for r in self.project_state.team if r.resource_id == primary_resource_id), None)
        swarm_resource = next((r for r in self.project_state.team if r.resource_id == swarm_resource_id), None)

        if swarm_resource is None:
            delay_days = 0.0
            notes = "No swarm resource identified; no parallelism benefit estimated."
            confidence = ConfidenceLevel.LOW
        else:
            item = next((w for w in self.project_state.work_items if w.item_id in candidate.affected_item_ids), None)
            sprint_ref = candidate.affected_sprint_ids[0] if candidate.affected_sprint_ids else (item.assigned_sprint if item else None)
            primary_ev = self.resource_intelligence.evidence(primary_resource, item, sprint_ref) if primary_resource else None
            swarm_ev = self.resource_intelligence.evidence(swarm_resource, item, sprint_ref)
            primary_rate = primary_ev.daily_rate_hrs if primary_ev else 0.0
            swarm_rate = swarm_ev.daily_rate_hrs
            parallel_hours = min(item_hours, swarm_ev.free_capacity_hrs) if swarm_ev.skill_match else 0.0
            if parallel_hours <= 0 or primary_rate <= 0 or swarm_rate <= 0:
                delay_days = 0.0
            else:
                sequential = item_hours / primary_rate
                primary_hours = item_hours - parallel_hours
                parallel = max(primary_hours / primary_rate, parallel_hours / swarm_rate)
                delay_days = max(0.0, sequential - parallel)
            notes = (
                f"Swarm {swarm_resource_id}: {swarm_ev.free_capacity_hrs:.1f}h free in target sprint; "
                f"{parallel_hours:.1f}h can be worked concurrently. No nominal-capacity or fixed-percent gain assumed."
            )
            confidence = ConfidenceLevel.MEDIUM if is_on_cp and parallel_hours > 0 else ConfidenceLevel.LOW

        risk_reduction = 0.08 if is_on_cp else 0.05

        return self._build_estimate(
            candidate,
            hours_recovered=0.0,   # FIX-15: hours_recovered not claimed; duration shortens, not effort destroyed
            delay_days=delay_days,
            risk_reduction=risk_reduction,
            confidence=confidence,
            evidence=[self._evidence(
                "CriticalPathEngine",
                "critical_path_duration_hours",
                float(self.upstream.cp_result.critical_path_duration_hours or 0.0),
                0.0,
                "Swarm formula mirrors applicator Brook's Law cap (max 40% parallelism gain)",
            )],
            notes=notes,
        )

    def _estimate_add_resource_skill(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        """
        Estimate impact of adding resource skill coverage.
        
        Consumes:
        - risk_result from RiskEngine for resource risk
        - resource_metrics from ProjectMetrics
        """
        # Skill coverage helps when resource risk is high
        resource_risk_score = float(
            getattr(self.upstream.risk_result, "resource_risk", {}).score
            if hasattr(self.upstream.risk_result, "resource_risk") else 0.0
        )
        
        hours_recovered = min(
            self.upstream.metrics.average_item_effort * 0.3 * min(1.0, resource_risk_score),
            self.upstream.forecast.remaining_effort_hours
        )
        
        return self._build_estimate(
            candidate,
            hours_recovered=hours_recovered,
            delay_days=0.0,
            risk_reduction=0.08 if resource_risk_score > 0.5 else 0.04,
            confidence=ConfidenceLevel.MEDIUM if resource_risk_score > 0.5 else ConfidenceLevel.LOW,
            evidence=[self._evidence(
                "RiskEngine",
                "resource_risk_score",
                resource_risk_score,
                0.0,
                "Skill coverage improves capacity resilience"
            )],
            notes="Impact depends on current resource risk level",
        )

    def _default_estimate(self, candidate: RecommendationCandidate) -> ImpactEstimate:
        return self._build_estimate(
            candidate,
            hours_recovered=0.0,
            delay_days=0.0,
            risk_reduction=0.0,
            confidence=ConfidenceLevel.LOW,
            evidence=[self._evidence("ForecastEngine", "remaining_effort_hours", self.upstream.forecast.remaining_effort_hours, 0.0, "No direct impact estimate available")],
            notes="Fell back to a neutral estimate",
        )

    def _build_estimate(
        self,
        candidate: RecommendationCandidate,
        *,
        hours_recovered: float,
        delay_days: float,
        risk_reduction: float,
        confidence: ConfidenceLevel,
        evidence: List[SignalEvidence],
        notes: str,
        forecast_confidence_gain: float = 0.0,
    ) -> ImpactEstimate:
        """Standard builder: clamps delay_days to ≥ 0 (positive = improvement)."""
        cap = max(0.0, self.upstream.forecast.remaining_effort_hours)
        return ImpactEstimate(
            estimated_hours_recovered=float(min(max(hours_recovered, 0.0), cap)),
            estimated_delay_reduction_days=float(max(delay_days, 0.0)),
            estimated_risk_reduction=float(max(risk_reduction, 0.0)),
            confidence=confidence,
            evidence=evidence,
            calculation_notes=notes,
            estimated_forecast_confidence_gain=float(max(0.0, min(1.0, forecast_confidence_gain))),
        )

    def _build_estimate_signed(
        self,
        candidate: RecommendationCandidate,
        *,
        hours_recovered: float,
        delay_days: float,
        risk_reduction: float,
        confidence: ConfidenceLevel,
        evidence: List[SignalEvidence],
        notes: str,
        forecast_confidence_gain: float = 0.0,
    ) -> ImpactEstimate:
        """
        Signed builder: allows negative delay_days to express schedule worsening.
        Used by FIX-07 (REBASELINE_ESTIMATE) and FIX-09 (REASSIGN worsening case).
        hours_recovered is still clamped to ≥ 0.
        """
        cap = max(0.0, self.upstream.forecast.remaining_effort_hours)
        return ImpactEstimate(
            estimated_hours_recovered=float(min(max(hours_recovered, 0.0), cap)),
            estimated_delay_reduction_days=float(delay_days),   # signed — negative = worsens schedule
            estimated_risk_reduction=float(max(risk_reduction, 0.0)),
            confidence=confidence,
            evidence=evidence,
            calculation_notes=notes,
            estimated_forecast_confidence_gain=float(max(0.0, min(1.0, forecast_confidence_gain))),
        )

    def _evidence(self, source_engine: str, metric_name: str, metric_value: float, threshold: float, explanation: str) -> SignalEvidence:
        return SignalEvidence(
            source_engine=source_engine,
            metric_name=metric_name,
            metric_value=float(metric_value),
            threshold=float(threshold),
            explanation=explanation,
        )
