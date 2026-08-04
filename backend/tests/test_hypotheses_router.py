import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup_hypotheses():
    """Delete only the hypotheses rows created during the test.

    The router writes to the real Postgres ``hypotheses`` table via
    SessionLocal. Snapshot pre-existing IDs before the test and delete only
    rows that were created during it, so the suite stays idempotent and never
    removes production data.
    """
    from app.db.database import engine
    from sqlalchemy import text, bindparam
    with engine.connect() as conn:
        pre_ids = {row[0] for row in conn.execute(text("SELECT id FROM hypotheses"))}
    yield
    with engine.begin() as conn:
        if pre_ids:
            conn.execute(
                text("DELETE FROM hypotheses WHERE id NOT IN :pre_ids")
                .bindparams(bindparam("pre_ids", expanding=True)),
                {"pre_ids": list(pre_ids)},
            )
        else:
            conn.execute(text("DELETE FROM hypotheses"))


def test_create_hypothesis_returns_201():
    r = client.post("/api/hypotheses", json={
        "source": "sectors",
        "why": "Tech leading with low vol",
        "ticker": "XLK",
        "regime": "BULL",
        "source_meta": {"page": "sectors", "tile": "XLK"},
    })
    assert r.status_code == 201
    body = r.json()
    assert body["why"] == "Tech leading with low vol"
    assert body["status"] == "open"


def test_list_hypotheses_default_returns_open_only():
    client.post("/api/hypotheses", json={"source": "manual", "why": "x"})
    r = client.get("/api/hypotheses")
    assert r.status_code == 200
    for h in r.json():
        assert h["status"] == "open"
