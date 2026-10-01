"""Cached per-ticker OHLCV access for the exit replay.

One query per ticker, not per trade: MQR's 29,736 trades span ~1,200 tickers.
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd
from sqlalchemy import text

from app.db.database import engine as default_engine
from app.services.exit_replay._dates import as_naive_dates
from app.utils.security import get_safe_table_name

BARS_COLUMNS = ["Date", "Open", "High", "Low", "Close"]


class PricePanel:
    """Forward OHLCV lookup with a per-ticker cache.

    A ticker whose table is absent or unreadable (delisted, renamed, or an
    invalid symbol) is remembered as missing and yields an empty frame rather
    than raising: the trade is censored, not fatal.
    """

    def __init__(self, engine=None, fetch_since: str | None = None):
        """`fetch_since` bounds the SQL by date.

        The default (None) loads a ticker's whole history, which is what the exit
        replay wants. It is a liability for whole-universe work: a single ticker
        whose table holds intraday-scale history drags the entire table and can
        stall a 1,500-ticker sweep for hours. Universe builds pass a date.
        """
        self._engine = engine if engine is not None else default_engine
        self._fetch_since = fetch_since
        self._cache: Dict[str, pd.DataFrame] = {}
        self._missing: set[str] = set()
        self.query_count = 0

    def bars(self, ticker: str, start, end) -> pd.DataFrame:
        """Bars for `ticker` within [start, end] inclusive, cached by ticker."""
        key = ticker.upper()
        if key in self._missing:
            return pd.DataFrame(columns=BARS_COLUMNS)
        if key not in self._cache:
            self._cache[key] = self._fetch(ticker)
        df = self._cache[key]
        if df.empty:
            return df
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        out = df[(df["Date"] >= s) & (df["Date"] <= e)]
        return out.reset_index(drop=True)

    def _fetch(self, ticker: str) -> pd.DataFrame:
        self.query_count += 1
        try:
            safe = get_safe_table_name(ticker)
            where = '"Close" > 0'
            params = {}
            if self._fetch_since:
                where += ' AND "Date" >= :since'
                params["since"] = self._fetch_since
            sql = (
                f'SELECT "Date", "Open", "High", "Low", "Close" FROM "{safe}" '
                f'WHERE {where} ORDER BY "Date"'
            )
            with self._engine.connect() as conn:
                df = conn.execute(text(sql), params).mappings().all()
            df = pd.DataFrame(df)
        except Exception:
            # Absent table, invalid symbol, or unreadable: censored, not fatal.
            self._missing.add(ticker.upper())
            return pd.DataFrame(columns=BARS_COLUMNS)
        if df.empty:
            self._missing.add(ticker.upper())
            return pd.DataFrame(columns=BARS_COLUMNS)
        df["Date"] = as_naive_dates(df["Date"])
        for c in ("Open", "High", "Low", "Close"):
            df[c] = df[c].astype(float)
        return df[BARS_COLUMNS]

    def next_open(self, ticker: str, date) -> Optional[float]:
        """Open of the first trading day strictly after `date`, else None."""
        df = self._cache.get(ticker.upper())
        if df is None or df.empty:
            return None
        d = pd.Timestamp(date)
        later = df[df["Date"] > d]
        if later.empty:
            return None
        return float(later.iloc[0]["Open"])
