"""Keystone gate: replay must reproduce the exits recorded in journal_trade.

journal_trade has no exit_reason column, so the gate uses a structural
signature: min_hold_days=14 gates rotation, therefore no trade held < 14 days
can have been exited by rotation -- every one must be reproduced by the price
rules alone.

NOTE ON FILL CONVENTION: the recorded data is CLOSE-filled. Verified directly:
of 600 sampled short-hold trades, 600 matched the trigger day's close and 0
matched the next open. The adapter's next-open logic postdates the rows that
wrote journal_trade, so the replay must fill at the close to reproduce the
baseline at all. `fill="next_open"` is kept for sensitivity checks.

These tests are deliberately exhaustive rather than sampled: a sample cannot
establish that semantics are right across 6,093 trades. Expect ~2-3 minutes.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from app.services.exit_replay.entry_set import MQR_STRATEGY_ID, extract_entry_set
from app.services.exit_replay.gate import (
    HARD_HOLD_THRESHOLD_DAYS,
    run_reproduction_gate,
)
from app.services.exit_replay.price_panel import PricePanel


@pytest.fixture(scope="module")
def entries():
    return extract_entry_set(MQR_STRATEGY_ID)


@pytest.fixture(scope="module")
def panel():
    return PricePanel()


@pytest.fixture(scope="module")
def gate_result(entries, panel):
    """Price rules must stand alone: no rotation cap."""
    return run_reproduction_gate(entries, panel)


@pytest.fixture(scope="module")
def capped_result(entries, panel):
    """Corroboration: with the rotation cap, every trade should reproduce."""
    return run_reproduction_gate(entries, panel, cap_to_actual=True)


def test_hard_threshold_is_min_hold_days():
    assert HARD_HOLD_THRESHOLD_DAYS == 14


def test_hard_set_matches_expected_size(gate_result):
    assert gate_result["hard_total"] == 6_093


def test_short_hold_trades_reproduce_on_date_and_reason(gate_result):
    """Rule semantics must be exact: every short-hold mismatch must be a PRICE-only
    difference, never a wrong trigger date and never a censored replay."""
    bad = [m for m in gate_result["hard_mismatches"]
           if m["class"] in ("date_mismatch", "not_fully_observed")]
    assert bad == [], f"semantic divergence on {len(bad)} trades: {bad[:5]}"


def test_short_hold_prices_reproduce_except_one_stale_vintage(gate_result):
    """6,093 short-hold trades reproduce; exactly one price does not, and it is a
    data-vintage artifact rather than a bug.

    ALB entered 2022-06-02 and triggered 2022-06-13 (both dates correct, reason
    Trailing Stop correct). The recorded fill is 211.91, a value that appears in
    NO bar of ALB's 8,203-row history -- not as a close, not as an open, on any
    date. The panel's close for 2022-06-13 is 210.14 and the next open is 211.32.
    So the database was revised after that backtest wrote the row, and no replay
    against the current panel could reproduce the value.

    Pinned at exactly one: a second stale vintage, or any semantic regression,
    fails this test.
    """
    assert gate_result["hard_reproduced"] >= gate_result["hard_total"] - 1
    assert gate_result["hard_rate"] >= 0.9998


def test_soft_rate_is_consistent_with_the_price_rule_share(gate_result):
    """Rotation-exited long-hold trades legitimately do NOT reproduce here,
    because without a cap the replay continues to a later price-rule exit.
    Expected share ~56% (65.4% price-based minus the 20.5% short-held)."""
    assert gate_result["soft_rate"] >= 0.45, gate_result["soft_rate"]
    assert gate_result["soft_rate"] <= 0.75, gate_result["soft_rate"]


def test_capped_replay_reproduces_recorded_exits_for_all_hold_lengths(capped_result):
    """Strongest end-to-end check: capping at the recorded exit date means
    price-rule exits reproduce via the rule and rotation exits via the cap.

    The semantic claim asserted here is DATE agreement across the entire corpus:
    all 29,736 trades must trigger on the recorded date. Prices agree on 98.95%;
    the ~1% that differ are a data-vintage class (the panel was revised after
    those backtests wrote their rows), which is common-mode across every policy
    and therefore immaterial to policy COMPARISON."""
    assert capped_result["class_counts"].get("date_mismatch", 0) == 0, (
        f"{capped_result['class_counts'].get('date_mismatch')} trades triggered on the "
        f"wrong date: {capped_result['hard_mismatches'][:5]}"
    )
    total = capped_result["hard_total"] + capped_result["soft_total"]
    reproduced = capped_result["hard_reproduced"] + capped_result["soft_reproduced"]
    overall = reproduced / total if total else 0.0
    assert overall >= 0.95, (
        f"capped reproduction {overall:.4f} ({reproduced}/{total}); "
        f"classes {capped_result['class_counts']}"
    )
