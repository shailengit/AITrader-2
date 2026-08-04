import pytest

from app.services.hypothesis_service import create_hypothesis
from app.services.crafter_shim import format_hypothesis_prompt


@pytest.fixture(autouse=True)
def _cleanup_hypotheses(db_session):
    """Delete hypotheses rows created during the test.

    The shared ``db_session`` fixture (conftest.py) only cleans up the
    ``deployments`` table, so hypotheses rows would otherwise accumulate across
    runs. Mirrors the pattern from Task 2.1 (test_hypothesis_service.py).
    """
    yield
    from app.models.hypothesis import Hypothesis
    db_session.query(Hypothesis).delete()
    db_session.commit()


def test_shim_includes_all_hypotheses(db_session):
    h1 = create_hypothesis(source="sectors", why="Tech leading", ticker="XLK",
                           regime="BULL", source_meta={"page": "sectors", "tile": "XLK"}, db=db_session)
    h2 = create_hypothesis(source="markov", why="Low vol regime", regime="BULL",
                           conviction=0.7, source_meta={"page": "markov"}, db=db_session)
    prompt = format_hypothesis_prompt([str(h1.id), str(h2.id)], db=db_session)
    assert "Tech leading" in prompt
    assert "Low vol regime" in prompt
    assert "regime: BULL" in prompt
    assert "Generate a strategy" in prompt


def test_shim_appends_user_instructions(db_session):
    h = create_hypothesis(source="manual", why="x", db=db_session)
    prompt = format_hypothesis_prompt([str(h.id)], extra_instructions="use RSI 14", db=db_session)
    assert "use RSI 14" in prompt
