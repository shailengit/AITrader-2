"""A content-addressed cache for LLM exit decisions.

Two reasons this exists, and neither is performance:
  1. Reproducibility. A backtest that re-asks an LLM can drift; a cache makes
     the arm replayable bit-for-bit.
  2. Feasibility. 100 starts produce ~40k exit decisions but only ~2.4k distinct
     decision contexts. Without the cache the arm is a multi-day job.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.exit_gate.cache import DecisionCache, canonicalize  # noqa: E402


def test_canonical_form_ignores_dict_order_and_float_noise():
    a = {"x": 1.0000000001, "y": {"b": 2, "a": 1}}
    b = {"y": {"a": 1.0, "b": 2}, "x": 1.0}
    assert canonicalize(a) == canonicalize(b)


def test_the_key_binds_the_model_and_the_prompt_version():
    c = DecisionCache("/tmp/_gate_cache_test.sqlite")
    try:
        p = canonicalize({"ret": 0.1})
        k = c.key("modelA|sha", "v1", p)
        assert k == c.key("modelA|sha", "v1", p)
        assert k != c.key("modelB|sha", "v1", p)
        assert k != c.key("modelA|sha", "v2", p)
        assert k != c.key("modelA|sha", "v1", canonicalize({"ret": 0.2}))
    finally:
        c.close()


def test_a_stored_decision_round_trips(tmp_path):
    path = str(tmp_path / "c.sqlite")
    c = DecisionCache(path)
    k = c.key("m", "v1", "ctx")
    c.put(k, {"prompt": "ctx"}, {"raw": "{\"veto\": true}"},
          {"veto": True, "confidence": 0.9, "reason": "hold"}, 0.42)
    got = c.get(k)
    assert got["veto"] is True
    assert got["confidence"] == 0.9
    assert got["reason"] == "hold"
    c.close()

    # Survives a new process/instance on the same file.
    c2 = DecisionCache(path)
    assert c2.get(k)["veto"] is True
    c2.close()


def test_a_miss_returns_none_and_is_counted(tmp_path):
    c = DecisionCache(str(tmp_path / "c.sqlite"))
    assert c.get("nope") is None
    assert c.stats()["hits"] == 0 and c.stats()["misses"] == 1
    c.close()


def test_stats_separate_hits_from_misses(tmp_path):
    c = DecisionCache(str(tmp_path / "c.sqlite"))
    c.put("k", {}, {}, {"veto": False, "confidence": 0.1, "reason": ""}, 0.0)
    c.get("k")
    c.get("missing")
    s = c.stats()
    assert s["hits"] == 1
    assert s["misses"] == 1
    assert s["hit_rate"] == 0.5
    c.close()


def test_a_corrupted_row_reads_as_a_miss(tmp_path):
    path = str(tmp_path / "c.sqlite")
    c = DecisionCache(path)
    c.put("k", {}, {}, {"veto": True, "confidence": 1.0, "reason": ""}, 0.0)
    c._conn.execute("UPDATE decisions SET decision_json='not json' WHERE key='k'")
    c._conn.commit()
    assert c.get("k") is None
    c.close()
