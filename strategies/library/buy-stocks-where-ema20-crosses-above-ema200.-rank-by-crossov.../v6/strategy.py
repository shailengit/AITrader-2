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
MIN_HOLD_DAYS = 0
TRAILING_STOP = 0.20
TAKE_PROFIT = 999.0       # disabled by default
TIME_STOP_DAYS = 9999     # disabled by default
MAX_SECTOR_COUNT = 2
BULL_EXPOSURE = 1.0
BEAR_EXPOSURE = 0.50
ANGLE_WEIGHT = 0.60
CAP_WEIGHT = 0.40
STRATEGY_NAME = "Golden Cross with Trailing Stop"


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
        close = df["Close"].values.astype(float)
        volume = df["Volume"].values.astype(float)
        dates = df["Date"].values

        # Compute EMAs
        close_series = pd.Series(close)
        ema20 = close_series.ewm(span=20, adjust=False).mean().values
        ema200 = close_series.ewm(span=200, adjust=False).mean().values

        # Detect crossovers
        # Golden cross: ema20[i] > ema200[i] and ema20[i-1] <= ema200[i-1]
        # Death cross: ema20[i] < ema200[i] and ema20[i-1] >= ema200[i-1]
        crossovers = []
        death_crosses = []
        for i in range(1, len(close)):
            # Golden cross
            if ema20[i] > ema200[i] and ema20[i-1] <= ema200[i-1]:
                # Compute angle: slope of EMA20 over 5 days ending at i
                lookback = min(4, i)  # at least 5 points? Use i-4 to i
                if i >= 4:
                    angle = (ema20[i] - ema20[i-4]) / 4.0
                else:
                    angle = 0.0
                # Volume ratio: average volume over last 20 days / average volume over last 60 days? Not specified, use 20d avg
                vol_20 = np.mean(volume[max(0,i-19):i+1])
                vol_60 = np.mean(volume[max(0,i-59):i+1])
                volume_ratio = vol_20 / vol_60 if vol_60 > 0 else 1.0
                crossovers.append({
                    "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                    "price": float(close[i]),
                    "angle": float(angle),
                    "volatility": float(np.std(close[max(0,i-13):i+1]) / close[i]),  # 14-day vol
                    "volume_ratio": float(volume_ratio),
                })
            # Death cross
            if ema20[i] < ema200[i] and ema20[i-1] >= ema200[i-1]:
                death_crosses.append({
                    "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                    "death_cross": True,
                })

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

        # Filter universe: price >= $5 and avg volume >= 500k over last 20 days
        if len(close) < 20:
            continue
        if close[-1] < 5.0:
            continue
        avg_vol_20 = np.mean(volume[-20:])
        if avg_vol_20 < 500_000:
            continue

        # Store
        stock_db[ticker] = {
            "close": close,
            "dates": dates,
            "ema20": ema20,
            "ema200": ema200,
            "crossovers": crossovers,
            "death_crosses": death_crosses,
            "market_cap": market_cap,
            "sector": sector,
        }
    return stock_db


def entry_score(candidate: dict, market_cap_stats: dict) -> float:
    """Score a candidate in [0, 1]. Higher = better.

    candidate has: ticker, angle, market_cap, price, sector, volume_ratio
    market_cap_stats has: cap_min, cap_max, cap_range

    Use ANGLE_WEIGHT and CAP_WEIGHT for the weighted score.
    Normalize angle and market_cap to [0, 1] before combining.
    """
    # Normalize angle: use global min/max from candidate? We'll use a fixed range or compute from all candidates?
    # Since we don't have global stats, we'll use a simple sigmoid or min-max with a reasonable range.
    # The plan says min-max across all candidates on that day, but we can't. Use a fixed range: assume angle between -1 and 1.
    # Better: use the candidate's angle relative to a typical range. We'll use a simple normalization: angle / (max_angle + 1e-9)
    # But we don't have max_angle. We'll use a fixed cap: angle between -5 and 5, then normalize to [0,1].
    # This is a simplification. For production, we'd need per-day stats.
    angle = candidate.get("angle", 0.0)
    # Clamp angle to [-5, 5] and normalize to [0,1]
    angle_clipped = max(-5.0, min(5.0, angle))
    angle_norm = (angle_clipped + 5.0) / 10.0  # 0 to 1

    # Normalize market cap using provided stats
    cap = candidate.get("market_cap", 0.0)
    cap_min = market_cap_stats.get("cap_min", 0.0)
    cap_max = market_cap_stats.get("cap_max", 1.0)
    cap_range = cap_max - cap_min
    if cap_range > 0:
        cap_norm = (cap - cap_min) / cap_range
    else:
        cap_norm = 0.5
    cap_norm = max(0.0, min(1.0, cap_norm))

    # Weighted score
    score = ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm
    return float(score)


def holding_score(ticker: str, date_str: str, holding: dict, market_cap_stats: dict) -> float:
    """Re-score an existing holding in [0, 1]. 0 = weak, rotate out.

    holding has: entry_date, entry_price, peak_price, shares, score, angle,
                 market_cap, sector, _stock_data
    holding._stock_data has the precomputed arrays: close, dates, ema20, ema200

    Use np.searchsorted(dates, np.datetime64(date_str)) to find the current index.
    """
    # No daily re-scoring: always return 1.0 to prevent rotation.
    return 1.0


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

    # Find current index
    idx = np.searchsorted(dates, np.datetime64(date_str))
    if idx >= len(dates):
        return None

    # 1. Death cross
    if idx > 0 and ema20[idx] < ema200[idx] and ema20[idx-1] >= ema200[idx-1]:
        return "Death Cross"

    # 2. Trailing stop
    entry_price = holding.get("entry_price", 0.0)
    peak_price = holding.get("peak_price", entry_price)
    # Update peak price
    current_close = close[idx]
    if current_close > peak_price:
        peak_price = current_close
        holding["peak_price"] = peak_price
    stop_level = peak_price * (1 - TRAILING_STOP)
    if current_close < stop_level:
        return "Trailing Stop"

    # 3. Take profit (disabled)
    # 4. Time stop
    entry_date = holding.get("entry_date", "")
    if entry_date:
        entry_dt = np.datetime64(entry_date)
        current_dt = np.datetime64(date_str)
        days_held = (current_dt - entry_dt).astype("timedelta64[D]").astype(int)
        if days_held >= TIME_STOP_DAYS:
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
