"""As-of features for the candidate scorer.

The as-of test is the point of this module: appending future bars must not change
any feature value for an earlier date. A leak here would not crash -- it would
quietly inflate every out-of-sample number downstream.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd

from app.services.exit_replay.features import FEATURE_COLUMNS, build_features
from app.services.exit_replay.ranking import RankingPanel

# 'sector' is a string (np.isfinite would raise) and 'days_to_earnings' is
# deliberately NaN when there is no calendar row, so neither belongs in a
# blanket finiteness assertion.
_NUMERIC = [c for c in FEATURE_COLUMNS if c not in ("sector", "days_to_earnings")]


def _panel(n_dates=120, n_tickers=3):
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    closes = np.array([[100.0 + 10 * j + i for j in range(n_tickers)]
                       for i in range(n_dates)])
    scores = closes / closes.max()
    return RankingPanel(dates, ["AAA", "BBB", "CCC"], closes, scores,
                        {"AAA": "Tech", "BBB": "Tech", "CCC": "Energy"})


def test_build_features_has_all_columns_and_numeric_values_finite():
    rp = _panel()
    f = build_features(rp, 80, 0)
    assert set(f) >= set(FEATURE_COLUMNS), set(FEATURE_COLUMNS) - set(f)
    assert all(np.isfinite(f[k]) for k in _NUMERIC), {
        k: f[k] for k in _NUMERIC if not np.isfinite(f[k])}


def test_features_are_unchanged_by_appending_future_bars():
    """THE AS-OF TEST. A feature at date i must not depend on later bars."""
    rp = _panel(n_dates=120)
    before = build_features(rp, 80, 0)

    dates2 = pd.bdate_range("2020-01-01", periods=160)
    closes2 = np.array([[100.0 + 10 * j + i for j in range(3)] for i in range(160)])
    rp2 = RankingPanel(dates2, rp.tickers, closes2, closes2 / closes2.max(), rp.sectors)
    after = build_features(rp2, 80, 0)

    for k in FEATURE_COLUMNS:
        a, b = before[k], after[k]
        same = (a == b) or (isinstance(a, float) and isinstance(b, float)
                            and np.isnan(a) and np.isnan(b))
        assert same, f"{k} changed when future bars were appended: {a} -> {b}"


def test_features_are_finite_even_with_short_history():
    """Newly listed tickers have < 200 bars; the builder must not emit NaN."""
    rp = _panel(n_dates=30)
    f = build_features(rp, 25, 0)
    assert all(np.isfinite(f[k]) for k in _NUMERIC), {
        k: f[k] for k in _NUMERIC if not np.isfinite(f[k])}


def test_earnings_feature_is_nan_without_a_calendar_row():
    """Explicit NaN, not a crash, and not silently coerced to 0 -- the model
    handles NaN natively and 0 would mean 'earnings today'."""
    rp = _panel()
    f = build_features(rp, 80, 0, earnings=None)
    assert np.isnan(f["days_to_earnings"])


def test_earnings_feature_uses_the_calendar_when_supplied():
    rp = _panel()
    f = build_features(rp, 80, 0, earnings={"AAA": 12})
    assert f["days_to_earnings"] == 12.0


def test_sector_and_rank_context_are_populated():
    rp = _panel()
    f = build_features(rp, 80, 0)
    assert f["sector"] == "Tech"
    assert 0.0 <= f["rank_frac"] <= 1.0
