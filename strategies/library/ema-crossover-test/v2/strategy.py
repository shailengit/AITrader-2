"""EMA 20/50 Golden Cross Rotation — fill in the 4 functions below.

⚠️  CRITICAL WARNINGS — violations produce LOSING strategies:
1. holding_score() MUST return a DYNAMIC score based on current indicators.
   Returning 1.0 disables rotation — the portfolio will hold stale positions
   indefinitely and lose money. Always re-score using current EMA spread, RSI,
   or whatever signal your strategy uses.
2. TAKE_PROFIT must be enabled (e.g. 0.20). Disabling it means winners never
   get locked in — they reverse and become losers.
3. TIME_STOP_DAYS must be reasonable (e.g. 60). Disabling it means
   stagnant positions are held forever, blocking better opportunities.
4. MIN_HOLD_DAYS should be >= 5 to prevent excessive churn.

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
MAX_VOLATILITY = 0.05     # 20-day ATR / close reject threshold
EMA_FAST = 20
EMA_SLOW = 50
STRATEGY_NAME = "EMA20/50 Golden Cross Rotation"


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  FILL IN THE 4 FUNCTIONS BELOW                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _idx_for_date(dates: np.ndarray, date_str: str) -> int:
    """Return index of the last date <= date_str, or -1 if none."""
    target = np.datetime64(date_str)
    idx = int(np.searchsorted(dates, target, side="right")) - 1
    return idx


def precompute(tickers: List[str], start: str, end: str) -> Dict[str, Any]:
    """Build stock_db: ticker → {close, dates, ema20, ema50, crossovers,
    market_cap, sector, spread_min, spread_max}.

    Filters applied at entry time:
      - 20-day ATR / close <= MAX_VOLATILITY
      - SPY close > SPY 200-day SMA (regime filter)
    """
    stock_db: Dict[str, Any] = {}
    all_events: List[Dict[str, Any]] = []
    global_spread_min = np.inf
    global_spread_max = -np.inf

    # ── SPY regime filter ───────────────────────────────────────────────────
    buffer_start = (pd.Timestamp(start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    spy_table = get_safe_table_name("SPY")
    spy_query = text(
        f'SELECT "Date", "Close" '
        f'FROM "{spy_table}" WHERE "Date" >= :start AND "Date" <= :end '
        f'ORDER BY "Date"'
    )
    try:
        spy_df = pd.read_sql(spy_query, engine, params={"start": buffer_start, "end": end})
    except Exception:
        spy_df = pd.DataFrame()

    regime_ok: Dict[str, bool] = {}
    if not spy_df.empty and len(spy_df) >= 200:
        spy_df["Date"] = pd.to_datetime(spy_df["Date"])
        spy_close = spy_df["Close"].values
        spy_sma200 = spy_df["Close"].rolling(window=200).mean().values
        spy_dates = spy_df["Date"].values.astype("datetime64[D]")
        for i, d in enumerate(spy_dates):
            if not np.isnan(spy_sma200[i]) and spy_close[i] > spy_sma200[i]:
                regime_ok[str(d)[:10]] = True

    # ── Per-ticker data ─────────────────────────────────────────────────────
    for ticker in tickers:
        try:
            table = get_safe_table_name(ticker)
        except ValueError:
            continue

        ohlcv_query = text(
            f'SELECT "Date", "Open", "High", "Low", "Close", "Volume" '
            f'FROM "{table}" WHERE "Date" >= :start AND "Date" <= :end '
            f'ORDER BY "Date"'
        )
        try:
            df = pd.read_sql(ohlcv_query, engine, params={"start": buffer_start, "end": end})
        except Exception:
            continue

        if df.empty or len(df) < max(EMA_SLOW, 60):
            continue

        df["Date"] = pd.to_datetime(df["Date"])
        dates = df["Date"].values.astype("datetime64[D]")
        close = df["Close"].values
        high = df["High"].values
        low = df["Low"].values

        ema20 = df["Close"].ewm(span=EMA_FAST, adjust=False).mean().values
        ema50 = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean().values

        # 20-day ATR as % of close
        prev_close = np.concatenate(([np.nan], close[:-1]))
        tr = np.maximum(np.maximum(high - low, np.abs(high - prev_close)), np.abs(low - prev_close))
        atr = pd.Series(tr).rolling(window=20).mean().values
        atr_pct = np.where(close != 0, atr / close, np.nan)

        # track global spread distribution for holding-score normalization
        valid_spread = (
            (~np.isnan(ema20))
            & (~np.isnan(ema50))
            & (ema50 != 0)
        )
        if np.any(valid_spread):
            spreads = (ema20[valid_spread] - ema50[valid_spread]) / ema50[valid_spread]
            spreads = spreads[np.isfinite(spreads)]
            if len(spreads):
                global_spread_min = min(global_spread_min, float(np.min(spreads)))
                global_spread_max = max(global_spread_max, float(np.max(spreads)))

        # metadata
        try:
            meta_df = pd.read_sql(
                text('SELECT sector, market_cap FROM stock_metadata WHERE ticker = :t'),
                engine,
                params={"t": ticker.upper()},
            )
        except Exception:
            continue
        if meta_df.empty:
            continue

        sector = meta_df["sector"].iloc[0] if pd.notna(meta_df["sector"].iloc[0]) else "Unknown"
        market_cap = meta_df["market_cap"].iloc[0]
        if market_cap is None or market_cap <= 0:
            continue
        market_cap = float(market_cap)

        crossovers: List[Dict[str, Any]] = []
        for i in range(1, len(df)):
            d = str(dates[i])[:10]
            if d < start or d > end:
                continue

            if (
                np.isnan(ema20[i - 1])
                or np.isnan(ema50[i - 1])
                or np.isnan(ema20[i])
                or np.isnan(ema50[i])
            ):
                continue

            # Golden cross
            if ema20[i - 1] <= ema50[i - 1] and ema20[i] > ema50[i]:
                # volatility filter
                if not np.isnan(atr_pct[i]) and atr_pct[i] > MAX_VOLATILITY:
                    continue
                # regime filter (if SPY data is available)
                if regime_ok and d not in regime_ok:
                    continue

                if ema20[i - 1] != 0 and ema50[i - 1] != 0:
                    slope20 = (ema20[i] - ema20[i - 1]) / ema20[i - 1]
                    slope50 = (ema50[i] - ema50[i - 1]) / ema50[i - 1]
                    angle = float(slope20 - slope50)
                else:
                    angle = 0.0

                event = {
                    "ticker": ticker.upper(),
                    "date": d,
                    "price": float(close[i]),
                    "angle": angle,
                    "market_cap": market_cap,
                    "sector": sector,
                    "atr_pct": float(atr_pct[i]) if not np.isnan(atr_pct[i]) else 0.0,
                }
                all_events.append(event)
                crossovers.append(event)

            # Death cross
            elif ema20[i - 1] >= ema50[i - 1] and ema20[i] < ema50[i]:
                crossovers.append(
                    {
                        "date": d,
                        "price": float(close[i]),
                        "death_cross": True,
                    }
                )

        if crossovers:
            stock_db[ticker.upper()] = {
                "close": close,
                "dates": dates,
                "ema20": ema20,
                "ema50": ema50,
                "crossovers": crossovers,
                "market_cap": market_cap,
                "sector": sector,
            }

    # ── Per-day min-max normalization for entry scores ─────────────────────
    if all_events:
        events_by_date: Dict[str, List[Dict[str, Any]]] = {}
        for ev in all_events:
            events_by_date.setdefault(ev["date"], []).append(ev)

        for group in events_by_date.values():
            angles = np.array([e["angle"] for e in group])
            log_mcaps = np.log(np.array([e["market_cap"] for e in group]))

            a_min, a_max = float(np.min(angles)), float(np.max(angles))
            m_min, m_max = float(np.min(log_mcaps)), float(np.max(log_mcaps))
            a_range = a_max - a_min
            m_range = m_max - m_min

            for e in group:
                if a_range > 0:
                    e["angle_score"] = float((e["angle"] - a_min) / a_range)
                else:
                    e["angle_score"] = 1.0

                if m_range > 0:
                    e["mcap_score"] = float((np.log(e["market_cap"]) - m_min) / m_range)
                else:
                    e["mcap_score"] = 0.5

    # ── Attach global spread normalization bounds ────────────────────────────
    if np.isfinite(global_spread_min) and np.isfinite(global_spread_max):
        for data in stock_db.values():
            data["spread_min"] = float(global_spread_min)
            data["spread_max"] = float(global_spread_max)
    else:
        for data in stock_db.values():
            data["spread_min"] = -1.0
            data["spread_max"] = 1.0

    return stock_db


def entry_score(candidate: dict, market_cap_stats: dict) -> float:
    """Score a candidate in [0, 1]. Higher = better.

    Uses precomputed per-day normalized angle_score and mcap_score when
    available; falls back to a sigmoid / log-cap normalization otherwise.
    """
    angle_score = candidate.get("angle_score")
    mcap_score = candidate.get("mcap_score")

    if angle_score is None or mcap_score is None:
        # Fallback robust normalization
        angle = candidate.get("angle", 0.0)
        angle_score = 1.0 / (1.0 + np.exp(-angle * 100.0))

        mcap = candidate.get("market_cap", 0.0)
        cap_min = market_cap_stats.get("cap_min", 0.0)
        cap_max = market_cap_stats.get("cap_max", 0.0)
        if mcap is None or mcap <= 0 or cap_min <= 0 or cap_max <= cap_min:
            mcap_score = 0.5
        else:
            log_min = np.log(cap_min)
            log_max = np.log(cap_max)
            log_mcap = np.log(mcap)
            denom = log_max - log_min
            mcap_score = (log_mcap - log_min) / denom if denom > 0 else 0.5

    angle_score = float(angle_score)
    mcap_score = float(mcap_score)
    angle_score = max(0.0, min(1.0, angle_score))
    mcap_score = max(0.0, min(1.0, mcap_score))

    return ANGLE_WEIGHT * angle_score + CAP_WEIGHT * mcap_score


def holding_score(ticker: str, date_str: str, holding: dict, market_cap_stats: dict) -> float:
    """Re-score an existing holding in [0, 1]. 0 = weak, rotate out.

    Uses the current EMA20/EMA50 spread normalized to [0,1] and combines
    with a log-market-cap score. Young holdings are protected from rotation
    while still receiving a dynamic score.
    """
    data = holding.get("_stock_data")
    if data is None:
        return 0.0

    dates = data["dates"]
    ema20 = data["ema20"]
    ema50 = data["ema50"]

    idx = _idx_for_date(dates, date_str)
    if idx < 0:
        return 0.0

    e20 = ema20[idx]
    e50 = ema50[idx]
    if np.isnan(e20) or np.isnan(e50) or e50 == 0:
        return 0.0

    spread = (e20 - e50) / e50

    s_min = data.get("spread_min", -1.0)
    s_max = data.get("spread_max", 1.0)
    if s_max > s_min:
        spread_score = (spread - s_min) / (s_max - s_min)
    else:
        spread_score = 0.5
    spread_score = float(max(0.0, min(1.0, spread_score)))

    mcap = holding.get("market_cap", 0.0)
    cap_min = market_cap_stats.get("cap_min", 0.0)
    cap_max = market_cap_stats.get("cap_max", 0.0)
    if mcap is None or mcap <= 0 or cap_min <= 0 or cap_max <= cap_min:
        mcap_score = 0.5
    else:
        log_min = np.log(cap_min)
        log_max = np.log(cap_max)
        log_mcap = np.log(mcap)
        denom = log_max - log_min
        mcap_score = (log_mcap - log_min) / denom if denom > 0 else 0.5
    mcap_score = float(max(0.0, min(1.0, mcap_score)))

    base_score = ANGLE_WEIGHT * spread_score + CAP_WEIGHT * mcap_score

    # Protect very young holdings from rotation while still being dynamic.
    days_held = (pd.Timestamp(date_str) - pd.Timestamp(holding["entry_date"])).days
    if days_held < MIN_HOLD_DAYS:
        return float(max(base_score, 0.75))

    return float(base_score)


def exit_check(ticker: str, date_str: str, holding: dict, stock_db: dict) -> Optional[str]:
    """Return exit reason string or None to hold.

    Priority: Death Cross, Trailing Stop, Take Profit, Time Stop.
    Death cross ignores min_hold_days; all other exits respect it.
    """
    data = holding.get("_stock_data")
    if data is None:
        return None

    dates = data["dates"]
    close = data["close"]
    ema20 = data["ema20"]
    ema50 = data["ema50"]

    idx = _idx_for_date(dates, date_str)
    if idx < 0:
        return None

    cur_price = float(close[idx])
    if cur_price <= 0 or np.isnan(cur_price):
        return None

    entry_price = float(holding["entry_price"])
    peak_price = float(holding["peak_price"])

    # 1. Death cross — immediate, regardless of min hold
    if idx >= 1:
        e20_t = ema20[idx]
        e50_t = ema50[idx]
        e20_y = ema20[idx - 1]
        e50_y = ema50[idx - 1]
        if not (
            np.isnan(e20_t)
            or np.isnan(e50_t)
            or np.isnan(e20_y)
            or np.isnan(e50_y)
        ):
            if e20_t < e50_t and e20_y >= e50_y:
                return "Death Cross"

    days_held = (pd.Timestamp(date_str) - pd.Timestamp(holding["entry_date"])).days
    if days_held < MIN_HOLD_DAYS:
        return None

    # 2. Trailing stop
    if peak_price > 0 and cur_price <= peak_price * (1.0 - TRAILING_STOP):
        return "Trailing Stop"

    # 3. Take profit
    if entry_price > 0 and cur_price >= entry_price * (1.0 + TAKE_PROFIT):
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
