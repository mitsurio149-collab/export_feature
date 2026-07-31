"""
EMIOS Validation Engine (Stage 2).

Confirms each Observation is REAL data, not a data-quality artifact. Handles the
17-detector metric vocabulary; adds DELIBERATE_RESCOPE and SECONDARY_SKILL_COVERS.
"""
from __future__ import annotations

from typing import List, Optional

from app.domain.models import ProjectState, SprintStatus, WorkItemStatus, WorkItemType
from app.domain.emios_models import (
    Observation, ObservationCluster, ArtifactType, SuppressedObservation, ValidationResult,
)

_SPIKE_TYPES = {WorkItemType.SPIKE}


class ValidationEngine:
    """Stage 2: validate an ObservationCluster into a ValidationResult."""

    PTO_CAPACITY_FLOOR: float = 0.60
    OUTLIER_SHARE: float = 0.50
    MIN_COMPLETED_SPRINTS: int = 2

    def run(self, cluster: ObservationCluster, state: ProjectState) -> ValidationResult:
        validated: List[Observation] = []
        suppressed: List[SuppressedObservation] = []
        warnings: List[str] = []
        completed_sprints = self._completed_sprint_count(state)

        for obs in cluster.observations:
            suppression = self._classify(obs, state, completed_sprints)
            if suppression is None:
                validated.append(obs)
            else:
                suppressed.append(suppression)
                warnings.append(suppression.reason)

        total = len(cluster.observations)
        data_confidence = (len(validated) / total) if total > 0 else 1.0
        if completed_sprints < self.MIN_COMPLETED_SPRINTS:
            warnings.append(
                f"Only {completed_sprints} completed sprint(s); "
                f"velocity-derived signals carry reduced confidence."
            )

        return ValidationResult(
            validated=validated,
            suppressed=suppressed,
            data_confidence=round(data_confidence, 4),
            warnings=warnings,
        )

    def _classify(self, obs, state, completed_sprints) -> Optional[SuppressedObservation]:
        metric = obs.metric_ref
        if metric == "velocity":
            return self._check_pto_artifact(obs, state)
        if metric == "carryover_rate":
            return self._check_estimate_outlier(obs, state)
        if metric == "on_time_probability":
            return self._check_insufficient_history(obs, completed_sprints)
        if metric == "blocker_delay_days":
            return self._check_early_blocker(obs, state)
        if metric == "estimation_drift":
            return self._check_estimation_drift_artifact(obs, state)
        if metric == "blocker_age_sprints":
            return self._check_early_blocker(obs, state)
        if metric == "skill_mismatch":
            return self._check_skill_mismatch_artifact(obs, state)
        return None

    def _check_pto_artifact(self, obs, state) -> Optional[SuppressedObservation]:
        if (obs.deviation_pct or 0.0) >= 0:
            return None
        current_sprint = self._current_sprint(state)
        if current_sprint is None:
            return None
        sprint_capacity = self._sprint_available_hours(current_sprint, state)
        baseline_capacity = self._team_baseline_capacity(state)
        if baseline_capacity <= 0:
            return None
        ratio = sprint_capacity / baseline_capacity
        if ratio < self.PTO_CAPACITY_FLOOR:
            return SuppressedObservation(
                observation=obs,
                artifact_type=ArtifactType.PLANNED_CAPACITY_REDUCTION,
                reason=(
                    f"Velocity drop suppressed: sprint '{getattr(current_sprint, 'sprint_name', '?')}' "
                    f"had only {ratio:.0%} of baseline team capacity available "
                    f"(planned capacity reduction, not a performance regression)."
                ),
            )
        return None

    def _check_estimate_outlier(self, obs, state) -> Optional[SuppressedObservation]:
        carried = self._carryover_items(state)
        if not carried:
            return None
        efforts = [
            (getattr(wi, "item_id", "?"), float(getattr(wi, "remaining_effort_hrs", 0.0) or 0.0))
            for wi in carried
        ]
        total_effort = sum(e for _, e in efforts)
        if total_effort <= 0:
            return None
        top_id, top_effort = max(efforts, key=lambda t: t[1])
        share = top_effort / total_effort
        if share > self.OUTLIER_SHARE:
            return SuppressedObservation(
                observation=obs,
                artifact_type=ArtifactType.ESTIMATE_OUTLIER,
                reason=(
                    f"Carryover spike suppressed: single item {top_id} accounts for "
                    f"{share:.0%} of carryover effort (estimate outlier, not systemic carryover)."
                ),
            )
        return None

    def _check_insufficient_history(self, obs, completed_sprints) -> Optional[SuppressedObservation]:
        if completed_sprints < self.MIN_COMPLETED_SPRINTS:
            return SuppressedObservation(
                observation=obs,
                artifact_type=ArtifactType.INSUFFICIENT_HISTORY,
                reason=(
                    f"On-time probability suppressed: only {completed_sprints} completed "
                    f"sprint(s) — insufficient velocity history to trust the estimate."
                ),
            )
        return None

    def _check_early_blocker(self, obs, state) -> Optional[SuppressedObservation]:
        blocker = self._find_blocker(state, obs.entity_id)
        if blocker is None:
            return None
        raised = getattr(blocker, "raised_date", None)
        current_sprint = self._current_sprint(state)
        if raised is None or current_sprint is None:
            return None
        sprint_start = getattr(current_sprint, "start_date", None)
        if sprint_start is None:
            return None
        raised_cmp = raised.replace(tzinfo=None) if getattr(raised, "tzinfo", None) else raised
        start_cmp = sprint_start.replace(tzinfo=None) if getattr(sprint_start, "tzinfo", None) else sprint_start
        if raised_cmp >= start_cmp:
            return SuppressedObservation(
                observation=obs,
                artifact_type=ArtifactType.EARLY_BLOCKER,
                reason=(
                    f"Blocker escalation suppressed: {getattr(blocker, 'blocker_id', '?')} was "
                    f"raised in the current sprint — insufficient age to assess real impact."
                ),
            )
        return None

    def _check_estimation_drift_artifact(self, obs, state) -> Optional[SuppressedObservation]:
        wi = self._find_work_item(state, obs.entity_id)
        if wi is None:
            return None
        rescoped = bool(getattr(wi, "rescoped", False)) or bool(getattr(wi, "is_scope_changed", False))
        is_spike = getattr(wi, "work_type", None) in _SPIKE_TYPES
        if rescoped or is_spike:
            reason_kind = "deliberately rescoped" if rescoped else "a spike/research item"
            return SuppressedObservation(
                observation=obs,
                artifact_type=ArtifactType.DELIBERATE_RESCOPE,
                reason=(
                    f"Estimation change suppressed: item {getattr(wi, 'item_id', '?')} is "
                    f"{reason_kind}, not unplanned drift."
                ),
            )
        return None

    def _check_skill_mismatch_artifact(self, obs, state) -> Optional[SuppressedObservation]:
        wi = self._find_work_item(state, obs.entity_id)
        if wi is None:
            return None
        req = getattr(wi, "required_skill", None)
        rid = getattr(wi, "assigned_resource", None)
        resource = self._find_resource(state, rid)
        if resource is None or not req:
            return None
        secondary = getattr(resource, "secondary_skill", None)
        coverage = [getattr(sc, "skill", None) for sc in getattr(resource, "skill_coverage", []) or []]
        if secondary == req or req in coverage:
            return SuppressedObservation(
                observation=obs,
                artifact_type=ArtifactType.SECONDARY_SKILL_COVERS,
                reason=(
                    f"Skill mismatch suppressed: {getattr(resource, 'name', rid)} covers "
                    f"'{req}' as a secondary/backup skill."
                ),
            )
        return None

    # --- helpers ----------------------------------------------------------
    def _completed_sprint_count(self, state) -> int:
        return sum(1 for s in getattr(state, "sprints", []) or []
                   if getattr(s, "status", None) == SprintStatus.COMPLETED)

    def _current_sprint(self, state):
        sprints = getattr(state, "sprints", []) or []
        for s in sprints:
            if getattr(s, "status", None) == SprintStatus.IN_PROGRESS:
                return s
        for s in sorted(sprints, key=lambda x: getattr(x, "sprint_number", 0)):
            if getattr(s, "status", None) == SprintStatus.NOT_STARTED:
                return s
        return None

    def _sprint_available_hours(self, sprint, state) -> float:
        breakdown = getattr(sprint, "capacity_breakdown", None) or []
        if breakdown:
            return float(sum(getattr(e, "hours", 0.0) or 0.0 for e in breakdown))
        planned = float(getattr(sprint, "planned_velocity_hrs", 0.0) or 0.0)
        if planned > 0:
            return planned
        working_days = float(getattr(sprint, "working_days", 0) or 0)
        return self._team_daily_capacity(state) * working_days

    def _team_baseline_capacity(self, state) -> float:
        completed = [s for s in getattr(state, "sprints", []) or []
                     if getattr(s, "status", None) == SprintStatus.COMPLETED]
        if completed:
            vals = [self._sprint_available_hours(s, state) for s in completed]
            vals = [v for v in vals if v > 0]
            if vals:
                return sum(vals) / len(vals)
        sprint_days = float(getattr(state.project_info, "sprint_duration_days", 14) or 14)
        return self._team_daily_capacity(state) * (sprint_days * 5.0 / 7.0)

    def _team_daily_capacity(self, state) -> float:
        total = 0.0
        for r in getattr(state, "team", []) or []:
            daily = float(getattr(r, "daily_capacity_hrs", 8.0) or 8.0)
            avail = float(getattr(r, "availability_pct", 1.0) or 1.0)
            alloc = float(getattr(r, "allocation_pct", 1.0) or 1.0)
            total += daily * avail * alloc
        return total

    def _carryover_items(self, state):
        out = []
        for wi in getattr(state, "work_items", []) or []:
            status = getattr(wi, "status", None)
            original = getattr(wi, "original_sprint", None)
            assigned = getattr(wi, "assigned_sprint", None)
            moved = original is not None and assigned is not None and original != assigned
            if status == WorkItemStatus.SPILLOVER or moved:
                out.append(wi)
        return out

    def _find_blocker(self, state, blocker_id):
        if not blocker_id:
            return None
        for b in getattr(state, "blockers", []) or []:
            if getattr(b, "blocker_id", None) == blocker_id:
                return b
        return None

    def _find_work_item(self, state, item_id):
        if not item_id:
            return None
        for wi in getattr(state, "work_items", []) or []:
            if getattr(wi, "item_id", None) == item_id:
                return wi
        return None

    def _find_resource(self, state, rid):
        if not rid:
            return None
        for r in getattr(state, "team", []) or []:
            if getattr(r, "resource_id", None) == rid or getattr(r, "name", None) == rid:
                return r
        return None