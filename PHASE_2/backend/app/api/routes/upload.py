"""
Upload Route

POST /api/upload - Upload and parse workbook
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, status
from datetime import datetime, date
import tempfile
import os

from app.parsers import WorkbookParser, WorkbookParseError
from app.validators import WorkbookValidator, ValidationError as ValidatorError
from app.storage import store
from app.core.config import settings
from app.api.models import (
    ApiResponse,
    UploadResponse,
    ProjectSummary,
    ValidationIssue,
    ValidationErrorResponse,
    ErrorCodes,
)
from app.domain.models import SprintStatus


router = APIRouter()


def _sanitize_detail(obj):
    """Recursively convert datetime objects to ISO strings for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _sanitize_detail(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_detail(i) for i in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


@router.post("/upload")
async def upload_workbook(file: UploadFile = File(...)) -> ApiResponse:
    """
    Upload Excel workbook for parsing.
    
    Flow:
    1. Validate file (type, size)
    2. Parse workbook into ProjectState
    3. Validate ProjectState
    4. Store in session
    5. Return summary
    
    Args:
        file: Excel workbook file
        
    Returns:
        UploadResponse with session ID and project summary
        
    Raises:
        HTTPException: If file invalid or parsing fails
    """
    
    # ─── Validate File ───────────────────────────────────────────────────────
    
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.INVALID_FILE_TYPE,
                message="No filename provided",
            ).model_dump()
        )
    
    # Check file extension
    if not any(file.filename.lower().endswith(ext) for ext in settings.allowed_extensions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.INVALID_FILE_TYPE,
                message=f"File must be one of: {', '.join(settings.allowed_extensions)}",
            ).model_dump()
        )
    
    # Check file size
    if file.size and file.size > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.FILE_TOO_LARGE,
                message=f"File size must be <= {settings.max_file_size_mb}MB",
            ).model_dump()
        )
    
    # ─── Save Temporary File ─────────────────────────────────────────────────
    
    temp_path = None
    try:
        # Write uploaded file to temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            content = await file.read()
            tmp.write(content)
            temp_path = tmp.name
        
        # ─── Parse Workbook ──────────────────────────────────────────────────
        
        try:
            parser = WorkbookParser(temp_path)
            project_state = parser.parse()
        except WorkbookParseError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ApiResponse(
                    success=False,
                    error_code=ErrorCodes.PARSE_ERROR,
                    message=f"Failed to parse workbook: {str(e)}",
                ).model_dump()
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=ApiResponse(
                    success=False,
                    error_code=ErrorCodes.INTERNAL_ERROR,
                    message=f"Parse error: {str(e)}",
                ).model_dump()
            )
        
        # ─── Validate Project State ──────────────────────────────────────────
        
        validator = WorkbookValidator(project_state)
        validation_warnings = []
        try:
            validation_warnings = validator.validate()
        except ValidatorError as e:
            raise HTTPException(
                status_code=422,
                detail=_sanitize_detail({"error": str(e)}),
            )
        
        # ─── Store in Session ─────────────────────────────────────────────────
        
        session_id = store.create_session(project_state)
        # attach raw bytes to stored session object
        session = store.get_session(session_id)
        if session:
            session.workbook_bytes = content
        
        # ─── Build Response ──────────────────────────────────────────────────
        
        # Count completed sprints
        completed_sprints = sum(
            1 for s in project_state.sprints
            if s.status == SprintStatus.COMPLETED
        )
        
        project_summary = ProjectSummary(
            session_id=session_id,
            project_name=project_state.project_info.project_name,
            project_manager=project_state.project_info.project_manager,
            customer=project_state.project_info.customer,
            start_date=project_state.project_info.start_date,
            target_end_date=project_state.project_info.target_end_date,
            total_sprints=len(project_state.sprints),
            total_work_items=len(project_state.work_items),
            total_resources=len(project_state.team),
            total_dependencies=len(project_state.dependencies),
            total_blockers=len(project_state.blockers),
            completed_sprints=completed_sprints,
        )
        
        return ApiResponse(
            success=True,
            message="Workbook uploaded and parsed successfully",
            data=UploadResponse(
                session_id=session_id,
                project_summary=project_summary,
                validation_warnings=[w.to_dict() for w in validation_warnings],
            ).model_dump(),
        )
    
    finally:
        # Clean up temporary file
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
