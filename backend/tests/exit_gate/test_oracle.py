"""Hindsight reference gate: the value of vetoing with perfect foresight.

This is a REFERENCE, not a policy. It reads forward returns that no live system
could know, so it can only ever bound what a real gate might achieve. Its job is
to decide whether building a learned/LLM gate is worth any effort at all.

It is deliberately slot-aware: the alternative to holding is buying today's best
feasible candidate, not merely going to cash. Ignoring that is what made phase
2's frozen-entry ranking wrong.
"""
import os
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.exit_gate.oracle import (  # noqa: E402
    OracleGate,
    build_forward_returns,
)
from app.services.exit_gate.types import ExitContext  # noqa: E402


def _cache():
    # AAA and BBB are the held name / candidate. Three future sessions.
    return {
        "aaa": {"2021-03-05": 100.0, "2021-03-08": 110.0,
                "2021-03-09": 120.0, "2021-03-10": 130.0},
        "bbb": {"2021-03-05": 50.0, "2021-03-08": 50.0,
                "2021-03-09": 50.0, "2021-03-10": 55.0},
    }


def _ctx(**over):
    base = dict(
        ticker="AAA", as_of_date="2021-03-05", rule="trailing_stop",
        entry_date="2021-01-04", entry_price=90.0, peak_price=100.0,
        current_price=95.0, shares=10, hold_days=60, sector="Tech",
        market_cap=1e10,
        top_candidates=(("BBB", 0.9),),
    )
    base.update(over)
    return ExitContext(**base)


def test_forward_returns_use_trading_days_from_the_calendar():
    cal = ["2021-03-05", "2021-03-08", "2021-03-09", "2021-03-10"]
    fwd = build_forward_returns(_cache(), cal, horizon=2)
    assert fwd[("aaa", "2021-03-05")] == pytest.approx(0.20)   # 120/100 - 1
    assert fwd[("aaa", "2021-03-09")] is None     # not enough future bars
    assert fwd[("aaa", "2021-03-10")] is None     # recorded as censored, not dropped


def test_veto_when_holding_beats_the_best_replacement():
    fwd = {("aaa", "2021-03-05"): 0.20, ("bbb", "2021-03-05"): 0.05}
    gate = OracleGate(fwd, horizon=2)
    assert gate.decide(_ctx()).veto is True


def test_no_veto_when_the_replacement_would_have_done_better():
    fwd = {("aaa", "2021-03-05"): 0.02, ("bbb", "2021-03-05"): 0.15}
    gate = OracleGate(fwd, horizon=2)
    assert gate.decide(_ctx()).veto is False


def test_cash_is_the_fallback_when_nothing_can_be_bought():
    fwd = {("aaa", "2021-03-05"): 0.02}
    gate = OracleGate(fwd, horizon=2)
    assert gate.decide(_ctx(top_candidates=())).veto is True


def test_an_unobservable_forward_return_never_vetoes():
    gate = OracleGate({}, horizon=2)
    assert gate.decide(_ctx()).veto is False


def test_margin_must_be_cleared():
    fwd = {("aaa", "2021-03-05"): 0.06, ("bbb", "2021-03-05"): 0.05}
    assert OracleGate(fwd, horizon=2, margin=0.0).decide(_ctx()).veto is True
    assert OracleGate(fwd, horizon=2, margin=0.02).decide(_ctx()).veto is False


def test_the_reference_declares_itself_and_reports_its_horizon():
    gate = OracleGate({}, horizon=20)
    d = gate.decide(_ctx())
    assert d.gate_id == "oracle:h20"
    assert gate.horizon == 20
