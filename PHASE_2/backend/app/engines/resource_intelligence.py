"""Canonical resource intelligence for Sprint Whisperer.

No skill-level productivity multipliers live here.  The model prefers measured
per-resource delivery history and otherwise falls back to the resource's own
workbook capacity.  Skill coverage is a feasibility constraint, not an invented
speed penalty.  Estimation reliability is reported separately from delivery rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.domain.models import ProjectState, Resource, WorkItem


@dataclass(frozen=True)
class ResourceRateEvidence:
    resource_id: str
    daily_rate_hrs: float
    source: str
    sample_size: int
    estimation_reliability: Optional[float]
    skill_match: bool
    sprint_capacity_hrs: float
    committed_hrs: float
    free_capacity_hrs: float


class ResourceIntelligence:
    def __init__(self, state: ProjectState):
        self.state = state

    def _skill_key(self, skill: Optional[str]) -> str:
        return str(skill or "").strip().lower()

    def _matches_required_skill(self, resource: Resource, required_skill: Optional[str]) -> bool:
        if not required_skill:
            return True
        return resource.covers_skill(required_skill)

    def _looks_like_new_team_member(self, resource: Resource) -> bool:
        notes = str(getattr(resource, "notes", "") or "").lower()
        markers = ["new team member", "new member", "joining", "ramp-up", "ramp up", "onboarding", "kt"]
        return any(marker in notes for marker in markers)

    def sprint(self, sprint_ref: Optional[str]):
        if not sprint_ref:
            return None
        return next((s for s in self.state.sprints
                     if s.sprint_id == sprint_ref or s.sprint_name == sprint_ref), None)

    def resource(self, resource_id: Optional[str]) -> Optional[Resource]:
        if not resource_id:
            return None
        return next((r for r in self.state.team
                     if r.resource_id == resource_id or r.name == resource_id), None)

    def sprint_days(self, sprint_ref: Optional[str]) -> float:
        sprint = self.sprint(sprint_ref)
        if sprint is not None:
            delta = (sprint.end_date - sprint.start_date).total_seconds() / 86400.0
            if delta > 0:
                return delta
        return float(self.state.project_info.sprint_duration_days or 10)

    def _resolve_sprint_id(self, sprint_ref: Optional[str]) -> Optional[str]:
        """Resolve sprint_ref (which may be a sprint_id OR a sprint_name) to
        the canonical sprint_id used to key Resource.sprint_allocation_pct /
        sprint_availability_pct. Falls back to the raw ref if it doesn't
        match a known Sprint object (e.g. a caller that already passes a
        sprint_id for a sprint outside project_state.sprints -- tests do
        this) so a plain "SPR-3" string still works as a lookup key."""
        if not sprint_ref:
            return None
        sprint = self.sprint(sprint_ref)
        return sprint.sprint_id if sprint is not None else sprint_ref

    def allocation_pct(self, resource: Resource, sprint_ref: Optional[str]) -> float:
        """Sprint-specific allocation when known, else the aggregate
        workbook fallback. Missing and explicit-zero are different: a
        sprint_id present in sprint_allocation_pct with value 0.0 is honored
        as 0.0; only an ABSENT sprint_id falls back to resource.allocation_pct."""
        sprint_id = self._resolve_sprint_id(sprint_ref)
        if sprint_id is not None:
            exact = resource.sprint_allocation_pct.get(sprint_id)
            if exact is not None:
                return max(0.0, float(exact))
        return max(0.0, float(resource.allocation_pct))

    def availability_pct(self, resource: Resource, sprint_ref: Optional[str]) -> float:
        """Sprint-specific availability when known, else the aggregate
        workbook fallback. Same missing-vs-zero semantics as allocation_pct
        above."""
        sprint_id = self._resolve_sprint_id(sprint_ref)
        if sprint_id is not None:
            exact = resource.sprint_availability_pct.get(sprint_id)
            if exact is not None:
                return max(0.0, float(exact))
        return max(0.0, float(resource.availability_pct))

    def daily_rate_capacity_fallback(self, resource: Resource, sprint_ref: Optional[str]) -> float:
        """Neutral, resource-specific hours/day capacity estimate for the
        given sprint context: daily_capacity_hrs * sprint-aware allocation *
        sprint-aware availability. This is the ONE place that formula lives;
        do not recompute it locally in another engine (see evidence() and
        _find_second_capable_resource-style callers, which should call this
        instead of reading resource.allocation_pct/availability_pct scalars
        directly when they already have a sprint_ref)."""
        return (
            max(0.0, float(resource.daily_capacity_hrs))
            * self.allocation_pct(resource, sprint_ref)
            * self.availability_pct(resource, sprint_ref)
        )

    def effective_capacity_hours(self, resource: Resource, sprint_ref: Optional[str]) -> float:
        return (
            max(0.0, float(resource.daily_capacity_hrs))
            * self.sprint_days(sprint_ref)
            * self.allocation_pct(resource, sprint_ref)
            * self.availability_pct(resource, sprint_ref)
        )

    def committed_hours(self, resource: Resource, sprint_ref: Optional[str],
                        exclude_item_ids: Optional[set[str]] = None) -> float:
        sprint = self.sprint(sprint_ref)
        sprint_name = sprint.sprint_name if sprint else sprint_ref
        excluded = exclude_item_ids or set()
        return sum(
            max(0.0, float(w.remaining_effort_hrs))
            for w in self.state.work_items
            if w.item_id not in excluded
            and w.assigned_resource in {resource.resource_id, resource.name}
            and (not sprint_name or w.assigned_sprint == sprint_name)
        )

    def free_capacity_hours(self, resource: Resource, sprint_ref: Optional[str],
                            exclude_item_ids: Optional[set[str]] = None) -> float:
        return max(0.0, self.effective_capacity_hours(resource, sprint_ref)
                   - self.committed_hours(resource, sprint_ref, exclude_item_ids))

    def _completed_history(self, resource: Resource, required_skill: Optional[str]):
        rows = []
        for w in self.state.work_items:
            if w.assigned_resource not in {resource.resource_id, resource.name}:
                continue
            status = str(getattr(w.status, "value", w.status)).lower()
            if status not in {"done", "completed"}:
                continue
            if required_skill and self._skill_key(w.required_skill) != self._skill_key(required_skill):
                continue
            rows.append(w)
        return rows

    def measured_daily_rate(self, resource: Resource, required_skill: Optional[str]) -> tuple[Optional[float], int]:
        """Historical delivery rate in hours/day using completed work evidence.

        The canonical model uses observed completed effort as the strongest signal of
        how quickly a resource can turn work into delivery. When the history is sparse,
        the rate remains conservative and falls back to the resource's workbook capacity.
        """
        rows = self._completed_history(resource, required_skill)
        if not rows:
            return None, 0
        delivered = sum(
            max(
                0.0,
                float(getattr(w, "actual_effort_hrs", 0.0) or 0.0)
                if float(getattr(w, "actual_effort_hrs", 0.0) or 0.0) > 0.0
                else float(getattr(w, "estimated_effort_hrs", 0.0) or 0.0),
            )
            for w in rows
        )
        if delivered <= 0:
            return None, 0
        return delivered / max(1.0, float(len(rows))), len(rows)

    def team_historical_rate(self, resource: Resource, required_skill: Optional[str]) -> Optional[float]:
        """Use peer history when the individual has no reliable history of their own."""
        candidates = []
        for peer in self.state.team:
            if peer.resource_id == resource.resource_id or peer.name == resource.name:
                continue
            if required_skill and not self._matches_required_skill(peer, required_skill):
                continue
            rate, _ = self.measured_daily_rate(peer, required_skill)
            if rate is not None and rate > 0:
                candidates.append(rate)
        if not candidates:
            return None
        return sum(candidates) / len(candidates)

    def estimation_reliability(self, resource: Resource, required_skill: Optional[str]) -> Optional[float]:
        rows = [w for w in self._completed_history(resource, required_skill)
                if float(w.actual_effort_hrs) > 0 and float(w.estimated_effort_hrs) > 0]
        if not rows:
            return None
        estimated = sum(float(w.estimated_effort_hrs) for w in rows)
        actual = sum(float(w.actual_effort_hrs) for w in rows)
        if actual <= 0:
            return None
        # 1.0 = aggregate estimate matched actual; lower values mean less reliable.
        return min(estimated, actual) / max(estimated, actual)

    def evidence(self, resource: Resource, item: Optional[WorkItem],
                 sprint_ref: Optional[str]) -> ResourceRateEvidence:
        required_skill = item.required_skill if item else None
        skill_match = self._matches_required_skill(resource, required_skill)
        measured, n = self.measured_daily_rate(resource, required_skill)
        team_rate = None
        source = "resource_capacity"
        if measured is not None:
            rate = measured
            source = "individual_history"
        elif self._looks_like_new_team_member(resource):
            rate = None
            source = "resource_capacity"
        else:
            team_rate = self.team_historical_rate(resource, required_skill)
            if team_rate is not None:
                rate = team_rate
                source = "team_history"
            else:
                rate = None
        # Fallback is neutral, resource-specific workbook capacity/day for
        # THIS sprint context (sprint-specific alloc/avail when known, else
        # the aggregate fallback) -- single canonical formula, see
        # daily_rate_capacity_fallback().
        capacity_daily = self.daily_rate_capacity_fallback(resource, sprint_ref)
        rate = rate if rate is not None else capacity_daily
        # A known mismatch is infeasible for reassignment; do not invent a mismatch penalty.
        if not skill_match:
            rate = 0.0
            source = "skill_mismatch"
        cap = self.effective_capacity_hours(resource, sprint_ref)
        committed = self.committed_hours(resource, sprint_ref)
        return ResourceRateEvidence(
            resource_id=resource.resource_id,
            daily_rate_hrs=max(0.0, rate),
            source=source,
            sample_size=n,
            estimation_reliability=self.estimation_reliability(resource, required_skill),
            skill_match=skill_match,
            sprint_capacity_hrs=cap,
            committed_hrs=committed,
            free_capacity_hrs=max(0.0, cap - committed),
        )

    def feasible_receiver(self, resource: Resource, item: WorkItem, sprint_ref: Optional[str],
                          required_hours: Optional[float] = None) -> bool:
        ev = self.evidence(resource, item, sprint_ref)
        need = float(item.remaining_effort_hrs if required_hours is None else required_hours)
        return ev.skill_match and ev.daily_rate_hrs > 0 and ev.free_capacity_hrs >= max(0.0, need)

    def best_receiver(self, item: WorkItem, sprint_ref: Optional[str],
                      exclude_resource_id: Optional[str] = None,
                      required_hours: Optional[float] = None) -> Optional[Resource]:
        candidates = []
        for r in self.state.team:
            if r.resource_id == exclude_resource_id:
                continue
            ev = self.evidence(r, item, sprint_ref)
            need = float(item.remaining_effort_hrs if required_hours is None else required_hours)
            if ev.skill_match and ev.daily_rate_hrs > 0 and ev.free_capacity_hrs >= max(0.0, need):
                candidates.append((ev.daily_rate_hrs, ev.free_capacity_hrs, r.resource_id, r))
        return max(candidates, default=(0, 0, "", None))[-1]
