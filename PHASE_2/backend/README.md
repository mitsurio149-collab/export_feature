# Sprint Whisperer Backend

> **Phase 1: Foundation & Ingestion** — Production-ready Python backend for parsing, validating, and storing project workbooks.

## Project Structure

```
backend/
├── app/                          # Main application package
│   ├── core/                     # Configuration and settings
│   │   ├── config.py            # All app configuration (Pydantic Settings)
│   │   └── __init__.py
│   │
│   ├── domain/                   # Domain models (business logic)
│   │   ├── models.py            # All Pydantic models
│   │   └── __init__.py
│   │
│   ├── parsers/                  # Workbook parsing
│   │   ├── workbook_parser.py   # Excel → ProjectState converter
│   │   └── __init__.py
│   │
│   ├── validators/               # Business rule validation
│   │   ├── workbook_validator.py # ProjectState validator
│   │   └── __init__.py
│   │
│   ├── storage/                  # Session management
│   │   ├── session_store.py     # In-memory session storage
│   │   └── __init__.py
│   │
│   ├── api/                      # HTTP API
│   │   ├── models.py            # Request/response DTOs
│   │   ├── routes/              # API endpoints
│   │   │   ├── upload.py        # POST /api/upload
│   │   │   └── __init__.py
│   │   ├── __init__.py
│   │   └── main.py              # FastAPI app setup
│   │
│   └── __init__.py
│
├── tests/                        # Unit and integration tests
│   ├── test_phase1.py           # Phase 1 tests (parser, validator, upload)
│   ├── conftest.py              # Pytest configuration
│   └── __init__.py
│
├── main.py                       # Entry point (uvicorn)
├── requirements.txt              # Python dependencies
├── .env                          # Environment configuration
├── .gitignore                    # Git ignore rules
└── README.md                     # This file
```

## Quick Start

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Run the Server

```bash
python main.py
# OR with uvicorn directly:
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Server will start at `http://localhost:8000`

### 3. API Documentation

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### 4. Health Check

```bash
curl http://localhost:8000/api/health
```

Expected response:
```json
{
  "success": true,
  "data": {
    "status": "ok",
    "version": "2.0.0",
    "timestamp": "2026-06-11T10:30:00.000Z"
  },
  "message": "Service is healthy"
}
```

## Phase 1: Foundation & Ingestion

### Implemented Endpoints

#### `POST /api/upload`

Upload Excel workbook for parsing.

**Request:**
```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@TIO2_Sprint_Intelligence_v5_final.xlsx"
```

**Response (Success):**
```json
{
  "success": true,
  "message": "Workbook uploaded and parsed successfully",
  "data": {
    "session_id": "abc123",
    "project_summary": {
      "session_id": "abc123",
      "project_name": "TIO2 – Telematics Gateway ECU Modernization",
      "project_manager": "Suresh Iyer",
      "customer": "Daimler Truck",
      "start_date": "2025-01-20T00:00:00",
      "target_end_date": "2025-05-11T00:00:00",
      "total_sprints": 10,
      "total_work_items": 67,
      "total_resources": 10,
      "total_dependencies": 22,
      "total_blockers": 5,
      "completed_sprints": 2
    },
    "validation_warnings": []
  }
}
```

**Response (Validation Error):**
```json
{
  "success": false,
  "error_code": "VALIDATION_ERROR",
  "message": "Validation failed: ...",
  "errors": [...],
  "warnings": [...]
}
```

### Workbook Requirements

The uploaded `.xlsx` file must have 7 sheets:

1. **Project_Info** — Project metadata (1 row)
2. **Team** — Resources and team members
3. **Sprint_Plan** — Sprint schedule
4. **Work_Items** — Tasks and work items
5. **Dependencies** — Task dependencies
6. **Blockers** — Blocking issues
7. **Sprint_Actuals** — Historical sprint data

Each sheet follows the pattern:
- Row 1: Title (merged cells, skipped)
- Row 2: Column headers
- Row 3+: Data rows

See [Workbook Mapping](../../IMPLEMENTATION_FLOW.md#workbook-column-mapping) for detailed column definitions.

## Configuration

All settings loaded from `.env` file:

```bash
# API
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=True

# Monte Carlo (Phase 3+)
MC_ITERATIONS=10000
EFFORT_VARIANCE_MIN=0.80
EFFORT_VARIANCE_MODE=1.00
EFFORT_VARIANCE_MAX=1.35

# File Upload
MAX_FILE_SIZE_MB=10
ALLOWED_EXTENSIONS=.xlsx
```

Access settings in code:
```python
from app.core.config import settings

print(settings.mc_iterations)  # 10000
print(settings.max_file_size_mb)  # 10
```

## Domain Models

All models are Pydantic v2 with full type hints:

```python
from app.domain.models import ProjectState, ProjectInfo, Resource

state: ProjectState = parser.parse()
print(state.project_info.project_name)
print(len(state.team))
```

## Testing

### Run All Tests

```bash
pytest tests/ -v
```

### Run Specific Test

```bash
pytest tests/test_phase1.py::TestWorkbookParser::test_parser_with_demo_workbook -v
```

### Test Coverage

```bash
pytest tests/ --cov=app --cov-report=html
# Open htmlcov/index.html in browser
```

## Error Handling

All API responses follow the standard envelope:

```python
class ApiResponse(BaseModel):
    success: bool                      # True/False
    data: Optional[Any]                # Response data (if success=True)
    error_code: Optional[str]          # Error code (if success=False)
    message: str                       # Human-readable message
    timestamp: datetime                # Response time
```

Common error codes:
- `FILE_NOT_FOUND` — Uploaded file not found
- `INVALID_FILE_TYPE` — Not an .xlsx file
- `FILE_TOO_LARGE` — Exceeds size limit
- `PARSE_ERROR` — Failed to parse workbook
- `VALIDATION_ERROR` — Business rule violation
- `SESSION_NOT_FOUND` — Session ID not found
- `INTERNAL_ERROR` — Server error

## Architecture Decisions

### Pydantic v2
- Type safety with runtime validation
- Auto-generated API documentation
- Built-in serialization/deserialization

### Enum Classes
- Restrict field values to predefined set
- Type-safe in Python code
- Validated at API boundary

### Session Store Pattern
- In-memory singleton for Phase 1 (hackathon)
- Easy to swap for Redis in production
- Thread-safe with locks

### Parser Architecture
- Raw data extraction (openpyxl)
- Enum parsing with fallback
- Formula handling (can't evaluate, use defaults)
- Comprehensive error messages

### Validation Strategy
1. **Structural**: All required fields present
2. **Referential**: All references valid
3. **Business Rules**: Domain constraints
4. **Warnings**: Non-critical issues

## Next Phases

**Phase 2**: Dependency Analysis & Spillover Processing  
**Phase 3**: Monte Carlo Simulation Engine  
**Phase 4**: Risk Analysis & Sprint-Level Heatmap  
**Phase 5**: Recommendations Engine  
**Phase 6**: Scope Change Workflow  
**Phase 7**: Reforecast Comparison  
**Phase 8**: Frontend Integration & Demo  

## Development Notes

### Adding New Routes

1. Create new file in `app/api/routes/`
2. Define router with `@router.post()` etc.
3. Import in `app/api/routes/__init__.py`
4. Register in `app/main.py`

### Modifying Configuration

1. Edit `app/core/config.py` (add new field to `Settings` class)
2. Update `.env` file
3. Use via `from app.core.config import settings`

### Adding New Domain Model

1. Define in `app/domain/models.py` (Pydantic BaseModel)
2. Add to `__all__` in `app/domain/__init__.py`
3. Use in parsers/validators

### Debugging

Enable debug mode in `.env`:
```bash
DEBUG=True
```

Then run with reload:
```bash
python main.py  # Auto-reloads on file changes
```

## Performance

**Workbook Parse + Validate + Store**: < 3 seconds (even for large workbooks)

Target for Phase 2-4:
- Monte Carlo 10k iterations: < 8 seconds
- Full pipeline: < 15 seconds

## Production Deployment

### Requirements

- Python 3.10+
- 2GB RAM minimum
- 1 CPU core (add more for parallel requests)

### Gunicorn Deployment

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 main:app
```

### Docker

See `Dockerfile` for containerized deployment.

### Environment Variables

Set production settings:
```bash
export DEBUG=False
export API_HOST=0.0.0.0
export API_PORT=8000
# etc.
```

## Contributing

- Follow PEP 8 style guide
- Add type hints to all functions
- Write tests for new features
- Update docstrings
- Keep functions small and testable

## License

Proprietary — Sprint Whisperer
