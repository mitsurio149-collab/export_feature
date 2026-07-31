"""
API Request/Response Models

Data transfer objects for HTTP API endpoints.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


# ──────────────────────────────────────────────────────────────────────────────
# Base Response Envelope
# ──────────────────────────────────────────────────────────────────────────────


class ApiResponse(BaseModel):
    """Standard API response envelope."""
    
    success: bool = Field(..., description="Whether request succeeded")
    data: Optional[Any] = Field(None, description="Response data (if successful)")
    error_code: Optional[str] = Field(None, description="Error code (if failed)")
    message: str = Field(default="", description="Human-readable message")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")


# ──────────────────────────────────────────────────────────────────────────────
# Validation Error
# ──────────────────────────────────────────────────────────────────────────────


class ValidationIssue(BaseModel):
    """Single validation error or warning."""
    
    category: str = Field(..., description="Issue category (structural, referential, business_rule)")
    message: str = Field(..., description="Issue message")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")


class ValidationErrorResponse(ApiResponse):
    """Response when validation fails."""
    
    errors: List[ValidationIssue] = Field(default_factory=list, description="Validation errors")
    warnings: List[ValidationIssue] = Field(default_factory=list, description="Validation warnings")


# ──────────────────────────────────────────────────────────────────────────────
# Upload Endpoint
# ──────────────────────────────────────────────────────────────────────────────


class ProjectSummary(BaseModel):
    """Summary of parsed project."""
    
    session_id: str = Field(..., description="Session ID for this project")
    project_name: str = Field(..., description="Project name")
    project_manager: str = Field(..., description="Project manager")
    customer: str = Field(..., description="Customer name")
    start_date: datetime = Field(..., description="Project start date")
    target_end_date: datetime = Field(..., description="Target completion date")
    total_sprints: int = Field(..., description="Total number of sprints")
    total_work_items: int = Field(..., description="Total work items")
    total_resources: int = Field(..., description="Team size")
    total_dependencies: int = Field(..., description="Number of dependencies")
    total_blockers: int = Field(..., description="Number of blockers")
    completed_sprints: int = Field(..., description="Number of completed sprints")


class UploadResponse(BaseModel):
    """Successful upload response."""
    
    session_id: str = Field(..., description="Session ID for subsequent requests")
    project_summary: ProjectSummary = Field(..., description="Project summary")
    validation_warnings: List[ValidationIssue] = Field(
        default_factory=list, description="Non-critical validation warnings"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Status Codes & Error Responses
# ──────────────────────────────────────────────────────────────────────────────


class ErrorResponse(ApiResponse):
    """Error response."""
    
    pass


# Standard error codes
class ErrorCodes:
    """Error code constants."""
    
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    PARSE_ERROR = "PARSE_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    PROCESSING_ERROR = "PROCESSING_ERROR"
    NOT_FOUND = "NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"
