"""
Sprint Whisperer Backend Launcher

Starts the FastAPI application using Uvicorn.

Run:
    python main.py

Equivalent to:
    uvicorn app.main:app --reload
"""

import uvicorn


def main() -> None:
    """Start the FastAPI server."""
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()