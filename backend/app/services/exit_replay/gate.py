"""Keystone gate: the replay must reproduce exits recorded in journal_trade.

journal_trade has no exit_reason column, so the gate uses a structural
signature: min_hold_days=14 gates rotation, therefore no trade held < 14 days
can have been exited by rotation -- every one must be reproduced by the price
rules alone. All conclusions are void until this passes.

Mismatches are CLASSIFIED rather than counted, because the adapter's price
caches were bounded by each run's [as_of, end] window (which journal_trade does
not record), so a trade exiting near a run boundary was filled at that day's
close rather than the next open. That class is explainable; anything else is a
semantic bug.
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from .engine import CURRENT_MQR_POLICY, ExitPolicy, replay_position

HARD_HOLD_THRESHOLD_DAYS = 14
_PRICE_DP = 2  # journal_trade stores prices rounded to 2dp
MAX_FORWARD_DAYS = 400


def _classify(out, exit_date, exit_px) -> str:
    """'exact' | 'date_mismatch' | 'px_mismatch' | 'not_fully_observed'."""
    if out.exit_date is None or out.exit_px is None:
        return "not_fully_observed"
    if pd.Timestamp(out.exit_date) != pd.Timestamp(exit_date):
        return "date_mismatch"
    if round(abs(float(out.exit_px) - float(exit_px)), _PRICE_DP) != 0:
        return "px_mismatch"
    return "exact"


def run_reproduction_gate(
    entry_df: pd.DataFrame,
    panel,
    policy: ExitPolicy = CURRENT_MQR_POLICY,
    limit: Optional[int] = None,
    cap_to_actual: bool = False,
) -> dict:
    """Replay `policy` from every frozen entry and compare to the recorded exit.

    cap_to_actual=False (the gate): price rules must stand alone, no rotation cap.
    cap_to_actual=True (the corroboration check): cap at the recorded exit date,
    so rotation trades should reproduce via the cap.
    """
    hard_total = hard_ok = 0
    soft_total = soft_ok = 0
    classes: dict[str, int] = {}
    mismatches: List[dict] = []

    rows = entry_df.itertuples(index=False)
    for i, row in enumerate(rows):
        if limit is not None and i >= limit:
            break
        bars = panel.bars(row.ticker, row.entry_date,
                          row.entry_date + pd.Timedelta(days=MAX_FORWARD_DAYS))
        out = replay_position(
            row.entry_px, row.entry_date, bars, policy,
            cap_date=row.exit_date if cap_to_actual else None,
            panel=panel, ticker=row.ticker,
        )
        cls = _classify(out, row.exit_date, row.exit_px)
        classes[cls] = classes.get(cls, 0) + 1
        ok = cls == "exact"

        if row.hold_days_calendar < HARD_HOLD_THRESHOLD_DAYS:
            hard_total += 1
            hard_ok += int(ok)
            if not ok and len(mismatches) < 40:
                mismatches.append({
                    "class": cls, "ticker": row.ticker,
                    "entry": str(pd.Timestamp(row.entry_date).date()),
                    "hold_days": int(row.hold_days_calendar),
                    "recorded_date": str(pd.Timestamp(row.exit_date).date()),
                    "recorded_px": round(float(row.exit_px), 2),
                    "replay_date": str(pd.Timestamp(out.exit_date).date()) if out.exit_date is not None else None,
                    "replay_px": round(float(out.exit_px), 2) if out.exit_px is not None else None,
                    "replay_reason": out.exit_reason,
                })
        else:
            soft_total += 1
            soft_ok += int(ok)

    return {
        "hard_total": hard_total,
        "hard_reproduced": hard_ok,
        "hard_rate": round(hard_ok / hard_total, 4) if hard_total else 0.0,
        "hard_mismatches": mismatches,
        "soft_total": soft_total,
        "soft_reproduced": soft_ok,
        "soft_rate": round(soft_ok / soft_total, 4) if soft_total else 0.0,
        "predicted_soft_rate": 0.56,
        "class_counts": classes,
        "cap_to_actual": cap_to_actual,
    }
