"""Simple EMA20/50 Crossover — Strategy ABC subclass for in-app use.

Scans stocks for EMA20 crossing above EMA50.
Ranks by: 60% crossover angle + 40% market cap.
Holds top 3, score-squared sizing.
Exits: death cross (EMA20 < EMA50) or time stop (30d).
"""

import logging
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np
from sqlalchemy import Engine, text

from app.services.strategy_base import Strategy, Signal, ExitCheck, RotationConfig, get_all_tickers

logger = logging.getLogger(__name__)

ANGLE_WEIGHT = 0.60
CAP_WEIGHT = 0.40
MAX_HOLDINGS = 3
TIME_STOP_DAYS = 30


class SimpleEMACross(Strategy):
    """Simple EMA20/50 crossover with score-squared sizing."""

    def __init__(self):
        super().__init__()
        self._price_cache: Optional[Dict[str, Dict[str, float]]] = None
        self._cap_min: float = 0.0
        self._cap_range: float = 1.0

    def get_name(self) -> str:
        return "Simple EMA Cross"

    @property
    def max_holdings(self) -> int:
        return MAX_HOLDINGS

    @property
    def sizing_pcts(self) -> List[float]:
        return [0.50, 0.30, 0.20]

    def get_rotation_config(self) -> RotationConfig:
        return RotationConfig(
            sizing_method="score_squared",
            hard_stop_loss=0.0,
            trailing_stop=0.0,
            take_profit=0.0,
            time_stop_days=TIME_STOP_DAYS,
            min_hold_days=3,
            max_sector_count=999,
            re_score_holdings=True,
            bear_exposure=1.0,
            exit_priority=["strategy_exit", "time_stop"],
        )

    def get_precomputed_price_cache(self) -> Optional[Dict[str, Dict[str, float]]]:
        return self._price_cache

    def get_signals(self, as_of_date: str, engine: Engine) -> List[Signal]:
        from app.utils.security import get_safe_table_name
        tickers = get_all_tickers(engine)
        candidates = []

        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue
            try:
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Close" FROM "{safe}" '
                        f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 200',
                        conn,
                    )
            except Exception:
                continue
            if df.empty or len(df) < 100:
                continue
            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"].astype(float)
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()
            i = len(df) - 1
            if not (pd.notna(ema20.iloc[i]) and pd.notna(ema50.iloc[i]) and
                    pd.notna(ema20.iloc[i-1]) and pd.notna(ema50.iloc[i-1])):
                continue
            if not (ema20.iloc[i-1] <= ema50.iloc[i-1] and ema20.iloc[i] > ema50.iloc[i]):
                continue
            angle = self._compute_angle(close, ema20, ema50, i)
            mc = 0.0
            try:
                with engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT market_cap FROM stock_metadata WHERE ticker = :t"),
                        {"t": ticker.upper()},
                    ).fetchone()
                if row and row[0] is not None:
                    mc = float(row[0])
            except Exception:
                pass
            candidates.append({
                "ticker": ticker.upper(), "angle": angle,
                "market_cap": mc, "price": float(close.iloc[i]),
                "date": str(df["Date"].iloc[i])[:10],
            })

        if not candidates:
            return []
        caps = [c["market_cap"] for c in candidates if c["market_cap"] > 0]
        cmax = max(caps) if caps else 1
        cmin = min(caps) if caps else 0
        crange = cmax - cmin if cmax > cmin else 1
        for c in candidates:
            an = 1 / (1 + np.exp(-c["angle"] * 100))
            cn = (c["market_cap"] - cmin) / crange if crange > 0 else 0.5
            c["score"] = ANGLE_WEIGHT * an + CAP_WEIGHT * cn
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return [
            Signal(ticker=c["ticker"], side="long", score=round(c["score"], 4),
                   angle=round(c["angle"], 4), price=c["price"],
                   entry_date=c["date"], entry_type="ema_cross",
                   market_cap=c["market_cap"])
            for c in candidates[:MAX_HOLDINGS]
        ]

    def should_exit(self, ticker: str, as_of_date: str,
                    engine: Engine, side: str = "long") -> ExitCheck:
        if side != "long":
            return ExitCheck()
        try:
            from app.utils.security import get_safe_table_name
            safe = get_safe_table_name(ticker)
            with engine.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Close" FROM "{safe}" '
                    f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 100',
                    conn,
                )
            if df.empty or len(df) < 50:
                return ExitCheck()
            df = df.sort_values("Date").reset_index(drop=True)
            ema20 = df["Close"].astype(float).ewm(span=20, adjust=False).mean()
            ema50 = df["Close"].astype(float).ewm(span=50, adjust=False).mean()
            if float(ema20.iloc[-1]) < float(ema50.iloc[-1]):
                return ExitCheck(should_close=True, reason="Death Cross")
        except Exception:
            pass
        return ExitCheck()

    def score_holding(self, ticker: str, as_of_date: str, engine: Engine,
                      entry_price: float, market_cap: float, sector: str,
                      side: str = "long") -> float:
        try:
            from app.utils.security import get_safe_table_name
            safe = get_safe_table_name(ticker)
            with engine.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Close" FROM "{safe}" '
                    f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 100',
                    conn,
                )
            if df.empty or len(df) < 50:
                return 0.0
            df = df.sort_values("Date").reset_index(drop=True)
            ema20 = df["Close"].astype(float).ewm(span=20, adjust=False).mean()
            ema50 = df["Close"].astype(float).ewm(span=50, adjust=False).mean()
            e20 = float(ema20.iloc[-1])
            e50 = float(ema50.iloc[-1])
            if e20 <= 0 or e50 <= 0:
                return 0.0
            spread = (e20 - e50) / e50
            an = 1 / (1 + np.exp(-spread * 100))
            cn = (market_cap - self._cap_min) / self._cap_range if self._cap_range > 0 else 0.5
            return ANGLE_WEIGHT * an + CAP_WEIGHT * cn
        except Exception:
            return 0.0

    def precompute_signals(self, all_dates: List[str], engine: Engine) -> Optional[Dict[str, List[Signal]]]:
        from app.utils.security import get_safe_table_name
        tickers = get_all_tickers(engine)
        first_date = all_dates[0]
        last_date = all_dates[-1]
        date_set = set(all_dates)

        meta_cache = {}
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT ticker, market_cap FROM stock_metadata")
                ).fetchall()
            for row in rows:
                mc = float(row[1]) if row[1] is not None else 0.0
                meta_cache[str(row[0]).lower()] = mc
        except Exception:
            pass

        all_candidates = {}
        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue
            try:
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Close" FROM "{safe}" '
                        f'WHERE "Date" >= \'2018-01-01\' AND "Date" <= \'{last_date}\' '
                        f'ORDER BY "Date" DESC LIMIT 3000',
                        conn,
                    )
            except Exception:
                continue
            if df.empty or len(df) < 100:
                continue
            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"].astype(float)
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()

            # Build price cache
            tl = ticker.lower()
            if self._price_cache is None:
                self._price_cache = {}
            if tl not in self._price_cache:
                pc = {}
                for _, row in df.iterrows():
                    pc[str(pd.Timestamp(row["Date"]))[:10]] = float(row["Close"])
                self._price_cache[tl] = pc

            mc = meta_cache.get(ticker.lower(), 0.0)
            for i in range(1, len(df)):
                ds = str(pd.Timestamp(df["Date"].iloc[i]))[:10]
                if ds not in date_set:
                    continue
                if not (pd.notna(ema20.iloc[i]) and pd.notna(ema50.iloc[i]) and
                        pd.notna(ema20.iloc[i-1]) and pd.notna(ema50.iloc[i-1])):
                    continue
                if not (ema20.iloc[i-1] <= ema50.iloc[i-1] and ema20.iloc[i] > ema50.iloc[i]):
                    continue
                angle = self._compute_angle(close, ema20, ema50, i)
                if ds not in all_candidates:
                    all_candidates[ds] = []
                all_candidates[ds].append({
                    "ticker": ticker.upper(), "angle": angle,
                    "market_cap": mc, "price": float(close.iloc[i]), "date": ds,
                })

        if not all_candidates:
            return {d: [] for d in all_dates}

        # Normalize using full universe
        all_caps = [mc for mc in meta_cache.values() if mc > 0]
        cmax = max(all_caps) if all_caps else 1
        cmin = min(all_caps) if all_caps else 0
        crange = cmax - cmin if cmax > cmin else 1
        self._cap_min = cmin
        self._cap_range = crange

        result = {}
        for date_str in all_dates:
            candidates = all_candidates.get(date_str, [])
            if not candidates:
                result[date_str] = []
                continue
            for c in candidates:
                an = 1 / (1 + np.exp(-c["angle"] * 100))
                cn = (c["market_cap"] - cmin) / crange if crange > 0 else 0.5
                c["score"] = ANGLE_WEIGHT * an + CAP_WEIGHT * cn
            candidates.sort(key=lambda x: x["score"], reverse=True)
            result[date_str] = [
                Signal(ticker=c["ticker"], side="long", score=round(c["score"], 4),
                       angle=round(c["angle"], 4), price=c["price"],
                       entry_date=c["date"], entry_type="ema_cross",
                       market_cap=c["market_cap"])
                for c in candidates
            ]
        return result

    @staticmethod
    def _compute_angle(close, ema_fast, ema_slow, cross_idx):
        lookback = 3
        if cross_idx < lookback:
            return 0.0
        end = min(cross_idx + lookback, len(close) - 1)
        start = max(0, cross_idx - lookback)
        if end == start:
            return 0.0
        spread_before = (ema_fast.iloc[start] - ema_slow.iloc[start])
        spread_after = (ema_fast.iloc[end] - ema_slow.iloc[end])
        angle = (spread_after - spread_before) / (end - start)
        return float(angle) if pd.notna(angle) else 0.0
