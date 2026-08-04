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
    # Snapshot pre-existing deployment IDs so teardown only removes rows the
    # test created, never production data.
    from sqlalchemy import text, bindparam
    with engine.connect() as conn:
        pre_ids = {row[0] for row in conn.execute(text("SELECT id FROM deployments"))}
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()
    # Delete only rows created during the test (not in the pre-test snapshot).
    with engine.begin() as conn:
        if pre_ids:
            conn.execute(
                text("DELETE FROM deployments WHERE id NOT IN :pre_ids")
                .bindparams(bindparam("pre_ids", expanding=True)),
                {"pre_ids": list(pre_ids)},
            )
        else:
            # No pre-existing rows, so everything present is test-created.
            conn.execute(text("DELETE FROM deployments"))


@pytest.fixture
def sample_strategy_path():
    return "strategies/_test_dummy.py"
