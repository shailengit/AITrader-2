"""Keystone gate: replay must reproduce the recorded price-rule exits.

CORRECTED 2026-09-30. The original gate inferred price-rule exits from a
structural signature (min_hold_days=14 gates rotation) because the design wrongly
believed no exit reason was recorded. `journal_trade.notes` carries
'backtest:<Reason>', so the gate now makes a direct claim: every trade whose
RECORDED reason is a price rule must be reproduced by replaying the current rules
uncapped. The signature survives as a consistency check.

FILL CONVENTION: the recorded data is CLOSE-filled (600/600 sampled short-hold
trades match the trigger-day close, 0 match the next open), so replay fills at the
close. `fill="next_open"` is kept for sensitivity checks.

Expect ~40s: these are exhaustive over the frozen set, not sampled.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from app.services.exit_replay.entry_set import MQR_STRATEGY_ID, extract_entry_set
from app.services.exit_replay.gate import (
    HARD_HOLD_THRESHOLD_DAYS,
    MIN_PRICE_REPRODUCTION,
    gate_passed,
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
    """End-to-end corroboration: cap at the recorded date and everything should match."""
    return run_reproduction_gate(entries, panel, cap_to_actual=True)


def test_price_rule_set_matches_the_recorded_reasons(gate_result):
    assert gate_result["price_total"] == 1_349
    assert gate_result["rotation_total"] == 664


def test_every_price_rule_trade_triggers_on_the_recorded_date(gate_result):
    """The semantic claim: rule precedence, the close-based peak, the activation
    arming test, the calendar-day time stop and the fill all agree with the
    adapter. A wrong date or a censored replay is a divergence."""
    assert gate_result["semantic_mismatches"] == 0, gate_result["mismatches"][:5]


def test_recorded_labels_agree_with_the_min_hold_signature(gate_result):
    """No trade held < 14 days may carry a rotation label, since rotation is gated
    by min_hold_days=14. This is now CHECKED rather than used to infer labels."""
    assert gate_result["label_inconsistencies"] == 0


def test_price_reproduction_clears_the_floor(gate_result):
    assert gate_result["price_rate"] >= MIN_PRICE_REPRODUCTION
    assert gate_result["price_reproduced"] == 1_342


def test_residual_price_differences_are_one_vintage_class(gate_result):
    """The 7 residuals are all ALB: the panel was revised after those backtests
    wrote their rows, so the recorded value exists in no bar of the current panel.
    A different ticker or a date mismatch here means the semantic claim is wrong."""
    residual = [m for m in gate_result["mismatches"] if m["class"] == "px_mismatch"]
    assert residual, "expected residuals to be present and explainable"
    assert {m["ticker"] for m in residual} == {"ALB"}, residual


def test_gate_passes_and_its_verdict_says_so(gate_result):
    assert gate_result["passed"] is True
    assert "reproduced" in gate_result["verdict"]


def test_capped_replay_matches_every_trade_on_date(capped_result):
    """Capping at the recorded exit date means price exits reproduce via the rule
    and rotation exits via the cap, so dates must agree across the whole set."""
    assert capped_result["class_counts"].get("date_mismatch", 0) == 0
    assert capped_result["capped_rate"] >= 0.95


def test_gate_passed_rejects_semantic_breakage_but_allows_vintage_drift():
    """gate_passed is the single source of truth; it must fail on semantics and
    tolerate only the enumerated vintage residue."""
    good = {"price_total": 100, "price_reproduced": 100, "semantic_mismatches": 0,
            "label_inconsistencies": 0}
    drift = {"price_total": 100, "price_reproduced": 99, "semantic_mismatches": 0,
             "label_inconsistencies": 0}
    wrong_date = {"price_total": 100, "price_reproduced": 100, "semantic_mismatches": 1,
                  "label_inconsistencies": 0}
    bad_labels = {"price_total": 100, "price_reproduced": 100, "semantic_mismatches": 0,
                  "label_inconsistencies": 1}
    empty = {"price_total": 0, "price_reproduced": 0, "semantic_mismatches": 0,
             "label_inconsistencies": 0}
    assert gate_passed(good)[0] is True
    assert gate_passed(drift)[0] is True          # 1% residue tolerated
    assert gate_passed(wrong_date)[0] is False
    assert gate_passed(bad_labels)[0] is False
    assert gate_passed(empty)[0] is False         # a vacuous gate must not pass


def test_hard_threshold_is_min_hold_days():
    assert HARD_HOLD_THRESHOLD_DAYS == 14
