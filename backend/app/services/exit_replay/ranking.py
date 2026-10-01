"""Phase 3 spike: reconstruct the daily ranking, then validate it.

The rotation decision compares a holding against candidates, so the spike needs
the SCORE OF EVERY UNIVERSE TICKER ON EVERY DATE. The score is price-only
(`sigmoid(perf_3m * 10)`, sector-capped at 2), so it is deterministically
reconstructable from the price panel -- no simulator, no chaos.

This module builds two matrices once (dates x tickers): closes and scores. Every
later step is then a vectorised row lookup, and stage 2 (the learned policy) reads
the same matrices for its features.

VALIDATION IS THE POINT OF THIS FILE. A reconstruction that is subtly wrong would
silently corrupt every bound computed from it, so before any oracle runs we check
the strongest available ground truth: on a date when the strategy recorded a NEW
ENTRY, that ticker must appear in the reconstructed top-5.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.services.exit_replay._dates import as_naive_dates
from app.services.exit_replay.price_panel import PricePanel

# From sector_scanner_top5_rotation: sigmoid steepness for score/sizing.
MOMENTUM_K = 10.0
# 3-month lookback is CALENDAR days in the strategy's own definition.
LOOKBACK_DAYS = 90
TOP_N = 5
TOP_K_CANDIDATES = 20

# MQR's universe filter, from the strategy's own definition. Without these the
# reconstruction ranks high-volatility names the strategy would never buy (GME,
# MARA, CLSK...) and the entry-match validation collapses to ~26%.
MIN_MARKET_CAP = 5e9
MAX_VOL_14D = 0.05
VOL_WINDOW = 14

# Symbols present in stock_metadata that are not tradeable equities. 'OHLCV' is a
# metadata artifact (and carries duplicate Date rows); 'VIX' is an index.
NON_EQUITY = {"OHLCV", "VIX", "SPX", "NDX", "RUT", "DJI"}


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


@dataclass
class RankingPanel:
    """dates x tickers matrices of close and momentum score."""

    dates: pd.DatetimeIndex
    tickers: List[str]
    closes: np.ndarray      # (D, T) float
    scores: np.ndarray      # (D, T) float, NaN where undefined
    sectors: Dict[str, str]

    def date_index(self, d, snap: bool = True) -> Optional[int]:
        """Index of date `d`; with snap, the first trading day on or after `d`.

        Snapping matters because calendar dates are routinely not trading days
        (2020-01-01 is a holiday). Returning None for those made callers index
        with None, which numpy treats as an axis-adding slice.
        """
        d = pd.Timestamp(d)
        pos = int(self.dates.searchsorted(d))
        if pos < len(self.dates) and self.dates[pos] == d:
            return pos
        if snap and pos < len(self.dates):
            return pos
        return None

    def ticker_index(self, t: str) -> Optional[int]:
        try:
            return self.tickers.index(t)
        except ValueError:
            return None

    def ranked_on(self, i: int, exclude=(), top_k: int = TOP_K_CANDIDATES,
                  max_per_sector: int = 2) -> List[tuple]:
        """[(ticker, score)] ranked on date index i, sector-capped.

        Mirrors the strategy's selection: descending score, at most
        `max_per_sector` names per sector.
        """
        row = self.scores[i]
        order = np.argsort(-np.nan_to_num(row, nan=-np.inf))
        out, per_sector = [], {}
        for j in order:
            if not np.isfinite(row[j]):
                break
            t = self.tickers[j]
            if t in exclude:
                continue
            s = self.sectors.get(t, "Unknown")
            if per_sector.get(s, 0) >= max_per_sector:
                continue
            per_sector[s] = per_sector.get(s, 0) + 1
            out.append((t, float(row[j])))
            if len(out) >= top_k:
                break
        return out

    def forward_return(self, i: int, j: int, horizon: int) -> Optional[float]:
        """Close-to-close return for ticker j from date i over `horizon` trading days."""
        k = i + horizon
        if k >= len(self.dates):
            return None
        c0, c1 = self.closes[i, j], self.closes[k, j]
        if not (np.isfinite(c0) and np.isfinite(c1)) or c0 <= 0:
            return None
        return float(c1 / c0 - 1.0)


def build_ranking_panel(panel: PricePanel, tickers: List[str],
                        sector_map: Dict[str, str],
                        market_caps: Dict[str, float] | None = None,
                        start: str = "2016-01-01", end: str = "2026-09-28",
                        min_coverage: float = 0.5) -> RankingPanel:
    """Build the score/close matrices over a common date index."""
    market_caps = market_caps or {}
    frames = {}
    dup_tickers: List[str] = []
    for n, t in enumerate(tickers, 1):
        if n % 500 == 0:
            print(f"    loaded {n}/{len(tickers)} tickers", flush=True)
        if t in NON_EQUITY:
            continue
        df = panel.bars(t, start, end)
        if df.empty:
            continue
        s = pd.Series(df["Close"].to_numpy(dtype=float),
                      index=pd.DatetimeIndex(df["Date"]))
        # Some ticker tables carry DUPLICATE Date rows (intraday-scale data flattened
        # per date). Those break reindex and are also the tables that stalled an
        # earlier unbounded sweep. Keep the last row per date and count the ticker.
        if s.index.has_duplicates:
            dup_tickers.append(t)
            s = s[~s.index.duplicated(keep="last")]
        frames[t] = s

    if not frames:
        raise RuntimeError("no ticker data loaded")
    if dup_tickers:
        print(f"  note: {len(dup_tickers)} tickers had duplicate Date rows and were "
              f"deduplicated (last row kept): {dup_tickers[:5]}", flush=True)

    # Common index = SPY-like trading calendar: use the union, then keep dates with
    # enough coverage so a gap in one ticker does not define a spurious date.
    # ONE concatenate, not 1,500 successive .union() calls: the incremental union
    # was O(n) per call on a growing index and stalled a 1,500-ticker build for
    # minutes (and, with one pathological ticker, hours).
    idx = pd.DatetimeIndex(
        np.unique(np.concatenate([s.index.values for s in frames.values()]))
    ).sort_values()
    coverage = np.zeros(len(idx))
    for s in frames.values():
        coverage += np.isin(idx.values, s.index.values).astype(float)
    keep = coverage >= min_coverage * len(frames)
    idx = idx[keep]

    keep_tickers = sorted(frames)
    closes = np.full((len(idx), len(keep_tickers)), np.nan)
    for j, t in enumerate(keep_tickers):
        closes[:, j] = frames[t].reindex(idx).to_numpy(dtype=float)

    # perf_3m via a 90-CALENDAR-day lookback, matching the strategy's definition.
    scores = np.full_like(closes, np.nan)
    idx_np = idx.values
    for j in range(len(keep_tickers)):
        col = closes[:, j]
        # for each date, the last index at or before date-90d
        target = idx_np - np.timedelta64(LOOKBACK_DAYS, "D")
        pos = np.searchsorted(idx_np, target, side="right") - 1
        ok = pos >= 0
        base = np.full(len(idx), np.nan)
        base[ok] = col[pos[ok]]
        with np.errstate(invalid="ignore", divide="ignore"):
            perf = col / base - 1.0
        scores[:, j] = _sigmoid(perf * MOMENTUM_K)

    # ── universe filter: 14-day vol and market cap, as the strategy applies ──
    with np.errstate(invalid="ignore", divide="ignore"):
        rets = np.full_like(closes, np.nan)
        rets[1:] = closes[1:] / closes[:-1] - 1.0
    # rolling 14-day std, vectorised
    vol = np.full_like(closes, np.nan)
    for j in range(closes.shape[1]):
        col = pd.Series(rets[:, j])
        vol[:, j] = col.rolling(VOL_WINDOW).std().to_numpy()

    filtered = scores.copy()
    filtered[~np.isfinite(vol)] = np.nan
    filtered[vol > MAX_VOL_14D] = np.nan
    for j, t in enumerate(keep_tickers):
        mc = market_caps.get(t)
        if mc is None or not np.isfinite(mc) or mc < MIN_MARKET_CAP:
            filtered[:, j] = np.nan

    kept = int(np.isfinite(filtered[-1]).sum()) if len(idx) else 0
    print(f"  universe filter applied: {kept:,} of {len(keep_tickers):,} tickers pass "
          f"on the last date (vol<={MAX_VOL_14D:.0%}, mcap>=${MIN_MARKET_CAP/1e9:.0f}B)",
          flush=True)

    return RankingPanel(idx, keep_tickers, closes, filtered,
                        {t: sector_map.get(t, "Unknown") for t in keep_tickers})


def load_universe(engine) -> tuple[List[str], Dict[str, str], Dict[str, float]]:
    """Universe tickers and their sectors from stock_metadata."""
    from sqlalchemy import text
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT ticker, sector, market_cap FROM stock_metadata WHERE ticker IS NOT NULL"
        )).mappings().all()
    tickers, sectors, caps = [], {}, {}
    for r in rows:
        t = str(r["ticker"]).strip().upper()
        if not t or t in NON_EQUITY:
            continue
        tickers.append(t)
        sectors[t] = (r["sector"] or "Unknown")
        try:
            caps[t] = float(r["market_cap"]) if r["market_cap"] is not None else float("nan")
        except (TypeError, ValueError):
            caps[t] = float("nan")
    return sorted(set(tickers)), sectors, caps
