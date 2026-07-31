"""
EMIOS Stage 17b — HistoricalAnalyzer (Phase 6b).

Runs on every pipeline execution. Analyses patterns across all sprints in
the project state: overbilling (closed items that ran way over estimate),
spillover (items that landed in a later sprint than planned), recurring
blocker categories, cascade chains (an overrun causing downstream spills),
and produces concrete prevention recommendations grounded in that evidence.

Field-name note: app/domain/models.WorkItem has no `sprint_id` -- the sprint
an item is currently in is `assigned_sprint` (a sprint *name*, e.g. "Sprint 5"),
and the sprint it was originally planned for is `original_sprint`. Likewise
Blocker has no `estimated_delay_days` field; it's derived via getattr with a
(target_resolution_date - raised_date).days fallback, same as cognition_common.py
does elsewhere in this codebase.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from uuid import uuid4

from app.domain.emios_models import (
    CascadePattern,
    HistoricalAnalysis,
    OverbillingInstance,
    PreventionRecommendation,
    RecurringBlockerPattern,
    SpilloverInstance,
)
from app.domain.models import (
    Blocker,
    BlockerStatus,
    ProjectState,
    Sprint,
    SprintStatus,
    WorkItem,
    WorkItemStatus,
)

_CLOSED_STATUSES = {WorkItemStatus.DONE, WorkItemStatus.COMPLETED}
_DONE_SPRINT_STATUSES = {SprintStatus.COMPLETED}
_OVERBILLING_TOLERANCE = 1.10  # 10% tolerance


class HistoricalAnalyzer:
    """Stage 17b: mine ProjectState for overbilling, spillover, recurring
    blockers, and cascade chains, then turn those patterns into concrete,
    evidence-backed prevention recommendations."""

    def run(self, state: ProjectState) -> HistoricalAnalysis:
        work_items = list(getattr(state, "work_items", []) or [])
        sprints = list(getattr(state, "sprints", []) or [])
        blockers = list(getattr(state, "blockers", []) or [])
        dependencies = list(getattr(state, "dependencies", []) or [])

        sprint_by_id = {s.sprint_id: s for s in sprints}
        sprint_by_name = {getattr(s, "sprint_name", None): s for s in sprints}

        overbilling = self._analyse_overbilling(work_items, blockers, sprint_by_name)
        spillover = self._analyse_spillover(
            work_items, blockers, dependencies, sprint_by_name
        )
        recurring_blockers = self._analyse_recurring_blockers(blockers)
        cascade_patterns = self._detect_cascades(overbilling, spillover, dependencies)
        prevention_recommendations = self._generate_prevention_recommendations(
            overbilling, spillover, recurring_blockers, cascade_patterns
        )

        completed = len(
            [s for s in sprints if getattr(s, "status", None) in _DONE_SPRINT_STATUSES]
        )

        summary = self._build_summary(
            completed, overbilling, spillover, recurring_blockers
        )

        return HistoricalAnalysis(
            analysis_id=f"hist-{uuid4().hex[:10]}",
            sprints_analysed=completed,
            overbilling=overbilling,
            spillover=spillover,
            recurring_blockers=recurring_blockers,
            cascade_patterns=cascade_patterns,
            prevention_recommendations=prevention_recommendations,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Overbilling
    # ------------------------------------------------------------------

    def _analyse_overbilling(
        self,
        work_items: List[WorkItem],
        blockers: List[Blocker],
        sprint_by_name: Dict[Optional[str], Sprint],
    ) -> List[OverbillingInstance]:
        results: List[OverbillingInstance] = []

        for item in work_items:
            status = getattr(item, "status", None)
            if status not in _CLOSED_STATUSES:
                continue

            estimated = getattr(item, "current_estimate_hrs", 0.0) or 0.0
            actual = getattr(
                item, "actual_hrs", getattr(item, "actual_effort_hrs", 0.0)
            ) or 0.0

            if not (actual > 0 and estimated > 0):
                continue
            if not (actual > estimated * _OVERBILLING_TOLERANCE):
                continue

            overrun_hrs = actual - estimated
            overrun_pct = overrun_hrs / estimated

            item_id = getattr(item, "item_id", "")
            related_blockers = [
                b for b in blockers
                if item_id in (getattr(b, "impacted_item_ids", None) or [])
            ]
            was_flagged = len(related_blockers) > 0

            first_flagged_sprint: Optional[str] = None
            if related_blockers:
                # The blocker itself doesn't carry a sprint_id; best available
                # proxy is the item's assigned sprint, since we have no
                # historical per-blocker sprint snapshot in this model.
                first_flagged_sprint = getattr(
                    item, "assigned_sprint", None
                ) or getattr(item, "original_sprint", None)

            results.append(
                OverbillingInstance(
                    item_id=item_id,
                    item_title=getattr(item, "title", item_id),
                    sprint_id=getattr(item, "assigned_sprint", "") or "",
                    estimated_hrs=round(estimated, 2),
                    actual_hrs=round(actual, 2),
                    overrun_hrs=round(overrun_hrs, 2),
                    overrun_pct=round(overrun_pct, 4),
                    assigned_to=getattr(
                        item, "assigned_resource", getattr(item, "assigned_to", "")
                    ) or "",
                    required_skill=getattr(item, "required_skill", "") or "",
                    was_flagged=was_flagged,
                    first_flagged_sprint=first_flagged_sprint,
                )
            )

        results.sort(key=lambda o: o.overrun_pct, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Spillover
    # ------------------------------------------------------------------

    def _analyse_spillover(
        self,
        work_items: List[WorkItem],
        blockers: List[Blocker],
        dependencies,
        sprint_by_name: Dict[Optional[str], Sprint],
    ) -> List[SpilloverInstance]:
        results: List[SpilloverInstance] = []

        open_blockers = [
            b for b in blockers if getattr(b, "status", None) == BlockerStatus.OPEN
        ]

        for item in work_items:
            status = getattr(item, "status", None)
            original_sprint = getattr(item, "original_sprint", None)
            current_sprint = getattr(item, "assigned_sprint", None)

            is_spillover_status = status == WorkItemStatus.SPILLOVER
            is_sprint_mismatch = (
                original_sprint is not None and original_sprint != current_sprint
            )
            if not (is_spillover_status or is_sprint_mismatch):
                continue

            original_sprint_obj = sprint_by_name.get(original_sprint)
            current_sprint_obj = sprint_by_name.get(current_sprint)

            if (
                original_sprint_obj is not None
                and current_sprint_obj is not None
                and getattr(original_sprint_obj, "sprint_number", None) is not None
                and getattr(current_sprint_obj, "sprint_number", None) is not None
            ):
                sprints_delayed = (
                    current_sprint_obj.sprint_number - original_sprint_obj.sprint_number
                )
                if sprints_delayed <= 0:
                    sprints_delayed = 1
            else:
                sprints_delayed = 1

            item_id = getattr(item, "item_id", "")

            matching_open_blockers = [
                b for b in open_blockers
                if item_id in (getattr(b, "impacted_item_ids", None) or [])
            ]
            matching_dependency = next(
                (
                    d for d in dependencies
                    if getattr(d, "successor_item_id", None) == item_id
                ),
                None,
            )

            if matching_open_blockers:
                reason_category = "BLOCKER"
                root_blocker_id = getattr(matching_open_blockers[0], "blocker_id", None)
            elif matching_dependency is not None:
                reason_category = "DEPENDENCY"
                root_blocker_id = None
            else:
                reason_category = "CAPACITY"
                root_blocker_id = None

            results.append(
                SpilloverInstance(
                    item_id=item_id,
                    item_title=getattr(item, "title", item_id),
                    original_sprint=original_sprint or (current_sprint or ""),
                    landed_sprint=current_sprint or "",
                    sprints_delayed=sprints_delayed,
                    reason_category=reason_category,
                    recurred=sprints_delayed > 1,
                    root_blocker_id=root_blocker_id,
                )
            )

        results.sort(key=lambda s: s.sprints_delayed, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Recurring blockers
    # ------------------------------------------------------------------

    def _analyse_recurring_blockers(
        self, blockers: List[Blocker]
    ) -> List[RecurringBlockerPattern]:
        groups: Dict[str, List[Blocker]] = {}
        for b in blockers:
            category = getattr(b, "category", None)
            category_str = getattr(category, "value", category) or "Other"
            groups.setdefault(category_str, []).append(b)

        patterns: List[RecurringBlockerPattern] = []
        for category, group in groups.items():
            if len(group) < 2:
                continue

            total_delay_days = 0.0
            for b in group:
                total_delay_days += self._blocker_delay_days(b)

            sprint_ids = sorted({
                sid for b in group
                for sid in self._blocker_related_sprint_ids(b)
            })

            has_open = any(
                getattr(b, "status", None) == BlockerStatus.OPEN for b in group
            )
            occurrences = len(group)

            if has_open:
                verdict = "UNRESOLVED"
            elif occurrences >= 3:
                verdict = "SYSTEMIC"
            else:
                verdict = "COINCIDENTAL"

            patterns.append(
                RecurringBlockerPattern(
                    category=category,
                    occurrences=occurrences,
                    sprint_ids=sprint_ids,
                    total_delay_days=round(total_delay_days, 2),
                    was_resolved_permanently=not has_open,
                    recurrence_verdict=verdict,
                )
            )

        patterns.sort(key=lambda p: p.occurrences, reverse=True)
        return patterns

    @staticmethod
    def _blocker_delay_days(b: Blocker) -> float:
        est = getattr(b, "estimated_delay_days", None)
        if est is not None:
            return float(est)
        raised = getattr(b, "raised_date", None)
        target = getattr(b, "target_resolution_date", None)
        if raised is not None and target is not None:
            return max((target - raised).days, 0)
        return 0.0

    @staticmethod
    def _blocker_related_sprint_ids(b: Blocker) -> List[str]:
        # Blocker has no direct sprint field; best-effort empty if unavailable.
        sid = getattr(b, "sprint_id", None)
        return [sid] if sid else []

    # ------------------------------------------------------------------
    # Cascade detection
    # ------------------------------------------------------------------

    def _detect_cascades(
        self,
        overbilling: List[OverbillingInstance],
        spillover: List[SpilloverInstance],
        dependencies,
    ) -> List[CascadePattern]:
        patterns: List[CascadePattern] = []
        dependency_spills = [s for s in spillover if s.reason_category == "DEPENDENCY"]

        for o in overbilling:
            matched = [
                s for s in dependency_spills
                if any(
                    getattr(d, "predecessor_item_id", None) == o.item_id
                    and getattr(d, "successor_item_id", None) == s.item_id
                    for d in dependencies
                )
            ]
            if matched:
                patterns.append(
                    CascadePattern(
                        trigger_item_id=o.item_id,
                        cascade_item_ids=[s.item_id for s in matched],
                        total_cascade_delay_sprints=sum(s.sprints_delayed for s in matched),
                    )
                )

        return patterns

    # ------------------------------------------------------------------
    # Prevention recommendations
    # ------------------------------------------------------------------

    def _generate_prevention_recommendations(
        self,
        overbilling: List[OverbillingInstance],
        spillover: List[SpilloverInstance],
        recurring_blockers: List[RecurringBlockerPattern],
        cascade_patterns: List[CascadePattern],
    ) -> List[PreventionRecommendation]:
        recs: List[PreventionRecommendation] = []

        # RULE 1 — unflagged overbilling
        unflagged = [o for o in overbilling if not o.was_flagged]
        if len(unflagged) >= 2:
            recs.append(
                PreventionRecommendation(
                    trigger=f"{len(unflagged)} overbilling items had no blocker raised before overrun",
                    action=(
                        "Add a mid-sprint check at day 5 of each sprint. Any item consuming "
                        ">120% of estimate must raise a blocker or risk flag immediately — "
                        "not at sprint review."
                    ),
                    sprint_to_apply="NEXT",
                    confidence="HIGH",
                    evidence=[
                        f"{o.item_id}: +{o.overrun_pct:.0%} overrun, not flagged"
                        for o in unflagged[:3]
                    ],
                )
            )

        # RULE 2 — cascade pattern
        if len(cascade_patterns) > 0:
            recs.append(
                PreventionRecommendation(
                    trigger=f"{len(cascade_patterns)} spillover items caused by upstream overruns",
                    action=(
                        "In sprint planning, identify all items depending on in-flight items "
                        "with active overruns. Add 20% buffer or move them to the next sprint "
                        "proactively."
                    ),
                    sprint_to_apply="PLANNING",
                    confidence="HIGH",
                    evidence=[
                        f"{c.trigger_item_id} overrun caused {len(c.cascade_item_ids)} downstream spills"
                        for c in cascade_patterns[:2]
                    ],
                )
            )

        # RULE 3 — systemic blocker category (one rec per systemic pattern)
        systemic_patterns = [
            p for p in recurring_blockers if p.recurrence_verdict == "SYSTEMIC"
        ]
        for pattern in systemic_patterns:
            recs.append(
                PreventionRecommendation(
                    trigger=(
                        f"{pattern.category} blockers recurred {pattern.occurrences}x "
                        f"({pattern.total_delay_days:.0f} total delay-days)"
                    ),
                    action=(
                        f"Treat {pattern.category} as a structural risk, not an incident. "
                        f"Assign a permanent owner for this dependency type. "
                        f"Establish an SLA or escalation path before the next sprint starts. "
                        f"Add as a standing agenda item in all sprint plannings."
                    ),
                    sprint_to_apply="IMMEDIATELY",
                    confidence="HIGH",
                    evidence=[f"Occurred in sprints: {', '.join(pattern.sprint_ids)}"],
                )
            )

        # RULE 4 — capacity-caused spillover
        capacity_spills = [s for s in spillover if s.reason_category == "CAPACITY"]
        if len(capacity_spills) >= 2:
            recs.append(
                PreventionRecommendation(
                    trigger=f"{len(capacity_spills)} spillovers caused by resource overcommitment",
                    action=(
                        "Before sprint commitment, verify no resource exceeds 85% planned load. "
                        "Items that would push a resource over 85% move to the next sprint "
                        "automatically."
                    ),
                    sprint_to_apply="PLANNING",
                    confidence="MEDIUM",
                    evidence=[
                        f"{s.item_id}: spilled from {s.original_sprint} (capacity)"
                        for s in capacity_spills[:3]
                    ],
                )
            )

        return recs[:4]

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        completed: int,
        overbilling: List[OverbillingInstance],
        spillover: List[SpilloverInstance],
        recurring_blockers: List[RecurringBlockerPattern],
    ) -> str:
        systemic_patterns = [
            p for p in recurring_blockers if p.recurrence_verdict == "SYSTEMIC"
        ]

        base = (
            f"{completed} completed sprints analysed: "
            f"{len(overbilling)} overbilling instance(s), "
            f"{len(spillover)} spillover instance(s), "
            f"{len(recurring_blockers)} recurring blocker pattern(s) detected. "
        )

        if systemic_patterns:
            top = systemic_patterns[0]
            tail = (
                f"Critical: {top.category} is a systemic blocker "
                f"({top.occurrences}x, {top.total_delay_days:.0f} days lost)."
            )
        else:
            tail = "No systemic blocker patterns detected."

        return base + tail
