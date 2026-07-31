"""API request/response models for Phase 2 endpoints."""

from typing import Dict, List, Tuple
from datetime import datetime
from pydantic import BaseModel


class MetricsResponse(BaseModel):
    """Response for GET /metrics endpoint."""
    session_id: str
    project_name: str
    
    # Completion
    total_items: int
    completed_items: int
    in_progress_items: int
    blocked_items: int
    completion_pct: float
    
    # Effort
    total_effort_hours: float
    remaining_effort_hours: float
    completed_effort_hours: float
    
    # Velocity
    planned_total_velocity: float
    actual_avg_velocity: float
    velocity_variance: float
    
    # Resources
    team_size: int
    avg_allocation_pct: float
    avg_availability_pct: float
    underutilized_count: int
    
    # Risk
    active_blocker_count: int
    blocker_velocity_impact: float  # Estimated fractional velocity reduction using complementary probability; range [0.0, 1.0), with diminishing returns across multiple active blockers.
    
    # Schedule
    current_sprint_number: int
    completed_sprints: int
    
    # Dependencies
    dependency_count: int
    expected_spillover_items: int


class CriticalPathItem(BaseModel):
    """Detailed information for a work item on the critical path."""
    item_id: str
    name: str
    effort_hours: float
    remaining_hours: float = 0.0
    float_hours: float
    sprint_id: str
    status: str = ""
    assigned_resource: str = ""
    is_blocked: bool = False
    blocking_count: int = 0    # downstream items this node gates
    depends_on_count: int = 0  # upstream items that must finish first
    blocker_ids: List[str] = []
    progress_pct: float = 0.0
    # FIX bug-1 / bug-2: predecessor and successor label lists so the UI can
    # show "WI-045 HSM Key Management…" instead of "1 task must finish first".
    depends_on_labels: List[str] = []   # ["WI-045 HSM Key Management & Certificate Provisioning", …]
    blocking_labels: List[str] = []     # ["WI-057 Manifest Validation & Signature Verification", …]


class DependenciesResponse(BaseModel):
    """Response for GET /dependencies endpoint."""
    session_id: str
    project_name: str
    
    # DAG structure
    total_items: int
    total_dependencies: int
    has_cycles: bool
    
    # Critical path
    critical_path: List[str]
    critical_path_items: List[str]
    critical_path_details: List[CriticalPathItem]
    critical_path_duration_hours: float
    critical_path_duration_hours_original: float
    critical_path_growth_hours: float
    critical_path_growth_percent: float
    critical_path_duration_days: float
    critical_path_item_count: int
    total_work_items: int
    total_float_hours: float
    
    # Risk assessment
    high_risk_items: List[str]
    medium_risk_items: List[str]
    low_risk_items: List[str]
    high_risk_item_details: List[Dict] = []  # Enriched per-item risk breakdown with drivers
    
    # Blocker impact
    active_blockers: List[str]
    items_blocked: List[str]
    
    # Slack analysis
    zero_slack_items: List[str]  # Items on critical path
    num_critical_paths: int = 1  # Number of parallel critical paths of equal length


class SpilloverResponse(BaseModel):
    """Response for GET /spillover endpoint."""
    session_id: str
    project_name: str
    
    # High-risk items
    high_spillover_risk_items: List[str]
    high_risk_count: int
    
    # Per-sprint predictions
    predicted_spillover_by_sprint: Dict[int, float]
    confidence_intervals: Dict[int, Tuple[float, float]]
    
    # Capacity analysis
    sprint_utilization_pct: Dict[int, float]
    
    # Historical patterns
    historical_carryover_rate: float
    historical_carryover_std_dev: float
    
    # Summary
    total_expected_spillover: float
    risk_level: str  # "Low", "Medium", "High"
