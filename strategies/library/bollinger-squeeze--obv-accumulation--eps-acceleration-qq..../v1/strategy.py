"""Bollinger Squeeze + OBV Accumulation + EPS Acceleration strategy.

Fills in the 4 filter functions for TradeCraft's StrategyEngine.
"""
import os
import sys
from typing import List, Dict, Any, Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.db.database import engine  # shared engine — do NOT use create_engine()
from app.utils.security import get_safe_table_name
import importlib.util


# ── Constants (override as needed) ───────────────────────────────────────
AS_OF = "2020-01-01"
END = "2026-07-08"
CAPITAL = 100_000.0
MAX_HOLDINGS = 3
MIN_HOLD_DAYS = 5           # plan: 5 days before replacement
TRAILING_STOP = 0.20        # engine safety net; active 5% trail is in exit_check
TAKE_PROFIT = 0.30          # keep enabled
TIME_STOP_DAYS = 20         # plan: 20 trading days (engine + custom check)
MAX_SECTOR_COUNT = 2
BULL_EXPOSURE = 1.0
BEAR_EXPOSURE = 0.33        # reduce effective exposure in bear regime
ANGLE_WEIGHT = 0.60         # unused by this strategy but required by config
CAP_WEIGHT = 0.40           # unused by this strategy but required by config
STRATEGY_NAME = "Bollinger Squeeze + OBV + EPS"

# Module-level caches (cleared on each precompute)
_REGIME_CACHE: Dict[str, str] = {}
_WEAK_DAYS_CACHE: Dict[str, int] = {}


# ── Helpers ──────────────────────────────────────────────────────────────
def _build_eps_series(price_dates: np.ndarray, ticker: str):
    """Return daily current-quarter EPS YoY growth, prior-quarter growth,
    and the report date that applies to each trading day.
    """
    n = len(price_dates)
    current = np.full(n, np.nan, dtype=float)
    prior = np.full(n, np.nan, dtype=float)
    report_arr = np.full(n, np.datetime64("NaT"), dtype="datetime64[D]")

    fin = None
    for id_col in ("ticker", "symbol"):
        try:
            fin = pd.read_sql(
                text(f'SELECT * FROM stock_financials_quarterly WHERE "{id_col}" = :t'),
                engine,
                params={"t": ticker.upper()},
            )
            if not fin.empty:
                break
        except Exception:
            fin = None
    if fin is None or fin.empty:
        return current, prior, report_arr

    date_col = None
    for c in ("date", "reportDate", "fiscalDateEnding", "period"):
        if c in fin.columns:
            date_col = c
            break
    eps_col = None
    for c in ("eps", "earningsPerShare", "eps_diluted", "eps_actual", "reportedEPS", "eps_basic"):
        if c in fin.columns:
            eps_col = c
            break
    if date_col is None or eps_col is None:
        return current, prior, report_arr

    fin[date_col] = pd.to_datetime(fin[date_col], errors="coerce")
    fin[eps_col] = pd.to_numeric(fin[eps_col], errors="coerce")
    fin = fin.dropna(subset=[date_col, eps_col]).sort_values(date_col)
    if len(fin) < 5:
        return current, prior, report_arr

    fin["fy"] = fin[date_col].dt.year.astype(int)
    fin["fq"] = fin[date_col].dt.quarter.astype(int)

    eps_map = {}
    for _, row in fin.iterrows():
        eps_map[(int(row["fy"]), int(row["fq"]))] = float(row[eps_col])

    growth_map = {}
    for (fy, fq), eps in eps_map.items():
        eps_ago = eps_map.get((fy - 1, fq))
        if eps_ago and eps_ago != 0:
            growth_map[(fy, fq)] = (eps - eps_ago) / abs(eps_ago) * 100.0
        else:
            growth_map[(fy, fq)] = np.nan

    prior_growth_map = {}
    for (fy, fq), g in growth_map.items():
        prior_key = (fy - 1, 4) if fq == 1 else (fy, fq - 1)
        prior_growth_map[(fy, fq)] = growth_map.get(prior_key, np.nan)

    fin_dates = np.array(fin[date_col].values, dtype="datetime64[D]")
    fin_fy = fin["fy"].values
    fin_fq = fin["fq"].values

    idxs = np.searchsorted(fin_dates, price_dates, side="right") - 1
    for i, idx in enumerate(idxs):
        if idx < 0:
            continue
        report = fin_dates[idx]
        days_since = int((price_dates[i] - report) / np.timedelta64(1, "D"))
        if days_since > 90:
            continue
        key = (int(fin_fy[idx]), int(fin_fq[idx]))
        current[i] = growth_map.get(key, np.nan)
        prior[i] = prior_growth_map.get(key, np.nan)
        report_arr[i] = report

    return current, prior, report_arr


def _compute_score(data: Dict[str, Any], idx: int) -> float:
    """Recompute the 0-1 entry/holding score for a given index."""
    if idx < 19:
        return 0.0

    width = data.get("width")
    max_width = data.get("max_width_20")
    obv = data.get("obv")
    obv_high = data.get("obv_high_20")
    obv_low = data.get("obv_low_20")
    eps_current = data.get("eps_current_growth")
    eps_prior = data.get("eps_prior_growth")
    eps_report = data.get("eps_report_date")
    dates = data.get("dates")

    if any(v is None for v in (width, max_width, obv, obv_high, obv_low,
                               eps_current, eps_prior, eps_report, dates)):
        return 0.0

    if not (np.isfinite(width[idx]) and np.isfinite(max_width[idx])):
        return 0.0

    squeeze_score = 1.0 - width[idx] / max_width[idx] if max_width[idx] > 0 else 1.0
    squeeze_score = float(np.clip(squeeze_score, 0.0, 1.0))

    obv_range = obv_high[idx] - obv_low[idx]
    obv_score = 0.5
    if obv_range > 0:
        obv_score = float(np.clip((obv[idx] - obv_low[idx]) / obv_range, 0.0, 1.0))

    eps_score = 0.0
    if not np.isnat(eps_report[idx]):
        days_since = int((dates[idx] - eps_report[idx]) / np.timedelta64(1, "D"))
        if days_since <= 90 and np.isfinite(eps_current[idx]) and np.isfinite(eps_prior[idx]):
            accel = eps_current[idx] - eps_prior[idx]
            eps_score = float(np.clip(accel / 100.0, 0.0, 1.0))

    score = 0.4 * squeeze_score + 0.3 * obv_score + 0.3 * eps_score
    return float(np.clip(score, 0.0, 1.0))


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  FILL IN THE 4 FUNCTIONS BELOW                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def precompute(tickers: List[str], start: str, end: str) -> Dict[str, Any]:
    """Build stock_db with Bollinger, OBV, EPS, liquidity and regime data."""
    global _REGIME_CACHE, _WEAK_DAYS_CACHE
    _REGIME_CACHE.clear()
    _WEAK_DAYS_CACHE.clear()

    buffer_start = (pd.Timestamp(start) - pd.Timedelta(days=300)).strftime("%Y-%m-%d")

    # ── SPY 200-day regime cache ────────────────────────────────────────────
    try:
        spy_table = get_safe_table_name("SPY")
        spy_df = pd.read_sql(
            text(
                f'SELECT "Date", "Close" '
                f'FROM "{spy_table}" WHERE "Date" >= :s AND "Date" <= :e '
                f'ORDER BY "Date"'
            ),
            engine,
            params={"s": buffer_start, "e": end},
        )
    except Exception:
        spy_df = pd.DataFrame()

    if not spy_df.empty:
        spy_df["Date"] = pd.to_datetime(spy_df["Date"])
        spy_df = spy_df.sort_values("Date")
        spy_close = spy_df["Close"].values.astype(float)
        spy_dates = np.array(spy_df["Date"].values, dtype="datetime64[D]")
        spy_sma200 = pd.Series(spy_close).rolling(window=200, min_periods=200).mean().values
        for i, d in enumerate(spy_dates):
            regime = "BEAR" if i >= 199 and spy_close[i] < spy_sma200[i] else "BULL"
            _REGIME_CACHE[str(d)[:10]] = regime

    # ── Metadata bulk load ─────────────────────────────────────────────────
    meta = {}
    try:
        meta_df = pd.read_sql(
            text("SELECT ticker, sector, market_cap FROM stock_metadata WHERE ticker = ANY(:tickers)"),
            engine,
            params={"tickers": [t.upper() for t in tickers]},
        )
        for _, row in meta_df.iterrows():
            meta[row["ticker"].upper()] = {
                "sector": row["sector"] if row["sector"] is not None else "Unknown",
                "market_cap": row["market_cap"],
            }
    except Exception:
        meta = {}

    stock_db: Dict[str, Any] = {}

    for ticker in tickers:
        try:
            table = get_safe_table_name(ticker)
        except ValueError:
            continue

        try:
            df = pd.read_sql(
                text(
                    f'SELECT "Date", "Open", "High", "Low", "Close", "Volume" '
                    f'FROM "{table}" WHERE "Date" >= :s AND "Date" <= :e '
                    f'ORDER BY "Date"'
                ),
                engine,
                params={"s": buffer_start, "e": end},
            )
        except Exception:
            continue

        if df.empty or len(df) < 60:
            continue

        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        for col in ("Open", "High", "Low", "Close", "Volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        if df[["Open", "High", "Low", "Close", "Volume"]].isna().any().any():
            continue

        close = df["Close"].values.astype(float)
        open_ = df["Open"].values.astype(float)
        high = df["High"].values.astype(float)
        low = df["Low"].values.astype(float)
        volume = df["Volume"].values.astype(float)
        dates = np.array(df["Date"].values, dtype="datetime64[D]")

        info = meta.get(ticker.upper(), {})
        sector = info.get("sector", "Unknown")
        market_cap = info.get("market_cap")
        if market_cap is None or market_cap <= 0:
            continue

        # ── Indicators ─────────────────────────────────────────────────────
        middle = pd.Series(close).rolling(window=20, min_periods=20).mean().values
        std = pd.Series(close).rolling(window=20, min_periods=20).std().values
        upper = middle + 2.0 * std
        lower = middle - 2.0 * std
        width = (upper - lower) / middle
        max_width = pd.Series(width).rolling(window=20, min_periods=20).max().values

        obv = np.zeros_like(close)
        obv[0] = volume[0]
        price_diff = np.diff(close)
        signed_vol = np.where(price_diff > 0, volume[1:],
                              np.where(price_diff < 0, -volume[1:], 0.0))
        obv[1:] = np.cumsum(signed_vol)
        obv_sma20 = pd.Series(obv).rolling(window=20, min_periods=20).mean().values
        obv_high_20 = pd.Series(obv).rolling(window=20, min_periods=20).max().values
        obv_low_20 = pd.Series(obv).rolling(window=20, min_periods=20).min().values

        dollar_volume = close * volume
        avg_dv_20 = pd.Series(dollar_volume).rolling(window=20, min_periods=20).mean().values

        eps_current, eps_prior, eps_report = _build_eps_series(dates, ticker)

        # ── Candidate generation ─────────────────────────────────────────────
        crossovers = []
        for i in range(20, len(dates)):
            if not (np.isfinite(width[i]) and np.isfinite(max_width[i]) and
                    np.isfinite(obv[i]) and np.isfinite(obv_sma20[i])):
                continue

            squeeze_active = width[i] < 0.10 and width[i - 1] < 0.10
            obv_ok = obv[i] > obv_sma20[i] and obv[i] > obv[i - 5]

            eps_ok = False
            eps_score = 0.0
            if (np.isfinite(eps_current[i]) and np.isfinite(eps_prior[i]) and
                    not np.isnat(eps_report[i])):
                accel = eps_current[i] - eps_prior[i]
                if accel >= 5.0:
                    eps_ok = True
                    eps_score = float(np.clip(accel / 100.0, 0.0, 1.0))

            liquid = avg_dv_20[i] >= 10_000_000.0
            gap_up = (i > 0 and close[i - 1] > 0 and
                      (open_[i] - close[i - 1]) / close[i - 1] > 0.05)

            if squeeze_active and obv_ok and eps_ok and liquid and not gap_up:
                squeeze_score = 1.0 - width[i] / max_width[i] if max_width[i] > 0 else 1.0
                squeeze_score = float(np.clip(squeeze_score, 0.0, 1.0))

                obv_range = obv_high_20[i] - obv_low_20[i]
                obv_score = 0.5
                if obv_range > 0:
                    obv_score = float(np.clip((obv[i] - obv_low_20[i]) / obv_range, 0.0, 1.0))

                score = 0.4 * squeeze_score + 0.3 * obv_score + 0.3 * eps_score
                crossovers.append({
                    "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                    "price": float(close[i]),
                    "sector": sector,
                    "market_cap": float(market_cap),
                    "squeeze_score": squeeze_score,
                    "obv_score": obv_score,
                    "eps_score": eps_score,
                    "score": float(score),
                })

        stock_db[ticker.upper()] = {
            "close": close,
            "open": open_,
            "high": high,
            "low": low,
            "volume": volume,
            "dates": dates,
            "width": width,
            "max_width_20": max_width,
            "obv": obv,
            "obv_sma20": obv_sma20,
            "obv_high_20": obv_high_20,
            "obv_low_20": obv_low_20,
            "eps_current_growth": eps_current,
            "eps_prior_growth": eps_prior,
            "eps_report_date": eps_report,
            "avg_dv_20": avg_dv_20,
            "market_cap": float(market_cap),
            "sector": sector,
            "crossovers": crossovers,
        }

    return stock_db


def entry_score(candidate: dict, market_cap_stats: dict) -> float:
    """Score a candidate in [0, 1]."""
    s = float(candidate.get("squeeze_score", 0.0))
    o = float(candidate.get("obv_score", 0.0))
    e = float(candidate.get("eps_score", 0.0))

    if not all(np.isfinite(x) for x in (s, o, e)):
        return 0.0

    score = 0.4 * s + 0.3 * o + 0.3 * e
    return float(np.clip(score, 0.0, 1.0))


def holding_score(ticker: str, date_str: str, holding: dict, market_cap_stats: dict) -> float:
    """Re-score an existing holding using current indicator values."""
    data = holding.get("_stock_data")
    if data is None:
        return 0.0

    dates = data.get("dates")
    if dates is None:
        return 0.0

    idx = np.searchsorted(dates, np.datetime64(date_str))
    if idx >= len(dates):
        idx = len(dates) - 1
    if idx < 0:
        return 0.0

    return _compute_score(data, idx)


def exit_check(ticker: str, date_str: str, holding: dict, stock_db: dict) -> Optional[str]:
    """Return exit reason or None to hold."""
    data = stock_db.get(ticker)
    if data is None:
        return None

    dates = data.get("dates")
    if dates is None:
        return None

    idx = np.searchsorted(dates, np.datetime64(date_str))
    if idx >= len(dates):
        idx = len(dates) - 1
    if idx < 0:
        return None

    close = float(data["close"][idx])
    open_ = float(data["open"][idx])
    entry_price = float(holding["entry_price"])

    # 1. Gap down > 5% at the open
    if idx > 0:
        prev_close = float(data["close"][idx - 1])
        if prev_close > 0 and (prev_close - open_) / prev_close > 0.05:
            return "Gap Down Exit"

    # 2. Stop loss (5% in bear regime, 8% otherwise)
    regime = _REGIME_CACHE.get(date_str, "BULL")
    stop_pct = 0.05 if regime == "BEAR" else 0.08
    if close < entry_price * (1.0 - stop_pct):
        return "Stop Loss"

    # 3. Trailing stop: activate at +10%, then trail 5% from peak
    peak = float(holding.get("peak_price", entry_price))
    if close > entry_price * 1.10 and close < peak * 0.95:
        return "Trailing Stop"

    # 4. Time stop: 20 trading days
    entry_idx = np.searchsorted(dates, np.datetime64(holding["entry_date"]))
    if entry_idx < len(dates) and idx - entry_idx >= 20:
        return "Time Stop"

    # 5. Re-score exit: score < 0.3 for 3 consecutive days
    score = _compute_score(data, idx)
    weak_key = f"{ticker}|{holding['entry_date']}"
    weak = _WEAK_DAYS_CACHE.get(weak_key, 0)
    if score < 0.3:
        weak += 1
    else:
        weak = 0
    _WEAK_DAYS_CACHE[weak_key] = weak
    if weak >= 3:
        return "Re-score Exit"

    return None


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  DO NOT CHANGE BELOW THIS LINE — engine wiring                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

_engine_path = os.path.join(os.path.dirname(__file__), "..", "..", "engine.py")
_spec = importlib.util.spec_from_file_location("strategies_engine_inline", _engine_path)
_engine = importlib.util.module_from_spec(_spec)
sys.modules["strategies_engine_inline"] = _engine
_spec.loader.exec_module(_engine)

CONFIG = _engine.StrategyConfig(
    as_of=AS_OF,
    end=END,
    capital=CAPITAL,
    max_holdings=MAX_HOLDINGS,
    min_hold_days=MIN_HOLD_DAYS,
    trailing_stop=TRAILING_STOP,
    take_profit=TAKE_PROFIT,
    time_stop_days=TIME_STOP_DAYS,
    max_sector_count=MAX_SECTOR_COUNT,
    bull_exposure=BULL_EXPOSURE,
    bear_exposure=BEAR_EXPOSURE,
    angle_weight=ANGLE_WEIGHT,
    cap_weight=CAP_WEIGHT,
    precompute_fn=precompute,
    entry_score_fn=entry_score,
    holding_score_fn=holding_score,
    exit_check_fn=exit_check,
    name=STRATEGY_NAME,
    score_squared_sizing=True,
)
