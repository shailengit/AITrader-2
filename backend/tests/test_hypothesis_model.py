from app.models.hypothesis import Hypothesis

def test_hypothesis_required_columns():
    h = Hypothesis(
        source="sectors",
        why="Tech leading",
        status="open",
        source_meta={"page": "sectors", "tile": "XLK"},
    )
    assert h.source == "sectors"
    assert h.status == "open"
    assert h.source_meta == {"page": "sectors", "tile": "XLK"}
