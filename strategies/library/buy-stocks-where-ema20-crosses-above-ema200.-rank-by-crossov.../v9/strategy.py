"""Golden Cross Hold-Until-Exit Strategy.

Entry: EMA20 crosses above EMA200.
Score: 50% crossover angle + 50% log10(market cap).
Hold: No daily re-ranking / no rotation; positions are held until an exit trigger.
Exits: Death cross, then trailing stop.
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
MIN_HOLD_DAYS = 0            # strategy has no minimum hold per plan
TRAILING_STOP = 0.20
TAKE_PROFIT = 999.0        # disabled per plan
TIME_STOP_DAYS = 9999      # disabled per plan
MAX_SECTOR_COUNT = 3
BULL_EXPOSURE = 1.0
BEAR_EXPOSURE = 0.50
ANGLE_WEIGHT = 0.50        # 50% crossover angle
CAP_WEIGHT = 0.50          # 50% market cap
STRATEGY_NAME = "Golden Cross Hold Until Exit"


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  FILL IN THE 4 FUNCTIONS BELOW                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def precompute(tickers: List[str], start: str, end: str) -> Dict[str, Any]:
    """Build stock_db: ticker → {close, dates, ema20, ema200, crossovers, market_cap, sector}."""
    stock_db: Dict[str, Any] = {}
    start_dt = pd.Timestamp(start)
    lookback_start = (start_dt - pd.Timedelta(days=300)).strftime("%Y-%m-%d")

    for ticker in tickers:
        try:
            table = get_safe_table_name(ticker)
        except ValueError:
            continue

        query = text(
            f'SELECT "Date", "Open", "High", "Low", "Close", "Volume" '
            f'FROM "{table}" WHERE "Date" >= :start AND "Date" <= :end '
            f'ORDER BY "Date"'
        )
        try:
            df = pd.read_sql(query, engine, params={"start": lookback_start, "end": end})
        except Exception:
            continue

        if df.empty or len(df) < 220:
            continue

        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date").reset_index(drop=True)

        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        volume = df["Volume"].astype(float)

        # Universe filter: latest price > $5 and 20-day avg dollar volume > $1M
        if close.iloc[-1] <= 5.0:
            continue
        dollar_volume = close * volume
        avg_dv_20 = dollar_volume.rolling(window=20).mean().iloc[-1]
        if pd.isna(avg_dv_20) or avg_dv_20 <= 1_000_000:
            continue

        ema20 = close.ewm(span=20, adjust=False).mean()
        ema200 = close.ewm(span=200, adjust=False).mean()

        # ATR(20) for optional volatility filter
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr20 = true_range.rolling(window=20).mean()

        # Metadata
        try:
            meta_query = text(
                'SELECT sector, market_cap FROM stock_metadata WHERE ticker = :ticker'
            )
            meta_df = pd.read_sql(meta_query, engine, params={"ticker": ticker.upper()})
            if meta_df.empty:
                continue
            sector = (
                str(meta_df.iloc[0]["sector"])
                if meta_df.iloc[0]["sector"] is not None
                else "Unknown"
            )
            market_cap = meta_df.iloc[0]["market_cap"]
            if market_cap is None or market_cap <= 0:
                continue
            market_cap = float(market_cap)
        except Exception:
            continue

        crossovers: List[Dict[str, Any]] = []
        avg_dv_series = dollar_volume.rolling(window=20).mean()

        for i in range(201, len(df)):
            if (
                pd.isna(ema20.iloc[i])
                or pd.isna(ema200.iloc[i])
                or pd.isna(ema20.iloc[i - 1])
                or pd.isna(ema200.iloc[i - 1])
            ):
                continue

            prev_spread = ema20.iloc[i - 1] - ema200.iloc[i - 1]
            curr_spread = ema20.iloc[i] - ema200.iloc[i]
            price = float(close.iloc[i])

            # Golden cross
            if prev_spread <= 0 and curr_spread > 0:
                # Optional volatility filter: skip if ATR(20) > 10% of price
                atr = atr20.iloc[i]
                if pd.notna(atr) and atr > 0.10 * price:
                    continue

                # Crossover angle: difference in EMA slopes over a 3-day window
                lookback = 3
                if i >= lookback:
                    slope_ema20 = (ema20.iloc[i] - ema20.iloc[i - lookback]) / lookback
                    slope_ema200 = (ema200.iloc[i] - ema200.iloc[i - lookback]) / lookback
                    angle_deg = float(np.degrees(np.arctan(slope_ema20 - slope_ema200)))
                else:
                    angle_deg = 0.0
                angle_deg = max(0.0, min(90.0, angle_deg))

                avg_dv = avg_dv_series.iloc[i]
                avg_dv_val = float(avg_dv) if pd.notna(avg_dv) else 0.0

                crossovers.append(
                    {
                        "date": pd.Timestamp(df["Date"].iloc[i]).strftime("%Y-%m-%d"),
                        "price": price,
                        "angle": angle_deg,
                        "volatility": float(atr) if pd.notna(atr) else 0.0,
                        "avg_dollar_volume_20": avg_dv_val,
                    }
                )

            # Death cross
            elif prev_spread >= 0 and curr_spread < 0:
                crossovers.append(
                    {
                        "date": pd.Timestamp(df["Date"].iloc[i]).strftime("%Y-%m-%d"),
                        "price": price,
                        "angle": 0.0,
                        "death_cross": True,
                    }
                )

        if crossovers:
            stock_db[ticker.upper()] = {
                "close": close.values,
                "dates": df["Date"].values,
                "ema20": ema20.values,
                "ema200": ema200.values,
                "crossovers": crossovers,
                "market_cap": market_cap,
                "sector": sector,
            }

    return stock_db


def entry_score(candidate: dict, market_cap_stats: dict) -> float:
    """Score a candidate in [0, 1]. Higher = better.

    50% crossover angle (normalized by 90°) + 50% log10(market cap) min-max normalized.
    Tie-breaker: tiny boost from 20-day average dollar volume.
    """
    angle = candidate.get("angle", 0.0)
    market_cap = candidate.get("market_cap", 0.0)
    avg_dv = candidate.get("avg_dollar_volume_20", 0.0)

    # Angle component: normalize by 90 degrees
    angle_norm = max(0.0, min(1.0, angle / 90.0))

    # Market cap component: log10 min-max normalization
    cap_min = market_cap_stats.get("cap_min", 0.0)
    cap_max = market_cap_stats.get("cap_max", 1.0)

    if market_cap <= 0 or cap_min <= 0 or cap_max <= cap_min:
        cap_norm = 0.0
    else:
        log_cap = np.log10(market_cap)
        log_min = np.log10(cap_min)
        log_max = np.log10(cap_max)
        log_range = log_max - log_min
        if log_range <= 0:
            cap_norm = 0.5
        else:
            cap_norm = (log_cap - log_min) / log_range
            cap_norm = max(0.0, min(1.0, cap_norm))

    score = ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm

    # Tie-breaker: prefer higher average daily dollar volume
    score += 1e-12 * avg_dv

    return float(score)


def holding_score(ticker: str, date_str: str, holding: dict, market_cap_stats: dict) -> float:
    """Re-score an existing holding.

    This strategy intentionally does NOT rotate positions based on rank changes;
    positions are held until an exit condition triggers. Returning a top score
    prevents the engine from rotating out holdings prematurely.
    """
    return 1.0


def exit_check(ticker: str, date_str: str, holding: dict, stock_db: dict) -> Optional[str]:
    """Return exit reason string or None to hold.

    Priority: Death Cross, then Trailing Stop.
    """
    data = stock_db.get(ticker)
    if data is None:
        return None

    dates = data["dates"]
    ema20 = data["ema20"]
    ema200 = data["ema200"]
    close = data["close"]

    idx = np.searchsorted(dates, np.datetime64(date_str))
    if idx >= len(dates):
        idx = len(dates) - 1
    elif idx > 0 and dates[idx] > np.datetime64(date_str):
        idx -= 1

    if idx < 1:
        return None

    current_price = float(close[idx])
    if current_price <= 0:
        return None

    # Update peak price for trailing stop
    peak = holding.get("peak_price", holding.get("entry_price", current_price))
    if current_price > peak:
        holding["peak_price"] = current_price
        peak = current_price

    # 1. Death cross
    if (
        pd.notna(ema20[idx])
        and pd.notna(ema200[idx])
        and pd.notna(ema20[idx - 1])
        and pd.notna(ema200[idx - 1])
    ):
        if ema20[idx - 1] >= ema200[idx - 1] and ema20[idx] < ema200[idx]:
            return "Death Cross"

    # 2. Trailing stop
    dd = (peak - current_price) / peak
    if dd >= TRAILING_STOP:
        return f"Trailing Stop ({dd:.1%})"

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
