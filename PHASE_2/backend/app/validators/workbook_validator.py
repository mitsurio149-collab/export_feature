"""
Workbook Validator

Validates ProjectState against business rules and referential integrity.
"""

from typing import List, Dict, Any
from pydantic import ValidationError

from app.domain.models import ProjectState, SprintStatus


class ValidationError(Exception):
    """Base validation error."""
    pass


class ValidationWarning:
    """Non-critical validation issue."""
    
    def __init__(self, category: str, message: str, details: Dict[str, Any] = None):
        self.category = category
        self.message = message
        self.details = details or {}
    
    def to_dict(self) -> Dict:
        return {
            "category": self.category,
            "message": self.message,
            "details": self.details,
        }


class WorkbookValidator:
    """
    Validates ProjectState for:
    1. Structural integrity (all sheets parsed correctly)
    2. Referential integrity (all references are valid)
    3. Business rules (dates, estimates, percentages, etc.)
    """
    
    def __init__(self, project_state: ProjectState):
        self.project_state = project_state
        self.warnings: List[ValidationWarning] = []
    
    def validate(self) -> List[ValidationWarning]:
        """
        Run all validations. Return list of warnings.
        
        Raises:
            ValidationError: If critical validation fails
        """
        self.warnings.clear()
        
        # Run validation suites
        self._validate_project_info()
        self._validate_structural_integrity()
        self._validate_referential_integrity()
        self._validate_business_rules()
        
        return self.warnings
    
    # ─── Structural Validation ───────────────────────────────────────────────
    
    def _validate_project_info(self) -> None:
        """Validate project info structure."""
        pi = self.project_state.project_info
        
        # Project name must be non-empty
        if not pi.project_name or not pi.project_name.strip():
            raise ValidationError("Project name cannot be empty")
        
        # Dates must be valid
        if pi.start_date >= pi.target_end_date:
            raise ValidationError(
                f"Target end date ({pi.target_end_date}) must be after "
                f"start date ({pi.start_date})"
            )

        if pi.release_date is not None:
            if pi.release_date < pi.start_date:
                raise ValidationError(
                    f"Release date ({pi.release_date}) must be on or after start date ({pi.start_date})"
                )
            if pi.release_date > pi.target_end_date:
                raise ValidationError(
                    f"Release date ({pi.release_date}) must be on or before target end date ({pi.target_end_date})"
                )
        
        # Sprint duration must be reasonable
        if pi.sprint_duration_days < 1 or pi.sprint_duration_days > 30:
            raise ValidationError(
                f"Sprint duration must be 1-30 days, got {pi.sprint_duration_days}"
            )
    
    def _validate_structural_integrity(self) -> None:
        """Validate all collections have required elements."""
        if not self.project_state.team:
            raise ValidationError("Project must have at least one team member")
        
        if not self.project_state.sprints:
            raise ValidationError("Project must have at least one sprint")
        
        if not self.project_state.work_items:
            raise ValidationError("Project must have at least one work item")
    
    # ─── Referential Integrity ───────────────────────────────────────────────
    
    def _validate_referential_integrity(self) -> None:
        """Validate all references point to existing entities."""
        # Build lookup indices
        resource_map = {r.resource_id: r for r in self.project_state.team}
        resource_names = {r.name: r.resource_id for r in self.project_state.team}
        sprint_map = {s.sprint_id: s for s in self.project_state.sprints}
        sprint_names = {s.sprint_name: s.sprint_id for s in self.project_state.sprints}
        work_item_map = {w.item_id: w for w in self.project_state.work_items}
        
        # Validate work items reference valid sprints and resources
        for wi in self.project_state.work_items:
            # Check sprint exists
            if wi.assigned_sprint not in sprint_map and wi.assigned_sprint not in sprint_names:
                raise ValidationError(
                    f"Work item {wi.item_id} references non-existent sprint '{wi.assigned_sprint}'"
                )
            
            # Check resource exists (if assigned)
            if wi.assigned_resource:
                if wi.assigned_resource not in resource_names and wi.assigned_resource not in resource_map:
                    self.warnings.append(ValidationWarning(
                        "referential",
                        f"Work item {wi.item_id} assigned to non-existent resource '{wi.assigned_resource}'",
                        {"item_id": wi.item_id, "resource": wi.assigned_resource}
                    ))
        
        # Validate dependencies reference valid work items
        for dep in self.project_state.dependencies:
            if dep.predecessor_item_id not in work_item_map:
                raise ValidationError(
                    f"Dependency {dep.dependency_id} references "
                    f"non-existent predecessor '{dep.predecessor_item_id}'"
                )
            if dep.successor_item_id not in work_item_map:
                raise ValidationError(
                    f"Dependency {dep.dependency_id} references "
                    f"non-existent successor '{dep.successor_item_id}'"
                )
        
        # Validate blockers reference valid work items
        for blocker in self.project_state.blockers:
            if blocker.related_item_id not in work_item_map:
                raise ValidationError(
                    f"Blocker {blocker.blocker_id} references "
                    f"non-existent work item '{blocker.related_item_id}'"
                )
            for impacted_id in blocker.impacted_item_ids:
                if impacted_id not in work_item_map:
                    raise ValidationError(
                        f"Blocker {blocker.blocker_id} references "
                        f"non-existent impacted item '{impacted_id}'"
                    )
        
        # Validate sprint actuals reference valid sprints
        for actual in self.project_state.actuals:
            if actual.sprint_id not in sprint_map:
                raise ValidationError(
                    f"Sprint actual references non-existent sprint '{actual.sprint_id}'"
                )
    
    # ─── Business Rule Validation ────────────────────────────────────────────
    
    def _validate_business_rules(self) -> None:
        """Validate business logic and constraints."""
        # Sprint dates should not overlap
        sorted_sprints = sorted(self.project_state.sprints, key=lambda s: s.start_date)
        for i in range(len(sorted_sprints) - 1):
            current = sorted_sprints[i]
            next_sprint = sorted_sprints[i + 1]
            if current.end_date > next_sprint.start_date:
                self.warnings.append(ValidationWarning(
                    "business_rule",
                    f"Sprint {current.sprint_name} end date overlaps with {next_sprint.sprint_name}",
                    {"sprint1": current.sprint_id, "sprint2": next_sprint.sprint_id}
                ))
        
        # Work item estimates should be positive
        for wi in self.project_state.work_items:
            if wi.estimated_effort_hrs <= 0:
                raise ValidationError(
                    f"Work item {wi.item_id} has invalid estimated effort: {wi.estimated_effort_hrs}"
                )
            if wi.current_estimate_hrs <= 0:
                raise ValidationError(
                    f"Work item {wi.item_id} has invalid current estimate: {wi.current_estimate_hrs}"
                )
        
        # Progress percentage should be 0-1
        for wi in self.project_state.work_items:
            if wi.progress_pct < 0.0 or wi.progress_pct > 1.0:
                raise ValidationError(
                    f"Work item {wi.item_id} has invalid progress: {wi.progress_pct}"
                )
        
        # Resource allocation and availability should be 0-1
        for resource in self.project_state.team:
            if resource.allocation_pct < 0.0 or resource.allocation_pct > 1.0:
                raise ValidationError(
                    f"Resource {resource.name} has invalid allocation: {resource.allocation_pct}"
                )
            if resource.availability_pct < 0.0 or resource.availability_pct > 1.0:
                raise ValidationError(
                    f"Resource {resource.name} has invalid availability: {resource.availability_pct}"
                )
        
        # Sprint planned velocity should be positive (or 0 for not-started sprints)
        for sprint in self.project_state.sprints:
            if sprint.planned_velocity_hrs < 0:
                raise ValidationError(
                    f"Sprint {sprint.sprint_name} has negative velocity: {sprint.planned_velocity_hrs}"
                )
            if sprint.planned_velocity_hrs == 0 and sprint.status in (
                SprintStatus.NOT_STARTED, SprintStatus.IN_PROGRESS
            ):
                # 0 velocity is acceptable for not-started or currently active sprints
                self.warnings.append(ValidationWarning(
                    "business_rule",
                    f"Sprint {sprint.sprint_name} has zero planned velocity (may still be in progress)",
                    {"sprint_id": sprint.sprint_id, "status": sprint.status.value}
                ))
            elif sprint.planned_velocity_hrs == 0:
                raise ValidationError(
                    f"Sprint {sprint.sprint_name} ({sprint.status.value}) has zero velocity"
                )
        
        # Lag days should be non-negative
        for dep in self.project_state.dependencies:
            if dep.lag_days < 0:
                raise ValidationError(
                    f"Dependency {dep.dependency_id} has negative lag days: {dep.lag_days}"
                )
        
        # Check for duplicate IDs
        item_ids = [wi.item_id for wi in self.project_state.work_items]
        if len(item_ids) != len(set(item_ids)):
            raise ValidationError("Duplicate work item IDs found")
        
        resource_ids = [r.resource_id for r in self.project_state.team]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValidationError("Duplicate resource IDs found")
        
        sprint_ids = [s.sprint_id for s in self.project_state.sprints]
        if len(sprint_ids) != len(set(sprint_ids)):
            raise ValidationError("Duplicate sprint IDs found")
        
        # Warn about underutilized resources
        for resource in self.project_state.team:
            effective_util = resource.allocation_pct * resource.availability_pct
            if effective_util < 0.60:
                self.warnings.append(ValidationWarning(
                    "utilization",
                    f"Resource {resource.name} is underutilized ({effective_util:.0%})",
                    {"resource_id": resource.resource_id, "utilization": effective_util}
                ))
        
        # Check for impossible sprint durations vs working days
        for sprint in self.project_state.sprints:
            # days_between doesn't include both endpoints, so add 1 to get inclusive count
            calendar_days = (sprint.end_date - sprint.start_date).days + 1
            if sprint.working_days > calendar_days:
                raise ValidationError(
                    f"Sprint {sprint.sprint_name} has {sprint.working_days} working days "
                    f"but only {calendar_days} calendar days"
                )
