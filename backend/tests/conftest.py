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

# ---------------------------------------------------------------------------
# Production-DB guard. Tests that touch Postgres (the `db_session` fixture)
# MUST run against a dedicated test database, never the production DB. The
# suite refuses to run those tests unless TEST_DATABASE_URL is set, and fails
# loudly if that URL names one of the production databases. When a test URL IS
# provided, we derive the app's DB_* env vars from it BEFORE app.main imports
# so the whole app (endpoints + fixtures) binds to the test DB consistently.
# ---------------------------------------------------------------------------
PRODUCTION_DB_NAMES = {"sp1500_1d", "sp1500_1m"}

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    test_db_name = TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0].strip()
    if test_db_name.lower() in PRODUCTION_DB_NAMES:
        raise SystemExit(
            f"refusing to run DB-touching tests: TEST_DATABASE_URL points at the "
            f"production database '{test_db_name}'. Set TEST_DATABASE_URL to a "
            f"dedicated test database."
        )
    # Point the app's engine/session at the test DB by deriving DB_* components
    # from the URL. Runs before `from app.main import app` below.
    from urllib.parse import urlsplit, unquote

    _u = urlsplit(TEST_DATABASE_URL)
    os.environ["DB_USER"] = unquote(_u.username or "postgres")
    os.environ["DB_PASSWORD"] = unquote(_u.password or "")
    os.environ["DB_HOST"] = _u.hostname or "127.0.0.1"
    os.environ["DB_PORT"] = str(_u.port or 5432)
    os.environ["DB_NAME"] = _u.path.lstrip("/")

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

    SAFETY: refuses to touch the production DB. Requires TEST_DATABASE_URL to
    point at a dedicated test database; otherwise the test is skipped. When set,
    conftest has already overridden the app's DB_* env vars from the URL so the
    app engine/session bind to the test DB.

    The Deployment model uses Postgres-specific types (UUID, JSONB, SAEnum),
    so SQLite will not work.
    """
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip(
            "TEST_DATABASE_URL not set — refusing to run DB-touching tests "
            "against the production DB. Set TEST_DATABASE_URL to a dedicated "
            "test database to enable these tests."
        )

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
