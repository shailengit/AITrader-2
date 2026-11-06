"""52-Week High Breakout Rotation Strategy — pluggable Strategy implementation.

Demo strategy for the strategy-crafter skill. Buys strength rather than dips: a
*fresh* 252-day closing high on above-average volume, ranked by 12-week relative
strength and market cap, held until momentum breaks.

Entry
  close >= its 252-day rolling max, and yesterday was below its own 252-day max
  (a fresh break, not every day of an uptrend), and
  volume > volume_mult * 50-day average volume, and
  14-day return std <= max_volatility.

Ranking
  70% 12-week relative strength + 30% log market cap. Both terms use FIXED
  scales rather than population-normalised ones, so the live path and the
  backtest produce identical scores by construction — no normalisation drift.

Exits (adapter priority order)
  momentum breakdown (close < EMA50), hard stop 12%, take profit 35%,
  trailing stop 20%, time stop 90 days. Min hold 7 days before rotation.

Risk
  top 5 holdings, max 2 per sector, 50% exposure when SPY < SMA200.

Warmup
  The 252-day high is exact, not converging: it needs 252 bars. No date is
  scanned with fewer than WARMUP_BARS_REQUIRED (300) bars behind it, and history
  always loads from a fixed early floor so the first simulated day is warm.

All levers live in DEFAULT_CONFIG and are overridable per instance by keyword,
e.g. HighBreakoutRotation(volume_mult=1.5, use_volume_filter=False).
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
    # Signal
    "high_window": 252,
    "rs_window": 63,
    "fast_span": 50,             # EMA for the momentum-breakdown exit
    "volume_ma_span": 50,
    "volume_mult": 1.2,
    "use_volume_filter": True,   # UNMEASURED assumption — see the spec doc
    "max_volatility": 0.06,
    # Ranking (fixed scales; no population normalisation)
    "rs_weight": 0.70,
    "cap_weight": 0.30,
    "rs_center": 0.10,
    "rs_scale": 10.0,
    "cap_log_lo": 9.0,           # log10($1B)
    "cap_log_hi": 12.0,          # log10($1T)
    # Universe / risk
    "max_holdings": 5,
    "max_sector_count": 2,
    "bear_exposure": 0.50,
    # Exits
    "hard_stop_loss": 0.12,
    "take_profit": 0.35,
    "trailing_stop": 0.20,
    "time_stop_days": 90,
    "min_hold_days": 7,
    # Keep a holding that leaves the top-5 while still above its entry price.
    # Measured on this strategy (3 starts, shared signals): False -> True roughly
    # halved turnover (292 -> 169 median trades) and improved everything --
    # median CAGR 1.3% -> 8.8%, Sharpe 0.22 -> 0.44, maxDD 46% -> 37%.
    # Without it, a fresh breakout almost always outranks an existing holding
    # because the entry rule and the score both reward recent strength, so the
    # book churns every few days and the costs eat the edge.
    "protect_winners": True,
    # Sizing
    "sizing_pcts": [0.30, 0.25, 0.20, 0.15, 0.10],
    # Execution
    "cost_bps": 5.0,
}
_PROPERTY_KEYS = {"max_holdings", "sizing_pcts"}

# ── Indicator warmup ──────────────────────────────────────────────────
# rolling(252).max() is exact: it returns NaN until 252 bars exist, so unlike an
# EMA it fails loudly rather than silently. 300 gives margin.
WARMUP_BARS_REQUIRED = 300
# 300 trading days ~= 450 calendar days; 600 leaves margin for holidays.
WARMUP_CALENDAR_DAYS = 600
WARMUP_FLOOR = "2008-01-01"
WARMUP_MAX_ROWS = 8000


def required_load_start(first_date: str) -> str:
    """Earliest date to load so the longest indicator is warm by `first_date`.

    Returns the EARLIER of the fixed floor and (first_date - warmup buffer), so
    early simulation starts are not truncated while late starts still get their
    buffer.
    """
    try:
        cutoff = (
            pd.Timestamp(first_date) - pd.Timedelta(days=WARMUP_CALENDAR_DAYS)
        ).strftime("%Y-%m-%d")
    except Exception:
        return WARMUP_FLOOR
    return min(WARMUP_FLOOR, cutoff)


class HighBreakoutRotation(Strategy):
    """Fresh 52-week high breakouts, ranked by relative strength + market cap."""

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
        if cfg["high_window"] < 2 or cfg["rs_window"] < 1:
            raise ValueError("high_window must be >= 2 and rs_window >= 1")
        self.config = cfg
        for key, value in cfg.items():
            if key not in _PROPERTY_KEYS:
                setattr(self, key, value)

        self._price_cache: Optional[Dict[str, Dict[str, float]]] = None
        # Date-indexed Close series per ticker (populated by precompute_signals)
        # so should_exit/score_holding avoid a DB query per holding per day.
        self._close_cache: Dict[str, pd.Series] = {}

    def get_name(self) -> str:
        return "52-Week High Breakout Rotation"

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
                "strategy_exit",     # Momentum breakdown first
                "hard_stop_loss",
                "take_profit",
                "trailing_stop",
                "time_stop",
            ],
        )

    def get_precomputed_price_cache(self) -> Optional[Dict[str, Dict[str, float]]]:
        return self._price_cache

    # ── Scoring ───────────────────────────────────────────────────────

    def _score(self, rs: float, market_cap: float) -> float:
        """Fixed-scale score: a pure function of the stock, never of its peers."""
        rs = float(rs) if rs is not None and np.isfinite(rs) else 0.0
        rs_norm = 1.0 / (1.0 + np.exp(-(rs - self.rs_center) * self.rs_scale))

        if market_cap is None or not np.isfinite(market_cap) or market_cap <= 0:
            cap_norm = 0.0
        else:
            cap_norm = (np.log10(market_cap) - self.cap_log_lo) / (
                self.cap_log_hi - self.cap_log_lo
            )
            cap_norm = float(min(1.0, max(0.0, cap_norm)))

        return float(self.rs_weight * rs_norm + self.cap_weight * cap_norm)

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

    @staticmethod
    def _relative_strength(close: pd.Series, window: int) -> float:
        if len(close) <= window:
            return 0.0
        prev = float(close.iloc[-1 - window])
        if prev <= 0:
            return 0.0
        return float(close.iloc[-1]) / prev - 1.0

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
            i = len(df) - 1

            roll_max = close.rolling(self.high_window).max()
            if pd.isna(roll_max.iloc[i]) or pd.isna(roll_max.iloc[i - 1]):
                continue
            # Fresh break: at a new high today, below the prior high yesterday.
            if not (close.iloc[i] >= roll_max.iloc[i]
                    and close.iloc[i - 1] < roll_max.iloc[i - 1]):
                continue

            if self.use_volume_filter:
                vol_ma = volume.rolling(self.volume_ma_span).mean()
                if (pd.isna(vol_ma.iloc[i])
                        or volume.iloc[i] <= self.volume_mult * vol_ma.iloc[i]):
                    continue

            vol_14 = close.pct_change(fill_method=None).rolling(14).std()
            current_vol = float(vol_14.iloc[i]) if pd.notna(vol_14.iloc[i]) else 0.0
            if current_vol > self.max_volatility:
                continue

            rs = self._relative_strength(close, self.rs_window)
            mc, sector = meta.get(ticker.lower(), (0.0, "Unknown"))
            candidates.append({
                "ticker": ticker.upper(),
                "rs": rs,
                "market_cap": mc,
                "sector": sector,
                "price": float(close.iloc[i]),
                "date": str(df["Date"].iloc[i])[:10],
            })

        if not candidates:
            return []

        for c in candidates:
            c["score"] = self._score(c["rs"], c["market_cap"])
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
                entry_type="breakout",
                market_cap=c["market_cap"], sector=c["sector"],
            )
            for c in selected
        ]

    # ── Exit Logic ────────────────────────────────────────────────────

    def should_exit(self, ticker: str, as_of_date: str,
                    engine: Engine, side: str = "long") -> ExitCheck:
        """Momentum breakdown: close below the EMA50 the breakout was bought on."""
        if side != "long":
            return ExitCheck()

        try:
            close = self._load_close(ticker, as_of_date, engine)
            if close is None or len(close) < WARMUP_BARS_REQUIRED:
                return ExitCheck()
            ema_fast = close.ewm(span=self.fast_span, adjust=False).mean()
            if float(close.iloc[-1]) < float(ema_fast.iloc[-1]):
                return ExitCheck(should_close=True, reason="Momentum Breakdown")
        except Exception:
            pass

        return ExitCheck()

    # ── Holding Re-scoring (for rotation) ─────────────────────────────

    def score_holding(self, ticker: str, as_of_date: str, engine: Engine,
                      entry_price: float, market_cap: float, sector: str,
                      side: str = "long") -> float:
        """Re-score a holding on its current relative strength + market cap."""
        try:
            close = self._load_close(ticker, as_of_date, engine)
            if close is None or len(close) < WARMUP_BARS_REQUIRED:
                return 0.0
            rs = self._relative_strength(close, self.rs_window)
            return self._score(rs, market_cap)
        except Exception:
            return 0.0

    def _load_close(self, ticker: str, as_of_date: str,
                    engine: Engine) -> Optional[pd.Series]:
        """Close series up to as_of_date, from the cache when available."""
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
        """Vectorised scan: load each ticker once, mask every date at once."""
        from app.utils.security import get_safe_table_name

        if not all_dates:
            return {}

        first_date, last_date = all_dates[0], all_dates[-1]
        tickers = get_all_tickers(engine)
        meta = self._metadata(engine)
        load_start = required_load_start(first_date)

        logger.info("Precomputing breakouts for %d tickers across %d dates...",
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
            volumev = volume.to_numpy()

            ticker_lower = ticker.lower()
            finite = np.isfinite(closev)
            self._price_cache[ticker_lower] = dict(zip(dates[finite], closev[finite]))
            self._close_cache[ticker_lower] = pd.Series(closev, index=dates)

            roll_max = close.rolling(self.high_window).max().to_numpy()
            at_high = closev >= roll_max          # NaN -> False
            transition = at_high[1:] & ~at_high[:-1]

            if self.use_volume_filter:
                vol_ma = volume.rolling(self.volume_ma_span).mean().to_numpy()
                volume_ok = volumev[1:] > self.volume_mult * vol_ma[1:]
            else:
                volume_ok = np.ones(len(transition), dtype=bool)

            vol_14 = close.pct_change(fill_method=None).rolling(14).std().to_numpy()
            vol_ok = ~(vol_14[1:] > self.max_volatility)   # NaN -> pass

            rs_series = (close / close.shift(self.rs_window) - 1.0).to_numpy()
            idx = np.arange(1, len(dates))
            warm_ok = (idx + 1) >= WARMUP_BARS_REQUIRED
            in_dates = np.isin(dates[1:], all_dates)

            mask = transition & volume_ok & vol_ok & warm_ok & in_dates
            hits = np.where(mask)[0] + 1

            if len(hits) == 0:
                continue

            mc, sector = meta.get(ticker_lower, (0.0, "Unknown"))
            for i in hits:
                ds = dates[i]
                all_candidates.setdefault(ds, []).append({
                    "ticker": ticker.upper(),
                    "rs": float(rs_series[i]) if np.isfinite(rs_series[i]) else 0.0,
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
                c["score"] = self._score(c["rs"], c["market_cap"])
            cands.sort(key=lambda x: x["score"], reverse=True)
            result[ds] = [
                Signal(
                    ticker=c["ticker"], side="long",
                    score=round(c["score"], 6),
                    price=c["price"], entry_date=ds,
                    entry_type="breakout",
                    market_cap=c["market_cap"], sector=c["sector"],
                )
                for c in cands
            ]

        logger.info("Precomputed breakouts: %d of %d dates have signals",
                    sum(1 for v in result.values() if v), len(all_dates))
        return result
