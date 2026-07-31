from typing import Dict, List, Tuple, Any

from app.engines.recommendation_engine.models import RecommendationAction


# Map each RecommendationAction to the forecast-facing fields it intends to change.
# Paths are high-level and interpreted by the applicator check (see helper below).
FORECAST_LEVER_MAP: Dict[RecommendationAction, List[str]] = {
    RecommendationAction.RESOLVE_BLOCKER: [
        "blocker.status",
        "work_item.remaining_effort_hrs",
    ],
    RecommendationAction.CROSS_TRAIN_BACKUP: [
        "resource.skill_coverage",       # backup peer gains a BACKUP SkillCoverage entry (when backup identified)
        "sprint.capacity_breakdown",     # backup peer's hours added as a SprintCapacityEntry (when backup identified)
        "sprint.planned_velocity_hrs",   # bumped in fallback path when no backup resource is identified
    ],
    RecommendationAction.SPLIT_ITEM: [
        "work_item.remaining_effort_hrs",  # original item's hours halved
        "work_item.current_estimate_hrs",  # original item's estimate halved
        "work_item.parent_item_id",        # sibling records its origin
        "work_item.can_parallel_with",     # both items explicitly marked parallelizable
    ],
    RecommendationAction.SWARM_ITEM: [
        "sprint.capacity_breakdown",     # swarm resource committed via SprintCapacityEntry
        "work_item.can_parallel_with",   # item records the swarming resource
        "work_item.remaining_effort_hrs",# reduced by derived parallelism factor
    ],
    RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK: [
        "dependency.lag_days",
    ],
    RecommendationAction.REASSIGN_ITEM: [
        "work_item.assigned_resource",
        "resource.allocation_pct",
    ],
    RecommendationAction.PARALLELIZE_ITEMS: [
        "dependency.lag_days",           # collapsed to 0 only when a direct dependency
                                          # edge exists between the two paired items
        "work_item.can_parallel_with",   # unconditionally recorded on both paired items;
                                          # current_estimate_hrs is intentionally never
                                          # touched here (parallelizing changes
                                          # serialization, not effort — see
                                          # ActionApplicatorV2._apply_parallelize_items)
    ],
    RecommendationAction.REBALANCE_SPRINT_LOAD: [
        "work_item.assigned_resource",  # _apply_rebalance_sprint_load reassigns the item's
                                         # owner to the receiving resource -- it does not
                                         # move the item between sprints, so declaring
                                         # assigned_sprint here was inaccurate metadata.
        "resource.allocation_pct",
    ],
    RecommendationAction.ADD_RESOURCE_SKILL: [
        "resource.primary_skill",
        "resource.availability_pct",
        "resource.daily_capacity_hrs",   # overtime fallback -- see simulation_engine._apply_add_resource_skill.
                                          # allocation_pct/availability_pct are capped at 1.0 by the Resource
                                          # model, so for resources already at 100% (the common case: this
                                          # recommendation targets exactly the people who are already maxed
                                          # out) those two levers are guaranteed no-ops. daily_capacity_hrs
                                          # (0-24h/day) has real headroom and is the only valid lever left.
    ],
    RecommendationAction.REBASELINE_ESTIMATE: [
        "work_item.current_estimate_hrs",
    ],
    RecommendationAction.PAIR_REVIEWER: [
        "work_item.remaining_effort_hrs",
    ],
    RecommendationAction.ESCALATE_BLOCKER_EARLY: [
        "blocker.severity",              # unconditional — always bumped by _apply_escalate_blocker_early
        "blocker.target_resolution_date",# conditional — pulled forward when date exists
        # work_item.remaining_effort_hrs intentionally removed: escalating a blocker
        # changes its resolution timeline, not the blocked item's effort. See PM
        # audit -- ALL_RECOMMENDATIONS_PM_AUDIT.md.
    ],
    RecommendationAction.PULL_FORWARD_ITEM: [
        "work_item.assigned_sprint",
    ],
    RecommendationAction.INSERT_REVIEW_GATE: [
        "work_item.remaining_effort_hrs",
    ],
    RecommendationAction.APPLY_RAMP_UP_DISCOUNT: [
        "sprint.planned_velocity_hrs",
    ],
    RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM: [
        "work_item.priority",   # demoted one level -- pure reorder, no effort change
        "dependency.lag_days",
    ],
    RecommendationAction.SPLIT_AND_PAIR: [
        "work_item.current_estimate_hrs",
    ],
    RecommendationAction.ASSIGN_AS_SECOND_REVIEWER: [
        "work_item.remaining_effort_hrs",
    ],
    RecommendationAction.FREEZE_SCOPE_REQUEST: [
        "work_item.current_estimate_hrs",
    ],
}


def _path_is_list_root(path: str) -> str:
    # return the root collection name (work_item, resource, sprint, blocker, dependency)
    return path.split(".")[0] if path and "." in path else path


def _snapshot(value):
    """Copy mutable container values so a 'before' sample can't be silently
    mutated in place by the applicator before the 'after' sample is taken.
    Without this, list-typed levers (skill_coverage, capacity_breakdown)
    always compare as unchanged, because before/after end up pointing at the
    exact same list object — appending to it updates 'before' too.
    """
    if isinstance(value, list):
        return tuple(value)  # shallow copy; elements themselves aren't mutated in place
    return value


def sample_lever_values(state_obj: Any, rec: Any, path: str):
    """Return a tuple of values for the given lever path scoped to the recommendation.

    For collection-rooted paths like "work_item.remaining_effort_hrs" we only sample
    the items referenced by the recommendation (e.g. affected_item_ids). For
    scalar paths (if present) we attempt a direct attribute access.

    Values are snapshotted via _snapshot() so mutable attributes (lists) are
    captured by value, not by reference — see _snapshot's docstring.
    """
    root = _path_is_list_root(path)
    attr = path.split(".", 1)[1] if "." in path else None

    try:
        if root == "work_item" and attr:
            ids = getattr(rec, "affected_item_ids", []) or []
            if not ids:
                return tuple()
            values = []
            for wi in getattr(state_obj, "work_items", []):
                if wi.item_id not in ids:
                    continue
                values.append(_snapshot(getattr(wi, attr, None)))
            return tuple(values)

        if root == "resource" and attr:
            ids = getattr(rec, "affected_resource_ids", []) or []
            if not ids:
                return tuple()
            values = []
            for r in getattr(state_obj, "team", []):
                if r.resource_id not in ids:
                    continue
                values.append(_snapshot(getattr(r, attr, None)))
            return tuple(values)

        if root == "sprint" and attr:
            ids = getattr(rec, "affected_sprint_ids", []) or []
            if not ids:
                return tuple()
            values = []
            for s in getattr(state_obj, "sprints", []):
                if s.sprint_name not in ids:
                    continue
                values.append(_snapshot(getattr(s, attr, None)))
            return tuple(values)

        if root == "blocker" and attr:
            ids = getattr(rec, "affected_blocker_ids", []) or []
            if not ids:
                return tuple()
            values = []
            for b in getattr(state_obj, "blockers", []):
                if b.blocker_id not in ids:
                    continue
                values.append(_snapshot(getattr(b, attr, None)))
            return tuple(values)

        if root == "dependency" and attr:
            # sample dependencies that touch any affected item
            ids = set(getattr(rec, "affected_item_ids", []) or [])
            if not ids:
                return tuple()
            values = []
            for d in getattr(state_obj, "dependencies", []):
                if not (d.predecessor_item_id in ids or d.successor_item_id in ids):
                    continue
                values.append(_snapshot(getattr(d, attr, None)))
            return tuple(values)

        # Fallback: attempt to get attribute directly
        if hasattr(state_obj, path):
            return (_snapshot(getattr(state_obj, path)),)
    except Exception:
        return tuple()

    return tuple()
