"""Strategy template — fill in the 4 functions below.

⚠️  CRITICAL WARNINGS — violations produce LOSING strategies:
1. holding_score() MUST return a DYNAMIC score based on current indicators.
   Returning 1.0 disables rotation — the portfolio will hold stale positions
   indefinitely and lose money. Always re-score using current EMA spread, RSI,
   or whatever signal your strategy uses.
2. TAKE_PROFIT must be enabled (e.g. 0.30). Disabling it means winners never
   get locked in — they reverse and become losers.
3. TIME_STOP_DAYS must be reasonable (e.g. 60-120). Disabling it means
   stagnant positions are held forever, blocking better opportunities.
4. MIN_HOLD_DAYS should be >= 7 to prevent excessive churn.

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
import math


# ── Constants (override as needed) ─────────────────────────────────────────
AS_OF = "2020-01-01"
END = "2026-07-08"
CAPITAL = 100_000.0
MAX_HOLDINGS = 5
MIN_HOLD_DAYS = 1          # no minimum hold
TRAILING_STOP = 0.20
TAKE_PROFIT = 0.50         # 50% take profit
TIME_STOP_DAYS = 9999      # effectively disabled
MAX_SECTOR_COUNT = 999     # no sector cap
BULL_EXPOSURE = 1.0
BEAR_EXPOSURE = 0.50
ANGLE_WEIGHT = 0.60
CAP_WEIGHT = 0.40
STRATEGY_NAME = "Golden Cross with SPY Filter"

# Global cache for SPY regime (date string -> bool: close > SMA200)
_spy_above_sma200: Dict[str, bool] = {}


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  FILL IN THE 4 FUNCTIONS BELOW                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def precompute(tickers: List[str], start: str, end: str) -> Dict[str, Any]:
    """Build stock_db: ticker → {close, dates, ema20, ema200, crossovers, market_cap, sector}.

    For each ticker:
      1. Get safe table name: get_safe_table_name(ticker)
      2. Query OHLCV: SELECT "Date", "Open", "High", "Low", "Close", "Volume"
         FROM "{table}" WHERE "Date" >= :start AND "Date" <= :end ORDER BY "Date"
         Use pd.read_sql(text(query), engine, params={...})
      3. Compute indicators (EMA20, EMA200, etc.)
      4. Detect golden crosses (EMA20 crosses above EMA200) and death crosses
      5. Get metadata: SELECT sector, market_cap FROM stock_metadata WHERE ticker = :ticker
         Use ticker.upper() for the parameter
         IMPORTANT: market_cap can be None — skip if so
      6. Populate crossovers list with {date, price, angle, volatility, volume_ratio}
         and {date, death_cross: True} for death crosses

    Returns stock_db dict.
    """
    global _spy_above_sma200
    _spy_above_sma200 = {}  # reset

    stock_db = {}

    for ticker in tickers:
        try:
            table = get_safe_table_name(ticker)
        except ValueError:
            continue

        # Fetch OHLCV
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

        df["Date"] = pd.to_datetime(df["Date"])
        df.sort_values("Date", inplace=True)
        close = df["Close"].values.astype(float)
        dates = df["Date"].values.astype("datetime64[D]")

        # Compute EMAs
        ema20 = pd.Series(close).ewm(span=20, adjust=False).mean().values
        ema200 = pd.Series(close).ewm(span=200, adjust=False).mean().values

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

        # Detect crossovers
        crossovers = []
        for i in range(1, len(close)):
            # Golden cross
            if ema20[i] > ema200[i] and ema20[i-1] <= ema200[i-1]:
                # Compute angle over up to 5 bars
                lookback = min(5, i)
                slope = (ema20[i] - ema20[i - lookback]) / lookback
                angle = math.degrees(math.atan(slope))
                crossovers.append({
                    "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                    "price": float(close[i]),
                    "angle": float(angle),
                    "market_cap": market_cap,
                    "sector": sector,
                    "volume_ratio": 1.0  # not used
                })
            # Death cross
            if ema20[i] < ema200[i] and ema20[i-1] >= ema200[i-1]:
                crossovers.append({
                    "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                    "price": float(close[i]),
                    "death_cross": True,
                    "market_cap": market_cap,
                    "sector": sector
                })

        # Special handling for SPY: compute SMA200 and cache regime
        if ticker.upper() == "SPY":
            sma200 = pd.Series(close).rolling(window=200, min_periods=200).mean().values
            for i in range(len(close)):
                if not np.isnan(sma200[i]):
                    date_str = pd.Timestamp(dates[i]).strftime("%Y-%m-%d")
                    _spy_above_sma200[date_str] = bool(close[i] > sma200[i])

        stock_db[ticker] = {
            "close": close,
            "dates": dates,
            "ema20": ema20,
            "ema200": ema200,
            "crossovers": crossovers,
            "market_cap": market_cap,
            "sector": sector
        }

    return stock_db


def entry_score(candidate: dict, market_cap_stats: dict) -> float:
    """Score a candidate in [0, 1]. Higher = better.

    candidate has: ticker, angle, market_cap, price, sector, volume_ratio, date
    market_cap_stats has: cap_min, cap_max, cap_range

    Use ANGLE_WEIGHT and CAP_WEIGHT for the weighted score.
    Normalize angle and market_cap to [0, 1] before combining.
    """
    # SPY regime filter: only enter if SPY close > SMA200 on that day
    date_str = candidate.get("date", "")
    if not _spy_above_sma200.get(date_str, False):
        return 0.0

    angle = candidate.get("angle", 0.0)
    normalized_angle = min(angle / 90.0, 1.0)

    market_cap = candidate.get("market_cap", 0.0)
    cap_max = market_cap_stats.get("cap_max", 2e12)
    if cap_max is None or cap_max <= 0:
        cap_max = 2e12
    normalized_cap = min(market_cap / cap_max, 1.0)

    score = ANGLE_WEIGHT * normalized_angle + CAP_WEIGHT * normalized_cap
    return score


def holding_score(ticker: str, date_str: str, holding: dict, market_cap_stats: dict) -> float:
    """Re-score an existing holding in [0, 1]. 0 = weak, rotate out.

    CRITICAL: This function MUST return a dynamic score based on current indicator
    values. Returning 1.0 disables rotation and will produce a LOSING strategy.
    The original golden cross strategy re-scores using the current EMA20/EMA200
    spread normalized to [0,1] and combines with market cap.

    holding has: entry_date, entry_price, peak_price, shares, score, angle,
                 market_cap, sector, _stock_data
    holding._stock_data has the precomputed arrays: close, dates, ema20, ema200

    Use np.searchsorted(dates, np.datetime64(date_str)) to find the current index.
    """
    stock_data = holding.get("_stock_data", {})
    if not stock_data:
        return 0.5

    dates = stock_data.get("dates")
    ema20 = stock_data.get("ema20")
    ema200 = stock_data.get("ema200")
    if dates is None or ema20 is None or ema200 is None:
        return 0.5

    idx = np.searchsorted(dates, np.datetime64(date_str), side="left")
    if idx >= len(dates) or dates[idx] != np.datetime64(date_str):
        # date not found, use previous day
        idx = idx - 1
    if idx < 0 or idx >= len(ema20):
        return 0.5

    ema20_val = ema20[idx]
    ema200_val = ema200[idx]
    if ema200_val == 0:
        spread = 0.0
    else:
        spread = (ema20_val - ema200_val) / ema200_val

    # Normalize spread to [0,1] using max 0.10
    normalized_spread = min(spread / 0.10, 1.0)

    market_cap = holding.get("market_cap", 0.0)
    cap_max = market_cap_stats.get("cap_max", 2e12)
    if cap_max is None or cap_max <= 0:
        cap_max = 2e12
    normalized_cap = min(market_cap / cap_max, 1.0)

    score = 0.6 * normalized_spread + 0.4 * normalized_cap
    return score


def exit_check(ticker: str, date_str: str, holding: dict, stock_db: dict) -> Optional[str]:
    """Return exit reason string or None to hold.

    Priority order: Death Cross, Trailing Stop, Take Profit, Time Stop.
    Check holding._stock_data for indicator arrays.
    Use np.searchsorted(dates, np.datetime64(date_str)) for index lookup.
    """
    stock_data = holding.get("_stock_data", {})
    if not stock_data:
        return None

    dates = stock_data.get("dates")
    close = stock_data.get("close")
    ema20 = stock_data.get("ema20")
    ema200 = stock_data.get("ema200")
    if dates is None or close is None or ema20 is None or ema200 is None:
        return None

    idx = np.searchsorted(dates, np.datetime64(date_str), side="left")
    if idx >= len(dates) or dates[idx] != np.datetime64(date_str):
        idx = idx - 1
    if idx < 0 or idx >= len(close):
        return None

    # 1. Death Cross
    if idx >= 1 and ema20[idx] < ema200[idx] and ema20[idx-1] >= ema200[idx-1]:
        return "Death Cross"

    current_price = close[idx]

    # 2. Trailing Stop
    peak_price = holding.get("peak_price", current_price)
    if current_price <= peak_price * (1 - TRAILING_STOP):
        return "Trailing Stop"

    # 3. Take Profit
    entry_price = holding.get("entry_price", current_price)
    if current_price >= entry_price * (1 + TAKE_PROFIT):
        return "Take Profit"

    # 4. Time Stop (disabled)
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
