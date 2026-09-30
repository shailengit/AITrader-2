"""Extract and freeze a strategy's historical entries from journal_trade.

The entry set is FROZEN: every policy comparison runs on byte-identical entries,
so differences between policies are attributable to the exit rule alone.

Frozen format is CSV (this venv has no pyarrow/fastparquet), with dtypes
restored explicitly on load.

TWO CORRECTIONS TO THE ORIGINAL DESIGN, both made after verifying against the DB:

1. The exit reason IS recorded, in `notes` (e.g. 'backtest:Trailing Stop'). The
   original design assumed there was no reason column and built a structural
   signature (min_hold_days=14 gates rotation) to infer it. `notes` is exact, so
   it is used directly now; the signature survives only as a cross-check.

2. Rows are DEDUPLICATED. MQR's 29,736 rows are only 2,013 distinct
   (ticker, entry_date) positions, replicated up to 110x (mean 14.8), all written
   in a two-minute window: a batch-writer artifact, not distinct positions.
   Multiplicity rises by entry year (2.5x in 2020 to 31.5x in 2026), so leaving
   them in made every dollar figure a multiplicity-weighted sum and made the
   fit/validate comparison non-comparable. Duplicates are byte-identical in
   2,011 of 2,013 groups.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.db.database import engine as default_engine
from app.services.exit_replay._dates import as_naive_dates

MQR_STRATEGY_ID = "8e78e543-18e2-4b7d-abff-04e754e33015"

#: The strategy's own live exit order, used when no reason is recorded.
EXIT_PRIORITY = ("hard_stop_loss", "trailing_stop", "take_profit", "time_stop")

ENTRY_COLUMNS = [
    "ticker", "entry_date", "entry_px", "qty",
    "exit_date", "exit_px", "hold_days_calendar", "exit_reason",
]

_SQL = """
    SELECT ticker, entry_at AS entry_date, entry_px, qty,
           exit_at AS exit_date, exit_px, notes
    FROM journal_trade
    WHERE strategy_id = :sid AND source = :src
      AND entry_px > 0 AND exit_px > 0
      AND exit_at IS NOT NULL
    ORDER BY entry_at, ticker, exit_at
"""


def _reason_from_notes(notes) -> str | None:
    """journal_trade.notes carries 'backtest:<Reason>' on backtest rows."""
    if not isinstance(notes, str):
        return None
    prefix = "backtest:"
    return notes[len(prefix):] if notes.startswith(prefix) else None


def extract_entry_set(
    strategy_id: str,
    source: str = "backtest",
    engine=None,
    dedupe: bool = True,
) -> pd.DataFrame:
    """Closed round trips for one strategy, deduplicated to distinct positions.

    `dedupe=False` returns the raw rows (useful for diagnosing the duplication
    itself, e.g. in tests and in duplicate_summary).
    """
    eng = engine if engine is not None else default_engine
    with eng.connect() as conn:
        rows = conn.execute(
            text(_SQL), {"sid": strategy_id, "src": source}
        ).mappings().all()
    df = pd.DataFrame(rows)
    df["entry_date"] = as_naive_dates(df["entry_date"])
    df["exit_date"] = as_naive_dates(df["exit_date"])
    for c in ("entry_px", "exit_px", "qty"):
        df[c] = df[c].astype(float)
    df["hold_days_calendar"] = (df["exit_date"] - df["entry_date"]).dt.days
    df["ticker"] = df["ticker"].astype(str)
    df["exit_reason"] = df["notes"].map(_reason_from_notes)
    df = df[ENTRY_COLUMNS + ["notes"]]

    if dedupe:
        # Sort is explicit so the kept row is deterministic, and the first row of
        # each group survives (duplicates are byte-identical in 2,011 of 2,013
        # groups; for the two that differ we keep the earliest exit).
        df = (
            df.sort_values(["ticker", "entry_date", "exit_date"], kind="stable")
              .drop_duplicates(subset=["ticker", "entry_date"], keep="first")
        )
    return df[ENTRY_COLUMNS].reset_index(drop=True)


def duplicate_summary(raw_df: pd.DataFrame) -> dict:
    """How much replication the raw rows carry. Reported, never silent."""
    if raw_df.empty:
        return {"rows": 0, "distinct": 0, "duplicates": 0, "max_multiplicity": 0,
                "mean_multiplicity": 0.0}
    g = raw_df.groupby(["ticker", "entry_date"]).size()
    return {
        "rows": int(len(raw_df)),
        "distinct": int(g.size),
        "duplicates": int(len(raw_df) - g.size),
        "max_multiplicity": int(g.max()),
        "mean_multiplicity": round(float(g.mean()), 2),
    }


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
