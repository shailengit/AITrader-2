"""Golden Cross Volume Rotation Strategy — pluggable Strategy implementation.

Scans 1500 stocks daily for an EMA20/50 golden cross with volume confirmation.
Entry requires ALL of:
  - Price above 200-day SMA (trend filter)
  - EMA20 crosses above EMA50 on the signal day (golden cross)
  - Volume > 1.5x 50-day average on the cross day (volume confirmation)
  - 14-day daily-return std <= 5% (volatility filter)
Ranks by: 60% crossover angle + 40% market cap.
Buys the top 5, holds while a position stays in the top 10 (buy/hold spread),
rotates out only when a holding drops out of the top 10 or an exit rule fires.
Exits: death cross, trailing stop (20%), take profit (25%), time stop (90d),
hard stop loss (10%), or rotated out.
Minimum hold days: 10 before rotation close.
Score-weighted position sizing (higher composite score = larger position).
Sector diversification (max 2 per sector).
Bear market mode: SPY < SMA(200) -> go to cash (0% exposure).
"""

import logging
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np
from sqlalchemy import Engine, text

from app.services.strategy_base import Strategy, Signal, ExitCheck, RotationConfig, get_all_tickers

logger = logging.getLogger(__name__)

# ── Strategy Parameters ───────────────────────────────────────────────
ANGLE_WEIGHT = 0.60
CAP_WEIGHT = 0.40
MAX_HOLDINGS = 5
HOLD_RANK = 10            # Buy/hold spread: keep a holding while it ranks in the top 10
MIN_HOLD_DAYS = 10
TIME_STOP_DAYS = 90
TAKE_PROFIT = 0.25
TRAILING_STOP = 0.20
HARD_STOP_LOSS = 0.10
MAX_VOLATILITY = 0.05
MAX_SECTOR_COUNT = 2
VOLUME_MULT = 1.0         # Volume confirmation: > 1.0x 50-day average (loosened from 1.5x)
EMA_FAST = 10             # Fast EMA (10-day catches trends earlier than 20)
EMA_SLOW = 200            # Slow EMA (200-day trend filter; EMA not SMA is critical)
SMA_TREND = 200           # Trend filter: price above 200-day SMA
BEAR_EXPOSURE = 0.0       # Go to cash in bear market (SPY < SMA200)


class GoldenCrossVolumeRotation(Strategy):
    """Golden cross + volume confirmation rotation with buy/hold spread."""

    def __init__(self, **overrides):
        super().__init__()
        self._price_cache: Optional[Dict[str, Dict[str, float]]] = None
        self._close_cache: Dict[str, pd.Series] = {}
        self._cap_min: float = 0.0
        self._cap_range: float = 1.0
        # Allow runtime parameter overrides for experimentation (Phase 4).
        self.p = {
            "angle_weight": ANGLE_WEIGHT,
            "cap_weight": CAP_WEIGHT,
            "max_holdings": MAX_HOLDINGS,
            "hold_rank": HOLD_RANK,
            "min_hold_days": MIN_HOLD_DAYS,
            "time_stop_days": TIME_STOP_DAYS,
            "take_profit": TAKE_PROFIT,
            "trailing_stop": TRAILING_STOP,
            "hard_stop_loss": HARD_STOP_LOSS,
            "max_volatility": MAX_VOLATILITY,
            "max_sector_count": MAX_SECTOR_COUNT,
            "volume_mult": VOLUME_MULT,
            "vol_mode": "cross_day",     # "cross_day" (spike on cross day) or "spike_window" (spike in recent window)
            "vol_avg_window": 50,        # Average-volume window for the volume check
            "vol_spike_window": 5,       # Look back this many days for a volume spike
            "ema_fast": EMA_FAST,
            "ema_slow": EMA_SLOW,
            "fast_ma_type": "ema",   # "ema" or "sma"
            "slow_ma_type": "ema",   # "ema" or "sma"
            "sma_trend": SMA_TREND,
            "bear_exposure": BEAR_EXPOSURE,
        }
        self.p.update(overrides)

    def get_name(self) -> str:
        return "Golden Cross Volume Rotation"

    @property
    def max_holdings(self) -> int:
        return self.p["max_holdings"]

    @property
    def sizing_pcts(self) -> List[float]:
        # Score-weighted sizing is handled by the adapter via sizing_method="linear".
        # This property is required by the ABC but unused when linear sizing is set.
        return [0.20, 0.20, 0.20, 0.20, 0.20]

    def get_rotation_config(self) -> RotationConfig:
        return RotationConfig(
            sizing_method="linear",        # Score-weighted: higher score = larger position
            hard_stop_loss=self.p["hard_stop_loss"],
            trailing_stop=self.p["trailing_stop"],
            take_profit=self.p["take_profit"],
            time_stop_days=self.p["time_stop_days"],
            min_hold_days=self.p["min_hold_days"],
            max_sector_count=self.p["max_sector_count"],
            re_score_holdings=True,        # Re-score holdings using current EMA spread
            protect_winners=False,         # Rotation handled by the top-10 hold band
            rotation_hold_rank=self.p["hold_rank"],  # Buy/hold spread: hold while in top 10
            bear_exposure=self.p["bear_exposure"],   # Go to cash in bear market
            exit_priority=[
                "strategy_exit",     # Death cross first (via should_exit)
                "hard_stop_loss",    # Then hard stop loss
                "take_profit",       # Then take profit
                "trailing_stop",     # Then trailing stop
                "time_stop",         # Then time stop
            ],
        )

    def get_precomputed_price_cache(self) -> Optional[Dict[str, Dict[str, float]]]:
        return self._price_cache

    # ── Signal Generation ──────────────────────────────────────────────

    def get_signals(self, as_of_date: str, engine: Engine) -> List[Signal]:
        """Scan all stocks for golden cross + volume signals, rank by score."""
        from app.utils.security import get_safe_table_name

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
            close = df["Close"]
            volume = df["Volume"].astype(float)
            ema_fast = self._ma(close, self.p["ema_fast"], self.p["fast_ma_type"])
            ema_slow = self._ma(close, self.p["ema_slow"], self.p["slow_ma_type"])
            sma_trend = close.rolling(window=self.p["sma_trend"]).mean()
            vol_ma50 = volume.rolling(50).mean()

            # 14-day rolling volatility
            returns = close.pct_change()
            vol_14 = returns.rolling(14).std()

            i = len(df) - 1
            if not (pd.notna(ema_fast.iloc[i]) and pd.notna(ema_slow.iloc[i]) and
                    pd.notna(ema_fast.iloc[i - 1]) and pd.notna(ema_slow.iloc[i - 1])):
                continue

            # Golden cross on the most recent trading day
            if not (ema_fast.iloc[i - 1] <= ema_slow.iloc[i - 1] and ema_fast.iloc[i] > ema_slow.iloc[i]):
                continue

            # Trend filter: price above 200-day SMA
            if pd.isna(sma_trend.iloc[i]) or close.iloc[i] <= sma_trend.iloc[i]:
                continue

            # Volume confirmation: volume > volume_mult x the vol_avg_window-day
            # average. In "cross_day" mode the spike must be on the cross day;
            # in "spike_window" mode it may occur anywhere in the recent window.
            if self.p["vol_mode"] == "spike_window":
                if not self._volume_spike_ok(volume, i):
                    continue
            else:
                vol_avg = volume.rolling(self.p["vol_avg_window"]).mean()
                if pd.isna(vol_avg.iloc[i]) or volume.iloc[i] <= self.p["volume_mult"] * vol_avg.iloc[i]:
                    continue

            # Volatility filter
            current_vol = float(vol_14.iloc[i]) if pd.notna(vol_14.iloc[i]) else 0.0
            if current_vol > self.p["max_volatility"]:
                continue

            angle = self._compute_crossover_angle(close, ema_fast, ema_slow, i)

            # Market cap for scoring
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

            candidates.append({
                "ticker": ticker.upper(),
                "angle": angle,
                "market_cap": mc,
                "sector": sector,
                "price": float(close.iloc[i]),
                "date": str(df["Date"].iloc[i])[:10],
            })

        if not candidates:
            return []

        # Normalize market caps
        caps = [c["market_cap"] for c in candidates if c["market_cap"] > 0]
        cap_max = max(caps) if caps else 1
        cap_min = min(caps) if caps else 0
        cap_range = cap_max - cap_min if cap_max > cap_min else 1

        # Score and rank
        for c in candidates:
            angle_norm = 1 / (1 + np.exp(-c["angle"] * 100))
            cap_norm = (c["market_cap"] - cap_min) / cap_range if cap_range > 0 else 0.5
            c["score"] = self.p["angle_weight"] * angle_norm + self.p["cap_weight"] * cap_norm

        candidates.sort(key=lambda x: x["score"], reverse=True)

        # Apply sector diversification (max MAX_SECTOR_COUNT per sector)
        selected = []
        sector_counts: Dict[str, int] = {}
        for c in candidates:
            if len(selected) >= self.p["max_holdings"]:
                break
            sec = c.get("sector", "Unknown")
            if sector_counts.get(sec, 0) >= self.p["max_sector_count"]:
                continue
            selected.append(c)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

        return [
            Signal(
                ticker=c["ticker"],
                side="long",
                score=round(c["score"], 4),
                angle=round(c["angle"], 4),
                price=c["price"],
                entry_date=c["date"],
                entry_type="golden_cross_volume",
                market_cap=c.get("market_cap", 0),
                sector=c.get("sector", "Unknown"),
            )
            for c in selected
        ]

    # ── Exit Logic ────────────────────────────────────────────────────

    def should_exit(self, ticker: str, as_of_date: str,
                    engine: Engine, side: str = "long") -> ExitCheck:
        """Check for death cross (EMA20 < EMA50)."""
        if side != "long":
            return ExitCheck()

        try:
            close = self._close_cache.get(ticker.lower())
            if close is not None:
                close_up_to = close[close.index <= as_of_date]
                if len(close_up_to) < 50:
                    return ExitCheck()
                ema_fast = self._ma(close_up_to, self.p["ema_fast"], self.p["fast_ma_type"])
                ema_slow = self._ma(close_up_to, self.p["ema_slow"], self.p["slow_ma_type"])
                last_fast = ema_fast.iloc[-1]
                last_slow = ema_slow.iloc[-1]
                if pd.isna(last_fast) or pd.isna(last_slow):
                    return ExitCheck()
                if last_fast < last_slow:
                    return ExitCheck(should_close=True, reason="Death Cross")
                return ExitCheck()

            # Fallback: load from DB (per-day mode, no precompute cache).
            from app.utils.security import get_safe_table_name
            safe = get_safe_table_name(ticker)
            with engine.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Close" FROM "{safe}" '
                    f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 250',
                    conn,
                )
            if df.empty or len(df) < 50:
                return ExitCheck()
            df = df.sort_values("Date").reset_index(drop=True)
            ema_fast = self._ma(df["Close"], self.p["ema_fast"], self.p["fast_ma_type"])
            ema_slow = self._ma(df["Close"], self.p["ema_slow"], self.p["slow_ma_type"])
            last_fast = ema_fast.iloc[-1]
            last_slow = ema_slow.iloc[-1]
            if pd.isna(last_fast) or pd.isna(last_slow):
                return ExitCheck()
            if last_fast < last_slow:
                return ExitCheck(should_close=True, reason="Death Cross")

        except Exception:
            pass

        return ExitCheck()

    # ── Holding Re-scoring (for rotation) ─────────────────────────────

    def score_holding(self, ticker: str, as_of_date: str, engine: Engine,
                      entry_price: float, market_cap: float, sector: str,
                      side: str = "long") -> float:
        """Re-score an existing holding using current EMA20/50 spread + market cap."""
        from app.utils.security import get_safe_table_name
        try:
            safe = get_safe_table_name(ticker)
            with engine.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Close" FROM "{safe}" '
                    f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 250',
                    conn,
                )
            if df.empty or len(df) < 50:
                return 0.0
            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"].astype(float)
            ema_fast = self._ma(close, self.p["ema_fast"], self.p["fast_ma_type"])
            ema_slow = self._ma(close, self.p["ema_slow"], self.p["slow_ma_type"])
            last_fast = float(ema_fast.iloc[-1])
            last_slow = float(ema_slow.iloc[-1])
            if pd.isna(last_fast) or pd.isna(last_slow) or last_slow <= 0:
                return 0.0
            spread_pct = (last_fast - last_slow) / last_slow
            angle_norm = 1 / (1 + np.exp(-spread_pct * 100))
            cap_norm = (market_cap - self._cap_min) / self._cap_range if self._cap_range > 0 else 0.5
            return self.p["angle_weight"] * angle_norm + self.p["cap_weight"] * cap_norm
        except Exception:
            return 0.0

    # ── Precomputed Signals (efficient backtesting) ─────────────────────

    def precompute_signals(self, all_dates: List[str], engine: Engine) -> Optional[Dict[str, List[Signal]]]:
        """Precompute golden cross + volume signals for all dates at once."""
        from app.utils.security import get_safe_table_name

        tickers = get_all_tickers(engine)
        logger.info("Precomputing signals for %d tickers across %d dates...", len(tickers), len(all_dates))

        first_date = all_dates[0]
        last_date = all_dates[-1]
        date_set = set(all_dates)

        # Load ticker data from an early fixed date so every run has full
        # indicator warmup (EMA200 needs ~200 bars) AND pre-2018 simulation
        # dates see signals. Hardcoding 2018 here made pre-2018 runs blind (no
        # signals until 2018) -> identical results regardless of start date.
        # Using `first_date - N days` is WRONG for early simulation starts: it
        # can push load_start later than the old hardcode, truncating warmup.
        # A fixed early start is always safe (indicators just warm up correctly).
        load_start = "2018-01-01"

        # Pre-fetch market cap and sector for all tickers
        meta_cache: Dict[str, tuple] = {}
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT ticker, market_cap, sector FROM stock_metadata")
                ).fetchall()
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

            load_start = _load_start
            try:
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Close", "Volume" FROM "{safe}" '
                        f'WHERE "Date" >= \'{load_start}\' AND "Date" <= \'{last_date}\' '
                        f'ORDER BY "Date" DESC LIMIT 3000',
                        conn,
                    )
            except Exception:
                continue

            if df.empty or len(df) < 250:
                continue

            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            ema_fast = self._ma(close, self.p["ema_fast"], self.p["fast_ma_type"])
            ema_slow = self._ma(close, self.p["ema_slow"], self.p["slow_ma_type"])
            sma_trend = close.rolling(window=self.p["sma_trend"]).mean()
            vol_ma50 = volume.rolling(self.p["vol_avg_window"]).mean()
            returns = close.pct_change()
            vol_14 = returns.rolling(14).std()

            # Build price cache (vectorized; skip NULL/NaT closes)
            ticker_lower = ticker.lower()
            if self._price_cache is None:
                self._price_cache = {}
            if ticker_lower not in self._price_cache:
                _d = df["Date"].astype(str).str[:10].to_numpy()
                _c = df["Close"].astype(float).to_numpy()
                _fin = np.isfinite(_c)
                self._price_cache[ticker_lower] = dict(zip(_d[_fin], _c[_fin]))
            self._close_cache[ticker_lower] = pd.Series(
                df["Close"].astype(float).to_numpy(), index=df["Date"].astype(str).str[:10]
            )

            # Market cap & sector
            mc, sector = meta_cache.get(ticker.lower(), (0.0, "Unknown"))

            # Vectorized golden-cross + volume scan
            dates = df["Date"].astype(str).str[:10].to_numpy()
            ema_fast_v = ema_fast.to_numpy()
            ema_slow_v = ema_slow.to_numpy()
            sma_trend_v = sma_trend.to_numpy()
            vol_avg_v = vol_ma50.to_numpy()
            vol14v = vol_14.to_numpy()
            closev = close.to_numpy()
            volv = volume.to_numpy()

            prev_ok = ~np.isnan(ema_fast_v[:-1]) & ~np.isnan(ema_slow_v[:-1])
            cur_ok = ~np.isnan(ema_fast_v[1:]) & ~np.isnan(ema_slow_v[1:])
            cross = prev_ok & cur_ok & (ema_fast_v[:-1] <= ema_slow_v[:-1]) & (ema_fast_v[1:] > ema_slow_v[1:])
            in_dates = np.array([d in date_set for d in dates[1:]])
            # Trend filter: close > SMA200
            trend_ok = ~np.isnan(sma_trend_v[1:]) & (closev[1:] > sma_trend_v[1:])
            # Volume confirmation. cross_day: spike on the cross day.
            # spike_window: spike anywhere in the last vol_spike_window days.
            if self.p["vol_mode"] == "spike_window":
                ratio = np.full_like(volv, np.nan)
                ok_avg = ~np.isnan(vol_avg_v)
                ratio[ok_avg] = volv[ok_avg] / vol_avg_v[ok_avg]
                ratio_series = pd.Series(ratio)
                max_ratio = ratio_series.rolling(self.p["vol_spike_window"], min_periods=1).max().to_numpy()
                vol_ok = ~np.isnan(max_ratio[1:]) & (max_ratio[1:] > self.p["volume_mult"])
            else:
                vol_ok = ~np.isnan(vol_avg_v[1:]) & (volv[1:] > self.p["volume_mult"] * vol_avg_v[1:])
            # Volatility filter
            vol14_ok = np.isnan(vol14v[1:]) | (vol14v[1:] <= self.p["max_volatility"])
            mask = cross & in_dates & trend_ok & vol_ok & vol14_ok
            hit_idx = np.where(mask)[0] + 1

            for i in hit_idx:
                ds = dates[i]
                angle = self._compute_crossover_angle(close, ema_fast, ema_slow, int(i))
                if ds not in all_candidates:
                    all_candidates[ds] = []
                all_candidates[ds].append({
                    "ticker": ticker.upper(),
                    "angle": angle,
                    "market_cap": mc,
                    "sector": sector,
                    "price": float(closev[i]),
                    "date": ds,
                })

        if not all_candidates:
            logger.info("No golden cross + volume signals found in date range")
            return {d: [] for d in all_dates}

        # Normalize market caps across ALL stocks in the universe
        all_caps = [mc for mc, _ in meta_cache.values() if mc > 0]
        cap_max = max(all_caps) if all_caps else 1
        cap_min = min(all_caps) if all_caps else 0
        cap_range = cap_max - cap_min if cap_max > cap_min else 1
        self._cap_min = cap_min
        self._cap_range = cap_range

        result: Dict[str, List[Signal]] = {}
        for date_str in all_dates:
            candidates = all_candidates.get(date_str, [])
            if not candidates:
                result[date_str] = []
                continue

            for c in candidates:
                angle_norm = 1 / (1 + np.exp(-c["angle"] * 100))
                cap_norm = (c["market_cap"] - cap_min) / cap_range if cap_range > 0 else 0.5
                c["score"] = self.p["angle_weight"] * angle_norm + self.p["cap_weight"] * cap_norm

            candidates.sort(key=lambda x: x["score"], reverse=True)

            result[date_str] = [
                Signal(
                    ticker=c["ticker"],
                    side="long",
                    score=round(c["score"], 4),
                    angle=round(c["angle"], 4),
                    price=c["price"],
                    entry_date=c["date"],
                    entry_type="golden_cross_volume",
                    market_cap=c.get("market_cap", 0),
                    sector=c.get("sector", "Unknown"),
                )
                for c in candidates
            ]

        logger.info(
            "Precomputed signals: %d dates with signals out of %d total dates",
            sum(1 for v in result.values() if v), len(all_dates),
        )
        return result

    # ── Internal Helpers ──────────────────────────────────────────────

    @staticmethod
    def _ma(close, window, ma_type):
        """Compute a moving average (EMA or SMA) of a close series."""
        if ma_type == "sma":
            return close.rolling(window=window).mean()
        return close.ewm(span=window, adjust=False).mean()

    def _volume_spike_ok(self, volume, i):
        """True if volume exceeded volume_mult x the vol_avg_window-day average
        at any point in the last vol_spike_window days (including the cross day).

        This is a looser confirmation than requiring the spike exactly on the
        cross day — it accepts a volume surge anywhere in a recent window.
        """
        avg_win = self.p["vol_avg_window"]
        spike_win = self.p["vol_spike_window"]
        mult = self.p["volume_mult"]
        vol_avg = volume.rolling(avg_win).mean()
        start = max(0, i - spike_win + 1)
        for j in range(start, i + 1):
            if pd.isna(vol_avg.iloc[j]):
                continue
            if volume.iloc[j] > mult * vol_avg.iloc[j]:
                return True
        return False

    @staticmethod
    def _compute_crossover_angle(close, ema_fast, ema_slow, cross_idx):
        """Compute the angle between EMA_fast and EMA_slow at crossover."""
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
