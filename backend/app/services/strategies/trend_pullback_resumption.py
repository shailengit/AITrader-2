"""Trend-Pullback Resumption Rotation — pluggable Strategy implementation.

Buys strength on a dip, not a breakout and not a bare crossover.

Each indicator has exactly one job:

  EMA200   primary regime  — close above it, and it is rising over 20 sessions
  EMA50    structure       — above EMA200 (the golden-cross *state*)
  EMA20    setup + trigger — crosses back above it today (the cross implies the
                             prior dip, so the separate pullback test is off)
  MACD     momentum        — MACD line above its signal line
  RSI      guard           — available (45..75) but OFF: measured to bind on 0
                             of 3,587 core stock-days, so it never changed a trade

Universe filters: 20-day dollar volume >= $10M, 20-day return std <= 4%.

Ranking: 60% risk-adjusted 126-day momentum + 40% log market cap, both on FIXED
scales so the live path and the backtest score identically by construction.

Exits: trend break (close < EMA200), hard stop 10%, take profit 40%, trailing
stop 20%, time stop 120 days; min hold 10 before rotation.

Warmup: EMA200 needs ~830 bars to converge, so no date is scanned with fewer
than WARMUP_BARS_REQUIRED bars behind it, and history always loads from a 2008
floor.

`require_fresh_cross` encodes the "golden crossovers are great" hypothesis as a
switch: when True, an entry additionally needs EMA50 to have crossed above
EMA200 within `cross_window` sessions. It defaults OFF and is meant to be
A/B'd, not assumed.

All levers live in DEFAULT_CONFIG and are overridable per instance by keyword,
e.g. TrendPullbackResumption(require_fresh_cross=True).
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from app.services.strategy_base import (
    ExitCheck, RotationConfig, Signal, Strategy, get_all_tickers,
)

logger = logging.getLogger(__name__)

# ── Strategy Parameters ───────────────────────────────────────────────
DEFAULT_CONFIG: Dict[str, Any] = {
    # Trend template
    "ema_fast": 20,
    "ema_mid": 50,
    "ema_slow": 200,
    "slow_rising_lookback": 20,
    # Pullback / trigger
    "pullback_window": 10,
    # Individual filters are switchable so the A/B can test whether each earns
    # its place instead of assuming a five-condition entry is better.
    # Measured inert (2026-11): across 3,587 core stock-days the pullback
    # condition bound 0 times (the EMA20 trigger already implies it) and the RSI
    # band bound 0 times (RSI inside the setup ranges 45.7-72.9). Keeping them ON
    # changes nothing, so they default OFF; the code stays because a broadened
    # trigger or a different setup could make them bind again.
    "use_pullback": False,
    "use_macd_filter": True,
    "use_rsi_filter": False,
    # MACD
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    # RSI guard
    "rsi_period": 14,
    "rsi_floor": 45.0,
    "rsi_ceiling": 75.0,
    # Universe filters
    "min_dollar_volume": 10_000_000.0,
    "max_volatility": 0.04,
    # Golden-cross hypothesis (OFF by default; A/B it, don't assume it)
    "require_fresh_cross": False,
    "cross_window": 20,
    # Ranking (fixed scales; no population normalisation)
    "mom_window": 126,
    "mom_weight": 0.60,
    "cap_weight": 0.40,
    "ra_center": 0.5,
    "ra_scale": 4.0,
    "cap_log_lo": 9.0,           # log10($1B)
    "cap_log_hi": 12.0,          # log10($1T)
    # Universe / risk
    "max_holdings": 5,
    "max_sector_count": 2,
    "bear_exposure": 0.50,
    # Exits
    "hard_stop_loss": 0.10,
    "take_profit": 0.40,
    "trailing_stop": 0.20,
    "time_stop_days": 120,
    "min_hold_days": 10,
    "protect_winners": True,
    # Sizing / execution
    "sizing_pcts": [0.30, 0.25, 0.20, 0.15, 0.10],
    "cost_bps": 5.0,
}
_PROPERTY_KEYS = {"max_holdings", "sizing_pcts"}

# ── Indicator warmup ──────────────────────────────────────────────────
# EMA200 needs ~830 bars (~4.15 x span) to converge. An EMA returns a value from
# the first bar, so an unconverged one is indistinguishable from a converged one.
WARMUP_BARS_REQUIRED = 830
WARMUP_CALENDAR_DAYS = 1300
WARMUP_FLOOR = "2008-01-01"
WARMUP_MAX_ROWS = 8000


def required_load_start(first_date: str) -> str:
    """Earliest date to load so the slowest indicator is warm by `first_date`."""
    try:
        cutoff = (
            pd.Timestamp(first_date) - pd.Timedelta(days=WARMUP_CALENDAR_DAYS)
        ).strftime("%Y-%m-%d")
    except Exception:
        return WARMUP_FLOOR
    return min(WARMUP_FLOOR, cutoff)


class TrendPullbackResumption(Strategy):
    """Trend regime + pullback + resumption trigger, ranked by risk-adjusted momentum."""

    def __init__(self, **overrides):
        super().__init__()
        unknown = set(overrides) - set(DEFAULT_CONFIG)
        if unknown:
            raise ValueError(
                f"Unknown config key(s): {sorted(unknown)}. "
                f"Valid keys: {sorted(DEFAULT_CONFIG)}"
            )
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(overrides)
        # ema_fast may EQUAL ema_mid: the same EMA20 can serve as both the
        # pullback/trigger line and the alignment line against the EMA200.
        if not (cfg["ema_fast"] <= cfg["ema_mid"] < cfg["ema_slow"]):
            raise ValueError("ema_fast <= ema_mid < ema_slow is required")
        if cfg["mom_window"] < 2:
            raise ValueError("mom_window must be >= 2")
        self.config = cfg
        for key, value in cfg.items():
            if key not in _PROPERTY_KEYS:
                setattr(self, key, value)

        self._price_cache: Optional[Dict[str, Dict[str, float]]] = None
        self._close_cache: Dict[str, pd.Series] = {}

    def get_name(self) -> str:
        return "Trend-Pullback Resumption Rotation"

    @property
    def max_holdings(self) -> int:
        return int(self.config["max_holdings"])

    @property
    def sizing_pcts(self) -> List[float]:
        return list(self.config["sizing_pcts"])

    def get_rotation_config(self) -> RotationConfig:
        return RotationConfig(
            sizing_method="linear",
            hard_stop_loss=self.hard_stop_loss,
            trailing_stop=self.trailing_stop,
            take_profit=self.take_profit,
            time_stop_days=self.time_stop_days,
            min_hold_days=self.min_hold_days,
            max_sector_count=self.max_sector_count,
            re_score_holdings=True,
            protect_winners=self.protect_winners,
            bear_exposure=self.bear_exposure,
            cost_bps=self.cost_bps,
            exit_priority=[
                "strategy_exit",     # Trend break (close < EMA200) first
                "hard_stop_loss",
                "take_profit",
                "trailing_stop",
                "time_stop",
            ],
        )

    def get_precomputed_price_cache(self) -> Optional[Dict[str, Dict[str, float]]]:
        return self._price_cache

    # ── Indicators ────────────────────────────────────────────────────

    def _rsi(self, close: pd.Series) -> pd.Series:
        period = self.rsi_period
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.ewm(alpha=1.0 / period, adjust=False,
                            min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, adjust=False,
                            min_periods=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
        rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
        return rsi

    def _conditions(self, close: pd.Series,
                    volume: pd.Series) -> Dict[str, pd.Series]:
        """Every entry condition as a boolean Series — one definition point.

        Returned separately rather than only as the composed `entry`, so
        diagnostics can attribute a missed winner to the exact condition that
        blocked it instead of guessing.
        """
        ema_fast = close.ewm(span=self.ema_fast, adjust=False).mean()
        ema_mid = close.ewm(span=self.ema_mid, adjust=False).mean()
        ema_slow = close.ewm(span=self.ema_slow, adjust=False).mean()

        macd = (close.ewm(span=self.macd_fast, adjust=False).mean()
                - close.ewm(span=self.macd_slow, adjust=False).mean())
        macd_line = macd.ewm(span=self.macd_signal, adjust=False).mean()

        rsi = self._rsi(close)
        returns = close.pct_change(fill_method=None)
        std_20 = returns.rolling(20).std()
        dollar_vol = (close * volume).rolling(20).mean()

        # Setup: price was below EMA20 at some point in the prior N sessions.
        below_fast = (close < ema_fast).astype(float)
        pullback = below_fast.shift(1).rolling(self.pullback_window).max() > 0
        # Trigger: price crosses back above EMA20 today.
        trigger = (close > ema_fast) & (close.shift(1) <= ema_fast.shift(1))

        trend = ((close > ema_slow)
                 & (ema_slow > ema_slow.shift(self.slow_rising_lookback)))
        aligned = ema_mid > ema_slow
        fresh_cross = ((ema_mid > ema_slow)
                       & (ema_mid.shift(1) <= ema_slow.shift(1)))
        recent_cross = fresh_cross.rolling(self.cross_window).max() > 0

        return {
            "trend": trend,
            "aligned": aligned,
            "pullback": pullback,
            "trigger": trigger,
            "macd_up": macd > macd_line,
            "rsi_ok": (rsi >= self.rsi_floor) & (rsi <= self.rsi_ceiling),
            "liquid": dollar_vol >= self.min_dollar_volume,
            "vol_ok": std_20 <= self.max_volatility,
            "recent_cross": recent_cross,
            "ema_slow": ema_slow,
            "momentum": close / close.shift(self.mom_window) - 1.0,
            "ann_vol": returns.rolling(self.mom_window).std() * np.sqrt(252.0),
        }

    def _required_conditions(self) -> List[str]:
        """Conditions that must all hold, given the current config."""
        required = ["trend", "aligned", "trigger", "liquid", "vol_ok"]
        if self.use_pullback:
            required.append("pullback")
        if self.use_macd_filter:
            required.append("macd_up")
        if self.use_rsi_filter:
            required.append("rsi_ok")
        if self.require_fresh_cross:
            required.append("recent_cross")
        return required

    def _indicators(self, close: pd.Series, volume: pd.Series) -> Dict[str, pd.Series]:
        """Compose the configured entry mask from the individual conditions."""
        cond = self._conditions(close, volume)
        required = self._required_conditions()
        entry = cond[required[0]].copy()
        for name in required[1:]:
            entry = entry & cond[name]
        return {
            "entry": entry,
            "ema_slow": cond["ema_slow"],
            "momentum": cond["momentum"],
            "ann_vol": cond["ann_vol"],
            "conditions": cond,
        }

    # ── Scoring ───────────────────────────────────────────────────────

    def _score(self, momentum: float, ann_vol: float, market_cap: float) -> float:
        """Fixed-scale score: a pure function of the stock, never of its peers."""
        if momentum is None or not np.isfinite(momentum):
            momentum = 0.0
        if ann_vol is None or not np.isfinite(ann_vol):
            ann_vol = 0.0
        risk_adj = momentum / (ann_vol + 1e-6)
        ra_norm = 1.0 / (1.0 + np.exp(-(risk_adj - self.ra_center) * self.ra_scale))

        if market_cap is None or not np.isfinite(market_cap) or market_cap <= 0:
            cap_norm = 0.0
        else:
            cap_norm = (np.log10(market_cap) - self.cap_log_lo) / (
                self.cap_log_hi - self.cap_log_lo
            )
            cap_norm = float(min(1.0, max(0.0, cap_norm)))

        return float(self.mom_weight * ra_norm + self.cap_weight * cap_norm)

    @staticmethod
    def _metadata(engine: Engine) -> Dict[str, tuple]:
        meta: Dict[str, tuple] = {}
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT ticker, market_cap, sector FROM stock_metadata")
                ).fetchall()
            for r in rows:
                mc = float(r[1]) if r[1] is not None else 0.0
                sec = str(r[2]) if r[2] is not None else "Unknown"
                meta[str(r[0]).lower()] = (mc, sec)
        except Exception:
            pass
        return meta

    # ── Signal Generation (live / per-day path) ───────────────────────

    def get_signals(self, as_of_date: str, engine: Engine) -> List[Signal]:
        from app.utils.security import get_safe_table_name

        tickers = get_all_tickers(engine)
        meta = self._metadata(engine)
        load_start = required_load_start(as_of_date)
        candidates: List[Dict[str, Any]] = []

        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue

            try:
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Close", "Volume" FROM "{safe}" '
                        f'WHERE "Date" >= \'{load_start}\' AND "Date" <= \'{as_of_date}\' '
                        f'ORDER BY "Date" DESC LIMIT {WARMUP_MAX_ROWS}',
                        conn,
                    )
            except Exception:
                continue

            if df.empty or len(df) < WARMUP_BARS_REQUIRED:
                continue

            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            ind = self._indicators(close, volume)
            i = len(df) - 1
            if not bool(ind["entry"].iloc[i]):
                continue

            mc, sector = meta.get(ticker.lower(), (0.0, "Unknown"))
            candidates.append({
                "ticker": ticker.upper(),
                "momentum": float(ind["momentum"].iloc[i])
                if pd.notna(ind["momentum"].iloc[i]) else 0.0,
                "ann_vol": float(ind["ann_vol"].iloc[i])
                if pd.notna(ind["ann_vol"].iloc[i]) else 0.0,
                "market_cap": mc,
                "sector": sector,
                "price": float(close.iloc[i]),
                "date": str(df["Date"].iloc[i])[:10],
            })

        if not candidates:
            return []

        for c in candidates:
            c["score"] = self._score(c["momentum"], c["ann_vol"], c["market_cap"])
        candidates.sort(key=lambda x: x["score"], reverse=True)

        selected: List[Dict[str, Any]] = []
        sector_counts: Dict[str, int] = {}
        for c in candidates:
            if len(selected) >= self.max_holdings:
                break
            sec = c.get("sector", "Unknown")
            if sector_counts.get(sec, 0) >= self.max_sector_count:
                continue
            selected.append(c)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

        return [
            Signal(
                ticker=c["ticker"], side="long",
                score=round(c["score"], 6),
                price=c["price"], entry_date=c["date"],
                entry_type="trend_pullback",
                market_cap=c["market_cap"], sector=c["sector"],
            )
            for c in selected
        ]

    # ── Exit Logic ────────────────────────────────────────────────────

    def should_exit(self, ticker: str, as_of_date: str,
                    engine: Engine, side: str = "long") -> ExitCheck:
        """Thesis break: close below the EMA200 the position was bought against."""
        if side != "long":
            return ExitCheck()

        try:
            close = self._load_close(ticker, as_of_date, engine)
            if close is None or len(close) < WARMUP_BARS_REQUIRED:
                return ExitCheck()
            ema_slow = close.ewm(span=self.ema_slow, adjust=False).mean()
            if float(close.iloc[-1]) < float(ema_slow.iloc[-1]):
                return ExitCheck(should_close=True, reason="Trend Break")
        except Exception:
            pass

        return ExitCheck()

    # ── Holding Re-scoring (for rotation) ─────────────────────────────

    def score_holding(self, ticker: str, as_of_date: str, engine: Engine,
                      entry_price: float, market_cap: float, sector: str,
                      side: str = "long") -> float:
        try:
            close = self._load_close(ticker, as_of_date, engine)
            if close is None or len(close) < WARMUP_BARS_REQUIRED:
                return 0.0
            returns = close.pct_change(fill_method=None)
            if len(close) <= self.mom_window:
                return 0.0
            momentum = float(close.iloc[-1]) / float(close.iloc[-1 - self.mom_window]) - 1.0
            ann_vol = float(returns.rolling(self.mom_window).std().iloc[-1])
            return self._score(momentum, ann_vol, market_cap)
        except Exception:
            return 0.0

    def _load_close(self, ticker: str, as_of_date: str,
                    engine: Engine) -> Optional[pd.Series]:
        cached = self._close_cache.get(ticker.lower())
        if cached is not None:
            return cached[cached.index <= as_of_date].astype(float)

        from app.utils.security import get_safe_table_name
        safe = get_safe_table_name(ticker)
        with engine.connect() as conn:
            df = pd.read_sql(
                f'SELECT "Date", "Close" FROM "{safe}" '
                f'WHERE "Date" >= \'{required_load_start(as_of_date)}\' '
                f'AND "Date" <= \'{as_of_date}\' '
                f'ORDER BY "Date" DESC LIMIT {WARMUP_MAX_ROWS}',
                conn,
            )
        if df.empty:
            return None
        df = df.sort_values("Date").reset_index(drop=True)
        return df["Close"].astype(float)

    # ── Precomputed Signals (efficient backtesting) ───────────────────

    def precompute_signals(self, all_dates: List[str],
                           engine: Engine) -> Optional[Dict[str, List[Signal]]]:
        from app.utils.security import get_safe_table_name

        if not all_dates:
            return {}

        first_date, last_date = all_dates[0], all_dates[-1]
        tickers = get_all_tickers(engine)
        meta = self._metadata(engine)
        load_start = required_load_start(first_date)

        logger.info("Precomputing trend-pullback signals for %d tickers across %d dates...",
                    len(tickers), len(all_dates))

        all_candidates: Dict[str, List[Dict[str, Any]]] = {}
        self._price_cache = {}

        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue

            try:
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Close", "Volume" FROM "{safe}" '
                        f'WHERE "Date" >= \'{load_start}\' AND "Date" <= \'{last_date}\' '
                        f'ORDER BY "Date" DESC LIMIT {WARMUP_MAX_ROWS}',
                        conn,
                    )
            except Exception:
                continue

            if df.empty or len(df) < WARMUP_BARS_REQUIRED:
                continue

            df = df.sort_values("Date").reset_index(drop=True)
            dates = df["Date"].astype(str).str[:10].to_numpy()
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            closev = close.to_numpy()

            ticker_lower = ticker.lower()
            finite = np.isfinite(closev)
            self._price_cache[ticker_lower] = dict(zip(dates[finite], closev[finite]))
            self._close_cache[ticker_lower] = pd.Series(closev, index=dates)

            ind = self._indicators(close, volume)
            entry = ind["entry"].to_numpy()
            momentum = ind["momentum"].to_numpy()
            ann_vol = ind["ann_vol"].to_numpy()

            idx = np.arange(len(dates))
            warm_ok = (idx + 1) >= WARMUP_BARS_REQUIRED
            in_dates = np.isin(dates, all_dates)
            mask = entry & warm_ok & in_dates
            hits = np.where(mask)[0]

            if len(hits) == 0:
                continue

            mc, sector = meta.get(ticker_lower, (0.0, "Unknown"))
            for i in hits:
                ds = dates[i]
                all_candidates.setdefault(ds, []).append({
                    "ticker": ticker.upper(),
                    "momentum": float(momentum[i]) if np.isfinite(momentum[i]) else 0.0,
                    "ann_vol": float(ann_vol[i]) if np.isfinite(ann_vol[i]) else 0.0,
                    "market_cap": mc,
                    "sector": sector,
                    "price": float(closev[i]),
                    "date": ds,
                })

        result: Dict[str, List[Signal]] = {}
        for ds in all_dates:
            cands = all_candidates.get(ds, [])
            if not cands:
                result[ds] = []
                continue
            for c in cands:
                c["score"] = self._score(c["momentum"], c["ann_vol"], c["market_cap"])
            cands.sort(key=lambda x: x["score"], reverse=True)
            result[ds] = [
                Signal(
                    ticker=c["ticker"], side="long",
                    score=round(c["score"], 6),
                    price=c["price"], entry_date=ds,
                    entry_type="trend_pullback",
                    market_cap=c["market_cap"], sector=c["sector"],
                )
                for c in cands
            ]

        logger.info("Precomputed trend-pullback signals: %d of %d dates have signals",
                    sum(1 for v in result.values() if v), len(all_dates))
        return result
