"""Golden Cross Rotation v2 — Strategy ABC subclass for in-app use.

Scans stocks daily for EMA20/200 golden cross.
Ranks by: 60% crossover angle + 40% market cap.
Holds top 5, rotates when better candidates appear.
Exits: hard stop loss (10%), trailing stop (20%), take profit (30%),
       death cross, death cross warning, time stop (60d).
Minimum hold days: 14 before rotation close.
Volatility filter — skips stocks with 14d daily return std > 5%.
Volume confirmation — requires >1.2x 50-day avg volume.
Market cap floor — $10B minimum.
Sector diversification — max 3 per sector.
Score-squared position sizing for aggressive top-pick weighting.
Regime filter — only take signals when SPY > SMA(50).
Bear market mode — SPY < SMA(200) → go to cash.
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
MIN_HOLD_DAYS = 14
HARD_STOP_LOSS = 0.10
TRAILING_STOP = 0.20
TAKE_PROFIT = 0.30
TIME_STOP_DAYS = 60
MAX_VOLATILITY = 0.05
MIN_VOLUME_RATIO = 1.2
MIN_MARKET_CAP = 10_000_000_000  # $10B
MAX_SECTOR_COUNT = 3


class GoldenCrossRotationV2(Strategy):
    """Golden cross rotation with volatility filter, volume confirmation,
    market cap floor, sector diversification, regime filter, and bear market cash mode."""

    def __init__(self):
        super().__init__()
        self._price_cache: Optional[Dict[str, Dict[str, float]]] = None

    def get_name(self) -> str:
        return "Golden Cross Rotation v2"

    @property
    def max_holdings(self) -> int:
        return MAX_HOLDINGS

    @property
    def sizing_pcts(self) -> List[float]:
        return [0.30, 0.25, 0.20, 0.15, 0.10]

    def get_precomputed_price_cache(self) -> Optional[Dict[str, Dict[str, float]]]:
        return self._price_cache

    def get_rotation_config(self) -> RotationConfig:
        return RotationConfig(
            sizing_method="score_squared",
            hard_stop_loss=0.10,
            trailing_stop=0.20,
            take_profit=0.30,
            time_stop_days=TIME_STOP_DAYS,
            min_hold_days=MIN_HOLD_DAYS,
            max_sector_count=MAX_SECTOR_COUNT,
            re_score_holdings=True,
            bear_exposure=0.0,  # Go to cash in bear market
            exit_priority=[
                "strategy_exit",     # Death cross first
                "hard_stop_loss",    # Then hard stop
                "take_profit",       # Then take profit
                "trailing_stop",     # Then trailing stop
                "time_stop",         # Then time stop
            ],
        )

    def score_holding(self, ticker: str, as_of_date: str, engine: Engine,
                      entry_price: float, market_cap: float, sector: str,
                      side: str = "long") -> float:
        """Re-score using current EMA20/EMA200 spread."""
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
            e20 = float(ema20.iloc[-1])
            e200 = float(ema200.iloc[-1])
            if pd.isna(e20) or pd.isna(e200) or e200 <= 0:
                return 0.0
            spread = (e20 - e200) / e200
            angle_norm = 1 / (1 + np.exp(-spread * 100))
            cap_norm = min(market_cap / 500_000_000_000, 1.0) if market_cap > 0 else 0.5
            return ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm
        except Exception:
            return 0.0

    # ── SPY Regime Checks ────────────────────────────────────────────

    def _spy_above_sma50(self, engine: Engine) -> bool:
        """Check if SPY is above its 50-day SMA."""
        try:
            with engine.connect() as conn:
                spy = pd.read_sql(
                    'SELECT "Date", "Close" FROM spy ORDER BY "Date" DESC LIMIT 60', conn
                )
            if spy.empty or len(spy) < 50:
                return True  # Default to allowing entries if not enough data
            spy = spy.sort_values("Date").reset_index(drop=True)
            close = spy["Close"].astype(float)
            sma50 = close.rolling(50).mean()
            return float(close.iloc[-1]) > float(sma50.iloc[-1])
        except Exception:
            return True

    def _spy_above_sma200(self, engine: Engine) -> bool:
        """Check if SPY is above its 200-day SMA (bear market check)."""
        try:
            with engine.connect() as conn:
                spy = pd.read_sql(
                    'SELECT "Date", "Close" FROM spy ORDER BY "Date" DESC LIMIT 250', conn
                )
            if spy.empty or len(spy) < 200:
                return True
            spy = spy.sort_values("Date").reset_index(drop=True)
            close = spy["Close"].astype(float)
            sma200 = close.rolling(200).mean()
            return float(close.iloc[-1]) > float(sma200.iloc[-1])
        except Exception:
            return True

    # ── Signal Generation ──────────────────────────────────────────────

    def get_signals(self, as_of_date: str, engine: Engine) -> List[Signal]:
        """Scan all stocks for golden cross signals, rank by score with filters."""

        # Regime filter: SPY must be above SMA(50) to take signals
        if not self._spy_above_sma50(engine):
            logger.info("SPY below SMA(50) — no entries")
            return []

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
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema200 = close.rolling(window=200).mean()
            vol_ma50 = volume.rolling(50).mean()

            # 14-day rolling volatility
            returns = close.pct_change(fill_method=None)
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

            # Volume confirmation
            current_vol_ratio = float(volume.iloc[i] / vol_ma50.iloc[i]) if pd.notna(vol_ma50.iloc[i]) and vol_ma50.iloc[i] > 0 else 0.0
            if current_vol_ratio < MIN_VOLUME_RATIO:
                continue

            angle = self._compute_crossover_angle(close, ema20, ema200, i)

            # Market cap for scoring and filtering
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

            # Market cap floor
            if mc < MIN_MARKET_CAP:
                continue

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

        # Apply sector diversification
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
                market_cap=c.get("market_cap", 0),
                sector=c.get("sector", "Unknown"),
            )
            for c in selected
        ]

    # ── Exit Logic ────────────────────────────────────────────────────

    def should_exit(self, ticker: str, as_of_date: str,
                    engine: Engine, side: str = "long") -> ExitCheck:
        """Check for death cross or death cross warning."""
        if side != "long":
            return ExitCheck()

        try:
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
            ema20 = df["Close"].astype(float).ewm(span=20, adjust=False).mean()
            ema200 = df["Close"].astype(float).rolling(window=200).mean()

            last_ema20 = float(ema20.iloc[-1])
            last_ema200 = float(ema200.iloc[-1])

            if pd.isna(last_ema20) or pd.isna(last_ema200):
                return ExitCheck()

            # Death cross
            if last_ema20 < last_ema200:
                return ExitCheck(should_close=True, reason="Death Cross")

            # Death cross warning
            spread_pct = (last_ema20 - last_ema200) / last_ema200
            if spread_pct < 0.001 and float(df["Close"].iloc[-1]) < last_ema20:
                return ExitCheck(should_close=True, reason="Death Cross Warning")

        except Exception:
            pass

        return ExitCheck()

    # ── Precomputed Signals (efficient backtesting) ─────────────────────

    def precompute_signals(self, all_dates: List[str], engine: Engine) -> Optional[Dict[str, List[Signal]]]:
        """Precompute golden cross signals for all dates at once.

        Loads each ticker's data once, computes indicators once, then
        scans every date for golden crosses. This is ~100x faster than
        calling get_signals() on each trading day.
        """
        from app.utils.security import get_safe_table_name

        # Compute SPY regime for every date upfront
        spy_regime = self._precompute_spy_regime(all_dates, engine)
        if spy_regime is None:
            return None  # Fall back to per-day

        tickers = get_all_tickers(engine)
        logger.info("Precomputing signals for %d tickers across %d dates...", len(tickers), len(all_dates))

        # Load data window: need 250 days before first date for EMA200, plus all dates
        first_date = all_dates[0]
        last_date = all_dates[-1]

        # Pre-fetch market cap and sector for all tickers
        meta_cache: Dict[str, tuple] = {}  # ticker -> (market_cap, sector)
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

        # Build a date-to-index lookup for all_dates
        date_set = set(all_dates)

        # For each ticker, load data once and scan all dates
        all_candidates: Dict[str, List[Dict[str, Any]]] = {}  # date_str -> list of candidate dicts

        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue

            # Load enough data: need 250 days before first_date for EMA200
            load_start = (
                pd.Timestamp(first_date) - pd.Timedelta(days=300)
            ).strftime("%Y-%m-%d")

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
            returns = close.pct_change(fill_method=None)
            vol_14 = returns.rolling(14).std()

            # Build price cache entry for this ticker (used by adapter for daily loop)
            ticker_lower = ticker.lower()
            if self._price_cache is None:
                self._price_cache = {}
            if ticker_lower not in self._price_cache:
                pc: Dict[str, float] = {}
                for _, row in df.iterrows():
                    pc[str(pd.Timestamp(row["Date"]))[:10]] = float(row["Close"])
                self._price_cache[ticker_lower] = pc

            # Market cap & sector
            mc, sector = meta_cache.get(ticker.lower(), (0.0, "Unknown"))
            if mc < MIN_MARKET_CAP:
                continue

            # Scan each row for golden crosses that fall on an all_dates date
            for i in range(1, len(df)):
                ds = str(pd.Timestamp(df["Date"].iloc[i]))[:10]
                if ds not in date_set:
                    continue

                if not (pd.notna(ema20.iloc[i]) and pd.notna(ema200.iloc[i]) and
                        pd.notna(ema20.iloc[i - 1]) and pd.notna(ema200.iloc[i - 1])):
                    continue

                if not (ema20.iloc[i - 1] <= ema200.iloc[i - 1] and ema20.iloc[i] > ema200.iloc[i]):
                    continue

                # Volatility filter
                current_vol = float(vol_14.iloc[i]) if pd.notna(vol_14.iloc[i]) else 0.0
                if current_vol > MAX_VOLATILITY:
                    continue

                # Volume confirmation
                current_vol_ratio = float(volume.iloc[i] / vol_ma50.iloc[i]) if pd.notna(vol_ma50.iloc[i]) and vol_ma50.iloc[i] > 0 else 0.0
                if current_vol_ratio < MIN_VOLUME_RATIO:
                    continue

                angle = self._compute_crossover_angle(close, ema20, ema200, i)

                if ds not in all_candidates:
                    all_candidates[ds] = []
                all_candidates[ds].append({
                    "ticker": ticker.upper(),
                    "angle": angle,
                    "market_cap": mc,
                    "sector": sector,
                    "price": float(close.iloc[i]),
                    "date": ds,
                })

        if not all_candidates:
            logger.info("No golden crosses found in date range")
            return {d: [] for d in all_dates}

        # Normalize market caps across all candidates
        all_caps = [c["market_cap"] for candidates in all_candidates.values() for c in candidates if c["market_cap"] > 0]
        cap_max = max(all_caps) if all_caps else 1
        cap_min = min(all_caps) if all_caps else 0
        cap_range = cap_max - cap_min if cap_max > cap_min else 1

        # Build result: for each date, score, rank, apply sector diversification
        result: Dict[str, List[Signal]] = {}
        for date_str in all_dates:
            candidates = all_candidates.get(date_str, [])
            if not candidates:
                result[date_str] = []
                continue

            # Regime filter: SPY must be above SMA(50)
            if not spy_regime.get(date_str, True):
                result[date_str] = []
                continue

            # Score and rank
            for c in candidates:
                angle_norm = 1 / (1 + np.exp(-c["angle"] * 100))
                cap_norm = (c["market_cap"] - cap_min) / cap_range if cap_range > 0 else 0.5
                c["score"] = ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm

            candidates.sort(key=lambda x: x["score"], reverse=True)

            # Apply sector diversification
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
                for c in selected
            ]

        logger.info(
            "Precomputed signals: %d dates with signals out of %d total dates",
            sum(1 for v in result.values() if v), len(all_dates),
        )
        return result

    def _precompute_spy_regime(self, all_dates: List[str], engine: Engine) -> Optional[Dict[str, bool]]:
        """Precompute SPY > SMA(50) for every date in the range."""
        try:
            first_date = all_dates[0]
            last_date = all_dates[-1]
            load_start = (
                pd.Timestamp(first_date) - pd.Timedelta(days=100)
            ).strftime("%Y-%m-%d")
            with engine.connect() as conn:
                spy = pd.read_sql(
                    f'SELECT "Date", "Close" FROM spy '
                    f'WHERE "Date" >= \'{load_start}\' AND "Date" <= \'{last_date}\' '
                    f'ORDER BY "Date"',
                    conn,
                )
            if spy.empty or len(spy) < 50:
                return None
            spy_close = spy["Close"].astype(float)
            spy_sma50 = spy_close.rolling(50).mean()
            spy_dates = [str(d)[:10] for d in spy["Date"]]
            regime: Dict[str, bool] = {}
            for i, ds in enumerate(spy_dates):
                if ds in all_dates and pd.notna(spy_sma50.iloc[i]):
                    regime[ds] = float(spy_close.iloc[i]) > float(spy_sma50.iloc[i])
            return regime
        except Exception as e:
            logger.warning("Failed to precompute SPY regime: %s", e)
            return None

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
