"""Integration tests for the strategy_lab FastAPI router."""
import os
import sys
import uuid

import pytest
from dotenv import load_dotenv

# Set up env before importing app
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models.strategy_lab import StrategySession


@pytest.fixture
def client():
    """TestClient that uses a unique X-Forwarded-For per test to bypass the rate limiter."""
    import uuid as _uuid
    c = TestClient(app)
    c.headers["X-Forwarded-For"] = f"127.0.0.{_uuid.uuid4().int % 254 + 1}"
    return c


@pytest.fixture
def cleanup():
    """Track session IDs to delete after test."""
    created = []
    yield created
    if created:
        with SessionLocal() as s:
            for sid in created:
                obj = s.get(StrategySession, sid)
                if obj:
                    s.delete(obj)
            s.commit()


def test_models_endpoint(client):
    res = client.get("/api/strategy-lab/models")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert len(body) > 0
    sample = body[0]
    assert "id" in sample and "variants" in sample
    assert isinstance(sample["variants"], list)
    if sample["variants"]:
        v = sample["variants"][0]
        assert "name" in v and "type" in v
        assert v["type"] in ("cloud", "local")


def test_create_and_get_session(client, cleanup):
    res = client.post("/api/strategy-lab/sessions", json={
        "name": f"router-test-{uuid.uuid4().hex[:8]}",
        "prompt": "Test from router",
        "model_id": "deepseek-v4-flash:cloud",
    })
    assert res.status_code == 201
    body = res.json()
    assert "id" in body
    cleanup.append(body["id"])

    # GET by id
    res2 = client.get(f"/api/strategy-lab/sessions/{body['id']}")
    assert res2.status_code == 200
    assert res2.json()["id"] == body["id"]


def test_update_session_via_patch(client, cleanup):
    res = client.post("/api/strategy-lab/sessions", json={
        "name": f"patch-test-{uuid.uuid4().hex[:8]}",
        "prompt": "p",
        "model_id": "deepseek-v4-flash:cloud",
    })
    sid = res.json()["id"]
    cleanup.append(sid)

    res2 = client.patch(f"/api/strategy-lab/sessions/{sid}", json={
        "plan_text": "## Plan",
        "code_text": "print('hi')",
        "tags": ["test"],
    })
    assert res2.status_code == 200
    body = res2.json()
    assert body["plan_text"] == "## Plan"
    assert body["code_text"] == "print('hi')"
    assert body["tags"] == ["test"]


def test_list_sessions_with_search(client, cleanup):
    unique = uuid.uuid4().hex[:8]
    res = client.post("/api/strategy-lab/sessions", json={
        "name": f"search-{unique}",
        "prompt": f"findme-{unique}",
        "model_id": "deepseek-v4-flash:cloud",
    })
    sid = res.json()["id"]
    cleanup.append(sid)

    res2 = client.get(f"/api/strategy-lab/sessions?search=findme-{unique}")
    assert res2.status_code == 200
    ids = [s["id"] for s in res2.json()]
    assert sid in ids


def test_delete_session(client, cleanup):
    res = client.post("/api/strategy-lab/sessions", json={
        "name": f"del-{uuid.uuid4().hex[:8]}",
        "prompt": "p",
        "model_id": "deepseek-v4-flash:cloud",
    })
    sid = res.json()["id"]
    cleanup.append(sid)

    res2 = client.delete(f"/api/strategy-lab/sessions/{sid}")
    assert res2.status_code == 204
    # If cleanup tries to delete again, it should be a no-op
    cleanup.remove(sid)

    res3 = client.get(f"/api/strategy-lab/sessions/{sid}")
    assert res3.status_code == 404


def test_get_nonexistent_session_returns_404(client):
    res = client.get(f"/api/strategy-lab/sessions/{uuid.uuid4()}")
    assert res.status_code == 404
