"""
Unit Tests for Phase 1 - Backend Foundation & Ingestion

Tests:
- Workbook parser
- Validator
- Upload endpoint
"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta
from pydantic import ValidationError

from app.parsers import WorkbookParser, WorkbookParseError
from app.validators import WorkbookValidator, ValidationError as ValidatorError
from app.storage import SessionStore
from app.domain.models import (
    ProjectInfo,
    Resource,
    Sprint,
    WorkItem,
    Dependency,
    Blocker,
    SprintActual,
    ProjectState,
    SkillLevel,
    Priority,
    WorkItemStatus,
    SprintStatus,
    BlockerStatus,
)


# ──────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_project_info() -> ProjectInfo:
    """Create sample ProjectInfo."""
    return ProjectInfo(
        project_name="Test Project",
        sponsor="Test Sponsor",
        business_unit="Test BU",
        project_manager="Test PM",
        start_date=datetime(2025, 1, 20),
        target_end_date=datetime(2025, 5, 11),
        sprint_duration_days=14,
        methodology="Agile Scrum",
        customer="Test Customer",
        status="Active",
    )


@pytest.fixture
def sample_resources() -> list:
    """Create sample resources."""
    return [
        Resource(
            resource_id="john_doe",
            name="John Doe",
            role="Backend Engineer",
            primary_skill="Python",
            secondary_skill="Docker",
            skill_level=SkillLevel.SENIOR,
            allocation_pct=1.0,
            availability_pct=1.0,
        ),
        Resource(
            resource_id="jane_smith",
            name="Jane Smith",
            role="Frontend Engineer",
            primary_skill="React",
            skill_level=SkillLevel.ADVANCED,
            allocation_pct=0.8,
            availability_pct=0.9,
        ),
    ]


@pytest.fixture
def sample_sprints() -> list:
    """Create sample sprints."""
    base_date = datetime(2025, 1, 20)
    return [
        Sprint(
            sprint_id="SPR-1",
            sprint_name="Sprint 1",
            sprint_number=1,
            start_date=base_date,
            end_date=base_date + timedelta(days=14),
            working_days=10,
            sprint_goal="Setup infrastructure",
            status=SprintStatus.COMPLETED,
            planned_velocity_hrs=160,
            carryover_count=0,
        ),
        Sprint(
            sprint_id="SPR-2",
            sprint_name="Sprint 2",
            sprint_number=2,
            start_date=base_date + timedelta(days=15),
            end_date=base_date + timedelta(days=29),
            working_days=10,
            sprint_goal="Implement core features",
            status=SprintStatus.IN_PROGRESS,
            planned_velocity_hrs=160,
            carryover_count=1,
        ),
    ]


@pytest.fixture
def sample_work_items() -> list:
    """Create sample work items."""
    return [
        WorkItem(
            item_id="WI-001",
            title="Setup CI/CD pipeline",
            work_type="Task",
            assigned_sprint="Sprint 1",
            assigned_resource="john_doe",
            required_skill="Python",
            priority=Priority.HIGH,
            estimated_effort_hrs=40,
            current_estimate_hrs=40,
            actual_effort_hrs=45,
            remaining_effort_hrs=0,
            progress_pct=1.0,
            status=WorkItemStatus.DONE,
        ),
        WorkItem(
            item_id="WI-002",
            title="Design database schema",
            work_type="Feature",
            assigned_sprint="Sprint 2",
            assigned_resource="jane_smith",
            required_skill="SQL",
            priority=Priority.CRITICAL,
            estimated_effort_hrs=60,
            current_estimate_hrs=60,
            actual_effort_hrs=0,
            remaining_effort_hrs=60,
            progress_pct=0.0,
            status=WorkItemStatus.NOT_STARTED,
        ),
    ]


@pytest.fixture
def sample_project_state(
    sample_project_info, sample_resources, sample_sprints, sample_work_items
) -> ProjectState:
    """Create sample ProjectState."""
    return ProjectState(
        project_id="test-project-1",
        project_info=sample_project_info,
        team=sample_resources,
        sprints=sample_sprints,
        work_items=sample_work_items,
        dependencies=[],
        blockers=[],
        actuals=[],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Parser Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestWorkbookParser:
    """Test workbook parser."""
    
    def test_parser_requires_file_path(self):
        """Parser should accept file path."""
        parser = WorkbookParser("/fake/path.xlsx")
        assert parser.file_path == "/fake/path.xlsx"
    
    def test_parser_with_demo_workbook(self):
        """Test parsing actual demo workbook."""
        demo_file = "PHASE_2/INPUT/TIO2_Sprint_Intelligence_v5_final.xlsx"
        
        if not os.path.exists(demo_file):
            pytest.skip(f"Demo workbook not found at {demo_file}")
        
        parser = WorkbookParser(demo_file)
        project_state = parser.parse()
        
        # Verify parsed state
        assert project_state.project_info.project_name == "TIO2 – Telematics Gateway ECU Modernization"
        assert len(project_state.team) > 0
        assert len(project_state.sprints) > 0
        assert len(project_state.work_items) > 0
        assert project_state.project_id  # Should have project ID

    def test_resolve_remaining_effort_not_started_blank_defaults_to_current(self):
        parser = WorkbookParser("/fake/path.xlsx")
        status = WorkItemStatus.NOT_STARTED
        current_estimate = 32.0

        result = parser._resolve_remaining_effort(None, current_estimate, status)
        assert result == 32.0

        result_blank = parser._resolve_remaining_effort("", current_estimate, status)
        assert result_blank == 32.0

    def test_resolve_remaining_effort_done_or_completed_blank_defaults_to_zero(self):
        parser = WorkbookParser("/fake/path.xlsx")

        done_result = parser._resolve_remaining_effort(None, 32.0, WorkItemStatus.DONE)
        assert done_result == 0.0

        completed_result = parser._resolve_remaining_effort(None, 28.0, WorkItemStatus.COMPLETED)
        assert completed_result == 0.0

    def test_resolve_remaining_effort_uses_populated_workbook_value(self):
        parser = WorkbookParser("/fake/path.xlsx")

        explicit_value = parser._resolve_remaining_effort(12, 32.0, WorkItemStatus.NOT_STARTED)
        assert explicit_value == 12.0

        explicit_str = parser._resolve_remaining_effort("  8  ", 32.0, WorkItemStatus.NOT_STARTED)
        assert explicit_str == 8.0

    def test_resolve_remaining_effort_in_progress_blank_falls_back_to_estimate(self):
        parser = WorkbookParser("/fake/path.xlsx")
        assert parser._resolve_remaining_effort(None, 40.0, WorkItemStatus.IN_PROGRESS, progress_pct=0.0) == 40.0
        assert parser._resolve_remaining_effort("", 40.0, WorkItemStatus.IN_PROGRESS, progress_pct=0.5) == 20.0

    def test_resolve_remaining_effort_blocked_blank_falls_back_to_estimate(self):
        parser = WorkbookParser("/fake/path.xlsx")
        assert parser._resolve_remaining_effort(None, 30.0, WorkItemStatus.BLOCKED, progress_pct=0.0) == 30.0

    def test_resolve_remaining_effort_completed_or_done_non_blank_ignores_remaining_value(self):
        parser = WorkbookParser("/fake/path.xlsx")
        assert parser._resolve_remaining_effort("10", 20.0, WorkItemStatus.COMPLETED) == 0.0
        assert parser._resolve_remaining_effort("10", 20.0, WorkItemStatus.DONE) == 0.0

    def test_resolve_remaining_effort_not_started_blank_defaults_to_current_for_empty_string(self):
        parser = WorkbookParser("/fake/path.xlsx")
        assert parser._resolve_remaining_effort("", 28.0, WorkItemStatus.NOT_STARTED) == 28.0

    def test_resolve_remaining_effort_zero_string_returns_zero(self):
        parser = WorkbookParser("/fake/path.xlsx")
        assert parser._resolve_remaining_effort("0", 32.0, WorkItemStatus.IN_PROGRESS, progress_pct=0.0) == 0.0

    def test_parse_progress_pct_converts_50_to_decimal(self):
        parser = WorkbookParser("/fake/path.xlsx")
        row = {"Progress %": 50}
        assert parser._parse_progress_pct(row) == 0.5

    def test_parse_progress_pct_accepts_decimal_values(self):
        parser = WorkbookParser("/fake/path.xlsx")
        row = {"Progress %": 0.25}
        assert parser._parse_progress_pct(row) == 0.25

    def test_parse_progress_pct_rejects_negative_values(self):
        parser = WorkbookParser("/fake/path.xlsx")
        row = {"Progress %": -5}
        with pytest.raises(WorkbookParseError):
            parser._parse_progress_pct(row)

    def test_parse_progress_pct_rejects_values_over_100(self):
        parser = WorkbookParser("/fake/path.xlsx")
        row = {"Progress %": 150}
        with pytest.raises(WorkbookParseError):
            parser._parse_progress_pct(row)


# ──────────────────────────────────────────────────────────────────────────────
# Validator Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestWorkbookValidator:
    """Test workbook validator."""
    
    def test_validator_accepts_valid_project(self, sample_project_state):
        """Validator should accept valid project state."""
        validator = WorkbookValidator(sample_project_state)
        warnings = validator.validate()
        
        # Should not raise
        assert isinstance(warnings, list)
    
    def test_validator_detects_invalid_end_date(self, sample_project_info):
        """Validator should reject end date before start date."""
        with pytest.raises(ValidationError):
            ProjectInfo(
                project_name="Test",
                sponsor="Sponsor",
                business_unit="BU",
                project_manager="PM",
                start_date=datetime(2025, 5, 11),
                target_end_date=datetime(2025, 1, 20),  # Before start date
                sprint_duration_days=14,
                methodology="Agile",
                customer="Customer",
                status="Active",
            )
    
    def test_validator_detects_referential_integrity_issues(self, sample_project_state):
        """Validator should detect missing references."""
        # Add work item referencing non-existent sprint
        sample_project_state.work_items[0].assigned_sprint = "NonExistentSprint"
        
        validator = WorkbookValidator(sample_project_state)
        with pytest.raises(ValidatorError):
            validator.validate()
    
    def test_validator_detects_duplicate_ids(self, sample_project_state):
        """Validator should detect duplicate IDs."""
        # Duplicate work item ID
        sample_project_state.work_items[1].item_id = sample_project_state.work_items[0].item_id
        
        validator = WorkbookValidator(sample_project_state)
        with pytest.raises(ValidatorError):
            validator.validate()
    
    def test_validator_warns_underutilized_resources(self, sample_project_state):
        """Validator should warn about underutilized resources."""
        # Add underutilized resource
        sample_project_state.team.append(
            Resource(
                resource_id="part_timer",
                name="Part Timer",
                role="Consultant",
                primary_skill="Testing",
                skill_level=SkillLevel.MID,
                allocation_pct=0.1,  # Very low
                availability_pct=0.3,
            )
        )
        
        validator = WorkbookValidator(sample_project_state)
        warnings = validator.validate()
        
        # Should have warning about utilization
        assert any(w.category == "utilization" for w in warnings)


# ──────────────────────────────────────────────────────────────────────────────
# Session Store Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestSessionStore:
    """Test session store."""
    
    def test_session_store_singleton(self):
        """SessionStore should be singleton."""
        store1 = SessionStore()
        store2 = SessionStore()
        assert store1 is store2
    
    def test_create_and_retrieve_session(self, sample_project_state):
        """Test creating and retrieving session."""
        store = SessionStore()
        store.clear_all()
        
        session_id = store.create_session(sample_project_state)
        
        assert session_id == sample_project_state.project_id
        
        session = store.get_session(session_id)
        assert session is not None
        assert session.project_state.project_id == sample_project_state.project_id
    
    def test_get_nonexistent_session(self):
        """Test retrieving non-existent session."""
        store = SessionStore()
        session = store.get_session("non-existent")
        assert session is None
    
    def test_delete_session(self, sample_project_state):
        """Test deleting session."""
        store = SessionStore()
        store.clear_all()
        
        session_id = store.create_session(sample_project_state)
        
        # Delete
        deleted = store.delete_session(session_id)
        assert deleted is True
        
        # Verify deleted
        session = store.get_session(session_id)
        assert session is None
    
    def test_list_sessions(self, sample_project_state):
        """Test listing sessions."""
        store = SessionStore()
        store.clear_all()
        
        session_id = store.create_session(sample_project_state)
        
        sessions = store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0][0] == session_id


# ──────────────────────────────────────────────────────────────────────────────
# Integration Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestIntegration:
    """Integration tests for Phase 1."""
    
    def test_parse_validate_store_flow(self):
        """Test full parse -> validate -> store flow."""
        demo_file = "PHASE_2/INPUT/TIO2_Sprint_Intelligence_v5_final.xlsx"
        
        if not os.path.exists(demo_file):
            pytest.skip(f"Demo workbook not found at {demo_file}")
        
        # Parse
        parser = WorkbookParser(demo_file)
        project_state = parser.parse()
        
        # Validate
        validator = WorkbookValidator(project_state)
        warnings = validator.validate()  # Should not raise
        
        # Store
        store = SessionStore()
        store.clear_all()
        session_id = store.create_session(project_state)
        
        # Verify
        retrieved = store.get_project_state(session_id)
        assert retrieved is not None
        assert retrieved.project_info.project_name == project_state.project_info.project_name


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
