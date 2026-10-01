"""As-of candidate features for the scoring model.

EVERY feature is computed from bars at or before index `i`. The as-of unit test is
the guard: appending future bars must not change any value at `i`.

`market_cap` and `beta` are deliberately NOT features. `stock_metadata` holds
current values, not historical ones, so using them would leak the future. The
strategy itself uses them as universe filters -- that is a pre-existing flaw in the
strategy, mirrored for fidelity in `ranking.py`, and not one to inherit here.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

LOOKBACKS = (5, 10, 20, 60, 120)
MOMENTUM_LOOKBACK = 63          # ~3 months
RSI_WINDOW = 14
VOL_SHORT, VOL_LONG = 14, 60
RANGE_WINDOW = 252              # 52-week

#: 'sector' is categorical and 'days_to_earnings' is allowed to be NaN, so the
#: numeric-feature finite checks elsewhere must exclude both.
CATEGORICAL = ("sector",)
ALLOW_NAN = ("days_to_earnings",)

FEATURE_COLUMNS = (
    ["perf_3m"] + [f"perf_{k}d" for k in LOOKBACKS]
    + ["vol_14d", "vol_60d", "dist_52w_high", "dist_52w_low", "rsi_14",
       "px_over_sma20", "px_over_sma50", "px_over_sma200",
       "vol_ratio_50", "days_to_earnings", "rank_frac", "score_gap",
       "spy_above_sma200", "spy_ret_20d", "sector"]
)


def _ret(col: np.ndarray, k: int) -> float:
    """Return over the last k bars, clipping at the start of the series."""
    j0 = max(len(col) - 1 - k, 0)
    base = col[j0]
    if not np.isfinite(base) or base <= 0:
        return np.nan
    return float(col[-1] / base - 1.0)


def _rsi(col: np.ndarray, w: int = RSI_WINDOW) -> float:
    seg = col[max(0, len(col) - 1 - w):]
    if len(seg) < 3:
        return np.nan
    d = np.diff(seg)
    up, dn = float(d[d > 0].sum()), float(-d[d < 0].sum())
    if up + dn == 0:
        return 50.0
    return 100.0 * up / (up + dn)


def _sma(col: np.ndarray, w: int) -> float:
    seg = col[max(0, len(col) - w):]
    seg = seg[np.isfinite(seg)]
    return float(seg.mean()) if len(seg) else np.nan


def build_features(rp, i: int, j: int, incumbent_j: Optional[int] = None,
                   earnings: Optional[Dict[str, int]] = None) -> Dict[str, float]:
    """Features for candidate `j` as of date index `i`. Empty dict if unusable."""
    col = rp.closes[:i + 1, j]
    col = col[np.isfinite(col)]
    if len(col) == 0 or col[-1] <= 0:
        return {}
    px = float(col[-1])

    win = col[max(0, len(col) - RANGE_WINDOW):]
    hi52, lo52 = float(win.max()), float(win.min())

    rets = np.diff(col) / col[:-1] if len(col) > 1 else np.array([0.0])
    rets = rets[np.isfinite(rets)]

    r: Dict[str, float] = {}
    r["perf_3m"] = _ret(col, MOMENTUM_LOOKBACK)
    for k in LOOKBACKS:
        r[f"perf_{k}d"] = _ret(col, k)
    r["vol_14d"] = float(np.std(rets[-VOL_SHORT:])) if len(rets) >= 3 else 0.0
    r["vol_60d"] = float(np.std(rets[-VOL_LONG:])) if len(rets) >= 3 else 0.0
    r["dist_52w_high"] = float(px / hi52 - 1.0) if hi52 > 0 else np.nan
    r["dist_52w_low"] = float(px / lo52 - 1.0) if lo52 > 0 else np.nan
    r["rsi_14"] = _rsi(col)
    for w in (20, 50, 200):
        s = _sma(col, w)
        r[f"px_over_sma{w}"] = float(px / s) if np.isfinite(s) and s > 0 else np.nan

    # Volume is not carried in RankingPanel (the ranking is close-only), so the
    # ratio is unavailable here and filled to 0 below rather than faked.
    r["vol_ratio_50"] = np.nan

    r["days_to_earnings"] = (float(earnings.get(rp.tickers[j], np.nan))
                             if earnings else np.nan)

    row = rp.scores[i]
    finite = np.isfinite(row)
    rank = int((row[finite] > row[j]).sum()) if np.isfinite(row[j]) else 0
    r["rank_frac"] = float(rank / max(int(finite.sum()) - 1, 1))
    r["score_gap"] = (float(row[j] - row[incumbent_j])
                      if (incumbent_j is not None and np.isfinite(row[j])
                          and np.isfinite(row[incumbent_j])) else 0.0)
    r["sector"] = rp.sectors.get(rp.tickers[j], "Unknown")

    spy_j = rp.ticker_index("SPY")
    if spy_j is not None:
        sc = rp.closes[:i + 1, spy_j]
        sc = sc[np.isfinite(sc)]
        sma = _sma(sc, 200)
        r["spy_above_sma200"] = float(1.0 if (np.isfinite(sma) and len(sc)
                                              and sc[-1] > sma) else 0.0)
        r["spy_ret_20d"] = _ret(sc, 20) if len(sc) else 0.0
    else:
        r["spy_above_sma200"] = 1.0
        r["spy_ret_20d"] = 0.0

    # Short histories and missing values: fill to 0 rather than emit NaN, EXCEPT
    # days_to_earnings, which stays NaN because 0 would mean "earnings today".
    for k in FEATURE_COLUMNS:
        if k in CATEGORICAL or k in ALLOW_NAN:
            continue
        v = r.get(k)
        if v is None or not np.isfinite(v):
            r[k] = 0.0
    if not np.isfinite(r.get("spy_ret_20d", np.nan)):
        r["spy_ret_20d"] = 0.0
    r["days_to_earnings"] = float(r["days_to_earnings"]) if np.isfinite(
        r.get("days_to_earnings", np.nan)) else np.nan

    return {k: r[k] for k in FEATURE_COLUMNS}


def feature_frame(rp, i: int, js: List[int], incumbent_j: Optional[int] = None,
                  earnings: Optional[Dict[str, int]] = None) -> pd.DataFrame:
    """Features for several candidates on one date, as a frame (one row each)."""
    rows = []
    for j in js:
        f = build_features(rp, i, j, incumbent_j=incumbent_j, earnings=earnings)
        if f:
            rows.append(f)
    return pd.DataFrame(rows, columns=list(FEATURE_COLUMNS))
