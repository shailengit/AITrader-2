import uuid
import pytest
from app.services.hypothesis_service import (
    create_hypothesis,
    list_hypotheses,
    mark_generated,
    archive_hypothesis,
)


@pytest.fixture(autouse=True)
def _cleanup_hypotheses(db_session):
    """Delete hypotheses rows created during the test.

    The shared ``db_session`` fixture (conftest.py) only cleans up the
    ``deployments`` table, so hypotheses rows would otherwise accumulate across
    runs and break ``test_create_and_list`` (which asserts a single row).
    """
    yield
    from app.models.hypothesis import Hypothesis
    db_session.query(Hypothesis).delete()
    db_session.commit()


def test_create_and_list(db_session):
    h = create_hypothesis(
        source="sectors", why="Tech leading",
        ticker="XLK", regime="BULL",
        source_meta={"page": "sectors", "tile": "XLK"},
        db=db_session,
    )
    assert h.id is not None
    rows = list_hypotheses(db=db_session)
    assert len(rows) == 1
    assert rows[0].why == "Tech leading"


def test_mark_generated(db_session):
    h = create_hypothesis(source="sectors", why="x", db=db_session)
    sid = str(uuid.uuid4())
    h2 = mark_generated(h.id, sid, db=db_session)
    assert h2.status.value == "generated"
    assert str(h2.generated_strategy_id) == sid


def test_archive(db_session):
    h = create_hypothesis(source="manual", why="y", db=db_session)
    h2 = archive_hypothesis(h.id, db=db_session)
    assert h2.status.value == "archived"


def test_filter_by_source_and_status(db_session):
    create_hypothesis(source="sectors", why="a", db=db_session)
    create_hypothesis(source="markov", why="b", db=db_session)
    only_markov = list_hypotheses(source="markov", db=db_session)
    assert len(only_markov) == 1
    assert only_markov[0].source.value == "markov"
