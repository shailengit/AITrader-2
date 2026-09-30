"""Extract and freeze a strategy's historical entries from journal_trade.

The entry set is FROZEN: every policy comparison runs on byte-identical entries,
so differences between policies are attributable to the exit rule alone.

Frozen format is CSV (this venv has no pyarrow/fastparquet), with dtypes
restored explicitly on load.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import text

from app.db.database import engine as default_engine

MQR_STRATEGY_ID = "8e78e543-18e2-4b7d-abff-04e754e33015"

ENTRY_COLUMNS = [
    "ticker", "entry_date", "entry_px", "qty",
    "exit_date", "exit_px", "hold_days_calendar",
]

_SQL = """
    SELECT ticker, entry_at AS entry_date, entry_px, qty,
           exit_at AS exit_date, exit_px
    FROM journal_trade
    WHERE strategy_id = :sid AND source = :src
      AND entry_px > 0 AND exit_px > 0
      AND exit_at IS NOT NULL
    ORDER BY entry_at, ticker
"""


def _as_naive_dates(s: pd.Series) -> pd.Series:
    """Parse to datetime and drop tz.

    These are calendar trading days. Postgres hands back tz-aware values while
    policy configs and test literals are naive, and comparing the two raises,
    so the whole package works in naive dates.
    """
    s = pd.to_datetime(s)
    return s.dt.tz_localize(None) if s.dt.tz is not None else s


def extract_entry_set(
    strategy_id: str, source: str = "backtest", engine=None
) -> pd.DataFrame:
    """Closed round trips for one strategy, as the frozen entry set."""
    eng = engine if engine is not None else default_engine
    with eng.connect() as conn:
        rows = conn.execute(
            text(_SQL), {"sid": strategy_id, "src": source}
        ).mappings().all()
    df = pd.DataFrame(rows)
    df["entry_date"] = _as_naive_dates(df["entry_date"])
    df["exit_date"] = _as_naive_dates(df["exit_date"])
    for c in ("entry_px", "exit_px", "qty"):
        df[c] = df[c].astype(float)
    df["hold_days_calendar"] = (df["exit_date"] - df["entry_date"]).dt.days
    df["ticker"] = df["ticker"].astype(str)
    return df[ENTRY_COLUMNS].reset_index(drop=True)


def freeze_entry_set(df: pd.DataFrame, path) -> str:
    """Write the entry set to CSV and return the sha256 of the written bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df[ENTRY_COLUMNS].copy()
    out["entry_date"] = out["entry_date"].dt.strftime("%Y-%m-%d")
    out["exit_date"] = out["exit_date"].dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_entry_set(path) -> pd.DataFrame:
    """Load a frozen entry set, restoring dtypes."""
    df = pd.read_csv(path)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    for c in ("entry_px", "exit_px", "qty"):
        df[c] = df[c].astype(float)
    df["hold_days_calendar"] = df["hold_days_calendar"].astype(int)
    df["ticker"] = df["ticker"].astype(str)
    return df[ENTRY_COLUMNS]
