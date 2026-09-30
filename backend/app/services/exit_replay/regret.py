"""Forward-return regret and MFE/MAE excursions (spec approaches A and C).

Answers "did we sell too early?" with the real forward path and no rule replay:
for each fixed entry, what would each forward horizon have returned, and how far
did the price run past where we actually sold?
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

HORIZONS = (1, 2, 3, 5, 10, 20, 40, 60, 90, 120)


def horizon_returns(
    entry_px: float,
    entry_date: pd.Timestamp,
    bars: pd.DataFrame,
    horizons=HORIZONS,
) -> Dict[int, Optional[float]]:
    """Return if exited at the close of the Nth trading day after entry.

    None for a horizon the data does not reach -- reported as censored, never
    silently treated as zero.
    """
    forward = bars[bars["Date"] > pd.Timestamp(entry_date)].reset_index(drop=True)
    out: Dict[int, Optional[float]] = {}
    for h in horizons:
        if len(forward) >= h:
            out[h] = (float(forward.iloc[h - 1]["Close"]) - float(entry_px)) / float(entry_px)
        else:
            out[h] = None
    return out


def regret_vs_actual(
    entry_px: float, actual_exit_px: float, hr: Dict[int, Optional[float]]
) -> Optional[float]:
    """Best observed horizon return minus the actual realised return.

    Positive = we sold too early. None when no horizon was observable.
    """
    seen = [v for v in hr.values() if v is not None]
    if not seen:
        return None
    actual = (float(actual_exit_px) - float(entry_px)) / float(entry_px)
    return max(seen) - actual


def excursion_stats(entry_df: pd.DataFrame, panel) -> pd.DataFrame:
    """MFE/MAE over each trade's ACTUAL holding period.

    Also the source for the optional journal_trade backfill, which fills the
    mae/mfe columns that are 0% populated across the corpus.
    """
    rows = []
    for row in entry_df.itertuples(index=False):
        bars = panel.bars(row.ticker, row.entry_date, row.exit_date)
        fwd = bars[(bars["Date"] > row.entry_date) & (bars["Date"] <= row.exit_date)]
        if fwd.empty:
            rows.append({"ticker": row.ticker, "entry_date": row.entry_date,
                         "mae": None, "mfe": None})
            continue
        rows.append({
            "ticker": row.ticker, "entry_date": row.entry_date,
            "mae": (float(fwd["Low"].min()) - float(row.entry_px)) / float(row.entry_px),
            "mfe": (float(fwd["High"].max()) - float(row.entry_px)) / float(row.entry_px),
        })
    return pd.DataFrame(rows)
