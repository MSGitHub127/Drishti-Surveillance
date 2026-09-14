"""
Pytest configuration and sys.path bootstrap for Team Vayunotics test suite.
"""

import sys
import os
import pytest

# Add backend directory to sys.path so 'import app...' resolves cleanly
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

@pytest.fixture(autouse=True, scope="session")
def bootstrap_database():
    """Initializes schema and seeds test data across all test modules."""
    from app.database import init_database_schema, seed_initial_data_if_empty
    init_database_schema()
    seed_initial_data_if_empty()
