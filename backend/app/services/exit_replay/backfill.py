"""Backfill journal_trade.mae / .mfe from the real price path.

Those columns have been 0% populated across the whole corpus while the schema
and the Coach MAE/MFE view have expected them all along.

DRY RUN BY DEFAULT: this writes to the production database, so a caller must
opt in with dry_run=False explicitly.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from .regret import excursion_stats

_UPDATE = text("""
    UPDATE journal_trade
       SET mae = :mae, mfe = :mfe
     WHERE ticker = :ticker
       AND entry_at::date = :entry_date
       AND source = 'backtest'
""")


def backfill(entry_df, panel, engine, dry_run: bool = True) -> dict:
    """Compute MFE/MAE per trade and (optionally) write them back.

    Returns n_updated (rows that would be / were written) and n_skipped (rows
    with no usable forward bars -- reported, never silently dropped).
    """
    exc = excursion_stats(entry_df, panel)
    usable = exc[exc["mae"].notna() & exc["mfe"].notna()]
    n_skipped = int(len(exc) - len(usable))

    if dry_run:
        return {"n_updated": int(len(usable)), "n_skipped": n_skipped, "dry_run": True}

    updated = 0
    with engine.begin() as conn:
        for row in usable.itertuples(index=False):
            conn.execute(_UPDATE, {
                "mae": float(row.mae),
                "mfe": float(row.mfe),
                "ticker": row.ticker,
                "entry_date": str(pd.Timestamp(row.entry_date).date()),
            })
            updated += 1
    return {"n_updated": updated, "n_skipped": n_skipped, "dry_run": False}
