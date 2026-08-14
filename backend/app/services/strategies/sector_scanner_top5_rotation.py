"""Sector Scanner Top-5 Rotation Strategy — pluggable Strategy implementation.

Replicates the Sector Rotation Scanner's stock-leader filter and holds the
top 5 stocks by 3-month momentum.

Universe filter (a stock qualifies only if it passes ALL of these):
  - Scanner sector filter: the stock's 3-month perf (perf_3m) beats its own
    sector ETF's momentum. min_perf = 0 if sector_3m > 0.20, else sector_3m * 0.5.
  - Market cap >= $5B.
  - 14-day daily-return std <= 5%.

Ranking: all qualifying stocks ranked by perf_3m (descending), sector-capped
at 2 per sector, top 5 selected.

Sizing: momentum-proportional ("linear" on sigmoid-normalized perf_3m) —
higher momentum names get larger positions.

Exits: hard stop loss (20%, overrides min hold) + rotation (sold when a
holding leaves the top 5, only after a 14-day minimum hold).
"""

import logging
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np
from sqlalchemy import Engine, text

from app.services.strategy_base import Strategy, Signal, ExitCheck, RotationConfig
from app.db.database import SECTOR_NAME_MAP

logger = logging.getLogger(__name__)

# ── Strategy Parameters ───────────────────────────────────────────────
MAX_HOLDINGS = 5
MIN_HOLD_DAYS = 14
HARD_STOP = 0.20
TAKE_PROFIT = 0.50      # +50% take profit
TRAILING_STOP = 0.10    # 10% trailing stop (from peak)
MAX_SECTOR_COUNT = 2
MAX_VOLATILITY = 0.05
MIN_MARKET_CAP = 5e9
SIZING_PCTS = [0.30, 0.25, 0.20, 0.15, 0.10]  # momentum-weighted intent; adapter uses score-proportional
MOMENTUM_K = 10.0  # sigmoid steepness for score/sizing


class SectorScannerTop5Rotation(Strategy):
    """Hold the top 5 stocks (by 3-month momentum) from the scanner-filtered universe."""

    def __init__(self):
        super().__init__()
        self._price_cache: Optional[Dict[str, Dict[str, float]]] = None

    def get_name(self) -> str:
        return "Sector Scanner Top-5 Rotation"

    @property
    def max_holdings(self) -> int:
        return MAX_HOLDINGS

    @property
    def sizing_pcts(self) -> List[float]:
        return SIZING_PCTS

    def get_rotation_config(self) -> RotationConfig:
        return RotationConfig(
            sizing_method="linear",        # momentum-proportional (score = sigmoid(perf_3m))
            hard_stop_loss=HARD_STOP,      # 20% hard stop, overrides min hold
            trailing_stop=TRAILING_STOP,   # 10% trailing stop from peak
            take_profit=TAKE_PROFIT,       # +50% take profit
            time_stop_days=0,              # never (rotation is the primary exit)
            min_hold_days=MIN_HOLD_DAYS,   # 14 days before rotation can sell
            max_sector_count=MAX_SECTOR_COUNT,
            re_score_holdings=True,        # re-score holdings on current momentum daily
            bear_exposure=1.0,
            exit_priority=["hard_stop_loss", "trailing_stop", "take_profit"],
        )

    def get_precomputed_price_cache(self) -> Optional[Dict[str, Dict[str, float]]]:
        return self._price_cache

    # ── Scoring / filtering helpers ──────────────────────────────────

    @staticmethod
    def _sigmoid_score(perf_3m: float) -> float:
        """Sigmoid-normalized 3-month momentum; monotonic + bounded; used for rank & sizing."""
        return 1.0 / (1.0 + np.exp(-perf_3m * MOMENTUM_K))

    @staticmethod
    def _perf3m_and_vol(dates: np.ndarray, close: np.ndarray):
        """Compute perf_3m (90-calendar-day lookback) and 14-day vol arrays.

        perf_3m[i] = close[i]/close[last trading day <= dates[i]-90d] - 1 (matches scanner).
        vol_14[i]  = std of trailing 14 daily returns (pct_change, default fill_method).
        Returns (perf3m, vol14) aligned to input arrays.
        """
        perf3m = np.full(len(close), np.nan)
        idx = np.searchsorted(dates, dates - np.timedelta64(90, "D"), side="right") - 1
        valid = idx >= 0
        j = np.clip(idx[valid], 0, len(close) - 1)
        perf3m[valid] = close[valid] / close[j] - 1.0
        returns = pd.Series(close).pct_change()
        vol14 = returns.rolling(14).std().to_numpy()
        return perf3m, vol14

    def _load_sector_etf_data(self, engine, load_start, load_end):
        """Load ETF close data. Returns {etf_table_lower: (dates, close, perf3m)}."""
        from app.utils.security import get_safe_table_name

        etf_data: Dict[str, Any] = {}
        for etf_lower in SECTOR_NAME_MAP:  # keys are lowercase (e.g. 'xlk')
            try:
                safe = get_safe_table_name(etf_lower)
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Close" FROM "{safe}" '
                        f'WHERE "Date" >= \'{load_start}\' AND "Date" <= \'{load_end}\' '
                        f'ORDER BY "Date" ASC',
                        conn,
                    )
            except Exception:
                continue
            if df.empty:
                continue
            dates = df["Date"].to_numpy()
            close = df["Close"].astype(float).to_numpy()
            perf3m, _ = self._perf3m_and_vol(dates, close)
            etf_data[etf_lower] = (dates, close, perf3m)
        return etf_data

    # ── Signal generation (live / per-day path) ───────────────────────

    def get_signals(self, as_of_date: str, engine: Engine) -> List[Signal]:
        """Scan all stocks for the given date, apply scanner + risk filters, return ranked signals."""
        from app.utils.security import get_safe_table_name

        sector_name_to_etf = {name: ticker for ticker, name in SECTOR_NAME_MAP.items()}

        # Load metadata once
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT ticker, market_cap, sector FROM stock_metadata")
                ).fetchall()
        except Exception:
            return []
        meta = {}
        for row in rows:
            mc = row[1]
            sec = row[2]
            if mc is None or sec is None:
                continue
            try:
                mc = float(mc)
            except Exception:
                continue
            if mc < MIN_MARKET_CAP:
                continue
            if sec not in sector_name_to_etf:
                continue
            meta[str(row[0]).lower()] = (mc, sec)

        # Load ETF closes for sector perf (as-of date)
        # Load ~300 days of history before the as-of date (90d perf + 200d MA
        # buffer) so the strategy generates signals from the actual start date
        # instead of a hardcoded 2009-01-01 (which made pre-2009 runs idle).
        load_start = (pd.Timestamp(as_of_date) - pd.Timedelta(days=300)).strftime("%Y-%m-%d")
        etf_data = self._load_sector_etf_data(engine, load_start, as_of_date)
        target_ts = np.datetime64(as_of_date)

        candidates: List[Dict[str, Any]] = []
        for ticker_lower, (mc, sec) in meta.items():
            try:
                safe = get_safe_table_name(ticker_lower)
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Close" FROM "{safe}" '
                        f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 250',
                        conn,
                    )
            except Exception:
                continue
            if df.empty or len(df) < 30:
                continue
            df = df.sort_values("Date").reset_index(drop=True)
            dates = df["Date"].to_numpy()
            close = df["Close"].astype(float).to_numpy()
            i = len(dates) - 1
            # ref date = the stock's latest trading day <= as_of_date
            ref_date = dates[i]
            # ETF sector perf as of the stock's ref date (use latest available)
            etf_key = sector_name_to_etf[sec]
            etf_dates, _, etf_perf3m = etf_data.get(etf_key, (None, None, None))
            if etf_perf3m is None:
                continue
            ei = np.searchsorted(etf_dates, ref_date, side="right") - 1
            if ei < 0:
                continue
            sector_3m = float(etf_perf3m[ei]) if np.isfinite(etf_perf3m[ei]) else 0.0

            # 90-day perf and volatility for the stock (aligned arrays)
            perf3m_arr, vol14_arr = self._perf3m_and_vol(dates, close)
            perf_3m = float(perf3m_arr[i]) if np.isfinite(perf3m_arr[i]) else np.nan
            vol_14 = float(vol14_arr[i]) if np.isfinite(vol14_arr[i]) else np.nan

            if not np.isfinite(perf_3m) or not np.isfinite(vol_14):
                continue
            if vol_14 > MAX_VOLATILITY:
                continue

            # Scanner sector filter
            min_perf = 0.0 if sector_3m > 0.20 else sector_3m * 0.5
            if perf_3m <= min_perf:
                continue

            candidates.append({
                "ticker": ticker_lower.upper(),
                "score": round(self._sigmoid_score(perf_3m), 6),
                "market_cap": mc,
                "sector": sec,
                "price": float(close[i]),
                "date": str(pd.Timestamp(ref_date))[:10],
            })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return [
            Signal(
                ticker=c["ticker"],
                side="long",
                score=c["score"],
                angle=0.0,
                price=c["price"],
                entry_date=c["date"],
                entry_type="sector_top5",
                market_cap=c["market_cap"],
                sector=c["sector"],
            )
            for c in candidates
        ]

    # ── Exit logic (rotation + hard stop handled by adapter) ──────────

    def should_exit(self, ticker: str, as_of_date: str,
                    engine: Engine, side: str = "long") -> ExitCheck:
        """No strategy-specific exit — rotation and the hard stop are handled by the adapter."""
        return ExitCheck()

    # ── Holding re-scoring (for rotation) ─────────────────────────────

    def score_holding(self, ticker: str, as_of_date: str, engine: Engine,
                      entry_price: float, market_cap: float, sector: str,
                      side: str = "long") -> float:
        """Re-score a holding using its CURRENT 3-month momentum so it competes fairly."""
        from app.utils.security import get_safe_table_name
        try:
            safe = get_safe_table_name(ticker)
            with engine.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Close" FROM "{safe}" '
                    f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 200',
                    conn,
                )
            if df.empty or len(df) < 30:
                return 0.0
            df = df.sort_values("Date").reset_index(drop=True)
            dates = df["Date"].to_numpy()
            close = df["Close"].astype(float).to_numpy()
            perf3m_arr, _ = self._perf3m_and_vol(dates, close)
            perf_3m = float(perf3m_arr[-1])
            if not np.isfinite(perf_3m):
                return 0.0
            return round(self._sigmoid_score(perf_3m), 6)
        except Exception:
            return 0.0

    # ── Precomputed signals (efficient backtesting) ───────────────────

    def precompute_signals(self, all_dates: List[str], engine: Engine) -> Optional[Dict[str, List[Signal]]]:
        """Precompute candidates for all dates at once (~100x faster than per-day calls).

        Loads each ticker's data once, computes indicators once, then scans every
        simulation date. Produces the exact same candidates as get_signals().
        """
        from app.utils.security import get_safe_table_name

        first_date = all_dates[0]
        last_date = all_dates[-1]
        # Load ~300 days of history before the first date (90d perf + 200d MA
        # buffer) so signals are generated from the actual start date.
        load_start = (pd.Timestamp(first_date) - pd.Timedelta(days=300)).strftime("%Y-%m-%d")
        date_set = set(all_dates)
        sector_name_to_etf = {name: ticker for ticker, name in SECTOR_NAME_MAP.items()}

        # Metadata
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT ticker, market_cap, sector FROM stock_metadata")
                ).fetchall()
        except Exception:
            return {d: [] for d in all_dates}
        meta: Dict[str, Any] = {}
        for row in rows:
            mc, sec = row[1], row[2]
            if mc is None or sec is None:
                continue
            try:
                mc = float(mc)
            except Exception:
                continue
            if mc < MIN_MARKET_CAP:
                continue
            if sec not in sector_name_to_etf:
                continue
            meta[str(row[0]).lower()] = (mc, sec)

        # ETF closes
        etf_data = self._load_sector_etf_data(engine, load_start, last_date)
        if not etf_data:
            logger.warning("No ETF data loaded; cannot apply scanner filter")
            return {d: [] for d in all_dates}

        all_candidates: Dict[str, List[Dict[str, Any]]] = {}

        for ticker_lower, (mc, sec) in meta.items():
            try:
                safe = get_safe_table_name(ticker_lower)
                with engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Close" FROM "{safe}" '
                        f'WHERE "Date" >= \'{load_start}\' AND "Date" <= \'{last_date}\' '
                        f'ORDER BY "Date" ASC',
                        conn,
                    )
            except Exception:
                continue
            if df.empty or len(df) < 30:
                continue
            dates = df["Date"].to_numpy()
            close = df["Close"].astype(float).to_numpy()
            perf3m_arr, vol14_arr = self._perf3m_and_vol(dates, close)

            # Price cache
            if self._price_cache is None:
                self._price_cache = {}
            if ticker_lower not in self._price_cache:
                pc = {str(pd.Timestamp(d))[:10]: float(c) for d, c in zip(dates, close)}
                self._price_cache[ticker_lower] = pc

            etf_key = sector_name_to_etf[sec]
            etf_dates, _, etf_perf3m = etf_data[etf_key]

            for i in range(len(dates)):
                ds = str(pd.Timestamp(dates[i]))[:10]
                if ds not in date_set:
                    continue
                perf_3m = float(perf3m_arr[i])
                vol_14 = float(vol14_arr[i])
                if not (np.isfinite(perf_3m) and np.isfinite(vol_14)):
                    continue
                if vol_14 > MAX_VOLATILITY:
                    continue
                ei = np.searchsorted(etf_dates, dates[i], side="right") - 1
                if ei < 0:
                    continue
                sector_3m = float(etf_perf3m[ei]) if np.isfinite(etf_perf3m[ei]) else 0.0
                min_perf = 0.0 if sector_3m > 0.20 else sector_3m * 0.5
                if perf_3m <= min_perf:
                    continue

                if ds not in all_candidates:
                    all_candidates[ds] = []
                all_candidates[ds].append({
                    "ticker": ticker_lower.upper(),
                    "score": round(self._sigmoid_score(perf_3m), 6),
                    "market_cap": mc,
                    "sector": sec,
                    "price": float(close[i]),
                    "date": ds,
                })

        result: Dict[str, List[Signal]] = {}
        for date_str in all_dates:
            cands = all_candidates.get(date_str, [])
            cands.sort(key=lambda x: x["score"], reverse=True)
            result[date_str] = [
                Signal(
                    ticker=c["ticker"],
                    side="long",
                    score=c["score"],
                    angle=0.0,
                    price=c["price"],
                    entry_date=c["date"],
                    entry_type="sector_top5",
                    market_cap=c["market_cap"],
                    sector=c["sector"],
                )
                for c in cands
            ]

        logger.info(
            "Precomputed: %d dates with candidates out of %d dates (universe=%d)",
            sum(1 for v in result.values() if v), len(all_dates), len(meta),
        )
        return result
