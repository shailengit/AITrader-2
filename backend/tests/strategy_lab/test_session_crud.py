"""Tests for session CRUD. Talks to the real sp1500_1d database.

Each test creates its own session and cleans up afterwards.
"""
import os
import sys
import uuid

import pytest

# Make sure backend is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Load .env before importing app modules
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))

from app.db.database import engine
from app.models.strategy_lab import StrategySession
from app.services.strategy_lab_session import (
    create_session, get_session, list_sessions, update_session, delete_session
)


@pytest.fixture
def db():
    from sqlalchemy.orm import Session
    with Session(engine) as s:
        yield s


def test_create_and_get_session(db):
    name = f"test-{uuid.uuid4().hex[:8]}"
    sess = create_session(db, name=name, prompt="Test prompt", model_id="deepseek-v4-flash:cloud")
    assert sess.id is not None
    assert sess.name == name
    assert sess.prompt == "Test prompt"
    assert sess.model_id == "deepseek-v4-flash:cloud"
    assert sess.tags == []
    assert sess.plan_text is None
    assert sess.code_text is None

    fetched = get_session(db, sess.id)
    assert fetched is not None
    assert fetched.id == sess.id
    assert fetched.prompt == "Test prompt"

    # Cleanup
    delete_session(db, sess.id)
    assert get_session(db, sess.id) is None


def test_update_session_fields(db):
    sess = create_session(db, name="to-update", prompt="orig", model_id="deepseek-v4-flash:cloud")
    updated = update_session(
        db, sess.id,
        plan_text="## Plan",
        code_text="print('hello')",
        tags=["experimental", "good"],
        name="renamed",
    )
    assert updated is not None
    assert updated.plan_text == "## Plan"
    assert updated.code_text == "print('hello')"
    assert updated.tags == ["experimental", "good"]
    assert updated.name == "renamed"
    assert updated.prompt == "orig"  # untouched

    delete_session(db, sess.id)


def test_list_sessions_with_search(db):
    # Create a uniquely-named session
    unique = f"unique-search-{uuid.uuid4().hex[:8]}"
    sess = create_session(db, name=unique, prompt="findme in search", model_id="deepseek-v4-flash:cloud")
    try:
        results = list_sessions(db, search="findme")
        ids = [s.id for s in results]
        assert sess.id in ids
    finally:
        delete_session(db, sess.id)


def test_list_sessions_with_tag_filter(db):
    sess = create_session(
        db, name="tagged", prompt="x", model_id="deepseek-v4-flash:cloud",
        tags=["only-this-tag-xyz"],
    )
    try:
        results = list_sessions(db, tags=["only-this-tag-xyz"])
        ids = [s.id for s in results]
        assert sess.id in ids
    finally:
        delete_session(db, sess.id)


def test_delete_session_returns_false_if_missing(db):
    fake_id = uuid.uuid4()
    assert delete_session(db, fake_id) is False
