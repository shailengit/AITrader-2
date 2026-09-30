"""Policy grid, per-policy evaluation, and honest aggregation."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd

from app.services.exit_replay.engine import CURRENT_MQR_POLICY, OFF, ExitPolicy
from app.services.exit_replay.evaluate import (
    NOTIONAL_PER_POSITION,
    evaluate_policy,
    summarise,
)
from app.services.exit_replay.policies import FIT_END, POLICY_GRID, VAL_END


class FakePanel:
    """Entry 2020-02-03 at 100; the 02-05 close of 155 fires +50% take profit."""

    def bars(self, *a, **k):
        return pd.DataFrame([
            {"Date": pd.Timestamp("2020-02-04"), "Open": 101, "High": 105, "Low": 99,  "Close": 104},
            {"Date": pd.Timestamp("2020-02-05"), "Open": 104, "High": 156, "Low": 103, "Close": 155},
            {"Date": pd.Timestamp("2020-02-06"), "Open": 152, "High": 153, "Low": 128, "Close": 130},
        ])

    def next_open(self, t, d):
        return {"2020-02-05": 152.0}.get(pd.Timestamp(d).strftime("%Y-%m-%d"))


def _one_entry():
    return pd.DataFrame([{
        "ticker": "AAPL", "entry_date": pd.Timestamp("2020-02-03"),
        "entry_px": 100.0, "qty": 10.0,
        "exit_date": pd.Timestamp("2020-03-02"), "exit_px": 155.0,
        "hold_days_calendar": 28,
    }])


def test_grid_contains_baseline_and_named_variants():
    assert "baseline" in POLICY_GRID
    assert POLICY_GRID["baseline"] == CURRENT_MQR_POLICY
    assert POLICY_GRID["trail_off"].trailing_stop == OFF
    assert POLICY_GRID["time_60"].time_stop_days == 60
    assert POLICY_GRID["hard_off"].hard_stop_loss == OFF
    assert all(isinstance(v, ExitPolicy) for v in POLICY_GRID.values())


def test_split_boundaries():
    assert FIT_END == pd.Timestamp("2023-12-31")
    assert VAL_END == pd.Timestamp("2025-12-31")


def test_evaluate_returns_expected_columns_and_observed_row():
    df = evaluate_policy(_one_entry(), FakePanel(), POLICY_GRID["baseline"])
    for col in ("ticker", "exit_date", "exit_reason", "observed_fully",
                "pnl_pct", "pnl_dollars", "bucket"):
        assert col in df.columns, col
    row = df.iloc[0]
    assert row["bucket"] == "fit"
    assert row["observed_fully"] is True or row["observed_fully"] == True
    assert row["exit_reason"] == "Take Profit"
    assert round(float(row["pnl_pct"]), 4) == 0.55
    assert round(float(row["pnl_dollars"]), 2) == round(0.55 * NOTIONAL_PER_POSITION, 2)
    s = summarise(df)
    assert s["n_total"] == 1 and s["n_observed"] == 1 and s["n_censored"] == 0


def test_summarise_counts_censored_separately_and_excludes_from_pnl():
    df = pd.DataFrame([
        {"pnl_pct": 0.10, "pnl_dollars": 100.0, "observed_fully": True,
         "exit_reason": "Take Profit", "bucket": "fit",
         "exit_date": pd.Timestamp("2024-01-05")},
        {"pnl_pct": None, "pnl_dollars": None, "observed_fully": False,
         "exit_reason": "Window End", "bucket": "fit",
         "exit_date": pd.Timestamp("2024-01-08")},
    ])
    s = summarise(df)
    assert s["n_total"] == 2 and s["n_observed"] == 1 and s["n_censored"] == 1
    assert s["total_pnl_dollars"] == 100.0


def test_bucket_assignment_by_entry_date():
    df = pd.DataFrame([
        {"ticker": "A", "entry_date": pd.Timestamp("2023-12-29"), "entry_px": 1.0,
         "qty": 1.0, "exit_date": pd.Timestamp("2024-01-05"), "exit_px": 1.1,
         "hold_days_calendar": 7},
        {"ticker": "B", "entry_date": pd.Timestamp("2024-06-03"), "entry_px": 1.0,
         "qty": 1.0, "exit_date": pd.Timestamp("2024-06-10"), "exit_px": 1.1,
         "hold_days_calendar": 7},
        {"ticker": "C", "entry_date": pd.Timestamp("2026-02-02"), "entry_px": 1.0,
         "qty": 1.0, "exit_date": pd.Timestamp("2026-02-09"), "exit_px": 1.1,
         "hold_days_calendar": 7},
    ])
    out = evaluate_policy(df, FakePanel(), POLICY_GRID["baseline"])
    assert list(out["bucket"]) == ["fit", "validate", "out"]


def test_max_dd_is_finite_over_many_trades():
    """Pins the overflow fix: compounding thousands of per-trade returns hit
    numpy's overflow warning and produced inf, making max_dd meaningless."""
    import math

    n = 5_000
    df = pd.DataFrame({
        "pnl_pct": [0.01] * n,
        "pnl_dollars": [200.0] * n,
        "observed_fully": [True] * n,
        "exit_reason": ["Take Profit"] * n,
        "bucket": ["fit"] * n,
        "exit_date": pd.date_range("2020-01-01", periods=n, freq="D"),
    })
    s = summarise(df)
    assert math.isfinite(s["max_dd_pct"])


def test_drawdown_is_additive_in_dollars_not_compounded_returns():
    """A losing trade after a winning one must show a drawdown."""
    df = pd.DataFrame({
        "pnl_pct": [0.10, -0.10],
        "pnl_dollars": [2000.0, -2000.0],
        "observed_fully": [True, True],
        "exit_reason": ["Take Profit", "Trailing Stop"],
        "bucket": ["fit", "fit"],
        "exit_date": [pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-03")],
    })
    s = summarise(df)
    assert s["max_dd_pct"] > 0
