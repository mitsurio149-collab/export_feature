"""
Critical Path Analysis Engine

Identifies longest path through dependency DAG and slack times.
"""

from datetime import datetime
from typing import List, Dict, Tuple, Optional
from pydantic import BaseModel, Field

from app.domain.models import ProjectState, WorkItem, WorkItemStatus
from app.engines.dependency_engine import DependencyGraphEngine, DependencyDAG


class CriticalPathResult(BaseModel):
    """Results from critical path analysis."""
    
    # Critical path details
    critical_path: List[str]  # Sequence of item IDs on critical path
    critical_path_items: List[str]  # Items on critical path, preserved for backward compatibility
    critical_path_duration_hours: float  # Full duration using current_estimate_hrs
    critical_path_duration_hours_original: float  # Full original duration using estimated_effort_hrs
    critical_path_growth_hours: float  # Current minus original estimates for critical path items
    critical_path_growth_percent: float  # Growth percent relative to original critical path duration
    critical_path_duration_days: float
    critical_path_remaining_hours: float  # Remaining effort on critical path (using remaining_effort_hrs)
    
    # Slack analysis
    item_slack_map: Dict[str, float]  # item_id -> slack hours
    items_on_critical_path: List[str]  # Items with zero slack
    
    # Risk assessment
    high_risk_items: List[str]  # Items on critical path
    num_critical_paths: int  # Multiple paths may exist with same length

    # Calendar-anchoring diagnostics (see _forward_pass real-time-floor note)
    calendar_shift_hours: float = 0.0  # How much the zero-anchored network was pushed forward by real elapsed time
    calendar_floored_items: List[str] = Field(default_factory=list)  # Items whose earliest_start was pushed by the real-time floor


class CriticalPathEngine:
    """Identifies critical path and slack times in project network."""
    
    def __init__(self, project_state: ProjectState, dag: DependencyDAG):
        self.project_state = project_state
        self.dag = dag
        self.work_items = {wi.item_id: wi for wi in project_state.work_items}
        self.dep_engine = DependencyGraphEngine(project_state)

        # Real-time floor: hours between project start and "today" (or a
        # pinned as_of_date). Used by _forward_pass so a not-yet-complete
        # item can never be scheduled as if it could still start back at
        # project day zero -- if the calendar has already moved past a
        # sprint's planned start and the item isn't done, the earliest it
        # could possibly still start is "now", not "day 0". Without this,
        # a stalled Sprint 6/7/8 item with no predecessors was treated by
        # the zero-anchored network exactly like a healthy on-time item,
        # and its lateness never propagated to successors.
        project_start = project_state.project_info.forecast_anchor_date()
        as_of = project_state.project_info.effective_as_of_date()
        self._real_time_floor_hours = max(
            0.0, (as_of - project_start).total_seconds() / 3600.0
        )
        self._sprints_by_name = {s.sprint_name: s for s in project_state.sprints}
        self.calendar_floored_items: List[str] = []
    
    def analyze(self) -> CriticalPathResult:
        """Perform critical path analysis."""
        
        if self.dag.has_cycles:
            # Cannot compute critical path if cycles exist - must fail loudly
            cycle_items = ", ".join(self.dag.cycle_nodes[:5])
            if len(self.dag.cycle_nodes) > 5:
                cycle_items += f", ... ({len(self.dag.cycle_nodes)} total)"
            raise ValueError(
                f"CriticalPathEngine cannot analyze project with dependency cycles. "
                f"Cyclic items: {cycle_items}. "
                f"Review dependencies and break circular relationships."
            )
        
        # Baseline forward pass (no real-time floor) — zero-anchored project end.
        # Diffing against the floored pass gives true network displacement.
        baseline_finish = self._forward_pass_baseline()
        baseline_end = max(baseline_finish.values()) if baseline_finish else 0.0

        # Compute earliest start/finish times (forward pass with real-time floor)
        earliest_start, earliest_finish = self._forward_pass()
        
        # Compute latest start/finish times (backward pass)
        latest_start, latest_finish = self._backward_pass(earliest_finish)
        
        # Compute slack (float) for each node
        slack_map = self._compute_slack(earliest_start, earliest_finish, latest_start, latest_finish)
        
        # Find critical path (path with items having zero slack)
        critical_items = [item_id for item_id, slack in slack_map.items() if abs(slack) < 0.01]
        critical_path = self._extract_critical_path(critical_items)
        
        # Compute critical path duration using current estimates (post-scope-change)
        cp_duration_hours = 0.0
        cp_duration_hours_original = 0.0
        cp_remaining_hours = 0.0
        for item_id in critical_path:
            work_item = self.work_items.get(item_id)
            if work_item is None:
                raise ValueError(
                    f"CriticalPathEngine integrity error: "
                    f"Critical path item '{item_id}' exists in DAG "
                    f"but not in ProjectState.work_items. "
                    f"This indicates referential integrity violation."
                )
            cp_duration_hours += work_item.current_estimate_hrs
            cp_duration_hours_original += work_item.estimated_effort_hrs
            cp_remaining_hours += max(0.0, work_item.remaining_effort_hrs)
        
        # Estimate working days (using avg 8 hours/day)
        cp_duration_days = cp_duration_hours / 8.0
        cp_growth_hours = cp_duration_hours - cp_duration_hours_original
        cp_growth_percent = (
            (cp_growth_hours / cp_duration_hours_original) * 100.0
            if cp_duration_hours_original else 0.0
        )
        
        # Count parallel critical paths (approximation)
        num_cp = self._count_critical_paths(slack_map)

        return CriticalPathResult(
            critical_path=critical_path,
            critical_path_items=critical_path,
            critical_path_duration_hours=cp_duration_hours,
            critical_path_duration_hours_original=cp_duration_hours_original,
            critical_path_growth_hours=cp_growth_hours,
            critical_path_growth_percent=cp_growth_percent,
            critical_path_duration_days=cp_duration_days,
            critical_path_remaining_hours=cp_remaining_hours,
            item_slack_map=slack_map,
            items_on_critical_path=critical_items,
            high_risk_items=critical_items,  # Critical path items are high risk
            num_critical_paths=num_cp,
            calendar_shift_hours=max(
                0.0,
                (max(earliest_finish.values()) if earliest_finish else 0.0) - baseline_end
            ),
            calendar_floored_items=sorted(set(self.calendar_floored_items)),
        )
    
    def _forward_pass_baseline(self) -> Dict[str, float]:
        """Forward pass with NO real-time floor — zero-anchored project end.
        Diff against floored pass to get true network displacement."""
        earliest_finish: Dict[str, float] = {}
        earliest_start: Dict[str, float] = {}
        for node in self.dag.topological_order:
            preds = self.dag.reverse_graph.get(node, [])
            if not preds:
                earliest_start[node] = 0.0
            else:
                max_pred = 0.0
                for pred in preds:
                    lag_h = self.dag.lag_days_map.get((pred, node), 0) * 8.0
                    max_pred = max(max_pred, earliest_finish.get(pred, 0.0) + lag_h)
                earliest_start[node] = max_pred
            wi = self.work_items.get(node)
            duration = wi.current_estimate_hrs if wi else 0.0
            earliest_finish[node] = earliest_start[node] + duration
        return earliest_finish

    def _forward_pass(self) -> Tuple[Dict[str, float], Dict[str, float]]:
        """Compute earliest start/finish times using topological sort."""
        earliest_start = {}
        earliest_finish = {}
        
        # Process nodes in topological order
        for node in self.dag.topological_order:
            # Earliest start is max of predecessors' finish times
            preds = self.dag.reverse_graph.get(node, [])
            
            if not preds:
                # Source node starts at time 0
                earliest_start[node] = 0.0
            else:
                # Start after all predecessors finish + lag
                max_pred_finish = 0.0
                for pred in preds:
                    lag = self.dag.lag_days_map.get((pred, node), 0)
                    lag_hours = lag * 8.0  # Convert to hours
                    pred_finish = earliest_finish.get(pred, 0.0) + lag_hours
                    max_pred_finish = max(max_pred_finish, pred_finish)
                
                earliest_start[node] = max_pred_finish
            
            # Finish time = start + duration (using current estimates for forecasting)
            work_item = self.work_items.get(node)
            if work_item is None:
                raise ValueError(
                    f"CriticalPathEngine integrity error in _forward_pass: "
                    f"Node '{node}' in topological order "
                    f"but not in ProjectState.work_items. "
                    f"This indicates DAG construction error."
                )

            # Real-time floor: a not-yet-complete item can never have an
            # earliest_start earlier than "now" (self._real_time_floor_hours).
            # This only changes anything when the predecessor-derived start
            # is ALREADY in the past relative to today -- i.e. the item is
            # genuinely stalled/late -- so it does not distort items that
            # are legitimately scheduled for the future by their real
            # dependency chain. This is what makes a stalled Sprint 6 item
            # (or a late-starting Sprint 7/8 item) push its own finish time,
            # and therefore every downstream successor's earliest_start,
            # forward automatically instead of silently starting the whole
            # network fresh at project day zero.
            is_complete = (
                work_item.status in (WorkItemStatus.COMPLETED, WorkItemStatus.DONE)
                or (isinstance(work_item.status, str) and work_item.status in (
                    WorkItemStatus.COMPLETED.value, WorkItemStatus.DONE.value,
                ))
            )
            if not is_complete and earliest_start[node] < self._real_time_floor_hours:
                earliest_start[node] = self._real_time_floor_hours
                self.calendar_floored_items.append(node)

            duration = work_item.current_estimate_hrs
            earliest_finish[node] = earliest_start[node] + duration
        
        return earliest_start, earliest_finish
    
    def _backward_pass(self, earliest_finish: Dict[str, float]) -> Tuple[Dict[str, float], Dict[str, float]]:
        """Compute latest start/finish times working backward."""
        latest_start = {}
        latest_finish = {}
        
        # Find project completion time (max earliest_finish)
        project_completion = max(earliest_finish.values()) if earliest_finish else 0.0
        
        # Process nodes in reverse topological order
        for node in reversed(self.dag.topological_order):
            succs = self.dag.graph.get(node, [])
            
            if not succs:
                # Sink node must finish by project completion
                latest_finish[node] = project_completion
            else:
                # Latest finish = min of successors' start times - lag
                min_succ_start = float('inf')
                for succ in succs:
                    lag = self.dag.lag_days_map.get((node, succ), 0)
                    lag_hours = lag * 8.0
                    succ_start = latest_start.get(succ, project_completion)
                    min_succ_start = min(min_succ_start, succ_start - lag_hours)
                
                latest_finish[node] = min_succ_start if min_succ_start != float('inf') else project_completion
            
            # Latest start = finish - duration (using current estimates for forecasting)
            work_item = self.work_items.get(node)
            if work_item is None:
                raise ValueError(
                    f"CriticalPathEngine integrity error in _backward_pass: "
                    f"Node '{node}' in topological order "
                    f"but not in ProjectState.work_items. "
                    f"This indicates DAG construction error."
                )
            duration = work_item.current_estimate_hrs
            latest_start[node] = latest_finish[node] - duration
        
        return latest_start, latest_finish
    
    @staticmethod
    def _compute_slack(
        earliest_start: Dict[str, float],
        earliest_finish: Dict[str, float],
        latest_start: Dict[str, float],
        latest_finish: Dict[str, float],
    ) -> Dict[str, float]:
        """Compute slack (float) for each node."""
        slack = {}
        
        for node in earliest_start:
            # Slack = Latest_start - Earliest_start (or Latest_finish - Earliest_finish)
            item_slack = latest_start.get(node, 0.0) - earliest_start.get(node, 0.0)
            slack[node] = max(0.0, item_slack)  # Slack cannot be negative
        
        return slack
    
    def _extract_critical_path(self, critical_items: List[str]) -> List[str]:
        """Extract an ordered critical path from critical items."""
        if not critical_items:
            return []
        
        # Build subgraph of only critical items
        critical_set = set(critical_items)
        
        # Find source node(s) (no predecessors in critical set)
        sources = [
            item for item in critical_items
            if not any(pred in critical_set for pred in self.dag.reverse_graph.get(item, []))
        ]
        
        if not sources:
            return sorted(critical_items)  # Fallback
        
        # DFS from first source to build path
        path = []
        visited = set()
        
        def dfs(node):
            if node in visited or node not in critical_set:
                return
            visited.add(node)
            path.append(node)
            
            for succ in self.dag.graph.get(node, []):
                if succ in critical_set and succ not in visited:
                    dfs(succ)
        
        dfs(sources[0])
        return path
    
    @staticmethod
    def _count_critical_paths(slack_map: Dict[str, float]) -> int:
        """Estimate number of critical paths."""
        critical_count = sum(1 for slack in slack_map.values() if abs(slack) < 0.01)
        
        # Rough heuristic: if many items on critical path, likely multiple paths
        if critical_count > 10:
            return 3
        elif critical_count > 5:
            return 2
        else:
            return 1
