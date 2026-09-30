"""Daily Golden Cross Rotation Strategy — pluggable Strategy implementation.

Scans 1500 stocks daily for EMA20/200 golden cross.
Ranks by: 60% crossover angle + 40% market cap.
Holds top 5, rotates when better candidates appear.
Exits: death cross, death cross warning, time stop (60d), or rotated out.
Minimum hold days: 7 before rotation close.
Volatility filter — skips stocks with 14d daily return std > 5%.
Sector diversification (max 2 per sector).
Score-squared position sizing for aggressive top-pick weighting.
"""

import logging
from typing import List, Dict, Any

import pandas as pd
import numpy as np
from sqlalchemy import Engine, text

from app.services.strategy_base import Strategy, Signal, ExitCheck, RotationConfig, get_all_tickers

logger = logging.getLogger(__name__)

# ── Strategy Parameters ───────────────────────────────────────────────
ANGLE_WEIGHT = 0.60
CAP_WEIGHT = 0.40
MAX_HOLDINGS = 5
MIN_HOLD_DAYS = 7
TIME_STOP_DAYS = 60
MAX_VOLATILITY = 0.05
MAX_SECTOR_COUNT = 2
SIZING_PCTS = [0.30, 0.25, 0.20, 0.15, 0.10]

# ── Data-driven performance levers ──────────────────────────────────────
# Death Cross Warning trigger spread. Kept at 0.001 (original): testing showed
# raising it (0.01) fired too many premature exits and HURT return/CAGR, so the
# earlier-exit hypothesis was wrong and was reverted.
DC_WARNING_SPREAD = 0.001
# Widened from 0.20 to 0.30. Trailing Stop was the worst per-trade exit
# (-$5,921.04 avg in the aggregate). A wider trail avoids stopping out winners
# early, letting profitable holds extend. (0.30/0.32/0.34 all measured identical
# once protect_winners is on, so 0.30 is the clean choice.)
TRAILING_STOP = 0.30
# Keep a holding that drops out of the top-N if it is still above its entry price.
# This lets high-quality winners run toward 20d+ (63.0% win / +$1,801.79 avg), the
# strongest holding bucket in the aggregate. Measured: return 165.5%->278.7%,
# CAGR 19.64%->26.59%, Sharpe 0.91->1.21, max DD 26.4%->23.2% across 8 fixed starts.
PROTECT_WINNERS = True


class DailyGoldenCrossRotation(Strategy):
    """Daily golden cross rotation with sector diversification and volatility filter."""

    def __init__(self):
        super().__init__()
        self._price_cache: Optional[Dict[str, Dict[str, float]]] = None
        # Date-indexed Close series per ticker, populated by precompute_signals
        # so should_exit() avoids a DB query per holding per day.
        self._close_cache: Dict[str, pd.Series] = {}
        # Market cap normalization constants (set during precompute_signals)
        self._cap_min: float = 0.0
        self._cap_range: float = 1.0

    def get_name(self) -> str:
        return "Daily Golden Cross Rotation"

    @property
    def max_holdings(self) -> int:
        return MAX_HOLDINGS

    @property
    def sizing_pcts(self) -> List[float]:
        return SIZING_PCTS

    def get_rotation_config(self) -> RotationConfig:
        """Match the standalone daily_golden_cross_rotation.py config exactly."""
        return RotationConfig(
            sizing_method="score_squared",
            hard_stop_loss=0.0,       # No hard stop in standalone
            trailing_stop=TRAILING_STOP,
            take_profit=0.30,
            time_stop_days=60,
            min_hold_days=7,
            max_sector_count=MAX_SECTOR_COUNT,
            re_score_holdings=True,    # Re-score holdings using current EMA spread
            protect_winners=PROTECT_WINNERS,
            bear_exposure=0.50,         # 50% exposure in bear market (matches standalone)
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
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema200 = close.rolling(window=200).mean()
            vol_ma50 = volume.rolling(50).mean()

            # 14-day rolling volatility
            returns = close.pct_change()  # Must match standalone (default fill_method='pad')
            vol_14 = returns.rolling(14).std()

            # Check for golden cross on the most recent trading day
            i = len(df) - 1
            if not (pd.notna(ema20.iloc[i]) and pd.notna(ema200.iloc[i]) and
                    pd.notna(ema20.iloc[i - 1]) and pd.notna(ema200.iloc[i - 1])):
                continue

            if not (ema20.iloc[i - 1] <= ema200.iloc[i - 1] and ema20.iloc[i] > ema200.iloc[i]):
                continue

            # Volatility filter
            current_vol = float(vol_14.iloc[i]) if pd.notna(vol_14.iloc[i]) else 0.0
            if current_vol > MAX_VOLATILITY:
                continue

            angle = self._compute_crossover_angle(close, ema20, ema200, i)

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
            c["score"] = ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm

        candidates.sort(key=lambda x: x["score"], reverse=True)

        # Apply sector diversification (max MAX_SECTOR_COUNT per sector)
        selected = []
        sector_counts: Dict[str, int] = {}
        for c in candidates:
            if len(selected) >= MAX_HOLDINGS:
                break
            sec = c.get("sector", "Unknown")
            if sector_counts.get(sec, 0) >= MAX_SECTOR_COUNT:
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
                if len(close_up_to) < 50:
                    return ExitCheck()
                ema20 = close_up_to.ewm(span=20, adjust=False).mean()
                ema200 = close_up_to.rolling(window=200).mean()
                last_ema20 = ema20.iloc[-1]
                last_ema200 = ema200.iloc[-1]
                if pd.isna(last_ema20) or pd.isna(last_ema200):
                    return ExitCheck()
                if last_ema20 < last_ema200:
                    return ExitCheck(should_close=True, reason="Death Cross")
                spread_pct = (last_ema20 - last_ema200) / last_ema200
                if spread_pct < DC_WARNING_SPREAD and close_up_to.iloc[-1] < last_ema20:
                    return ExitCheck(should_close=True, reason="Death Cross Warning")
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
            ema20 = df["Close"].ewm(span=20, adjust=False).mean()
            ema200 = df["Close"].rolling(window=200).mean()
            last_ema20 = ema20.iloc[-1]
            last_ema200 = ema200.iloc[-1]
            if pd.isna(last_ema20) or pd.isna(last_ema200):
                return ExitCheck()
            if last_ema20 < last_ema200:
                return ExitCheck(should_close=True, reason="Death Cross")
            spread_pct = (last_ema20 - last_ema200) / last_ema200
            if spread_pct < DC_WARNING_SPREAD and df["Close"].iloc[-1] < last_ema20:
                return ExitCheck(should_close=True, reason="Death Cross Warning")

        except Exception:
            pass

        return ExitCheck()

    # ── Holding Re-scoring (for rotation) ─────────────────────────────

    def score_holding(self, ticker: str, as_of_date: str, engine: Engine,
                      entry_price: float, market_cap: float, sector: str,
                      side: str = "long") -> float:
        """Re-score an existing holding using current EMA20/EMA200 spread + market cap.

        Matches the standalone's compute_holding_score() logic.
        """
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
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema200 = close.rolling(window=200).mean()
            last_ema20 = float(ema20.iloc[-1])
            last_ema200 = float(ema200.iloc[-1])
            if pd.isna(last_ema20) or pd.isna(last_ema200) or last_ema200 <= 0:
                return 0.0
            spread_pct = (last_ema20 - last_ema200) / last_ema200
            angle_norm = 1 / (1 + np.exp(-spread_pct * 100))
            # Normalize market cap using same constants as precompute_signals
            cap_norm = (market_cap - self._cap_min) / self._cap_range if self._cap_range > 0 else 0.5
            return ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm
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
        date_set = set(all_dates)

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

            load_start = "2018-01-01"  # Match standalone's hardcoded start
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
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema200 = close.rolling(window=200).mean()
            vol_ma50 = volume.rolling(50).mean()
            returns = close.pct_change()  # Must match standalone (default fill_method='pad')
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

            # Vectorized golden-cross scan (numpy masks instead of a per-row loop)
            dates = df["Date"].astype(str).str[:10].to_numpy()
            ema20v = ema20.to_numpy()
            ema200v = ema200.to_numpy()
            vol14v = vol_14.to_numpy()
            closev = close.to_numpy()
            prev_ok = ~np.isnan(ema20v[:-1]) & ~np.isnan(ema200v[:-1])
            cur_ok = ~np.isnan(ema20v[1:]) & ~np.isnan(ema200v[1:])
            cross = prev_ok & cur_ok & (ema20v[:-1] <= ema200v[:-1]) & (ema20v[1:] > ema200v[1:])
            in_dates = np.array([d in date_set for d in dates[1:]])
            vol_ok = np.isnan(vol14v[1:]) | (vol14v[1:] <= MAX_VOLATILITY)
            mask = cross & in_dates & vol_ok
            hit_idx = np.where(mask)[0] + 1

            for i in hit_idx:
                ds = dates[i]
                angle = self._compute_crossover_angle(close, ema20, ema200, int(i))
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
                c["score"] = ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm

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
    def _compute_crossover_angle(close, ema20, ema200, cross_idx):
        """Compute the angle between EMA20 and EMA200 at crossover."""
        lookback = 3
        if cross_idx < lookback:
            return 0.0

        end = min(cross_idx + lookback, len(close) - 1)
        start = max(0, cross_idx - lookback)

        if end == start:
            return 0.0

        spread_before = (ema20.iloc[start] - ema200.iloc[start])
        spread_after = (ema20.iloc[end] - ema200.iloc[end])
        angle = (spread_after - spread_before) / (end - start)
        return float(angle) if pd.notna(angle) else 0.0
