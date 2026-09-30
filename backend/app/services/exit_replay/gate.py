"""Keystone gate: the replay must reproduce the exits recorded in journal_trade.

CORRECTED 2026-09-30. The original design assumed `journal_trade` had no
exit-reason column and inferred one from a structural signature (min_hold_days=14
gates rotation). That premise was false: every backtest row carries
`notes = 'backtest:<Reason>'`, e.g. 'backtest:Trailing Stop'. The reason is now
read directly, which is exact rather than inferred.

The gate therefore becomes a direct claim, and a stronger one:

    For every trade whose RECORDED reason is a price rule, replaying the current
    MQR policy UNCAPPED must reproduce the recorded (exit_date, exit_px).

Rotation-exited trades are excluded from the hard requirement, because rotation
is deliberately held fixed in phase 1 and cannot be reproduced by price rules
alone. The old min_hold signature survives as a consistency check: a trade held
< 14 days cannot have been rotated out, so any such trade with reason
'Rotated Out' would mean the recorded labels contradict the rules.
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from .engine import CURRENT_MQR_POLICY, ExitPolicy, replay_position

HARD_HOLD_THRESHOLD_DAYS = 14
_PRICE_DP = 2
MAX_FORWARD_DAYS = 400

PRICE_RULES = ("Trailing Stop", "Take Profit", "Time Stop", "Stop Loss")
ROTATION_RULE = "Rotated Out"

#: Price-only reproduction floor. Date reproduction must be perfect; prices are
#: allowed a small residual because the panel was revised after some backtests
#: wrote their rows (documented in spec 7.1).
MIN_PRICE_REPRODUCTION = 0.99


def _class(out, exit_date, exit_px) -> str:
    """'exact' | 'date_mismatch' | 'px_mismatch' | 'not_fully_observed'."""
    if out.exit_date is None or out.exit_px is None:
        return "not_fully_observed"
    if pd.Timestamp(out.exit_date) != pd.Timestamp(exit_date):
        return "date_mismatch"
    if round(abs(float(out.exit_px) - float(exit_px)), _PRICE_DP) != 0:
        return "px_mismatch"
    return "exact"


def gate_passed(gate: dict) -> tuple[bool, str]:
    """Single source of truth for the gate verdict.

    Three call sites (runner, report, tests) each encoded their own rule and
    disagreed; they all call this now.
    """
    total = int(gate.get("price_total", 0))
    ok = int(gate.get("price_reproduced", 0))
    semantic = int(gate.get("semantic_mismatches", 0))
    inconsistent = int(gate.get("label_inconsistencies", 0))
    if total == 0:
        return False, "no price-rule-exited trades in the entry set; gate vacuous"
    if inconsistent:
        return False, (f"{inconsistent} trade(s) held < {HARD_HOLD_THRESHOLD_DAYS} days "
                       f"carry a rotation label, which the rules forbid — labels and "
                       f"rules disagree; conclusions void")
    if semantic:
        return False, (f"{semantic} price-rule trades triggered on the wrong date or "
                       f"were censored — rule semantics diverge; conclusions void")
    rate = ok / total
    if rate < MIN_PRICE_REPRODUCTION:
        return False, (f"price reproduction {rate:.4f} below the {MIN_PRICE_REPRODUCTION} "
                       f"floor — conclusions void")
    return True, (f"{ok:,}/{total:,} price-rule trades reproduced ({rate:.4f}); "
                  f"semantics exact; {total - ok} residual data-vintage difference(s)")


def run_reproduction_gate(
    entry_df: pd.DataFrame,
    panel,
    policy: ExitPolicy = CURRENT_MQR_POLICY,
    cap_to_actual: bool = False,
) -> dict:
    """Replay `policy` from every frozen entry and compare to the recorded exit.

    cap_to_actual=False (the gate): price rules must stand alone.
    cap_to_actual=True: cap at the recorded exit date, so rotation-exited trades
    should reproduce too (an end-to-end corroboration of the whole pipeline).
    """
    classes: dict[str, int] = {}
    mismatches: List[dict] = []
    price_total = price_ok = 0
    rot_total = rot_ok = 0
    semantic = 0
    label_inconsistencies = 0
    capped_total = capped_ok = 0

    for row in entry_df.itertuples(index=False):
        bars = panel.bars(row.ticker, row.entry_date,
                          row.entry_date + pd.Timedelta(days=MAX_FORWARD_DAYS))
        out = replay_position(
            row.entry_px, row.entry_date, bars, policy,
            cap_date=row.exit_date if cap_to_actual else None,
            panel=panel, ticker=row.ticker,
        )
        cls = _class(out, row.exit_date, row.exit_px)
        classes[cls] = classes.get(cls, 0) + 1
        is_price_rule = row.exit_reason in PRICE_RULES

        if row.hold_days_calendar < HARD_HOLD_THRESHOLD_DAYS and not is_price_rule:
            label_inconsistencies += 1

        if is_price_rule:
            price_total += 1
            price_ok += int(cls == "exact")
            if cls in ("date_mismatch", "not_fully_observed"):
                semantic += 1
            if cls != "exact" and len(mismatches) < 40:
                mismatches.append({
                    "class": cls, "ticker": row.ticker,
                    "recorded_reason": row.exit_reason,
                    "entry": str(pd.Timestamp(row.entry_date).date()),
                    "hold_days": int(row.hold_days_calendar),
                    "recorded_date": str(pd.Timestamp(row.exit_date).date()),
                    "recorded_px": round(float(row.exit_px), 2),
                    "replay_date": str(pd.Timestamp(out.exit_date).date()) if out.exit_date is not None else None,
                    "replay_px": round(float(out.exit_px), 2) if out.exit_px is not None else None,
                    "replay_reason": out.exit_reason,
                })
        else:
            rot_total += 1
            rot_ok += int(cls == "exact")

        capped_total += 1
        capped_ok += int(cls == "exact")

    result = {
        "price_total": price_total,
        "price_reproduced": price_ok,
        "price_rate": round(price_ok / price_total, 4) if price_total else 0.0,
        "rotation_total": rot_total,
        "rotation_reproduced": rot_ok,
        "semantic_mismatches": semantic,
        "label_inconsistencies": label_inconsistencies,
        "mismatches": mismatches,
        "class_counts": classes,
        "capped_total": capped_total,
        "capped_reproduced": capped_ok,
        "capped_rate": round(capped_ok / capped_total, 4) if capped_total else 0.0,
        "cap_to_actual": cap_to_actual,
    }
    result["passed"], result["verdict"] = gate_passed(result)
    return result
