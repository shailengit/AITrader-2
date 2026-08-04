"""Strategy template — fill in the 4 functions below.

This is a KNOWN-WORKING template. Do NOT change:
- The imports at the top
- The engine wiring at the bottom
- The CONFIG instantiation
- The function signatures

Only fill in the bodies of precompute(), entry_score(), holding_score(), exit_check().
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


# ── Constants (override as needed) ─────────────────────────────────────────
AS_OF = "2020-01-01"
END = "2026-07-08"
CAPITAL = 100_000.0
MAX_HOLDINGS = 5
MIN_HOLD_DAYS = 5
TRAILING_STOP = 0.20
TAKE_PROFIT = 999.0       # disabled by default
TIME_STOP_DAYS = 60
MAX_SECTOR_COUNT = 2
BULL_EXPOSURE = 1.0
BEAR_EXPOSURE = 0.50
ANGLE_WEIGHT = 0.60
CAP_WEIGHT = 0.40
STRATEGY_NAME = "Golden Cross with Rotation"
MIN_PRICE = 5.0
MIN_VOLUME = 500_000
MAX_ATR_RATIO = 0.10
SLOPE_CAP = 0.005  # 0.5% of price per day


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  FILL IN THE 4 FUNCTIONS BELOW                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def precompute(tickers: List[str], start: str, end: str) -> Dict[str, Any]:
    """Build stock_db: ticker → {close, dates, ema20, ema200, crossovers, market_cap, sector, ...}.

    For each ticker:
      1. Get safe table name: get_safe_table_name(ticker)
      2. Query OHLCV: SELECT "Date", "Open", "High", "Low", "Close", "Volume"
         FROM "{table}" WHERE "Date" >= :start AND "Date" <= :end ORDER BY "Date"
         Use pd.read_sql(text(query), engine, params={...})
      3. Compute indicators (EMA20, EMA200, ATR, avg volume)
      4. Filter by price > $5, avg volume > 500k, ATR ratio < 10%
      5. Detect golden crosses (EMA20 crosses above EMA200) and death crosses
      6. Get metadata: SELECT sector, market_cap FROM stock_metadata WHERE ticker = :ticker
         Use ticker.upper() for the parameter
         IMPORTANT: market_cap can be None — skip if so
      7. Populate crossovers list with {date, price, angle, death_cross: True/False}

    Returns stock_db dict.
    """
    stock_db = {}
    for ticker in tickers:
        try:
            table = get_safe_table_name(ticker)
        except ValueError:
            continue

        query = text(
            f'SELECT "Date", "Open", "High", "Low", "Close", "Volume" '
            f'FROM "{table}" WHERE "Date" >= :start AND "Date" <= :end ORDER BY "Date"'
        )
        try:
            df = pd.read_sql(query, engine, params={"start": start, "end": end})
        except Exception:
            continue
        if df.empty:
            continue

        close = df["Close"].values.astype(float)
        high = df["High"].values.astype(float)
        low = df["Low"].values.astype(float)
        volume = df["Volume"].values.astype(float)
        dates = df["Date"].values.astype("datetime64[D]")

        # Price filter: latest close > $5
        if close[-1] < MIN_PRICE:
            continue

        # Volume filter: average daily volume > 500k
        avg_vol = np.mean(volume)
        if avg_vol < MIN_VOLUME:
            continue

        # Compute EMAs
        close_series = pd.Series(close)
        ema20 = close_series.ewm(span=20, adjust=False).mean().values
        ema200 = close_series.ewm(span=200, adjust=False).mean().values

        # Compute ATR (20-day EMA of True Range)
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]  # first day no previous
        tr = np.maximum(high - low,
                        np.maximum(np.abs(high - prev_close),
                                   np.abs(low - prev_close)))
        atr = pd.Series(tr).ewm(span=20, adjust=False).mean().values
        atr_ratio = atr / close
        if np.any(atr_ratio[-20:] > MAX_ATR_RATIO):  # check recent 20 days
            continue

        # Detect crossovers
        crossovers = []
        for i in range(1, len(close)):
            # Golden cross
            if ema20[i-1] <= ema200[i-1] and ema20[i] > ema200[i]:
                # Compute slope of spread over last 5 days
                if i >= 5:
                    spread_today = ema20[i] - ema200[i]
                    spread_5 = ema20[i-5] - ema200[i-5]
                    slope = (spread_today - spread_5) / 5.0
                else:
                    slope = 0.0
                crossovers.append({
                    "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                    "price": float(close[i]),
                    "angle": float(slope),
                    "death_cross": False
                })
            # Death cross
            elif ema20[i-1] >= ema200[i-1] and ema20[i] < ema200[i]:
                crossovers.append({
                    "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                    "price": float(close[i]),
                    "angle": 0.0,
                    "death_cross": True
                })

        if not crossovers:
            continue

        # Fetch metadata
        meta_query = text(
            "SELECT sector, market_cap FROM stock_metadata WHERE ticker = :ticker"
        )
        try:
            meta_df = pd.read_sql(meta_query, engine, params={"ticker": ticker.upper()})
        except Exception:
            continue
        if meta_df.empty:
            continue
        sector = meta_df.iloc[0]["sector"]
        market_cap = meta_df.iloc[0]["market_cap"]
        if market_cap is None or market_cap <= 0:
            continue
        market_cap = float(market_cap)

        stock_db[ticker] = {
            "close": close,
            "dates": dates,
            "ema20": ema20,
            "ema200": ema200,
            "crossovers": crossovers,
            "market_cap": market_cap,
            "sector": sector,
            "atr_ratio": float(atr_ratio[-1]),
            "avg_volume": float(avg_vol),
        }
    return stock_db


def entry_score(candidate: dict, market_cap_stats: dict) -> float:
    """Score a candidate in [0, 1]. Higher = better.

    candidate has: ticker, angle, market_cap, price, sector, volume_ratio
    market_cap_stats has: cap_min, cap_max, cap_range

    Use ANGLE_WEIGHT and CAP_WEIGHT for the weighted score.
    Normalize angle and market_cap to [0, 1] before combining.
    """
    angle = candidate.get("angle", 0.0)
    # Normalize angle: cap at SLOPE_CAP
    angle_score = min(1.0, max(0.0, angle / SLOPE_CAP))

    mcap = candidate.get("market_cap", 0)
    if mcap <= 0:
        return 0.0
    log_mcap = np.log10(mcap)
    cap_min = market_cap_stats.get("cap_min", 0)
    cap_max = market_cap_stats.get("cap_max", 1)
    if cap_max > cap_min:
        cap_score = (log_mcap - cap_min) / (cap_max - cap_min)
    else:
        cap_score = 0.5
    cap_score = max(0.0, min(1.0, cap_score))

    return ANGLE_WEIGHT * angle_score + CAP_WEIGHT * cap_score


def holding_score(ticker: str, date_str: str, holding: dict, market_cap_stats: dict) -> float:
    """Re-score an existing holding in [0, 1]. 0 = weak, rotate out.

    holding has: entry_date, entry_price, peak_price, shares, score, angle,
                 market_cap, sector, _stock_data
    holding._stock_data has the precomputed arrays: close, dates, ema20, ema200

    Use np.searchsorted(dates, np.datetime64(date_str)) to find the current index.
    """
    sd = holding.get("_stock_data", {})
    dates = sd.get("dates")
    ema20 = sd.get("ema20")
    ema200 = sd.get("ema200")
    market_cap = holding.get("market_cap", 0)
    if dates is None or ema20 is None or ema200 is None or market_cap <= 0:
        return 0.0

    idx = np.searchsorted(dates, np.datetime64(date_str))
    if idx >= len(dates):
        idx = len(dates) - 1
    if idx < 5:
        # Not enough data to compute slope
        angle_score = 0.0
    else:
        spread_today = ema20[idx] - ema200[idx]
        spread_5 = ema20[idx-5] - ema200[idx-5]
        slope = (spread_today - spread_5) / 5.0
        angle_score = min(1.0, max(0.0, slope / SLOPE_CAP))

    log_mcap = np.log10(market_cap)
    cap_min = market_cap_stats.get("cap_min", 0)
    cap_max = market_cap_stats.get("cap_max", 1)
    if cap_max > cap_min:
        cap_score = (log_mcap - cap_min) / (cap_max - cap_min)
    else:
        cap_score = 0.5
    cap_score = max(0.0, min(1.0, cap_score))

    return ANGLE_WEIGHT * angle_score + CAP_WEIGHT * cap_score


def exit_check(ticker: str, date_str: str, holding: dict, stock_db: dict) -> Optional[str]:
    """Return exit reason string or None to hold.

    Priority order: Death Cross, Trailing Stop, Take Profit, Time Stop.
    Check holding._stock_data for indicator arrays.
    Use np.searchsorted(dates, np.datetime64(date_str)) for index lookup.
    """
    sd = holding.get("_stock_data", {})
    dates = sd.get("dates")
    ema20 = sd.get("ema20")
    ema200 = sd.get("ema200")
    close = sd.get("close")
    if dates is None or ema20 is None or ema200 is None or close is None:
        return None

    idx = np.searchsorted(dates, np.datetime64(date_str))
    if idx >= len(dates):
        idx = len(dates) - 1
    if idx < 1:
        return None

    # 1. Death cross
    if ema20[idx] < ema200[idx] and ema20[idx-1] >= ema200[idx-1]:
        return "Death Cross"

    # 2. Trailing stop
    peak_price = holding.get("peak_price", holding.get("entry_price", 0))
    current_price = close[idx]
    if current_price < peak_price * (1.0 - TRAILING_STOP):
        return "Trailing Stop"

    # 3. Time stop
    entry_date_str = holding.get("entry_date", "")
    if entry_date_str:
        entry_date = np.datetime64(entry_date_str)
        current_date = np.datetime64(date_str)
        days_held = (current_date - entry_date).astype("timedelta64[D]").astype(int)
        if days_held > TIME_STOP_DAYS:
            return "Time Stop"

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
