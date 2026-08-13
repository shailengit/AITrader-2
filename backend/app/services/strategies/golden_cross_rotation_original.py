"""
Golden Cross Rotation (Original) — Strategy subclass.

Faithful port of the original alpaca_runner scan/rank logic (Entry A + Entry B)
that ran live paper trading successfully on 2026-07-17 (b4c549b). The v2
strategy that replaced it added strict filters (volume-ratio >= 1.2, market-cap
floor >= $10B, and required the golden cross to occur on the exact latest day),
which caused it to generate zero candidates. This class restores the original
loose dual-entry logic:
  - Entry A: EMA20/200 golden cross within the last 5 days
  - Entry B: Price > EMA50 > EMA200 AND RSI > 60 AND volume > 1.2x avg
  - Rank by 60% crossover angle + 40% market cap, take top MAX_HOLDINGS.
  - No hard volume-ratio or market-cap floor (market cap only weights the score).
"""

import logging
import numpy as np
import pandas as pd
from sqlalchemy import Engine, text
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

from app.services.strategy_base import (
    Strategy,
    Signal,
    ExitCheck,
    RotationConfig,
    get_all_tickers,
)
from app.utils.security import get_safe_table_name

ANGLE_WEIGHT = 0.60
CAP_WEIGHT = 0.40
MAX_HOLDINGS = 5
MIN_HOLD_DAYS = 10
SIZING_PCTS = [0.30, 0.25, 0.20, 0.15, 0.10]
TRAILING_STOP_PCT = 0.08
TAKE_PROFIT_PCT = 0.20


class GoldenCrossRotationOriginal(Strategy):
    """Golden Cross Rotation using the original dual-entry signal logic."""

    def get_name(self) -> str:
        return "Golden Cross Rotation (Original)"

    @property
    def max_holdings(self) -> int:
        return MAX_HOLDINGS

    @property
    def sizing_pcts(self) -> List[float]:
        return SIZING_PCTS

    def get_rotation_config(self) -> RotationConfig:
        return RotationConfig(
            trailing_stop=TRAILING_STOP_PCT,
            take_profit=TAKE_PROFIT_PCT,
            min_hold_days=MIN_HOLD_DAYS,
        )

    def __init__(self):
        self._price_cache: Optional[Dict[str, Dict[str, float]]] = None
        # Close series per ticker (Date-indexed), populated by precompute_signals
        # so should_exit() doesn't re-query the DB for every holding every day.
        self._close_cache: Dict[str, pd.Series] = {}

    def get_precomputed_price_cache(self) -> Optional[Dict[str, Dict[str, float]]]:
        return self._price_cache

    @staticmethod
    def compute_ema_crossover_angle(close, ema20, ema200, cross_idx) -> float:
        """Compute the angle between EMA20 and EMA200 at crossover."""
        lookback = 3
        if cross_idx < lookback or cross_idx + lookback >= len(close):
            return 0.0
        spread_before = (ema20.iloc[cross_idx - lookback] - ema200.iloc[cross_idx - lookback])
        spread_after = (ema20.iloc[cross_idx + lookback] - ema200.iloc[cross_idx + lookback])
        angle = (spread_after - spread_before) / (lookback * 2)
        return float(angle) if pd.notna(angle) else 0.0

    def get_signals(self, as_of_date: str, engine: Engine) -> List[Signal]:
        """Scan all stocks, rank candidates by the original dual-entry logic."""
        tickers = get_all_tickers(engine)
        candidates: List[Dict[str, Any]] = []

        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue

            try:
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Open", "High", "Low", "Close", "Volume" FROM "{safe}" '
                        f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 300',
                        conn,
                    )
            except Exception:
                continue

            if df.empty or len(df) < 250:
                continue

            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema200 = close.rolling(window=200).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()

            # RSI(14)
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / (avg_loss + 1e-9)
            rsi = 100 - (100 / (1 + rs))

            vol_ma50 = volume.rolling(50).mean()

            # Entry A: EMA20/200 golden cross in the last 5 days
            entry_a = None
            for i in range(len(df) - 5, len(df)):
                if (pd.notna(ema20.iloc[i]) and pd.notna(ema200.iloc[i]) and
                        pd.notna(ema20.iloc[i - 1]) and pd.notna(ema200.iloc[i - 1])):
                    if ema20.iloc[i - 1] <= ema200.iloc[i - 1] and ema20.iloc[i] > ema200.iloc[i]:
                        angle = self.compute_ema_crossover_angle(close, ema20, ema200, i)
                        entry_a = {
                            "angle": angle,
                            "price": float(close.iloc[i]),
                            "date": str(df["Date"].iloc[i])[:10],
                        }
                        break

            # Entry B: Price > EMA50 > EMA200 AND RSI > 60 AND volume > 1.2x avg
            entry_b = None
            last = df.iloc[-1]
            if (pd.notna(ema50.iloc[-1]) and pd.notna(ema200.iloc[-1]) and
                    pd.notna(rsi.iloc[-1]) and pd.notna(vol_ma50.iloc[-1]) and vol_ma50.iloc[-1] > 0):
                if (last["Close"] > ema50.iloc[-1] and ema50.iloc[-1] > ema200.iloc[-1] and
                        rsi.iloc[-1] > 60 and last["Volume"] > vol_ma50.iloc[-1] * 1.2):
                    slope = (ema50.iloc[-1] - ema50.iloc[-5]) / ema50.iloc[-5] if len(df) >= 5 else 0
                    entry_b = {
                        "angle": float(slope * 100),
                        "price": float(last["Close"]),
                        "date": str(last["Date"])[:10],
                    }

            if entry_a or entry_b:
                mc = 0.0
                sector = "Unknown"
                try:
                    with engine.connect() as conn:
                        row = conn.execute(
                            text("SELECT market_cap, sector FROM stock_metadata WHERE ticker = :t"),
                            {"t": ticker.upper()},
                        ).fetchone()
                    if row:
                        if row[0] is not None:
                            mc = float(row[0])
                        if row[1] is not None:
                            sector = row[1]
                except Exception:
                    pass

                entry = entry_a or entry_b
                angle_norm = 1 / (1 + np.exp(-entry["angle"] * 100))
                cap_norm = min(1.0, mc / 100e9)
                score = ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm

                candidates.append({
                    "ticker": ticker.upper(),
                    "score": round(score, 4),
                    "angle": round(entry["angle"], 4),
                    "price": entry["price"],
                    "entry_date": entry["date"],
                    "entry_type": "A" if entry_a else "B",
                    "market_cap": mc,
                    "sector": sector,
                })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        selected = candidates[:MAX_HOLDINGS]

        return [
            Signal(
                ticker=c["ticker"],
                side="long",
                score=c["score"],
                angle=c["angle"],
                price=c["price"],
                entry_date=c["entry_date"],
                entry_type=c["entry_type"],
                market_cap=c["market_cap"],
                sector=c["sector"],
            )
            for c in selected
        ]

    def precompute_signals(self, all_dates: List[str], engine: Engine) -> Optional[Dict[str, List[Signal]]]:
        """Precompute dual-entry signals for all dates at once (vectorized).

        Loads each ticker once, computes indicators once, then evaluates
        Entry A (EMA20/200 golden cross within the last 5 days) and Entry B
        (price > EMA50 > EMA200 AND RSI > 60 AND volume > 1.2x avg) for every
        date. This avoids the per-day get_signals() path that reloaded all
        ~1500 tickers for each of thousands of dates (the cause of the hang).
        """
        from app.utils.security import get_safe_table_name

        tickers = get_all_tickers(engine)
        logger.info("Precomputing signals for %d tickers across %d dates...", len(tickers), len(all_dates))
        first_date = all_dates[0]
        last_date = all_dates[-1]
        date_set = set(all_dates)

        meta_cache: Dict[str, tuple] = {}
        try:
            with engine.connect() as conn:
                rows = conn.execute(text("SELECT ticker, market_cap, sector FROM stock_metadata")).fetchall()
            for row in rows:
                mc = float(row[1]) if row[1] is not None else 0.0
                sec = str(row[2]) if row[2] is not None else "Unknown"
                meta_cache[str(row[0]).lower()] = (mc, sec)
        except Exception:
            pass

        all_candidates: Dict[str, List[Dict[str, Any]]] = {}

        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue
            load_start = (pd.Timestamp(first_date) - pd.Timedelta(days=300)).strftime("%Y-%m-%d")
            try:
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Close", "Volume" FROM "{safe}" '
                        f'WHERE "Date" >= \'{load_start}\' AND "Date" <= \'{last_date}\' '
                        f'ORDER BY "Date" DESC LIMIT 3000', conn)
            except Exception:
                continue
            if df.empty or len(df) < 250:
                continue
            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema200 = close.rolling(window=200).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / (avg_loss + 1e-9)
            rsi = 100 - (100 / (1 + rs))
            vol_ma50 = volume.rolling(50).mean()

            ticker_lower = ticker.lower()
            if self._price_cache is None:
                self._price_cache = {}
            if ticker_lower not in self._price_cache:
                self._price_cache[ticker_lower] = dict(zip(df["Date"].astype(str).str[:10], close))
            # Cache the Date-indexed Close series for fast should_exit lookups.
            self._close_cache[ticker_lower] = pd.Series(
                close.to_numpy(), index=df["Date"].astype(str).str[:10]
            )

            mc, sector = meta_cache.get(ticker_lower, (0.0, "Unknown"))

            dates = df["Date"].astype(str).str[:10].to_numpy()
            closev = close.to_numpy()
            ema20v = ema20.to_numpy()
            ema200v = ema200.to_numpy()
            ema50v = ema50.to_numpy()
            rsiv = rsi.to_numpy()
            volv = volume.to_numpy()
            volma50v = vol_ma50.to_numpy()

            # Entry A: golden cross (ema20 crosses above ema200)
            prev_ok = ~np.isnan(ema20v[:-1]) & ~np.isnan(ema200v[:-1])
            cur_ok = ~np.isnan(ema20v[1:]) & ~np.isnan(ema200v[1:])
            cross = prev_ok & cur_ok & (ema20v[:-1] <= ema200v[:-1]) & (ema20v[1:] > ema200v[1:])
            cross_here = np.zeros(len(df), dtype=bool)
            cross_here[1:][cross] = True
            cum = np.cumsum(cross_here)
            # window_count[i] = number of crosses in rows [i-4, i]
            window_count = np.zeros(len(df), dtype=int)
            window_count[5:] = cum[5:] - cum[:-5]
            window_count[:5] = cum[:5]
            entry_a_trigger = window_count > 0

            # Entry B: price > ema50 > ema200 AND rsi > 60 AND volume > 1.2x avg
            entry_b_trigger = (
                (closev > ema50v) & (ema50v > ema200v) & (rsiv > 60) &
                (volma50v > 0) & (volv > volma50v * 1.2) &
                ~np.isnan(ema50v) & ~np.isnan(ema200v) & ~np.isnan(rsiv)
            )

            for i in range(len(df)):
                ds = dates[i]
                if ds not in date_set:
                    continue
                entry_a = None
                if entry_a_trigger[i]:
                    for ci in range(max(1, i - 4), i + 1):
                        if cross_here[ci]:
                            angle = self.compute_ema_crossover_angle(close, ema20, ema200, ci)
                            entry_a = {"angle": angle, "price": float(closev[i]), "date": ds}
                            break
                entry_b = None
                if entry_b_trigger[i]:
                    sl = 0.0
                    if i >= 5 and pd.notna(ema50v[i - 5]) and ema50v[i - 5] != 0:
                        sl = (ema50v[i] - ema50v[i - 5]) / ema50v[i - 5]
                    entry_b = {"angle": float(sl * 100), "price": float(closev[i]), "date": ds}

                if entry_a or entry_b:
                    entry = entry_a or entry_b
                    angle_norm = 1 / (1 + np.exp(-entry["angle"] * 100))
                    cap_norm = min(1.0, mc / 100e9)
                    score = ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm
                    if ds not in all_candidates:
                        all_candidates[ds] = []
                    all_candidates[ds].append({
                        "ticker": ticker.upper(), "score": round(score, 4), "angle": round(entry["angle"], 4),
                        "price": entry["price"], "entry_date": entry["date"],
                        "entry_type": "A" if entry_a else "B", "market_cap": mc, "sector": sector,
                    })

        result: Dict[str, List[Signal]] = {}
        for date_str in all_dates:
            candidates = all_candidates.get(date_str, [])
            candidates.sort(key=lambda c: c["score"], reverse=True)
            selected = candidates[:MAX_HOLDINGS]
            result[date_str] = [
                Signal(ticker=c["ticker"], side="long", score=c["score"], angle=c["angle"],
                       price=c["price"], entry_date=c["entry_date"], entry_type=c["entry_type"],
                       market_cap=c["market_cap"], sector=c["sector"])
                for c in selected
            ]

        logger.info("Precomputed signals: %d dates with signals out of %d total dates",
                    sum(1 for v in result.values() if v), len(all_dates))
        return result

    def should_exit(self, ticker: str, as_of_date: str, engine: Engine, side: str = "long") -> ExitCheck:
        """Original exit rule: death cross (EMA20 below EMA200).

        Uses the Date-indexed Close cache populated by precompute_signals to
        avoid a DB query per holding per day. Falls back to a DB load if the
        cache isn't populated (e.g. per-day mode).
        """
        try:
            close = self._close_cache.get(ticker.lower())
            if close is not None:
                close_up_to = close[close.index <= as_of_date]
                if len(close_up_to) < 50:
                    return ExitCheck(should_close=False)
                ema20 = close_up_to.ewm(span=20, adjust=False).mean()
                ema200 = close_up_to.rolling(window=200).mean()
                if pd.notna(ema20.iloc[-1]) and pd.notna(ema200.iloc[-1]) and ema20.iloc[-1] < ema200.iloc[-1]:
                    return ExitCheck(should_close=True, reason="Death Cross")
                return ExitCheck(should_close=False)

            # Fallback: load from DB (per-day mode, no precompute cache).
            safe = get_safe_table_name(ticker)
            with engine.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Close" FROM "{safe}" WHERE "Date" <= \'{as_of_date}\' '
                    f'ORDER BY "Date" DESC LIMIT 250',
                    conn,
                )
            if df.empty or len(df) < 50:
                return ExitCheck(should_close=False)
            df = df.sort_values("Date").reset_index(drop=True)
            ema20 = df["Close"].ewm(span=20, adjust=False).mean()
            ema200 = df["Close"].rolling(window=200).mean()
            if pd.notna(ema20.iloc[-1]) and pd.notna(ema200.iloc[-1]) and ema20.iloc[-1] < ema200.iloc[-1]:
                return ExitCheck(should_close=True, reason="Death Cross")
        except Exception:
            pass
        return ExitCheck(should_close=False)
