import os
import sys

# Ensure backend is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from fastapi.testclient import TestClient

# Set test environment variables before importing app
os.environ["DB_PASSWORD"] = "test_password"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-for-testing-only"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

from app.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_db(monkeypatch):
    """Mock database connection for tests."""
    from app.db import database
    monkeypatch.setattr(database, "db_connected", True)
    return database


@pytest.fixture
def db_session():
    """Postgres real-DB session for tests that need the deployments registry.

    The Deployment model uses Postgres-specific types (UUID, JSONB, SAEnum),
    so SQLite will not work. Uses the project's engine directly.
    """
    from app.db.database import Base, SessionLocal, engine
    Base.metadata.create_all(engine)
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()
    # Clean up rows written by the test so the real deployments registry is
    # not left with a bogus active deployment that would break production.
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM deployments"))


@pytest.fixture
def sample_strategy_path():
    return "strategies/_test_dummy.py"
