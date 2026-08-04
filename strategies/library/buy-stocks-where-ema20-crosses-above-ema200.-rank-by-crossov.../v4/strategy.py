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
STRATEGY_NAME = "Golden Cross with Angle & Cap"

# Global bear market flag (set in precompute)
_bear_market = False


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
    global _bear_market
    stock_db = {}

    # Compute SPY 200-day MA for bear market filter
    try:
        spy_table = get_safe_table_name("SPY")
        spy_query = text(
            f'SELECT "Date", "Close" '
            f'FROM "{spy_table}" WHERE "Date" >= :start AND "Date" <= :end ORDER BY "Date"'
        )
        spy_df = pd.read_sql(spy_query, engine, params={"start": start, "end": end})
        if len(spy_df) >= 200:
            spy_close = spy_df["Close"].values.astype(float)
            spy_ema200 = pd.Series(spy_close).ewm(span=200, adjust=False).mean().values
            _bear_market = spy_close[-1] < spy_ema200[-1]
        else:
            _bear_market = False
    except Exception:
        _bear_market = False

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

        if len(df) < 200:
            continue

        # Convert to numpy arrays
        dates = df["Date"].values.astype("datetime64[D]")
        close = df["Close"].values.astype(float)
        high = df["High"].values.astype(float)
        low = df["Low"].values.astype(float)
        volume = df["Volume"].values.astype(float)

        # Compute EMAs
        ema20 = pd.Series(close).ewm(span=20, adjust=False).mean().values
        ema200 = pd.Series(close).ewm(span=200, adjust=False).mean().values

        # Compute ATR (20-day)
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        tr = np.maximum(high - low,
                        np.maximum(np.abs(high - prev_close),
                                   np.abs(low - prev_close)))
        atr = pd.Series(tr).rolling(window=20).mean().values

        # Compute average volume over last 20 days
        avg_vol_20 = pd.Series(volume).rolling(window=20).mean().values
        overall_avg_vol = volume.mean()
        volume_ratio = avg_vol_20 / overall_avg_vol if overall_avg_vol > 0 else np.ones_like(volume)

        # Fetch metadata
        meta_query = text(
            "SELECT sector, market_cap FROM stock_metadata WHERE ticker = :ticker"
        )
        try:
            meta_row = pd.read_sql(meta_query, engine, params={"ticker": ticker.upper()})
        except Exception:
            continue
        if meta_row.empty:
            continue
        sector = meta_row.iloc[0]["sector"]
        market_cap = meta_row.iloc[0]["market_cap"]
        if market_cap is None or market_cap <= 0:
            continue
        market_cap = float(market_cap)

        crossovers = []

        # Detect crossovers
        for i in range(1, len(close)):
            # Golden cross
            if ema20[i] > ema200[i] and ema20[i-1] <= ema200[i-1]:
                # Filters
                if close[i] < 5.0:
                    continue
                if avg_vol_20[i] < 100000:
                    continue
                if atr[i] / close[i] > 0.10:
                    continue

                # Compute angle: slope of EMA20 over last 3 days
                if i >= 2:
                    y = ema20[i-2:i+1]
                    x = np.array([0, 1, 2], dtype=float)
                    n = 3
                    slope = (n * np.sum(x * y) - np.sum(x) * np.sum(y)) / (n * np.sum(x**2) - np.sum(x)**2)
                else:
                    slope = 0.0
                angle_deg = float(np.degrees(np.arctan(slope)))

                crossovers.append({
                    "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                    "price": float(close[i]),
                    "angle": angle_deg,
                    "volatility": float(atr[i] / close[i]),
                    "volume_ratio": float(volume_ratio[i]),
                })

            # Death cross
            if ema20[i] < ema200[i] and ema20[i-1] >= ema200[i-1]:
                crossovers.append({
                    "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                    "price": float(close[i]),
                    "death_cross": True,
                })

        if not crossovers:
            continue

        stock_db[ticker] = {
            "close": close,
            "dates": dates,
            "ema20": ema20,
            "ema200": ema200,
            "crossovers": crossovers,
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
    global _bear_market
    if _bear_market:
        return 0.0

    # Normalize angle (degrees) to [0,1] by dividing by 90, cap at 1
    angle = candidate.get("angle", 0.0)
    norm_angle = min(angle / 90.0, 1.0)

    # Normalize log market cap
    mc = candidate.get("market_cap", 0)
    if mc <= 0:
        return 0.0
    log_mc = np.log(mc)
    cap_min = market_cap_stats.get("cap_min", log_mc)
    cap_max = market_cap_stats.get("cap_max", log_mc)
    if cap_max > cap_min:
        norm_cap = (log_mc - cap_min) / (cap_max - cap_min)
    else:
        norm_cap = 0.5
    norm_cap = max(0.0, min(1.0, norm_cap))

    score = ANGLE_WEIGHT * norm_angle + CAP_WEIGHT * norm_cap
    return float(score)


def holding_score(ticker: str, date_str: str, holding: dict, market_cap_stats: dict) -> float:
    """Re-score an existing holding in [0, 1]. 0 = weak, rotate out.

    holding has: entry_date, entry_price, peak_price, shares, score, angle,
                 market_cap, sector, _stock_data
    holding._stock_data has the precomputed arrays: close, dates, ema20, ema200

    Use np.searchsorted(dates, np.datetime64(date_str)) to find the current index.
    """
    stock_data = holding.get("_stock_data", {})
    dates = stock_data.get("dates")
    ema20 = stock_data.get("ema20")
    ema200 = stock_data.get("ema200")
    if dates is None or ema20 is None or ema200 is None:
        return 1.0  # fallback

    idx = np.searchsorted(dates, np.datetime64(date_str))
    if idx >= len(dates):
        idx = len(dates) - 1

    # Spread = (EMA20 - EMA200) / EMA200
    spread = (ema20[idx] - ema200[idx]) / ema200[idx] if ema200[idx] != 0 else 0.0

    # Normalize spread using min-max across holdings (provided in market_cap_stats)
    spread_min = market_cap_stats.get("spread_min", 0.0)
    spread_max = market_cap_stats.get("spread_max", 0.5)
    if spread_max > spread_min:
        norm_spread = (spread - spread_min) / (spread_max - spread_min)
    else:
        norm_spread = 0.5
    norm_spread = max(0.0, min(1.0, norm_spread))

    # Normalize log market cap (use static market_cap from holding)
    mc = holding.get("market_cap", 0)
    if mc <= 0:
        norm_cap = 0.5
    else:
        log_mc = np.log(mc)
        cap_min = market_cap_stats.get("cap_min", log_mc)
        cap_max = market_cap_stats.get("cap_max", log_mc)
        if cap_max > cap_min:
            norm_cap = (log_mc - cap_min) / (cap_max - cap_min)
        else:
            norm_cap = 0.5
        norm_cap = max(0.0, min(1.0, norm_cap))

    score = 0.60 * norm_spread + 0.40 * norm_cap
    return float(score)


def exit_check(ticker: str, date_str: str, holding: dict, stock_db: dict) -> Optional[str]:
    """Return exit reason string or None to hold.

    Priority order: Death Cross, Trailing Stop, Take Profit, Time Stop.
    Check holding._stock_data for indicator arrays.
    Use np.searchsorted(dates, np.datetime64(date_str)) for index lookup.
    """
    stock_data = holding.get("_stock_data", {})
    dates = stock_data.get("dates")
    close = stock_data.get("close")
    ema20 = stock_data.get("ema20")
    ema200 = stock_data.get("ema200")
    if dates is None or close is None or ema20 is None or ema200 is None:
        return None

    idx = np.searchsorted(dates, np.datetime64(date_str))
    if idx >= len(dates):
        idx = len(dates) - 1

    # 1. Death Cross
    if idx > 0:
        if ema20[idx] < ema200[idx] and ema20[idx-1] >= ema200[idx-1]:
            return "Death Cross"

    # 2. Trailing Stop
    peak_price = holding.get("peak_price", holding.get("entry_price", close[idx]))
    stop_level = peak_price * (1.0 - TRAILING_STOP)
    if close[idx] < stop_level:
        return "Trailing Stop"

    # 3. Take Profit (disabled)
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
