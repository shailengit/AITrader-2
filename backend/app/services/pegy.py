"""PEGY computation.

PEGY = P/E  /  (Earnings Growth % + Dividend Yield %)

A valuation metric that adjusts the P/E ratio for a company's earnings growth
and dividend yield. Lower PEGY is generally considered more attractive.

Data sources (PostgreSQL):
  - Price: per-ticker price table (latest close)
  - EPS:   stock_financials_yearly.diluted_eps (trailing FY + prior FY)
  - Dividends: stock_financials_yearly.cash_dividends_paid / ordinary_shares_number
"""

import logging
from typing import Dict, List, Any

from sqlalchemy import text

from app.db.database import engine
from app.utils.security import get_safe_table_name

logger = logging.getLogger(__name__)


def compute_pegy(ticker: str) -> Dict[str, Any]:
    """Compute PEGY for a single ticker.

    Returns a dict with close, eps, pe, earnings_growth_pct, dividend_yield_pct,
    and pegy (None if it can't be computed).
    """
    ticker = ticker.upper()
    try:
        safe = get_safe_table_name(ticker)
        with engine.connect() as conn:
            close_row = conn.execute(
                text(f'SELECT "Close" FROM "{safe}" ORDER BY "Date" DESC LIMIT 1')
            ).fetchone()
            if not close_row or not close_row[0]:
                return {"ticker": ticker, "pegy": None, "error": "no price data"}
            close = float(close_row[0])

            eps_rows = conn.execute(
                text(
                    "SELECT report_date, diluted_eps FROM stock_financials_yearly "
                    "WHERE ticker=:t ORDER BY report_date DESC LIMIT 2"
                ),
                {"t": ticker},
            ).fetchall()
            if len(eps_rows) < 2:
                return {"ticker": ticker, "pegy": None, "error": "insufficient EPS data"}
            eps_now = float(eps_rows[0][1]) if eps_rows[0][1] else None
            eps_prior = float(eps_rows[1][1]) if eps_rows[1][1] else None
            if not eps_now or not eps_prior or eps_prior == 0:
                return {"ticker": ticker, "pegy": None, "error": "invalid EPS"}

            pe = close / eps_now
            growth = (eps_now - eps_prior) / eps_prior

            div_row = conn.execute(
                text(
                    "SELECT cash_dividends_paid, ordinary_shares_number "
                    "FROM stock_financials_yearly WHERE ticker=:t "
                    "ORDER BY report_date DESC LIMIT 1"
                ),
                {"t": ticker},
            ).fetchone()
            div_yield = 0.0
            if div_row and div_row[0] and div_row[1]:
                div_per_share = abs(float(div_row[0])) / float(div_row[1])
                div_yield = div_per_share / close

            # PEGY = P/E / (Earnings Growth % + Dividend Yield %). The growth
            # and yield are fractions here, so multiply by 100 to get percent.
            denom = (growth + div_yield) * 100
            pegy = pe / denom if denom > 0 else None

            return {
                "ticker": ticker,
                "close": round(close, 2),
                "eps": round(eps_now, 2),
                "pe": round(pe, 2),
                "earnings_growth_pct": round(growth * 100, 2),
                "dividend_yield_pct": round(div_yield * 100, 2),
                "pegy": round(pegy, 2) if pegy is not None else None,
            }
    except Exception as e:
        logger.warning("PEGY computation failed for %s: %s", ticker, e)
        return {"ticker": ticker, "pegy": None, "error": str(e)}


def compute_pegy_batch(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """Compute PEGY for a list of tickers efficiently (batched queries)."""
    tickers = [t.upper() for t in tickers]
    result: Dict[str, Dict[str, Any]] = {t: {"ticker": t, "pegy": None} for t in tickers}
    if not tickers:
        return result
    try:
        with engine.connect() as conn:
            eps_rows = conn.execute(
                text(
                    "SELECT ticker, report_date, diluted_eps FROM stock_financials_yearly "
                    "WHERE ticker = ANY(:tickers) ORDER BY ticker, report_date DESC"
                ),
                {"tickers": tickers},
            ).fetchall()
            eps_by_ticker: Dict[str, List[float]] = {}
            for t, _rd, eps in eps_rows:
                if eps is not None:
                    eps_by_ticker.setdefault(t, []).append(float(eps))

            div_rows = conn.execute(
                text(
                    "SELECT ticker, cash_dividends_paid, ordinary_shares_number "
                    "FROM stock_financials_yearly WHERE ticker = ANY(:tickers) "
                    "ORDER BY ticker, report_date DESC"
                ),
                {"tickers": tickers},
            ).fetchall()
            div_by_ticker: Dict[str, tuple] = {}
            for t, cdp, osn in div_rows:
                if t not in div_by_ticker and cdp and osn:
                    div_by_ticker[t] = (abs(float(cdp)), float(osn))

            for t in tickers:
                try:
                    safe = get_safe_table_name(t)
                    close_row = conn.execute(
                        text(f'SELECT "Close" FROM "{safe}" ORDER BY "Date" DESC LIMIT 1')
                    ).fetchone()
                    close = float(close_row[0]) if close_row and close_row[0] else None
                except Exception:
                    close = None
                if close is None:
                    continue
                eps_list = eps_by_ticker.get(t, [])
                if len(eps_list) < 2:
                    continue
                eps_now, eps_prior = eps_list[0], eps_list[1]
                if not eps_now or not eps_prior or eps_prior == 0:
                    continue
                pe = close / eps_now
                growth = (eps_now - eps_prior) / eps_prior
                div_yield = 0.0
                if t in div_by_ticker:
                    cdp, osn = div_by_ticker[t]
                    div_yield = (cdp / osn) / close
                denom = (growth + div_yield) * 100
                pegy = pe / denom if denom > 0 else None
                result[t] = {
                    "ticker": t,
                    "close": round(close, 2),
                    "eps": round(eps_now, 2),
                    "pe": round(pe, 2),
                    "earnings_growth_pct": round(growth * 100, 2),
                    "dividend_yield_pct": round(div_yield * 100, 2),
                    "pegy": round(pegy, 2) if pegy is not None else None,
                }
    except Exception as e:
        logger.warning("PEGY batch failed: %s", e)
    return result
