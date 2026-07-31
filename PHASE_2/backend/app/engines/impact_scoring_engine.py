"""
Dependency Impact Scoring Engine

Scores risk of work items based on dependency graph and blockers.
"""

from typing import Dict, List, Set, Tuple
from pydantic import BaseModel

from app.domain.models import ProjectState, BlockerSeverity
from app.engines.dependency_engine import DependencyGraphEngine, DependencyDAG


class RiskScores(BaseModel):
    """Risk scores for work items due to dependencies and blockers."""
    
    # Per-item risk scores
    item_risk_scores: Dict[str, float]  # item_id -> risk (0.0-1.0)
    
    # Blocker cascade analysis
    items_impacted_by_blockers: Dict[str, List[str]]  # blocker_id -> [impacted_item_ids]
    cascade_depth_map: Dict[str, int]  # item_id -> max cascade depth from blockers
    
    # Risk by severity
    high_risk_items: List[str]  # Risk score >= 0.7
    medium_risk_items: List[str]  # 0.4 <= risk < 0.7
    low_risk_items: List[str]  # risk < 0.4
    
    # Sprint-level impact
    sprint_risk_by_blocker: Dict[str, Dict[int, float]]  # blocker_id -> {sprint_num -> impact}


# FIX bug-3 / bug-4: statuses that mean "this item is finished and cannot be at risk"
_DONE_STATUSES = {"COMPLETED", "DONE"}


def _is_done(work_item) -> bool:
    """Return True if the work item's status is a completed/done state."""
    raw = work_item.status.value if hasattr(work_item.status, "value") else str(work_item.status)
    return raw.upper() in _DONE_STATUSES


class ImpactScoringEngine:
    """Scores risk and impact from dependencies and blockers."""
    
    def __init__(self, project_state: ProjectState, dag: DependencyDAG):
        self.project_state = project_state
        self.dag = dag
        self.work_items = {wi.item_id: wi for wi in project_state.work_items}
        self.sprints = {s.sprint_id: s for s in project_state.sprints}
        self.blockers = project_state.blockers
        self.dep_engine = DependencyGraphEngine(project_state)
        
        # Severity weights
        self.severity_weight = {
            BlockerSeverity.CRITICAL: 1.0,
            BlockerSeverity.HIGH: 0.7,
            BlockerSeverity.MEDIUM: 0.4,
            BlockerSeverity.LOW: 0.1,
        }
    
    def score(self) -> RiskScores:
        """Compute risk scores for all work items."""
        
        # FIX bug-3: exclude completed/done items — they cannot be at risk.
        # Scoring them produces false positives when a finished item has high
        # out-degree (many things depended on it) or was previously blocked.
        item_risk_scores = {
            item_id: 0.0
            for item_id, wi in self.work_items.items()
            if not _is_done(wi)
        }
        
        # Score based on blockers
        blocker_impacts = self._score_blocker_impacts()
        for item_id, blocker_risk in blocker_impacts.items():
            if item_id in item_risk_scores:   # guard: skip completed items
                item_risk_scores[item_id] = max(item_risk_scores[item_id], blocker_risk)
        
        # Score based on dependency depth (items with many dependencies are riskier)
        dependency_depth_scores = self._score_dependency_depth()
        for item_id, depth_risk in dependency_depth_scores.items():
            if item_id in item_risk_scores:   # guard: skip completed items
                item_risk_scores[item_id] = max(item_risk_scores[item_id], depth_risk * 0.3)
        
        # Categorize by risk level
        high_risk = [item_id for item_id, score in item_risk_scores.items() if score >= 0.7]
        medium_risk = [item_id for item_id, score in item_risk_scores.items() if 0.4 <= score < 0.7]
        low_risk = [item_id for item_id, score in item_risk_scores.items() if score < 0.4]
        
        # Cascade analysis from blockers
        cascade_map, blocker_cascade = self._compute_blocker_cascade()
        
        # Sprint-level blocker impact
        sprint_impact = self._compute_sprint_blocker_impact(blocker_cascade)
        
        return RiskScores(
            item_risk_scores=item_risk_scores,
            items_impacted_by_blockers=blocker_cascade,
            cascade_depth_map=cascade_map,
            high_risk_items=sorted(high_risk),
            medium_risk_items=sorted(medium_risk),
            low_risk_items=sorted(low_risk),
            sprint_risk_by_blocker=sprint_impact,
        )
    
    def _score_blocker_impacts(self) -> Dict[str, float]:
        """Score risk from active blockers."""
        item_scores = {}
        
        for blocker in self.blockers:
            # Only score active blockers
            if blocker.actual_resolution_date:
                continue
            
            severity_weight = self.severity_weight.get(blocker.severity, 0.5)
            
            # Directly impacted items get full severity weight
            for item_id in blocker.impacted_item_ids:
                if item_id not in item_scores:
                    item_scores[item_id] = 0.0
                item_scores[item_id] = max(item_scores[item_id], severity_weight)
            
            # Downstream items get reduced weight
            for impacted_item_id in blocker.impacted_item_ids:
                downstream = self.dep_engine.get_all_successors(impacted_item_id, self.dag)
                for item_id in downstream:
                    if item_id not in item_scores:
                        item_scores[item_id] = 0.0
                    # Decay with distance (each level reduces by 50%)
                    downstream_weight = severity_weight * 0.5
                    item_scores[item_id] = max(item_scores[item_id], downstream_weight)
        
        return item_scores
    
    def _score_dependency_depth(self) -> Dict[str, float]:
        """Score risk based on dependency depth (in-degree and out-degree)."""
        scores = {}
        max_in_degree = max(self.dag.in_degree.values()) if self.dag.in_degree else 1
        max_out_degree = max(self.dag.out_degree.values()) if self.dag.out_degree else 1
        
        for item_id in self.work_items:
            in_deg = self.dag.in_degree.get(item_id, 0)
            out_deg = self.dag.out_degree.get(item_id, 0)
            
            # Normalize and combine
            in_score = (in_deg / max_in_degree) if max_in_degree > 0 else 0.0
            out_score = (out_deg / max_out_degree) if max_out_degree > 0 else 0.0
            
            # Items blocking many others are higher risk
            combined_score = (in_score * 0.3 + out_score * 0.7)
            scores[item_id] = combined_score
        
        return scores
    
    def _compute_blocker_cascade(self) -> Tuple[Dict[str, int], Dict[str, List[str]]]:
        """Compute cascade depth and impacted items for each blocker."""
        cascade_depth_map = {item_id: 0 for item_id in self.work_items}
        blocker_cascade = {}
        
        for blocker in self.blockers:
            # FIX bug-4: the original code ran BFS for *all* blockers including
            # resolved ones.  A blocker with actual_resolution_date=None on a
            # COMPLETED item (stale data) therefore populated cascade_depth_map
            # for that item, causing it to appear in the AT-RISK panel with a
            # "Directly blocked (BLK-xxx)" driver even though it was done.
            # Guard matches _score_blocker_impacts so cascade data is consistent
            # with which blockers are considered active.
            if blocker.actual_resolution_date:
                continue

            all_impacted = set(blocker.impacted_item_ids)
            
            # BFS to find all transitive impacts
            queue = list(blocker.impacted_item_ids)
            visited = set(queue)
            depth = 0
            
            while queue:
                next_queue = []
                for item_id in queue:
                    successors = self.dag.graph.get(item_id, [])
                    for succ in successors:
                        if succ not in visited:
                            visited.add(succ)
                            all_impacted.add(succ)
                            next_queue.append(succ)
                queue = next_queue
                if queue:
                    depth += 1
            
            blocker_cascade[blocker.blocker_id] = list(all_impacted)
            
            # Update cascade depth
            for item_id in all_impacted:
                cascade_depth_map[item_id] = max(cascade_depth_map[item_id], depth)
        
        return cascade_depth_map, blocker_cascade
    
    def _compute_sprint_blocker_impact(self, blocker_cascade: Dict[str, List[str]]) -> Dict[str, Dict[int, float]]:
        """Compute per-sprint blocker impact."""
        sprint_impact = {}
        
        for blocker in self.blockers:
            if blocker.actual_resolution_date:
                continue
            
            blocker_id = blocker.blocker_id
            impacted_items = blocker_cascade.get(blocker_id, [])
            sprint_impact[blocker_id] = {}
            
            severity_weight = self.severity_weight.get(blocker.severity, 0.5)
            
            # Determine which sprints are affected
            affected_sprints = set()
            for item_id in impacted_items:
                wi = self.work_items.get(item_id)
                if wi and wi.assigned_sprint:
                    # Find sprint number
                    for sprint in self.project_state.sprints:
                        if sprint.sprint_name == wi.assigned_sprint:
                            affected_sprints.add(sprint.sprint_number)
            
            # Assign impact to affected sprints
            for sprint_num in affected_sprints:
                # All items in this sprint get reduced effective capacity
                sprint_impact[blocker_id][sprint_num] = severity_weight * 0.5  # 50% of direct blocker weight
        
        return sprint_impact
