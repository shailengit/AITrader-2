"""Forward-return regret and MFE/MAE excursions (spec approaches A and C).

Answers "did we sell too early?" from the real forward path, with no rule replay.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd

from app.services.exit_replay.regret import (
    HORIZONS,
    excursion_stats,
    horizon_returns,
    regret_vs_actual,
)


def bars(n=30, start=100.0, step=1.0):
    """Bar i sits on day i+1 and closes at start + (i+1)*step, so the first
    forward bar is already one step above entry."""
    d0 = pd.Timestamp("2020-01-01")
    return pd.DataFrame([
        {"Date": d0 + pd.Timedelta(days=i + 1), "Open": start + i * step,
         "High": start + (i + 1) * step, "Low": start + (i - 1) * step,
         "Close": start + (i + 1) * step}
        for i in range(n)
    ])


def test_horizon_returns_uses_nth_trading_day_close():
    hr = horizon_returns(100.0, pd.Timestamp("2020-01-01"), bars(), horizons=(1, 5))
    assert round(hr[1], 4) == round((101.0 - 100.0) / 100.0, 4)
    assert round(hr[5], 4) == round((105.0 - 100.0) / 100.0, 4)


def test_horizon_returns_none_when_window_too_short():
    hr = horizon_returns(100.0, pd.Timestamp("2020-01-01"), bars(n=3), horizons=(5,))
    assert hr[5] is None


def test_horizons_constant_is_ascending():
    assert list(HORIZONS) == sorted(HORIZONS)
    assert HORIZONS[0] == 1


def test_regret_is_best_horizon_minus_actual():
    hr = {1: -0.05, 5: 0.02, 20: 0.20, 60: 0.15}
    assert round(regret_vs_actual(100.0, 110.0, hr), 4) == round(0.20 - 0.10, 4)


def test_regret_none_when_no_horizon_observed():
    assert regret_vs_actual(100.0, 110.0, {1: None, 5: None}) is None


class FakePanel:
    def bars(self, ticker, start, end):
        return pd.DataFrame([
            {"Date": pd.Timestamp("2020-02-04"), "Open": 101, "High": 120, "Low": 90, "Close": 110},
            {"Date": pd.Timestamp("2020-02-05"), "Open": 110, "High": 130, "Low": 105, "Close": 125},
        ])


def test_excursion_stats_uses_the_actual_holding_period():
    entry = pd.DataFrame([{
        "ticker": "AAPL", "entry_date": pd.Timestamp("2020-02-03"),
        "entry_px": 100.0, "qty": 1.0,
        "exit_date": pd.Timestamp("2020-02-05"), "exit_px": 125.0,
        "hold_days_calendar": 2,
    }])
    out = excursion_stats(entry, FakePanel())
    assert round(float(out.iloc[0]["mfe"]), 4) == 0.30   # high 130
    assert round(float(out.iloc[0]["mae"]), 4) == -0.10  # low 90
