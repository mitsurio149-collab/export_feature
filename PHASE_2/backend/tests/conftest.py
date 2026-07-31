"""
Pytest Configuration

Shared fixtures and configuration for tests.
"""

import sys
from pathlib import Path

# Add backend directory to path so app can be imported
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
