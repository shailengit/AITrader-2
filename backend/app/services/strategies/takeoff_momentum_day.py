"""Takeoff Momentum Day-Trade Strategy — pluggable Strategy implementation.

Scans ~1500 stocks on DAILY data (`sp1500_1d`) on signal day D for stocks
"primed to take off", then executes intraday on 1-MINUTE data (`sp1500_1m`)
on the next trading day D+1.

Daily composite screen (day D):
  - Momentum 70%  — EMA5 crosses above EMA200, close[yesterday] > EMA5[yesterday],
                    ranked by 5-day angle between EMA5 and EMA200.
  - Volatility 10% — Bollinger (20,2) squeeze (low bandwidth = building energy).
  - Volume    20%  — volume surge: volume[D] >= 1.5x the prior-5-day average.
  Filters: price > $10, avg 20d daily dollar volume > $50M, entry-day gap<=MAX_ENTRY_GAP; ETFs excluded.
  Select top 5, max 2 per sector.

Intraday execution (day D+1, on 1-minute bars):
  - Entry: close of first 1-min bar whose close > prior day close (confirmation).
  - Exits (priority): +4% take-profit -> -2% stop-loss -> 2% trailing ->
    3:55 PM end-of-day liquidation. No overnight positions.
Position sizing: score-weighted across the day's picks over $100k capital.

Both the standalone runner and this in-app class share the SAME
`intraday_backtest()` engine, so standalone and in-app results are identical.
Also plugs into the Strategy ABC / app adapter for the daily screen via
get_signals().
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from app.db.database import engine as daily_engine, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
from sqlalchemy import create_engine
from app.utils.security import get_safe_table_name
from app.services.strategy_base import Strategy, Signal, ExitCheck, RotationConfig

logger = logging.getLogger(__name__)

# ── Parameters (defaults) ──────────────────────────────────────────────
TOTAL_CAPITAL = 100_000.0
MAX_HOLDINGS = 5
MIN_PRICE = 10.0
MIN_DAILY_DOLLAR_VOL = 50e6
VOLUME_SURGE = 1.5
VOLUME_AVG_WINDOW = 5
BB_WINDOW = 20
BB_STD = 2.0
ANGLE_LOOKBACK = 5
TAKE_PROFIT = 0.04
STOP_LOSS = 0.02
TRAILING_STOP = 0.02
END_OF_DAY = "15:55"
SECTOR_CAP = 2
MAX_ENTRY_GAP = 0.0   # skip names that gap up more than this (%) on entry day; 0 = disabled (Phase-4 lever)

W_MOMENTUM = 0.70
W_VOLATILITY = 0.10
W_VOLUME = 0.20

# Univerity exclusions: ETFs / funds / indices (not day-tradable individual stocks)
ETF_TICKERS = {
    'spy', 'qqq', 'dia', 'iwm', 'vix', 'xlb', 'xlc', 'xle', 'xlf', 'xli', 'xlk',
    'xlp', 'xlre', 'xlu', 'xlv', 'xly', 'fez', 'ewz', 'eem', 'efa', 'eusa',
    'vti', 'vee', 'dij', 'gdx', 'gdxj', 'uso', 'tlt', 'iyr', 'xln', 'voo',
}

# 1-minute database engine
_engine_1m = create_engine(
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/sp1500_1m",
    pool_size=5, max_overflow=10, pool_pre_ping=True,
)


class TakeoffMomentumDay(Strategy):
    """Daily-screen + intraday-execution day-trading strategy."""

    def __init__(self):
        super().__init__()
        self._meta: Dict[str, Dict[str, Any]] = {}

    # ── Strategy ABC interface (for app / Alpaca daily adapter) ────────

    def get_name(self) -> str:
        return "Takeoff Momentum Day Trade"

    @property
    def max_holdings(self) -> int:
        return MAX_HOLDINGS

    @property
    def sizing_pcts(self) -> List[float]:
        # Score-weighted; fallback buckets for the app adapter.
        return [0.30, 0.25, 0.20, 0.15, 0.10]

    def get_rotation_config(self) -> RotationConfig:
        return RotationConfig(
            sizing_method="score_squared",   # app adapter daily mode
            hard_stop_loss=0.0,
            trailing_stop=0.0,
            take_profit=0.0,
            time_stop_days=0,
            min_hold_days=0,
            max_sector_count=SECTOR_CAP,
            re_score_holdings=False,
            exit_priority=["strategy_exit"],
        )

    # ── Helpers: metadata / universe ──────────────────────────────────

    def _load_metadata(self) -> Dict[str, Dict[str, Any]]:
        if self._meta:
            return self._meta
        self._meta = {}
        try:
            with daily_engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT ticker, sector, market_cap FROM stock_metadata"
                )).fetchall()
            for ticker, sector, mc in rows:
                t = str(ticker)
                if t.lower() in ETF_TICKERS:
                    continue
                if not sector:   # require sector metadata (exclude ETFs/funds)
                    continue
                self._meta[t] = {
                    "sector": sector,
                    "market_cap": float(mc) if mc is not None and mc is not None else 0.0,
                }
        except Exception as e:
            logger.warning("load_metadata failed: %s", e)
        return self._meta

    def _universe_tickers(self) -> List[str]:
        return sorted(self._load_metadata().keys())

    # ── Daily screen ──────────────────────────────────────────────────

    def _screen_candidates(self, as_of_date: str) -> List[Dict[str, Any]]:
        """Run the daily composite screen on `as_of_date`. Returns scored candidates."""
        meta = self._load_metadata()
        tickers = sorted(meta.keys())
        as_of = pd.Timestamp(as_of_date)
        # Preload daily data for the screen in one pass per ticker (approx last 250 days)
        results: List[Dict[str, Any]] = []
        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue
            try:
                with daily_engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Open", "High", "Low", "Close", "Volume" FROM "{safe}" '
                        f"WHERE \"Date\" <= '{as_of_date}' ORDER BY \"Date\" DESC LIMIT 260",
                        conn,
                    )
            except Exception:
                continue
            if df.empty or len(df) < 210:
                continue
            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            i = len(df) - 1
            if i < 201:
                continue

            ema5 = close.ewm(span=5, adjust=False).mean()
            ema200 = close.rolling(200).mean()
            # Fresh EMA5 > EMA200 crossover today
            if pd.isna(ema5.iloc[i]) or pd.isna(ema200.iloc[i]) or pd.isna(ema5.iloc[i-1]) or pd.isna(ema200.iloc[i-1]):
                continue
            if not (ema5.iloc[i-1] <= ema200.iloc[i-1] and ema5.iloc[i] > ema200.iloc[i]):
                continue
            # Price closed yesterday above EMA5
            if not (close.iloc[i-1] > ema5.iloc[i-1]):
                continue
            # Price filter
            px = float(close.iloc[i])
            if px <= MIN_PRICE:
                continue
            # Volume surge vs prior 5-day avg (excl today)
            vma5 = volume.shift(1).rolling(VOLUME_AVG_WINDOW).mean()
            vr = float(volume.iloc[i] / vma5.iloc[i]) if (pd.notna(vma5.iloc[i]) and vma5.iloc[i] > 0) else 0.0
            if vr < VOLUME_SURGE:
                continue
            # Liquidity: avg daily dollar volume > $100M (20d)
            dollar_vol = close * volume
            ddv = float(dollar_vol.iloc[max(0, i-19):i+1].mean())
            if ddv <= MIN_DAILY_DOLLAR_VOL:
                continue

            # --- Sub-scores ---
            # Momentum angle over ANGLE_LOOKBACK days
            lb = min(ANGLE_LOOKBACK, i)
            d_ema5 = ema5.iloc[i] - ema5.iloc[i-lb]
            d_200 = ema200.iloc[i] - ema200.iloc[i-lb]
            # Use spread change per day -> proxy angle (higher = faster EMA5 rising)
            m = (d_ema5 - d_200) / lb
            angle = float(m)

            # Volatility squeeze: Bollinger bandwidth (lower = more squeezed)
            sma20 = close.rolling(BB_WINDOW).mean()
            std20 = close.rolling(BB_WINDOW).std()
            b_up = sma20 + BB_STD * std20
            b_low = sma20 - BB_STD * std20
            if pd.isna(b_up.iloc[i]) or pd.isna(b_low.iloc[i]) or b_up.iloc[i] == b_low.iloc[i]:
                continue
            bandwidth = float((b_up.iloc[i] - b_low.iloc[i]) / sma20.iloc[i])
            squeeze = 1.0 / max(bandwidth, 1e-9)

            results.append({
                "ticker": ticker,
                "score": 0.0,
                "angle": angle,
                "squeeze": squeeze,
                "vol_ratio": vr,
                "px": px,
                "prior_close": float(close.iloc[i]),
                "sector": meta[ticker]["sector"],
                "market_cap": meta[ticker]["market_cap"],
            })
        return results

    def _rank_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize sub-scores, compute composite, rank, apply sector cap, top-N."""
        if not candidates:
            return []
        n = len(candidates)

        def _minmax(vals):
            lo, hi = min(vals), max(vals)
            if hi <= lo:
                return [0.5] * len(vals)
            return [(v - lo) / (hi - lo) for v in vals]

        ang = _minmax([c["angle"] for c in candidates])
        sqz = _minmax([c["squeeze"] for c in candidates])
        volr = _minmax([c["vol_ratio"] for c in candidates])

        for idx, c in enumerate(candidates):
            c["score"] = (
                W_MOMENTUM * ang[idx]
                + W_VOLATILITY * sqz[idx]
                + W_VOLUME * volr[idx]
            )

        candidates.sort(key=lambda x: x["score"], reverse=True)

        # Sector cap
        selected = []
        sector_counts: Dict[str, int] = {}
        for c in candidates:
            if len(selected) >= MAX_HOLDINGS:
                break
            sec = c["sector"]
            if sector_counts.get(sec, 0) >= SECTOR_CAP:
                continue
            selected.append(c)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
        return selected

    def get_signals(self, as_of_date: str, engine: Engine) -> List[Signal]:
        """Daily screen signals for a given date (app adapter / Alpaca)."""
        cands = self._screen_candidates(as_of_date)
        rank = self._rank_candidates(cands)
        return [
            Signal(
                ticker=r["ticker"], side="long", score=round(r["score"], 4),
                angle=round(r["angle"], 4), price=r["px"],
                entry_date=as_of_date, entry_type="takeoff",
                market_cap=r["market_cap"], sector=r["sector"],
            )
            for r in rank
        ]

    def should_exit(self, ticker, as_of_date, engine, side="long") -> ExitCheck:
        # Day-trade exits happen intraday in intraday_backtest(). No daily-level exit.
        return ExitCheck()

    # ── Intraday execution (the core day-trade backtest) ───────────────

    def _prior_trading_day(self, prev_daily_dates: List[str], trade_day: str) -> Optional[str]:
        idx = prev_daily_dates.index(trade_day) if trade_day in prev_daily_dates else None
        if idx is None:
            return None
        return prev_daily_dates[idx - 1] if idx > 0 else None

    def _load_1m(self, ticker: str, trade_day: str) -> pd.DataFrame:
        """Load 1-minute bars for a single trade day (09:30..15:59 ET)."""
        try:
            safe = get_safe_table_name(ticker)
        except ValueError:
            return pd.DataFrame()
        start = f"{trade_day} 09:30:00"
        end = f"{trade_day} 15:59:00"
        try:
            with _engine_1m.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Open", "High", "Low", "Close", "Volume" FROM "{safe}" '
                    f"WHERE \"Date\" >= '{start}' AND \"Date\" <= '{end}' ORDER BY \"Date\"",
                    conn,
                )
            if df.empty:
                return pd.DataFrame()
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.sort_values("Date").reset_index(drop=True)
            return df
        except Exception as e:
            logger.warning("load_1m failed for %s on %s: %s", ticker, trade_day, e)
            return pd.DataFrame()

    @staticmethod
    def _time_str(dt) -> str:
        return pd.Timestamp(dt).strftime("%H:%M")

    def _intraday_strategy(self, ticker: str, trade_day: str, prior_close: float,
                           alloc_budget: float, weight: float) -> Dict[str, Any]:
        """Simulate one intraday session for a single pick. Returns trade(s) + equity."""
        df = self._load_1m(ticker, trade_day)
        if df.empty:
            return {"entered": False, "trades": [], "equity": [], "reason": "no_data"}

        # Gap filter (optional, Phase-4 lever): skip names that gap up above
        # MAX_ENTRY_GAP on entry day. Research showed gap-up EMA-cross names
        # tend to fade (momentum exhaustion). Disabled when MAX_ENTRY_GAP <= 0.
        if MAX_ENTRY_GAP > 0:
            open_px = float(df["Open"].iloc[0])
            gap_pct = (open_px / prior_close - 1) * 100 if prior_close > 0 else 0.0
            if gap_pct > MAX_ENTRY_GAP:
                return {"entered": False, "trades": [], "equity": [], "reason": f"gap_too_high_{gap_pct:.1f}"}

        # Entry confirmation: close of first 1-min bar above prior day close.
        idx = None
        for k in range(len(df)):
            if float(df["Close"].iloc[k]) > prior_close:
                idx = k
                break
        if idx is None:
            return {"entered": False, "trades": [], "equity": [], "reason": "no_confirmation"}

        entry_price = float(df["Close"].iloc[idx])
        entry_time = self._time_str(df["Date"].iloc[idx])
        # Score-weighted allocation
        target_value = alloc_budget * weight
        shares = int(target_value / entry_price) if entry_price > 0 else 0
        if shares <= 0:
            return {"entered": False, "trades": [], "equity": [], "reason": "no_budget"}

        trades = [{
            "ticker": ticker, "side": "BUY", "entry_date": trade_day,
            "exit_date": trade_day, "entry_price": round(entry_price, 2),
            "exit_price": 0, "return_pct": 0.0, "holding_days": idx,
            "exit_reason": "New Entry", "pnl_dollars": 0.0,
            "entry_time": entry_time,
        }]

        equity = [{
            "date": trade_day, "time": entry_time, "value": round(alloc_budget, 2),
            "cash": 0.0, "holdings": round(target_value, 2), "n_holdings": 1,
        }]

        peak = entry_price
        exit_price = None
        exit_reason = None
        exit_idx = None
        bars_held = 0

        for k in range(idx + 1, len(df)):
            bar_time = self._time_str(df["Date"].iloc[k])
            bar_close = float(df["Close"].iloc[k])
            bars_held = k - idx
            peak = max(peak, bar_close)
            ret = (bar_close - entry_price) / entry_price
            drawdown = (peak - bar_close) / peak if peak > 0 else 0.0

            # Priority: TP -> SL -> trailing -> end-of-day
            if ret >= TAKE_PROFIT:
                exit_reason, exit_price = "Take Profit", bar_close
                exit_idx = k
                break
            if ret <= -STOP_LOSS:
                exit_reason, exit_price = "Stop Loss", bar_close
                exit_idx = k
                break
            if drawdown >= TRAILING_STOP:
                exit_reason, exit_price = "Trailing Stop", bar_close
                exit_idx = k
                break
            if bar_time >= END_OF_DAY:
                exit_reason, exit_price = "End of Day", bar_close
                exit_idx = k
                break
        else:
            # Reached last bar without an exit -> liquidate at last close
            exit_reason, exit_price = "End of Day", float(df["Close"].iloc[-1])
            exit_idx = len(df) - 1

        pnl = shares * (exit_price - entry_price)
        trades.append({
            "ticker": ticker, "side": "SELL", "entry_date": trade_day,
            "exit_date": trade_day, "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "return_pct": round((exit_price - entry_price) / entry_price * 100, 2),
            "holding_days": exit_idx - idx,
            "exit_reason": exit_reason, "pnl_dollars": round(pnl, 2),
            "entry_time": entry_time,
            "exit_time": self._time_str(df["Date"].iloc[exit_idx]),
        })
        equity.append({
            "date": trade_day, "time": self._time_str(df["Date"].iloc[exit_idx]),
            "value": round(alloc_budget + pnl, 2),
            "cash": round(alloc_budget + pnl, 2), "holdings": 0.0, "n_holdings": 0,
        })
        return {"entered": True, "trades": trades, "equity": equity, "reason": exit_reason}

    def intraday_backtest(
        self,
        trade_days: Optional[List[str]] = None,
        start_date: str = "",
        end_date: str = "",
        capital: float = TOTAL_CAPITAL,
    ) -> Dict[str, Any]:
        """Run the full daily-screen + intraday 1-minute day-trade backtest.

        Args:
            trade_days: explicit list of trade days (D+1). Derive from 1m data if empty.
            start_date/end_date: filter for trade_days.
            capital: starting day capital.
        Returns:
            {"trades": [...], "daily_equity": [...], "summary": {...}}
        """
        # SPY daily trading calendar (for screen day D before each trade day)
        with daily_engine.connect() as conn:
            spy_df = pd.read_sql('SELECT "Date" FROM spy ORDER BY "Date"', conn)
        all_daily_dates = [str(d)[:10] for d in spy_df["Date"]]

        if not trade_days:
            # Derive trade days from available 1-minute data (all tickers share same days)
            try:
                with _engine_1m.connect() as conn:
                    ddf = pd.read_sql(
                        "SELECT \"Date\" FROM aapl WHERE \"Date\" >= '2026-07-30' "
                        'ORDER BY "Date"',
                        conn,
                    )
                trade_days = sorted({str(d)[:10] for d in ddf["Date"]})
            except Exception:
                trade_days = []

        if start_date:
            trade_days = [d for d in trade_days if d >= start_date]
        if end_date:
            trade_days = [d for d in trade_days if d <= end_date]
        trade_days = sorted(trade_days)

        trades: List[Dict[str, Any]] = []
        daily_equity: List[Dict[str, Any]] = []
        portfolio_value = capital
        cash = capital

        for trade_day in trade_days:
            screen_day = self._prior_trading_day(all_daily_dates, trade_day)
            if screen_day is None:
                continue
            cands = self._screen_candidates(screen_day)
            rank = self._rank_candidates(cands)

            # Score-weighted sizing across the day's picks
            total_score = sum(r["score"] for r in rank) if rank else 0.0
            day_start_portfolio = portfolio_value

            day_entered = 0
            for k, r in enumerate(rank):
                weight = (r["score"] / total_score) if total_score > 0 else (1.0 / len(rank))
                result = self._intraday_strategy(
                    r["ticker"], trade_day, r["prior_close"],
                    day_start_portfolio, weight,
                )
                if result["entered"]:
                    day_entered += 1
                    trades.extend(result["trades"])
                    # Realize P&L from this session
                    pnl = result["trades"][-1]["pnl_dollars"]
                    portfolio_value += pnl
                    daily_equity.extend(result["equity"])

            if day_entered == 0:
                daily_equity.append({
                    "date": trade_day, "time": "15:55", "value": round(portfolio_value, 2),
                    "cash": round(portfolio_value, 2), "holdings": 0.0, "n_holdings": 0,
                })

        summary = self._compute_summary(trades, daily_equity, capital, trade_days)
        return {"trades": trades, "daily_equity": daily_equity, "summary": summary}

    # ── KPI summary (matches adapter output format) ─────────────────────
    @staticmethod
    def _compute_summary(trades, daily_equity, capital, trade_days):
        from app.services.strategy_backtest_adapter import _compute_summary as _cs
        as_of = trade_days[0] if trade_days else ""
        end = trade_days[-1] if trade_days else ""
        return _cs(trades, daily_equity, capital, as_of, end)
