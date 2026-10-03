"""Daily Golden Cross Rotation Strategy — pluggable Strategy implementation.

Scans 1500 stocks daily for an EMA20/EMA200 golden cross.
Ranks by: 60% crossover angle + 40% market cap.
Holds top 5, rotates when better candidates appear.
Exits: death cross, death cross warning, time stop (60d), or rotated out.
Minimum hold days: 7 before rotation close.
Entry filters: 14d daily return std <= 5%. A volume filter (cross-day volume
above its 50-day average) is available via use_volume_filter but defaults OFF.
Sector diversification (max 2 per sector).
Score-squared position sizing for aggressive top-pick weighting.

All levers live in DEFAULT_CONFIG and can be overridden per instance by keyword,
e.g. DailyGoldenCrossRotation(fast_span=10, use_volume_filter=True).

Indicator warmup is guaranteed: history is always loaded from an early fixed
date so EMA200 is converged before the first simulated day. If the available
history is too short, a warning is recorded (see get_warmup_warnings()).
"""

import logging
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np
from sqlalchemy import Engine, text

from app.services.strategy_base import Strategy, Signal, ExitCheck, RotationConfig, get_all_tickers

logger = logging.getLogger(__name__)

# ── Strategy Parameters ───────────────────────────────────────────────
# Pinned defaults. An instance may override any of these by keyword
# (DailyGoldenCrossRotation(fast_span=20)); an unknown key raises rather than
# silently running the default, so a typo'd sweep key fails loudly.
#
# The fast/slow MA pair is the primary lever. Defaults are EMA20/EMA200, chosen
# by a paired 6-start multi-start A/B (2026-10-02) rather than by the prior:
#   - the EMA slow line is validated — EMA10/EMA200 beat EMA10/SMA200 on
#     CAGR/alpha/Sharpe/PF 6/6 starts (p=0.031). An SMA slow line collapses the
#     golden-cross edge, so slow_ma_type stays "ema".
#   - fast_span=20 beat fast_span=10 in both slow-line contexts (6/6 on SMA200,
#     4/6 on EMA200), so the default is 20, not 10.
#   - the volume filter removes ~58% of crossovers and cost return in every
#     context tested (on EMA20/EMA200 it cut median CAGR from 22.4% to 6.4%),
#     while buying some drawdown. It is kept as an available lever but defaults
#     OFF; turn it on if drawdown control matters more than return.
DEFAULT_CONFIG: Dict[str, Any] = {
    # Signal
    "fast_span": 20,
    "slow_span": 200,
    "slow_ma_type": "ema",          # "ema" | "sma"
    "volume_ma_span": 50,
    "use_volume_filter": False,     # require cross-day Volume > its 50d average
    "angle_weight": 0.60,
    "cap_weight": 0.40,
    # Universe / risk
    "max_holdings": 5,
    "max_volatility": 0.05,
    "max_sector_count": 2,
    "bear_exposure": 0.50,
    # Exits
    "take_profit": 0.30,
    "trailing_stop": 0.30,
    "time_stop_days": 60,
    "min_hold_days": 7,
    "dc_warning_spread": 0.001,
    "protect_winners": True,
    # Sizing
    "sizing_pcts": [0.30, 0.25, 0.20, 0.15, 0.10],
}
# Keys backed by properties rather than plain attributes.
_PROPERTY_KEYS = {"max_holdings", "sizing_pcts"}

# ── Indicator warmup (non-negotiable) ──────────────────────────────────
# An EMA carries no warmup guard of its own: ewm() returns a number from the
# very first bar, so an unconverged EMA200 is indistinguishable from a
# converged one. (rolling(200) used to return NaN and mask this; ewm does not.)
# EMA200 needs ~830 bars (~4.15 x span) to converge, so no ticker may be
# scanned on a date with fewer than that many bars behind it.
WARMUP_BARS_REQUIRED = 830
# 830 trading days ≈ 1200 calendar days; 1300 leaves margin for holidays.
WARMUP_CALENDAR_DAYS = 1300
# Never load later than this, so early simulation starts keep their warmup.
WARMUP_FLOOR = "2008-01-01"
# Bars to load for the live (per-day) path — enough for EMA200 to converge
# without pulling 18 years of history for every ticker every day.
WARMUP_LIVE_BARS = WARMUP_BARS_REQUIRED + 200
# History rows to request per ticker in the backtest precompute. A DESC LIMIT
# means this is the most recent N bars, so it bounds the load window too.
WARMUP_MAX_ROWS = 5000
# The per-day path re-evaluates warmup on every call, and each message carries
# its own date, so cap the list or a day-by-day loop grows it without bound.
MAX_WARMUP_WARNINGS = 5


def required_load_start(first_date: str) -> str:
    """Earliest date to load so the slow MA is warm by `first_date`.

    Returns the EARLIER of the fixed floor and (first_date - warmup buffer).
    Taking the floor alone would over-load for late starts; taking
    `first_date - buffer` alone would truncate warmup for early starts (e.g. a
    2010 start would load from 2009 and have only ~250 warm bars). Taking the
    earlier of the two is correct in both directions.
    """
    try:
        cutoff = (
            pd.Timestamp(first_date) - pd.Timedelta(days=WARMUP_CALENDAR_DAYS)
        ).strftime("%Y-%m-%d")
    except Exception:
        return WARMUP_FLOOR
    return min(WARMUP_FLOOR, cutoff)

# ── Notes on the tuned exit levers (defaults live in DEFAULT_CONFIG) ────
# dc_warning_spread: kept at 0.001 (original). Raising it (0.01) fired too many
#   premature exits and HURT return/CAGR, so that hypothesis was reverted.
#   NOTE: this was tuned against an EMA20/SMA200 pair. The shipped default keeps
#   fast_span=20 but switches the slow line to an EMA, so the spread distribution
#   it was tuned against has changed. It has NOT been re-tuned — an open item.
# trailing_stop: widened 0.20 -> 0.30. Trailing Stop was the worst per-trade
#   exit (-$5,921.04 avg in the aggregate); a wider trail avoids stopping out
#   winners early. 0.30/0.32/0.34 measured identical once protect_winners is on.
# protect_winners: keep a holding that leaves the top-N while it is still above
#   its entry price, so high-quality winners run toward 20d+ (63.0% win /
#   +$1,801.79 avg), the strongest holding bucket. Measured across 8 fixed
#   starts: return 165.5%->278.7%, Sharpe 0.91->1.21, max DD 26.4%->23.2%.


class DailyGoldenCrossRotation(Strategy):
    """Daily golden cross rotation with sector diversification and volatility filter.

    Config is pinned by DEFAULT_CONFIG and overridable by keyword; see that
    dict for the full set of levers.
    """

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
        if cfg["slow_ma_type"] not in ("ema", "sma"):
            raise ValueError(
                f"slow_ma_type must be 'ema' or 'sma', got {cfg['slow_ma_type']!r}"
            )
        if cfg["fast_span"] < 2 or cfg["slow_span"] < 2:
            raise ValueError("fast_span and slow_span must both be >= 2")
        self.config = cfg
        for key, value in cfg.items():
            if key not in _PROPERTY_KEYS:
                setattr(self, key, value)

        self._price_cache: Optional[Dict[str, Dict[str, float]]] = None
        # Date-indexed Close series per ticker, populated by precompute_signals
        # so should_exit() avoids a DB query per holding per day.
        self._close_cache: Dict[str, pd.Series] = {}
        # Market cap normalization constants (set during precompute_signals)
        self._cap_min: float = 0.0
        self._cap_range: float = 1.0
        # Warmup shortfall messages, surfaced by the adapter and the standalone.
        self.warmup_warnings: List[str] = []

    # ── Indicator helpers (single definition point for the MA pair) ─────

    def _fast_line(self, close: pd.Series) -> pd.Series:
        return close.ewm(span=self.fast_span, adjust=False).mean()

    def _slow_line(self, close: pd.Series) -> pd.Series:
        """The slow trend line: EMA by default, SMA only when explicitly asked."""
        if self.slow_ma_type == "sma":
            return close.rolling(window=self.slow_span).mean()
        return close.ewm(span=self.slow_span, adjust=False).mean()

    def get_name(self) -> str:
        return "Daily Golden Cross Rotation"

    def get_warmup_warnings(self) -> List[str]:
        """Warmup shortfall messages recorded during signal generation."""
        return list(self.warmup_warnings)

    def _record_warmup_warning(self, msg: str) -> None:
        """Record a warmup shortfall once (deduplicated) and log it.

        Bounded: the per-day path can re-detect the same shortfall on every
        date, each with a different date in the message, so the list is capped.
        """
        if msg in self.warmup_warnings:
            return
        if len(self.warmup_warnings) >= MAX_WARMUP_WARNINGS:
            return
        self.warmup_warnings.append(msg)
        logger.warning(msg)

    def _warn_on_warmup(self, warm_ok: int, warm_short: int,
                        warm_min: Optional[int], first_date: str) -> None:
        """Warn when any part of the universe is too short for a converged EMA."""
        total = warm_ok + warm_short
        if not total or warm_short == 0:
            return

        min_txt = f", shortest {warm_min} bars" if warm_min is not None else ""
        pct = 100.0 * warm_ok / total
        self._record_warmup_warning(
            f"EMA{self.slow_span} warmup shortfall at {first_date}: {warm_short} of {total} "
            f"tickers ({100 - pct:.1f}%) have fewer than {WARMUP_BARS_REQUIRED} bars"
            f"{min_txt} and are skipped — their EMA{self.slow_span} is not converged. "
            f"Move the start date later, or extend the database history, to trade them."
        )
        if warm_ok == 0:
            self._record_warmup_warning(
                f"EMA{self.slow_span} warmup FAILED at {first_date}: no ticker in the "
                f"universe has {WARMUP_BARS_REQUIRED} bars of history. The start date "
                f"is earlier than the data supports, so all signals are unreliable."
            )

    @property
    def max_holdings(self) -> int:
        return int(self.config["max_holdings"])

    @property
    def sizing_pcts(self) -> List[float]:
        return list(self.config["sizing_pcts"])

    def get_rotation_config(self) -> RotationConfig:
        """Match the standalone daily_golden_cross_rotation.py config exactly."""
        return RotationConfig(
            sizing_method="score_squared",
            hard_stop_loss=0.0,       # No hard stop in standalone
            trailing_stop=self.trailing_stop,
            take_profit=self.take_profit,
            time_stop_days=self.time_stop_days,
            min_hold_days=self.min_hold_days,
            max_sector_count=self.max_sector_count,
            re_score_holdings=True,    # Re-score holdings using current EMA spread
            protect_winners=self.protect_winners,
            bear_exposure=self.bear_exposure,  # 50% exposure in bear market by default
            exit_priority=[
                "strategy_exit",     # Death cross first (via should_exit)
                "take_profit",       # Then take profit
                "trailing_stop",     # Then trailing stop
                "time_stop",         # Then time stop
            ],
        )

    def get_precomputed_price_cache(self) -> Optional[Dict[str, Dict[str, float]]]:
        return self._price_cache

    # ── Signal Generation ──────────────────────────────────────────────

    def get_signals(self, as_of_date: str, engine: Engine) -> List[Signal]:
        """Scan all stocks for golden cross signals, rank by score with sector diversification."""
        from app.utils.security import get_safe_table_name

        tickers = get_all_tickers(engine)
        candidates: List[Dict[str, Any]] = []
        # Warmup accounting — how many tickers have enough history to trust EMA200.
        warm_ok = 0
        warm_short = 0
        warm_min = None

        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue

            try:
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Open", "High", "Low", "Close", "Volume" FROM "{safe}" '
                        f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC '
                        f'LIMIT {WARMUP_LIVE_BARS}',
                        conn,
                    )
            except Exception:
                continue

            if df.empty:
                continue

            # EMA200 is only trustworthy with WARMUP_BARS_REQUIRED bars behind
            # it. Count the shortfall so the caller learns the universe is
            # partly unwarmed rather than silently getting bad signals.
            if len(df) < WARMUP_BARS_REQUIRED:
                warm_short += 1
                warm_min = len(df) if warm_min is None else min(warm_min, len(df))
                continue
            warm_ok += 1

            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"]
            volume = df["Volume"].astype(float)
            fast_ma = self._fast_line(close)
            slow_ma = self._slow_line(close)
            vol_ma50 = volume.rolling(self.volume_ma_span).mean()

            # 14-day rolling volatility
            returns = close.pct_change()  # Must match standalone (default fill_method='pad')
            vol_14 = returns.rolling(14).std()

            # Check for golden cross on the most recent trading day
            i = len(df) - 1
            if not (pd.notna(fast_ma.iloc[i]) and pd.notna(slow_ma.iloc[i]) and
                    pd.notna(fast_ma.iloc[i - 1]) and pd.notna(slow_ma.iloc[i - 1])):
                continue

            if not (fast_ma.iloc[i - 1] <= slow_ma.iloc[i - 1] and fast_ma.iloc[i] > slow_ma.iloc[i]):
                continue

            # Volatility filter
            current_vol = float(vol_14.iloc[i]) if pd.notna(vol_14.iloc[i]) else 0.0
            if current_vol > self.max_volatility:
                continue

            # Volume confirmation: the cross-day volume must beat its 50-day
            # average. A cross on thin volume has no participation behind it.
            if self.use_volume_filter:
                current_vol_ma50 = vol_ma50.iloc[i]
                if not (pd.notna(current_vol_ma50) and volume.iloc[i] > current_vol_ma50):
                    continue

            angle = self._compute_crossover_angle(close, fast_ma, slow_ma, i)

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

        # Warn if part of the universe is too short for a converged EMA200.
        self._warn_on_warmup(warm_ok, warm_short, warm_min, as_of_date)

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
            c["score"] = self.angle_weight * angle_norm + self.cap_weight * cap_norm

        candidates.sort(key=lambda x: x["score"], reverse=True)

        # Apply sector diversification (max self.max_sector_count per sector)
        selected = []
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
                ticker=c["ticker"],
                side="long",
                score=round(c["score"], 4),
                angle=round(c["angle"], 4),
                price=c["price"],
                entry_date=c["date"],
                entry_type="golden_cross",
            )
            for c in selected
        ]

    # ── Exit Logic ────────────────────────────────────────────────────

    def should_exit(self, ticker: str, as_of_date: str,
                    engine: Engine, side: str = "long") -> ExitCheck:
        """Check for death cross, death cross warning, or time stop."""
        if side != "long":
            return ExitCheck()

        try:
            # Use the Date-indexed Close cache (populated by precompute_signals)
            # to avoid a DB query per holding per day.
            close = self._close_cache.get(ticker.lower())
            if close is not None:
                close_up_to = close[close.index <= as_of_date]
                # ewm() yields a value from the first bar, so a short series
                # produces a plausible-looking but unconverged EMA200. Refuse to
                # act on it (and on any death cross built from it) until warmed.
                if len(close_up_to) < WARMUP_BARS_REQUIRED:
                    return ExitCheck()
                fast_ma = self._fast_line(close_up_to)
                slow_ma = self._slow_line(close_up_to)
                last_fast = fast_ma.iloc[-1]
                last_slow = slow_ma.iloc[-1]
                if pd.isna(last_fast) or pd.isna(last_slow):
                    return ExitCheck()
                if last_fast < last_slow:
                    return ExitCheck(should_close=True, reason="Death Cross")
                spread_pct = (last_fast - last_slow) / last_slow
                if spread_pct < self.dc_warning_spread and close_up_to.iloc[-1] < last_fast:
                    return ExitCheck(should_close=True, reason="Death Cross Warning")
                return ExitCheck()

            # Fallback: load from DB (per-day mode, no precompute cache).
            from app.utils.security import get_safe_table_name
            safe = get_safe_table_name(ticker)
            with engine.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Close" FROM "{safe}" '
                    f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC '
                    f'LIMIT {WARMUP_LIVE_BARS}',
                    conn,
                )
            if df.empty or len(df) < WARMUP_BARS_REQUIRED:
                return ExitCheck()
            df = df.sort_values("Date").reset_index(drop=True)
            fast_ma = self._fast_line(df["Close"])
            slow_ma = self._slow_line(df["Close"])
            last_fast = fast_ma.iloc[-1]
            last_slow = slow_ma.iloc[-1]
            if pd.isna(last_fast) or pd.isna(last_slow):
                return ExitCheck()
            if last_fast < last_slow:
                return ExitCheck(should_close=True, reason="Death Cross")
            spread_pct = (last_fast - last_slow) / last_slow
            if spread_pct < self.dc_warning_spread and df["Close"].iloc[-1] < last_fast:
                return ExitCheck(should_close=True, reason="Death Cross Warning")

        except Exception:
            pass

        return ExitCheck()

    # ── Holding Re-scoring (for rotation) ─────────────────────────────

    def score_holding(self, ticker: str, as_of_date: str, engine: Engine,
                      entry_price: float, market_cap: float, sector: str,
                      side: str = "long") -> float:
        """Re-score an existing holding using the current fast/slow spread + market cap.

        Prefers the precomputed Close cache (same series should_exit uses) so a
        re-score does not cost a DB round trip per holding per day.
        """
        from app.utils.security import get_safe_table_name
        try:
            cached = self._close_cache.get(ticker.lower())
            if cached is not None:
                close = cached[cached.index <= as_of_date].astype(float)
                if len(close) < WARMUP_BARS_REQUIRED:
                    return 0.0
            else:
                safe = get_safe_table_name(ticker)
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Close" FROM "{safe}" '
                        f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC '
                        f'LIMIT {WARMUP_LIVE_BARS}',
                        conn,
                    )
                if df.empty or len(df) < WARMUP_BARS_REQUIRED:
                    return 0.0
                df = df.sort_values("Date").reset_index(drop=True)
                close = df["Close"].astype(float)

            fast_ma = self._fast_line(close)
            slow_ma = self._slow_line(close)
            last_fast = float(fast_ma.iloc[-1])
            last_slow = float(slow_ma.iloc[-1])
            if pd.isna(last_fast) or pd.isna(last_slow) or last_slow <= 0:
                return 0.0
            spread_pct = (last_fast - last_slow) / last_slow
            angle_norm = 1 / (1 + np.exp(-spread_pct * 100))
            # Normalize market cap using same constants as precompute_signals
            cap_norm = (market_cap - self._cap_min) / self._cap_range if self._cap_range > 0 else 0.5
            return self.angle_weight * angle_norm + self.cap_weight * cap_norm
        except Exception:
            return 0.0

    # ── Precomputed Signals (efficient backtesting) ─────────────────────

    def precompute_signals(self, all_dates: List[str], engine: Engine) -> Optional[Dict[str, List[Signal]]]:
        """Precompute golden cross signals for all dates at once.

        Loads each ticker's data once, computes indicators once, then
        scans every date for golden crosses. ~100x faster than per-day calls.
        """
        from app.utils.security import get_safe_table_name

        tickers = get_all_tickers(engine)
        logger.info("Precomputing signals for %d tickers across %d dates...", len(tickers), len(all_dates))

        first_date = all_dates[0]
        last_date = all_dates[-1]

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
        # Warmup accounting — how many tickers have enough history to trust EMA200.
        warm_ok = 0
        warm_short = 0
        warm_min: Optional[int] = None

        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue

            # Always load from an early fixed date so EMA200 is converged before
            # the first simulated day. This deliberately does NOT start at the
            # simulation start — that leaves early dates with an unconverged
            # EMA200, which changes signals silently.
            load_start = required_load_start(first_date)
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

            if df.empty or len(df) < self.slow_span + 2:
                continue

            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            fast_ma = self._fast_line(close)
            slow_ma = self._slow_line(close)
            vol_ma50 = volume.rolling(self.volume_ma_span).mean()
            returns = close.pct_change()  # Must match standalone (default fill_method='pad')
            vol_14 = returns.rolling(14).std()

            dates = df["Date"].astype(str).str[:10].to_numpy()

            # Bars strictly before the first simulated day are what make EMA200
            # trustworthy at the start of the run.
            n_before_first = int((dates < first_date).sum())
            if n_before_first >= WARMUP_BARS_REQUIRED:
                warm_ok += 1
            else:
                warm_short += 1
                warm_min = (
                    n_before_first if warm_min is None
                    else min(warm_min, n_before_first)
                )

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

            # Vectorized golden-cross scan (numpy masks instead of a per-row loop)
            fast_mav = fast_ma.to_numpy()
            slow_mav = slow_ma.to_numpy()
            vol14v = vol_14.to_numpy()
            vol50v = vol_ma50.to_numpy()
            volumev = volume.to_numpy()
            closev = close.to_numpy()
            prev_ok = ~np.isnan(fast_mav[:-1]) & ~np.isnan(slow_mav[:-1])
            cur_ok = ~np.isnan(fast_mav[1:]) & ~np.isnan(slow_mav[1:])
            cross = prev_ok & cur_ok & (fast_mav[:-1] <= slow_mav[:-1]) & (fast_mav[1:] > slow_mav[1:])
            # np.isin is vectorized; the old per-element `d in date_set` loop
            # cost one Python-level membership test per bar per ticker.
            in_dates = np.isin(dates[1:], all_dates)
            vol_ok = np.isnan(vol14v[1:]) | (vol14v[1:] <= self.max_volatility)
            # Volume confirmation: cross-day volume above its 50-day average.
            if self.use_volume_filter:
                vol_confirm = ~np.isnan(vol50v[1:]) & (volumev[1:] > vol50v[1:])
            else:
                vol_confirm = np.ones(len(cross), dtype=bool)
            # Warmup gate: the cross date must have enough bars behind it for a
            # converged EMA200, or the cross itself is an artifact.
            idx_cur = np.arange(1, len(dates))
            warm_ok_mask = (idx_cur + 1) >= WARMUP_BARS_REQUIRED
            mask = cross & in_dates & vol_ok & vol_confirm & warm_ok_mask
            hit_idx = np.where(mask)[0] + 1

            for i in hit_idx:
                ds = dates[i]
                angle = self._compute_crossover_angle(close, fast_ma, slow_ma, int(i))
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

        # Surface a warmup shortfall even when no crosses were found, so an
        # empty run is not mistaken for a quiet market.
        self._warn_on_warmup(warm_ok, warm_short, warm_min, first_date)

        if not all_candidates:
            logger.info("No golden crosses found in date range")
            return {d: [] for d in all_dates}

        # Normalize market caps across ALL stocks in the universe
        # (not just those with crossovers) to match standalone behavior
        all_caps = [mc for mc, _ in meta_cache.values() if mc > 0]
        cap_max = max(all_caps) if all_caps else 1
        cap_min = min(all_caps) if all_caps else 0
        cap_range = cap_max - cap_min if cap_max > cap_min else 1
        # Store for score_holding() to use
        self._cap_min = cap_min
        self._cap_range = cap_range

        # Build result: return ALL candidates (no sector cap or max holdings filter here)
        # The daily loop handles scoring, ranking, and sector diversification.
        # precompute_signals only detects crossovers and computes scores.
        result: Dict[str, List[Signal]] = {}
        for date_str in all_dates:
            candidates = all_candidates.get(date_str, [])
            if not candidates:
                result[date_str] = []
                continue

            # Score each candidate
            for c in candidates:
                angle_norm = 1 / (1 + np.exp(-c["angle"] * 100))
                cap_norm = (c["market_cap"] - cap_min) / cap_range if cap_range > 0 else 0.5
                c["score"] = self.angle_weight * angle_norm + self.cap_weight * cap_norm

            # Sort by score descending (so the daily loop picks the best first)
            candidates.sort(key=lambda x: x["score"], reverse=True)

            result[date_str] = [
                Signal(
                    ticker=c["ticker"],
                    side="long",
                    score=round(c["score"], 4),
                    angle=round(c["angle"], 4),
                    price=c["price"],
                    entry_date=c["date"],
                    entry_type="golden_cross",
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
    def _compute_crossover_angle(close, fast_ma, slow_ma, cross_idx):
        """Compute the angle between EMA20 and EMA200 at crossover."""
        lookback = 3
        if cross_idx < lookback:
            return 0.0

        end = min(cross_idx + lookback, len(close) - 1)
        start = max(0, cross_idx - lookback)

        if end == start:
            return 0.0

        spread_before = (fast_ma.iloc[start] - slow_ma.iloc[start])
        spread_after = (fast_ma.iloc[end] - slow_ma.iloc[end])
        angle = (spread_after - spread_before) / (end - start)
        return float(angle) if pd.notna(angle) else 0.0
