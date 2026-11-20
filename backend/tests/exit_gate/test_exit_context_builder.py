"""Assembling the gate context from the simulation's own state.

The replacement list (`top_candidates`) is the point of this module. A gate that
cannot see what the freed slot would buy is deciding blind on the one variable
that determines whether holding helps -- the mistake phase 2 paid for.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.exit_gate.context import build_exit_context  # noqa: E402
from app.services.strategy_base import Signal  # noqa: E402


def _sig(ticker, score, sector="Tech"):
    return Signal(ticker=ticker, score=score, sector=sector)


def _holdings(*tickers, sector="Tech"):
    return {
        t: {"entry_date": "2021-01-04", "entry_price": 100.0, "peak_price": 120.0,
            "shares": 10, "score": 0.9, "market_cap": 2e10, "sector": sector}
        for t in tickers
    }


def _build(**over):
    kw = dict(
        ticker="AAA",
        current_date="2021-03-05",
        holding=_holdings("AAA")["AAA"],
        current_price=114.0,
        hold_days=60,
        rule="trailing_stop",
        holdings=_holdings("AAA", "BBB", sector="Tech"),
        today_signals=[_sig("CCC", 0.95, "Energy"), _sig("DDD", 0.90, "Health")],
        max_holdings=5,
        max_sector_count=2,
        top_k=5,
    )
    kw.update(over)
    return build_exit_context(**kw)


def test_context_mirrors_the_holding_and_derives_its_numbers():
    c = _build()
    assert c.ticker == "AAA"
    assert c.entry_date == "2021-01-04"
    assert c.entry_price == 100.0
    assert c.peak_price == 120.0
    assert c.current_price == 114.0
    assert c.hold_days == 60
    assert c.rule == "trailing_stop"
    assert c.sector == "Tech"
    assert c.market_cap == pytest.approx(2e10)
    assert c.ret == pytest.approx(0.14)
    assert c.drawdown_from_peak == pytest.approx(1.0 - 114.0 / 120.0)


def test_replacement_candidates_exclude_held_names_including_the_triggering_one():
    sigs = [_sig("AAA", 0.99, "Tech"), _sig("BBB", 0.98, "Tech"),
            _sig("CCC", 0.50, "Energy")]
    c = _build(today_signals=sigs)
    assert [t for t, _ in c.top_candidates] == ["CCC"]


def test_replacement_candidates_respect_the_sector_cap_against_current_holdings():
    # Tech already holds 2 of the cap of 2, so a third Tech name is not buyable.
    sigs = [_sig("NEWTECH", 0.99, "Tech"), _sig("XLE1", 0.40, "Energy")]
    c = _build(today_signals=sigs, max_sector_count=2)
    assert [t for t, _ in c.top_candidates] == ["XLE1"]


def test_replacement_candidates_are_score_descending_and_truncated_to_top_k():
    sigs = [_sig("A1", 0.10, "Energy"), _sig("A2", 0.90, "Energy"),
            _sig("A3", 0.50, "Health"), _sig("A4", 0.70, "Industrial")]
    c = _build(today_signals=sigs, top_k=2)
    assert c.top_candidates == (("A2", 0.90), ("A4", 0.70))


def test_duplicate_signals_do_not_produce_duplicate_candidates():
    sigs = [_sig("A1", 0.80, "Energy"), _sig("A1", 0.70, "Energy")]
    c = _build(today_signals=sigs)
    assert c.top_candidates == (("A1", 0.80),)


def test_free_slots_are_counted_before_this_exit_frees_another():
    c = _build(holdings=_holdings("AAA", "BBB", "CCC", "DDD", "EEE"), max_holdings=5)
    assert c.n_open_slots == 0
    c2 = _build(holdings=_holdings("AAA"), max_holdings=5)
    assert c2.n_open_slots == 4


def test_held_tickers_are_reported_sorted():
    c = _build(holdings=_holdings("CCC", "AAA", "BBB"))
    assert c.held_tickers == ("AAA", "BBB", "CCC")
