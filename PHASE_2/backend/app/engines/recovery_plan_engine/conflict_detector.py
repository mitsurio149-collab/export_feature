"""
Conflict Detection Engine for Recovery Plans

Determines if two recommendations conflict (touch same items/resources with incompatible actions).
Uses a static action compatibility matrix to keep detection deterministic and fast.
"""

from typing import Dict, Set, Tuple

from app.engines.recommendation_engine.models import Recommendation, RecommendationAction


class ConflictDetector:
    """
    Detects conflicts between recommendations in a recovery plan.
    
    Two recommendations conflict if they:
    1. Touch the same work item or resource, AND
    2. Have mutually exclusive action types
    
    Uses a static compatibility matrix to avoid fragile heuristics.
    """

    # Action compatibility matrix: (action1, action2) -> is_compatible
    # If actions are NOT in this dict, they are assumed compatible (most action pairs can coexist)
    # Only add entries where actions are MUTUALLY EXCLUSIVE
    ACTION_COMPATIBILITY_MATRIX: Dict[Tuple[RecommendationAction, RecommendationAction], bool] = {
        # Same action on same item is always a conflict
        # (e.g., cannot split an item twice, reassign an item twice to different resources)
        (RecommendationAction.SPLIT_ITEM, RecommendationAction.SPLIT_ITEM): False,
        (RecommendationAction.REASSIGN_ITEM, RecommendationAction.REASSIGN_ITEM): False,
        (RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT, RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT): False,
        
        # Mutually exclusive pairs on same item
        # Cannot both split and reassign the same item
        (RecommendationAction.SPLIT_ITEM, RecommendationAction.REASSIGN_ITEM): False,
        (RecommendationAction.REASSIGN_ITEM, RecommendationAction.SPLIT_ITEM): False,
        
        # Cannot both split and advance the same item
        (RecommendationAction.SPLIT_ITEM, RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT): False,
        (RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT, RecommendationAction.SPLIT_ITEM): False,
        
        # Cannot both reassign and advance the same item (advancing may require different resources)
        (RecommendationAction.REASSIGN_ITEM, RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT): False,
        (RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT, RecommendationAction.REASSIGN_ITEM): False,
        
        # Most other actions can coexist (e.g., resolving a blocker + reassigning an item that depends on it)
        # Add more incompatibilities here as discovered in testing
    }

    @classmethod
    def detect_conflict(cls, rec_a: Recommendation, rec_b: Recommendation) -> bool:
        """
        Detect if two recommendations conflict.
        
        Returns True if they conflict (cannot both be in the same plan),
        False if they are compatible.
        """
        # Check if they touch the same work items
        shared_items = set(rec_a.affected_item_ids) & set(rec_b.affected_item_ids)
        if not shared_items:
            # Check if they touch the same resources
            shared_resources = set(rec_a.affected_resource_ids) & set(rec_b.affected_resource_ids)
            if not shared_resources:
                # No overlap → no conflict
                return False
        
        # They share affected items or resources; check action compatibility
        action_pair = (rec_a.action_type, rec_b.action_type)
        
        # If the pair is explicitly in the matrix, use the defined compatibility
        if action_pair in cls.ACTION_COMPATIBILITY_MATRIX:
            return not cls.ACTION_COMPATIBILITY_MATRIX[action_pair]
        
        # If not in matrix, actions are compatible (default assumption)
        # This keeps the matrix small and maintainable
        return False

    @classmethod
    def detect_conflicts_in_plan(cls, plan: list) -> bool:
        """
        Detect if any pair of recommendations in a plan conflict.
        
        Returns True if any conflict exists, False if plan is conflict-free.
        """
        for i, rec_a in enumerate(plan):
            for rec_b in plan[i + 1 :]:
                if cls.detect_conflict(rec_a, rec_b):
                    return True
        return False

    @classmethod
    def get_conflicting_pairs(cls, rec_a: Recommendation, plan: list) -> list:
        """
        Return all recommendations in 'plan' that conflict with rec_a.
        """
        conflicts = []
        for rec in plan:
            if cls.detect_conflict(rec_a, rec):
                conflicts.append(rec)
        return conflicts
