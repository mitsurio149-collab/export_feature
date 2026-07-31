"""
Dependency Graph Engine

Builds and analyzes DAG structure from dependencies.
"""

from typing import List, Dict, Set, Tuple, Optional
from pydantic import BaseModel
from collections import defaultdict, deque

from app.domain.models import ProjectState, Dependency


class DependencyDAG(BaseModel):
    """Directed acyclic graph of work item dependencies."""
    
    # Adjacency lists
    graph: Dict[str, List[str]]  # item_id -> [successor_ids]
    reverse_graph: Dict[str, List[str]]  # item_id -> [predecessor_ids]
    
    # Metadata
    all_nodes: Set[str]
    has_cycles: bool
    cycle_nodes: List[str]  # If cycles detected
    
    # Paths
    transitive_closure: Dict[str, Set[str]]  # item_id -> all reachable items
    in_degree: Dict[str, int]  # number of predecessors
    out_degree: Dict[str, int]  # number of successors
    
    # Levels (topological)
    topological_order: List[str]  # Items ordered by dependency level
    item_levels: Dict[str, int]  # item_id -> topological level
    
    # Lag information
    lag_days_map: Dict[Tuple[str, str], int]  # (pred, succ) -> lag_days


class DependencyGraphEngine:
    """Builds and analyzes project dependency DAG."""
    
    def __init__(self, project_state: ProjectState):
        self.project_state = project_state
        self.dependencies = project_state.dependencies
        self.work_items = {wi.item_id: wi for wi in project_state.work_items}
    
    def build_dag(self) -> DependencyDAG:
        """Build and analyze the dependency DAG."""
        
        # Initialize graph structures
        graph = defaultdict(list)
        reverse_graph = defaultdict(list)
        lag_days_map = {}
        all_nodes = set(self.work_items.keys())
        
        # Build adjacency lists from dependencies
        for dep in self.dependencies:
            pred = dep.predecessor_item_id
            succ = dep.successor_item_id
            
            # Only add edges for items that exist in work_items
            if pred in all_nodes and succ in all_nodes:
                graph[pred].append(succ)
                reverse_graph[succ].append(pred)
                lag_days_map[(pred, succ)] = dep.lag_days
        
        # Convert to regular dicts
        graph = dict(graph)
        reverse_graph = dict(reverse_graph)
        
        # Ensure all nodes are in both graphs (even isolated ones)
        for node in all_nodes:
            if node not in graph:
                graph[node] = []
            if node not in reverse_graph:
                reverse_graph[node] = []
        
        # Detect cycles using DFS
        has_cycles, cycle_nodes = self._detect_cycles(graph)
        
        # Compute transitive closure (all reachable nodes)
        transitive_closure = self._compute_transitive_closure(graph)
        
        # Compute degrees
        in_degree = {node: len(reverse_graph[node]) for node in all_nodes}
        out_degree = {node: len(graph[node]) for node in all_nodes}
        
        # Topological sort
        topological_order = self._topological_sort(graph, reverse_graph)
        item_levels = {node: idx for idx, node in enumerate(topological_order)}
        
        return DependencyDAG(
            graph=graph,
            reverse_graph=reverse_graph,
            all_nodes=all_nodes,
            has_cycles=has_cycles,
            cycle_nodes=cycle_nodes,
            transitive_closure=transitive_closure,
            in_degree=in_degree,
            out_degree=out_degree,
            topological_order=topological_order,
            item_levels=item_levels,
            lag_days_map=lag_days_map,
        )
    
    @staticmethod
    def _detect_cycles(graph: Dict[str, List[str]]) -> Tuple[bool, List[str]]:
        """Detect cycles in graph using DFS."""
        visited = set()
        rec_stack = set()
        cycle_nodes = []
        
        def dfs(node):
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        cycle_nodes.append(node)
                        return True
                elif neighbor in rec_stack:
                    cycle_nodes.append(node)
                    return True
            
            rec_stack.remove(node)
            return False
        
        for node in graph:
            if node not in visited:
                if dfs(node):
                    return True, list(set(cycle_nodes))
        
        return False, []
    
    @staticmethod
    def _compute_transitive_closure(graph: Dict[str, List[str]]) -> Dict[str, Set[str]]:
        """Compute transitive closure using BFS from each node."""
        closure = {}
        
        for start_node in graph:
            reachable = set()
            queue = deque(graph.get(start_node, []))
            visited = set([start_node])
            
            while queue:
                node = queue.popleft()
                if node in visited:
                    continue
                
                visited.add(node)
                reachable.add(node)
                queue.extend(graph.get(node, []))
            
            closure[start_node] = reachable
        
        return closure
    
    @staticmethod
    def _topological_sort(
        graph: Dict[str, List[str]], 
        reverse_graph: Dict[str, List[str]]
    ) -> List[str]:
        """Kahn's algorithm for topological sorting."""
        
        # Copy in-degrees
        in_degree = {node: len(reverse_graph[node]) for node in graph}
        
        # Queue of nodes with no incoming edges
        queue = deque([node for node in graph if in_degree[node] == 0])
        result = []
        
        while queue:
            node = queue.popleft()
            result.append(node)
            
            # For each successor, reduce in-degree
            for successor in graph.get(node, []):
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)
        
        # If we processed all nodes, no cycle
        # Otherwise append remaining (cyclic) nodes
        remaining = [n for n, d in in_degree.items() if d > 0]
        result.extend(remaining)
        
        return result
    
    def get_predecessors(self, item_id: str, dag: DependencyDAG) -> List[str]:
        """Get all direct predecessors of an item."""
        return dag.reverse_graph.get(item_id, [])
    
    def get_successors(self, item_id: str, dag: DependencyDAG) -> List[str]:
        """Get all direct successors of an item."""
        return dag.graph.get(item_id, [])
    
    def get_all_predecessors(self, item_id: str, dag: DependencyDAG) -> Set[str]:
        """Get all transitive predecessors (all items that must complete first)."""
        if item_id not in dag.reverse_graph:
            return set()
        
        all_preds = set()
        queue = deque(dag.reverse_graph[item_id])
        
        while queue:
            pred = queue.popleft()
            if pred in all_preds:
                continue
            all_preds.add(pred)
            queue.extend(dag.reverse_graph.get(pred, []))
        
        return all_preds
    
    def get_all_successors(self, item_id: str, dag: DependencyDAG) -> Set[str]:
        """Get all transitive successors (all items blocked by this item)."""
        if item_id not in dag.graph:
            return set()
        
        all_succs = set()
        queue = deque(dag.graph[item_id])
        
        while queue:
            succ = queue.popleft()
            if succ in all_succs:
                continue
            all_succs.add(succ)
            queue.extend(dag.graph.get(succ, []))
        
        return all_succs
