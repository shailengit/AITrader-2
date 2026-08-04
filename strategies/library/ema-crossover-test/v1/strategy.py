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


# ── Constants (override as needed) ─────────────────────────────────────────
AS_OF = "2020-01-01"
END = "2026-07-08"
CAPITAL = 100_000.0
MAX_HOLDINGS = 10
MIN_HOLD_DAYS = 5         # minimum days before rotation — prevents churn
TRAILING_STOP = 0.10
TAKE_PROFIT = 0.20        # 20% take profit — locks in winners
TIME_STOP_DAYS = 60       # max hold — prevents indefinite holding of stale positions
MAX_SECTOR_COUNT = 3
BULL_EXPOSURE = 1.0
BEAR_EXPOSURE = 0.50
ANGLE_WEIGHT = 0.60
CAP_WEIGHT = 0.40
STRATEGY_NAME = "EMA20/50 Golden Cross Rotation"

EMA_FAST = 20
EMA_SLOW = 50
ATR_PERIOD = 20
VOLATILITY_FILTER = 0.05


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  FILL IN THE 4 FUNCTIONS BELOW                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def precompute(tickers: List[str], start: str, end: str) -> Dict[str, Any]:
    """Build stock_db: ticker → {close, dates, ema20, ema50, atr20, crossovers,
    market_cap, sector}.

    For each ticker:
      1. Get safe table name: get_safe_table_name(ticker)
      2. Query OHLCV: SELECT "Date", "Open", "High", "Low", "Close", "Volume"
         FROM "{table}" WHERE "Date" >= :start AND "Date" <= :end ORDER BY "Date"
         Use pd.read_sql(text(query), engine, params={...})
      3. Compute indicators (EMA20, EMA50, ATR20)
      4. Detect golden crosses (EMA20 crosses above EMA50) and death crosses
      5. Get metadata: SELECT sector, market_cap FROM stock_metadata WHERE ticker = :ticker
         Use ticker.upper() for the parameter
         IMPORTANT: market_cap can be None — skip if so
      6. Populate crossovers list with {date, price, angle, atr_pct, volume_ratio}
         and {date, death_cross: True} for death crosses

    Returns stock_db dict.
    """
    lookback_start = (pd.Timestamp(start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")

    # ── Load SPY for regime filter ─────────────────────────────────────────
    spy_dates = np.array([], dtype="datetime64[ns]")
    spy_close = np.array([])
    spy_sma200 = np.array([])
    try:
        spy_table = get_safe_table_name("SPY")
        spy_query = text(
            f'SELECT "Date", "Close" FROM "{spy_table}" '
            f'WHERE "Date" >= :start AND "Date" <= :end ORDER BY "Date"'
        )
        spy_df = pd.read_sql(spy_query, engine, params={"start": lookback_start, "end": end})
        if not spy_df.empty and len(spy_df) >= 200:
            spy_df["Date"] = pd.to_datetime(spy_df["Date"])
            spy_close_s = spy_df["Close"].astype(float)
            spy_sma200_s = spy_close_s.rolling(window=200).mean()
            spy_dates = spy_df["Date"].values
            spy_close = spy_close_s.values
            spy_sma200 = spy_sma200_s.values
    except Exception:
        pass

    def spy_above_sma200(date_str: str) -> bool:
        if len(spy_dates) == 0:
            return True
        target = np.datetime64(date_str)
        idx = int(np.searchsorted(spy_dates, target))
        if idx >= len(spy_dates):
            idx = len(spy_dates) - 1
        if idx > 0 and spy_dates[idx] > target:
            idx -= 1
        if idx < 0 or idx >= len(spy_dates) or spy_dates[idx] > target:
            return False
        c = spy_close[idx]
        s = spy_sma200[idx]
        if pd.isna(c) or pd.isna(s) or float(s) <= 0:
            return False
        return float(c) > float(s)

    stock_db: Dict[str, Any] = {}

    for ticker in tickers:
        try:
            table = get_safe_table_name(ticker)
        except ValueError:
            continue

        try:
            query = text(
                f'SELECT "Date", "Open", "High", "Low", "Close", "Volume" '
                f'FROM "{table}" WHERE "Date" >= :start AND "Date" <= :end '
                f'ORDER BY "Date"'
            )
            df = pd.read_sql(query, engine, params={"start": lookback_start, "end": end})
        except Exception:
            continue

        if df.empty or len(df) < EMA_SLOW + ATR_PERIOD + 5:
            continue

        df["Date"] = pd.to_datetime(df["Date"])
        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        volume = df["Volume"].astype(float)
        dates = df["Date"].values

        ema20_s = close.ewm(span=EMA_FAST, adjust=False).mean()
        ema50_s = close.ewm(span=EMA_SLOW, adjust=False).mean()
        ema20 = ema20_s.values
        ema50 = ema50_s.values

        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr20_s = tr.rolling(window=ATR_PERIOD).mean()
        atr20 = atr20_s.values
        atr_pct = atr20 / close.values

        vol_avg20 = volume.rolling(window=20).mean().values

        # ── Metadata ───────────────────────────────────────────────────────
        try:
            meta_query = text('SELECT sector, market_cap FROM stock_metadata WHERE ticker = :t')
            with engine.connect() as conn:
                row = conn.execute(meta_query, {"t": ticker.upper()}).fetchone()
        except Exception:
            continue

        if row is None:
            continue

        sector = row[0] if row[0] is not None else "Unknown"
        market_cap = row[1]
        if market_cap is None or market_cap <= 0:
            continue
        market_cap = float(market_cap)

        # ── Crossovers ─────────────────────────────────────────────────────
        crossovers: List[Dict[str, Any]] = []
        for i in range(1, len(df)):
            if pd.isna(ema20[i]) or pd.isna(ema50[i]) or pd.isna(ema20[i - 1]) or pd.isna(ema50[i - 1]):
                continue

            date_i = pd.Timestamp(dates[i]).strftime("%Y-%m-%d")
            price_i = float(close.iloc[i])

            if ema20[i - 1] <= ema50[i - 1] and ema20[i] > ema50[i]:
                # Golden cross
                if date_i < start or date_i > end:
                    continue
                if not spy_above_sma200(date_i):
                    continue

                ap = float(atr_pct[i]) if not pd.isna(atr_pct[i]) else 1.0
                if ap > VOLATILITY_FILTER:
                    continue

                slope20 = (ema20[i] - ema20[i - 1]) / ema20[i - 1] if ema20[i - 1] != 0 else 0.0
                slope50 = (ema50[i] - ema50[i - 1]) / ema50[i - 1] if ema50[i - 1] != 0 else 0.0
                angle = float(slope20 - slope50)

                vr = 1.0
                if not pd.isna(vol_avg20[i]) and float(vol_avg20[i]) > 0:
                    vr = float(volume.iloc[i]) / float(vol_avg20[i])

                crossovers.append({
                    "date": date_i,
                    "price": price_i,
                    "angle": angle,
                    "atr_pct": ap,
                    "volume_ratio": vr,
                })

            elif ema20[i - 1] >= ema50[i - 1] and ema20[i] < ema50[i]:
                # Death cross
                crossovers.append({
                    "date": date_i,
                    "price": price_i,
                    "angle": 0.0,
                    "death_cross": True,
                })

        stock_db[ticker.upper()] = {
            "close": close.values,
            "dates": dates,
            "ema20": ema20,
            "ema50": ema50,
            "atr20": atr20,
            "crossovers": crossovers,
            "market_cap": market_cap,
            "sector": sector,
        }

    # ── Min-max normalize golden-cross angles across all candidates ────────
    raw_angles = [
        co["angle"]
        for data in stock_db.values()
        for co in data["crossovers"]
        if not co.get("death_cross")
    ]
    if raw_angles:
        ang_min = float(min(raw_angles))
        ang_max = float(max(raw_angles))
        ang_range = ang_max - ang_min
        for data in stock_db.values():
            for co in data["crossovers"]:
                if co.get("death_cross"):
                    continue
                if ang_range > 0:
                    co["angle"] = float(max(0.0, min(1.0, (co["angle"] - ang_min) / ang_range)))
                else:
                    co["angle"] = 0.5

    return stock_db


def entry_score(candidate: dict, market_cap_stats: dict) -> float:
    """Score a candidate in [0, 1]. Higher = better.

    candidate has: ticker, angle, market_cap, price, sector, volume_ratio
    market_cap_stats has: cap_min, cap_max, cap_range

    Use ANGLE_WEIGHT and CAP_WEIGHT for the weighted score.
    Normalize angle and market_cap to [0, 1] before combining.
    """
    angle_score = float(candidate.get("angle", 0.0))
    angle_score = max(0.0, min(1.0, angle_score))

    mcap = float(candidate.get("market_cap", 0.0))
    if mcap <= 0:
        return 0.0

    cap_min = float(market_cap_stats.get("cap_min", 0.0))
    cap_max = float(market_cap_stats.get("cap_max", mcap))
    if cap_min <= 0 or cap_max <= cap_min:
        cap_score = 0.5
    else:
        log_min = np.log(cap_min)
        log_max = np.log(cap_max)
        log_range = log_max - log_min
        if log_range <= 0:
            cap_score = 0.5
        else:
            cap_score = (np.log(mcap) - log_min) / log_range

    cap_score = max(0.0, min(1.0, float(cap_score)))

    score = ANGLE_WEIGHT * angle_score + CAP_WEIGHT * cap_score
    return float(max(0.0, min(1.0, score)))


def holding_score(ticker: str, date_str: str, holding: dict, market_cap_stats: dict) -> float:
    """Re-score an existing holding in [0, 1]. 0 = weak, rotate out.

    CRITICAL: This function MUST return a dynamic score based on current indicator
    values. Returning 1.0 disables rotation and will produce a LOSING strategy.
    The strategy re-scores using the current EMA20/EMA50 spread normalized to
    [0,1] and combines with market cap.

    holding has: entry_date, entry_price, peak_price, shares, score, angle,
                 market_cap, sector, _stock_data
    holding._stock_data has the precomputed arrays: close, dates, ema20, ema50

    Use np.searchsorted(dates, np.datetime64(date_str)) to find the current index.
    """
    data = holding.get("_stock_data")
    if data is None:
        return 0.0

    dates = data.get("dates")
    ema20 = data.get("ema20")
    ema50 = data.get("ema50")
    if dates is None or ema20 is None or ema50 is None:
        return 0.0

    target = np.datetime64(date_str)
    idx = int(np.searchsorted(dates, target))
    if idx >= len(dates):
        idx = len(dates) - 1
    if idx > 0 and dates[idx] > target:
        idx -= 1
    if idx < 0:
        return 0.0

    e20 = float(ema20[idx])
    e50 = float(ema50[idx])
    if e50 == 0 or pd.isna(e20) or pd.isna(e50):
        return 0.0

    spread = (e20 - e50) / e50
    spread_score = 1.0 / (1.0 + np.exp(-spread * 20.0))
    spread_score = float(max(0.0, min(1.0, spread_score)))

    mcap = float(holding.get("market_cap", 0.0))
    cap_min = float(market_cap_stats.get("cap_min", 0.0))
    cap_max = float(market_cap_stats.get("cap_max", mcap))
    if mcap <= 0 or cap_min <= 0 or cap_max <= cap_min:
        cap_score = 0.5
    else:
        log_min = np.log(cap_min)
        log_max = np.log(cap_max)
        log_range = log_max - log_min
        if log_range <= 0:
            cap_score = 0.5
        else:
            cap_score = (np.log(mcap) - log_min) / log_range

    cap_score = float(max(0.0, min(1.0, cap_score)))

    score = ANGLE_WEIGHT * spread_score + CAP_WEIGHT * cap_score
    return float(max(0.0, min(1.0, score)))


def exit_check(ticker: str, date_str: str, holding: dict, stock_db: dict) -> Optional[str]:
    """Return exit reason string or None to hold.

    Priority order: Death Cross, Trailing Stop, Take Profit, Time Stop.
    Check holding._stock_data for indicator arrays.
    Use np.searchsorted(dates, np.datetime64(date_str)) for index lookup.
    """
    data = holding.get("_stock_data")
    if data is None:
        return None

    dates = data.get("dates")
    close_arr = data.get("close")
    ema20 = data.get("ema20")
    ema50 = data.get("ema50")
    if dates is None or close_arr is None or ema20 is None or ema50 is None:
        return None

    target = np.datetime64(date_str)
    idx = int(np.searchsorted(dates, target))
    if idx >= len(dates):
        idx = len(dates) - 1
    if idx > 0 and dates[idx] > target:
        idx -= 1
    if idx < 0:
        return None

    # 1. Death cross — immediate, ignores min hold
    if idx > 0:
        e20_prev = ema20[idx - 1]
        e50_prev = ema50[idx - 1]
        e20_now = ema20[idx]
        e50_now = ema50[idx]
        if not (pd.isna(e20_prev) or pd.isna(e50_prev) or pd.isna(e20_now) or pd.isna(e50_now)):
            if float(e20_prev) >= float(e50_prev) and float(e20_now) < float(e50_now):
                return "Death Cross"

    entry_date = holding.get("entry_date")
    if entry_date:
        days_held = (pd.Timestamp(date_str) - pd.Timestamp(entry_date)).days
    else:
        days_held = 9999

    # Other exits respect min hold
    if days_held < MIN_HOLD_DAYS:
        return None

    close_price = float(close_arr[idx])
    entry_price = float(holding.get("entry_price", close_price))
    peak_price = float(holding.get("peak_price", entry_price))

    # 2. Trailing stop
    if peak_price > 0:
        dd = (peak_price - close_price) / peak_price
        if dd >= TRAILING_STOP:
            return "Trailing Stop"

    # 3. Take profit
    if entry_price > 0:
        gain = (close_price - entry_price) / entry_price
        if gain >= TAKE_PROFIT:
            return "Take Profit"

    # 4. Time stop
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
