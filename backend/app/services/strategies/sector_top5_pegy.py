"""Sector Top-5 Momentum + PEGY — combined rotation strategy.

Combines the Sector Scanner Top-5 Rotation v3 momentum engine with a PEGY
fundamental screen.

PEGY = P/E / (Earnings Growth % + Dividend Yield %). Lower PEGY is more
attractive. This variant:

  - Keeps the v3 universe filter: market cap >= $5B, 14-day vol <= 5%,
    and the scanner sector filter (stock's 3-mo perf beats its sector ETF).
  - Adds a HARD PEGY filter: a name is buyable only if its as-of PEGY is
    computable AND < 2.0. No valid as-of PEGY -> not buyable.
  - Ranks with an 80/20 blended composite score:
        composite = 0.80*momentum_score + 0.20*pegy_score
        momentum_score = 1/(1+e^(-perf_3m*10))   (sigmoid of 3-mo momentum)
        pegy_score     = 1/(1+PEGY)              (lower PEGY -> higher score)
  - Preserves v3 "ride the winners" exits: hard stop 20%, trailing stop 10%,
    +50% take profit, rotation disabled (min_hold_days effectively infinite).

Look-ahead safety: PEGY is computed as-of — only annual reports with
report_date <= the trade date are used, and the price is that day's close.
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from app.services.strategy_base import Strategy, Signal, RotationConfig
from app.services.strategies.sector_scanner_top5_rotation import (
    SectorScannerTop5Rotation,
    MAX_HOLDINGS, SIZING_PCTS, HARD_STOP, TAKE_PROFIT, MIN_HOLD_DAYS,
    MAX_SECTOR_COUNT, MIN_MARKET_CAP, MAX_VOLATILITY, MOMENTUM_K,
)

logger = logging.getLogger(__name__)

# ── PEGY-specific parameters ─────────────────────────────────────────
PEGY_THRESHOLD = 2.0      # hard value gate: only PEGY < 2.0 is buyable
MOM_W = 0.8               # momentum weight in composite
PEGY_W = 0.2              # PEGY weight in composite

# Huge min-hold disables the rotation exit entirely (hold until stop/TP/trailing).
_NO_ROTATION_HOLD_DAYS = 1_000_000


class SectorTop5MomentumPEGY(SectorScannerTop5Rotation, Strategy):
    """Top-5 momentum names filtered by PEGY < 1.0, ranked by 50/50 blend."""

    def __init__(self):
        super().__init__()

    def get_name(self) -> str:
        return "Sector Top-5 Momentum + PEGY"

    def get_rotation_config(self) -> RotationConfig:
        return RotationConfig(
            sizing_method="linear",        # composite-proportional
            hard_stop_loss=HARD_STOP,      # 20% hard stop
            trailing_stop=0.10,            # 10% trailing stop (exits dead money)
            take_profit=TAKE_PROFIT,       # +50% take profit
            time_stop_days=0,              # never
            min_hold_days=_NO_ROTATION_HOLD_DAYS,  # rotation effectively disabled
            max_sector_count=MAX_SECTOR_COUNT,
            re_score_holdings=True,        # re-score holdings on current composite daily
            protect_winners=False,
            bear_exposure=1.0,
            exit_priority=["hard_stop_loss", "trailing_stop", "take_profit"],
        )

    # ── PEGY helpers ─────────────────────────────────────────────────

    @staticmethod
    def _pegy_score(pegy: Optional[float]) -> Optional[float]:
        """Map a PEGY value to a bounded score. None if not computable/buyable."""
        if pegy is None or pegy <= 0:
            return None
        return 1.0 / (1.0 + pegy)

    @staticmethod
    def _composite(mom_score: float, pegy_score: Optional[float]) -> Optional[float]:
        """50/50 blended composite score. None if PEGY is missing/negative."""
        if pegy_score is None:
            return None
        return MOM_W * mom_score + PEGY_W * pegy_score

    def _pegy_for_dates(self, ticker_lower: str, all_dates: List[str],
                        close_by_date: Dict[str, float], eps_rows, div_rows):
        """As-of PEGY value per sim date for one ticker.

        eps_rows: sorted [(report_date, diluted_eps)] ascending, prior to any filter.
        div_rows: sorted [(report_date, cash_dividends_paid, ordinary_shares_number)] ascending.
        Returns {date_str: pegy_value} only where computable and pegy > 0.
        """
        if len(eps_rows) < 2:
            return {}
        eps_dates = np.array([pd.Timestamp(r[0]) for r in eps_rows], dtype="datetime64[D]")
        eps_vals = np.array([r[1] for r in eps_rows], dtype=float)
        div_map = None
        if div_rows:
            div_map = (
                np.array([pd.Timestamp(r[0]) for r in div_rows], dtype="datetime64[D]"),
                np.array([r[1] for r in div_rows], dtype=float),
                np.array([r[2] for r in div_rows], dtype=float),
            )
        out: Dict[str, float] = {}
        for ds in all_dates:
            close = close_by_date.get(ds)
            if close is None or close <= 0:
                continue
            dt = np.datetime64(ds)
            i = np.searchsorted(eps_dates, dt, side="right") - 1
            if i < 1:  # need at least two annual reports <= as-of date
                continue
            eps_now, eps_prior = eps_vals[i], eps_vals[i - 1]
            if not (eps_now and eps_prior) or eps_prior == 0:
                continue
            pe = close / eps_now
            growth = (eps_now - eps_prior) / eps_prior
            div_yield = 0.0
            if div_map is not None:
                j = np.searchsorted(div_map[0], dt, side="right") - 1
                if j >= 0:
                    div_yield = (div_map[1][j] / div_map[2][j]) / close
            denom = (growth + div_yield) * 100
            pegy = pe / denom if denom > 0 else None
            if pegy is None or pegy <= 0:
                continue
            out[ds] = float(pegy)
        return out

    def _load_financials(self, engine: Engine):
        """Load all yearly EPS + dividend rows grouped by ticker, once per backtest."""
        with engine.connect() as conn:
            eps_rows = conn.execute(
                text(
                    "SELECT ticker, report_date, diluted_eps FROM stock_financials_yearly "
                    "WHERE report_date IS NOT NULL AND diluted_eps IS NOT NULL "
                    "ORDER BY ticker, report_date ASC"
                )
            ).fetchall()
            div_rows = conn.execute(
                text(
                    "SELECT ticker, report_date, cash_dividends_paid, ordinary_shares_number "
                    "FROM stock_financials_yearly "
                    "WHERE report_date IS NOT NULL AND cash_dividends_paid IS NOT NULL "
                    "AND ordinary_shares_number IS NOT NULL "
                    "ORDER BY ticker, report_date ASC"
                )
            ).fetchall()
        eps_by: Dict[str, list] = {}
        for t, rd, eps in eps_rows:
            eps_by.setdefault(str(t).lower(), []).append((rd, float(eps)))
        div_by: Dict[str, list] = {}
        for t, rd, cdp, osn in div_rows:
            div_by.setdefault(str(t).lower(), []).append((rd, abs(float(cdp)), float(osn)))
        return eps_by, div_by

    # ── Precomputed signals (efficient backtesting) ───────────────────

    def precompute_signals(self, all_dates: List[str], engine: Engine) -> Optional[Dict[str, List[Signal]]]:
        """Vectorized per-ticker scan: momentum + as-of PEGY -> composite.

        Builds, in one pass over each ticker's price data:
          - the price cache (via base get_precomputed_price_cache),
          - self._pegy_map   {ticker: {date: pegy_value}},
          - self._score_map  {ticker: {date: composite_score}} (used by score_holding),
          - the per-date candidate Signals (PEGY-filtered, ranked by composite).
        """
        from app.utils.security import get_safe_table_name
        from app.db.database import SECTOR_NAME_MAP

        first_date = all_dates[0]
        last_date = all_dates[-1]
        load_start = (pd.Timestamp(first_date) - pd.Timedelta(days=300)).strftime("%Y-%m-%d")
        date_set = set(all_dates)
        sector_name_to_etf = {name: ticker for ticker, name in SECTOR_NAME_MAP.items()}

        # Metadata universe (market cap + sector)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT ticker, market_cap, sector FROM stock_metadata")
                ).fetchall()
        except Exception:
            return {d: [] for d in all_dates}
        meta: Dict[str, object] = {}
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
        if not meta:
            return {d: [] for d in all_dates}

        # ETF closes (for the scanner sector filter)
        etf_data = self._load_sector_etf_data(engine, load_start, last_date)
        if not etf_data:
            logger.warning("No ETF data loaded; cannot apply scanner filter")
            return {d: [] for d in all_dates}

        # Financials (as-of PEGY), once
        eps_by, div_by = self._load_financials(engine)

        # Ensure caches
        if self._price_cache is None:
            self._price_cache = {}
        if self._score_map is None:
            self._score_map = {}

        all_candidates: Dict[str, List[dict]] = {}

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
            if ticker_lower not in self._price_cache:
                self._price_cache[ticker_lower] = {
                    str(pd.Timestamp(d))[:10]: float(c) for d, c in zip(dates, close)
                }

            # As-of PEGY values for this ticker
            ticker_pegy = self._pegy_for_dates(
                ticker_lower, all_dates, self._price_cache[ticker_lower],
                eps_by.get(ticker_lower, []), div_by.get(ticker_lower, []),
            )
            if not ticker_pegy:
                continue  # never has a valid as-of PEGY -> not buyable

            etf_key = sector_name_to_etf[sec]
            etf_dates, _, etf_perf3m = etf_data[etf_key]
            date_to_i = {str(pd.Timestamp(dates[i]))[:10]: i for i in range(len(dates))}

            # Score map for this ticker
            ticker_scores: Dict[str, float] = {}

            for ds in all_dates:
                i = date_to_i.get(ds)
                if i is None:
                    continue
                pegy = ticker_pegy.get(ds)
                if pegy is None:
                    continue
                mom = self._sigmoid_score(float(perf3m_arr[i]))
                ps = self._pegy_score(pegy)
                composite = self._composite(mom, ps)
                if composite is None:
                    continue
                ticker_scores[ds] = round(composite, 6)

                # Candidate filter
                perf_3m = float(perf3m_arr[i])
                vol_14 = float(vol14_arr[i])
                if not (np.isfinite(perf_3m) and np.isfinite(vol_14)):
                    continue
                if vol_14 > MAX_VOLATILITY:
                    continue
                if pegy >= PEGY_THRESHOLD:
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
                    "score": round(composite, 6),
                    "market_cap": mc,
                    "sector": sec,
                    "price": float(close[i]),
                    "date": ds,
                })

            if ticker_scores:
                self._score_map[ticker_lower] = ticker_scores

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
                    entry_type="sector_top5_pegy",
                    market_cap=c["market_cap"],
                    sector=c["sector"],
                )
                for c in cands
            ]

        logger.info(
            "PEGY: %d tickers with valid scores out of universe %d",
            len(self._score_map), len(meta),
        )
        return result

    def precompute_scores(self, all_dates: List[str], engine: Engine) -> Optional[Dict[str, Dict[str, float]]]:
        """Composite score map is already built by precompute_signals. Just ensure it exists."""
        if self._score_map is None:
            # Fallback: build it directly (batch path calls precompute_signals first,
            # so this only triggers if something called precompute_scores standalone).
            self.precompute_signals(all_dates, engine)
        return self._score_map

    # ── Holding re-scoring (for rotation) ─────────────────────────────

    def score_holding(self, ticker: str, as_of_date: str, engine: Engine,
                      entry_price: float, market_cap: float, sector: str,
                      side: str = "long") -> float:
        """Composite score for a holding (momentum + as-of PEGY).

        Uses the precomputed composite map when available; otherwise computes
        the composite on the fly from the database.
        """
        if self._score_map is not None:
            m = self._score_map.get(str(ticker).lower(), {})
            v = m.get(as_of_date)
            if v is not None:
                return float(v)
        # Fallback: compute composite live
        try:
            from app.utils.security import get_safe_table_name
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
            mom = self._sigmoid_score(perf_3m)
            # as-of PEGY from latest two annual reports <= as_of_date
            eps_by, div_by = self._load_financials(engine)
            close_by_date = {str(pd.Timestamp(dates[-1]))[:10]: float(close[-1])}
            tpegy = self._pegy_for_dates(
                str(ticker).lower(), [as_of_date], close_by_date,
                eps_by.get(str(ticker).lower(), []), div_by.get(str(ticker).lower(), []),
            )
            pegy = tpegy.get(as_of_date)
            ps = self._pegy_score(pegy)
            composite = self._composite(mom, ps)
            return round(composite, 6) if composite is not None else 0.0
        except Exception:
            return 0.0

    # ── Live / per-day signal path (Alpaca runner) ────────────────────

    def get_signals(self, as_of_date: str, engine: Engine) -> List[Signal]:
        """Live path: build momentum candidates via the base, then apply PEGY
        filter and re-rank by the composite score."""
        base_signals = super().get_signals(as_of_date, engine)
        if not base_signals:
            return []

        eps_by, div_by = self._load_financials(engine)
        result: List[Signal] = []
        for sig in base_signals:
            ticker_lower = str(sig.ticker).lower()
            try:
                from app.utils.security import get_safe_table_name
                safe = get_safe_table_name(ticker_lower)
                with engine.connect() as conn:
                    close_row = conn.execute(
                        text(f'SELECT "Close" FROM "{safe}" WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 1')
                    ).fetchone()
                close = float(close_row[0]) if close_row and close_row[0] else None
            except Exception:
                close = None
            if close is None or close <= 0:
                continue
            tpegy = self._pegy_for_dates(
                ticker_lower, [as_of_date], {as_of_date: close},
                eps_by.get(ticker_lower, []), div_by.get(ticker_lower, []),
            )
            pegy = tpegy.get(as_of_date)
            ps = self._pegy_score(pegy)
            if ps is None or pegy >= PEGY_THRESHOLD:
                continue
            composite = self._composite(sig.score, ps)  # sig.score is the momentum score
            if composite is None:
                continue
            sig.score = round(composite, 6)
            sig.entry_type = "sector_top5_pegy"
            result.append(sig)

        result.sort(key=lambda x: x.score, reverse=True)
        return result
