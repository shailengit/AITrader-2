"""The trade audit must know the cost model.

A costed run's recorded `return_pct` is net of both fills, so comparing it to a
GROSS (exit/entry - 1) formula flags every single trade. That produced 1,102
phantom issues on the V1 validation before this was fixed.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest

from validate_top5_100run import audit_run  # noqa: E402


def _trades():
    # 10 shares, entry 100 -> exit 110, 10 bps per side.
    buy_notional, sell_notional = 1000.0, 1100.0
    cost = 10 / 10_000.0
    pnl = sell_notional - buy_notional - cost * buy_notional - cost * sell_notional
    return [
        {"ticker": "AAA", "side": "BUY", "entry_date": "2024-02-01",
         "exit_date": "", "entry_price": 100.0, "exit_price": 0.0,
         "return_pct": 0.0, "holding_days": 0, "exit_reason": "New Entry",
         "pnl_dollars": 0.0},
        {"ticker": "AAA", "side": "SELL", "entry_date": "2024-02-01",
         "exit_date": "2024-03-01", "entry_price": 100.0, "exit_price": 110.0,
         "return_pct": round(pnl / buy_notional * 100, 2),
         "holding_days": 29, "exit_reason": "Take Profit",
         "pnl_dollars": round(pnl, 2)},
    ]


def test_a_costed_run_is_clean_when_the_audit_is_told_the_cost():
    a = audit_run("2024-01-01", "2024-12-31", _trades(), [], {}, cost_bps=10.0)
    assert a["n_issues"] == 0, a["issues"]


def test_the_same_trades_look_wrong_against_a_gross_formula():
    a = audit_run("2024-01-01", "2024-12-31", _trades(), [], {}, cost_bps=0.0)
    assert a["n_issues"] == 1
    assert "return_pct" in a["issues"][0]


def test_a_zero_cost_run_still_reconciles():
    t = _trades()
    t[1]["return_pct"] = 10.0
    t[1]["pnl_dollars"] = 100.0
    a = audit_run("2024-01-01", "2024-12-31", t, [], {}, cost_bps=0.0)
    assert a["n_issues"] == 0, a["issues"]
