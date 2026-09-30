"""End-to-end MQR exit replay: freeze entries, pass the gate, rank policies.

Usage: cd backend && ./venv/bin/python scripts/mqr_exit_replay.py

Writes:
  backend/data/mqr_entry_set.csv            frozen entries (sha256 printed)
  docs/reports/mqr_exit_replay_<ts>.html    the report
  docs/reports/mqr_exit_replay_<ts>.json    machine-readable results

Exits non-zero if the reproduction gate fails: the numbers would be void.

Two bounds are reported for the leading policies, because they are not the same
number:
  PRIMARY  price-exited trades replay uncapped to the 180-day horizon, rotation
           exits are capped at their recorded date. This is an UPPER bound --
           rotation is held fixed and could have removed a name sooner.
  CAPPED   every trade capped at its recorded exit date: a LOWER bound (nothing
           may hold longer than it actually did).
A policy that only wins on the upper bound is not a candidate.

A next-open sensitivity run quantifies the look-ahead optimism of filling at an
observed close, since the live adapter fills at the next open.
"""
import json
import os
import sys
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(".")), ".env"))
sys.path.insert(0, ".")

from app.services.exit_replay.entry_set import (  # noqa: E402
    ENTRY_COLUMNS,
    MQR_STRATEGY_ID,
    duplicate_summary,
    extract_entry_set,
    freeze_entry_set,
    load_entry_set,
)
from app.services.exit_replay.evaluate import (  # noqa: E402
    evaluate_policy,
    price_exit_mask,
    summarise,
)
from app.services.exit_replay.gate import run_reproduction_gate  # noqa: E402
from app.services.exit_replay.policies import POLICY_GRID  # noqa: E402
from app.services.exit_replay.price_panel import PricePanel  # noqa: E402
from app.services.exit_replay.regret import excursion_stats  # noqa: E402
from app.services.exit_replay.report import build_report  # noqa: E402

ENTRY_PATH = "data/mqr_entry_set.csv"
REPORT_DIR = "../docs/reports"
SENSITIVITY_TOP_N = 5


def _val(pt):
    return summarise(pt[pt["bucket"] == "validate"])


def main() -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    os.makedirs("data", exist_ok=True)

    print("Extracting entry set...", flush=True)
    raw = extract_entry_set(MQR_STRATEGY_ID, dedupe=False)
    dup = duplicate_summary(raw)
    print(f"  raw rows {dup['rows']:,} -> distinct {dup['distinct']:,} "
          f"(dropped {dup['duplicates']:,} duplicates; max multiplicity "
          f"{dup['max_multiplicity']}, mean {dup['mean_multiplicity']})", flush=True)
    entries = extract_entry_set(MQR_STRATEGY_ID)
    digest = freeze_entry_set(entries, ENTRY_PATH)
    print(f"  frozen {len(entries):,} entries, sha256 {digest[:16]}…", flush=True)
    entries = load_entry_set(ENTRY_PATH)
    assert list(entries.columns) == ENTRY_COLUMNS
    dupes_left = int(entries.duplicated(["ticker", "entry_date"]).sum())
    assert dupes_left == 0, f"{dupes_left} duplicate positions survived dedup"
    panel = PricePanel()

    print("Reproduction gate (exhaustive)...", flush=True)
    gate = run_reproduction_gate(entries, panel)
    print(f"  price-rule {gate['price_reproduced']:,}/{gate['price_total']:,} "
          f"= {gate['price_rate']:.4f}", flush=True)
    print(f"  semantic mismatches {gate['semantic_mismatches']}  "
          f"label inconsistencies {gate['label_inconsistencies']}", flush=True)
    print(f"  capped corroboration {gate['capped_reproduced']:,}/"
          f"{gate['capped_total']:,} = {gate['capped_rate']:.4f}", flush=True)
    print(f"  VERDICT: {gate['verdict']}", flush=True)

    mask = price_exit_mask(entries)
    n_price = int(mask.sum())
    print(f"\nPrice-rule exits {n_price:,}  rotation exits {len(mask) - n_price:,}",
          flush=True)

    print(f"Evaluating {len(POLICY_GRID)} policies (primary = upper bound)...",
          flush=True)
    ranking = []
    for name, policy in POLICY_GRID.items():
        pt = evaluate_policy(entries, panel, policy, price_exit=mask)
        fit, val = summarise(pt[pt["bucket"] == "fit"]), _val(pt)
        ranking.append({
            "policy": name,
            "fit_dollars": fit.get("total_pnl_dollars"),
            "val_dollars": val.get("total_pnl_dollars"),
            "val_sum_pct": val.get("sum_pnl_pct"),
            "mean_pnl_pct": val.get("mean_pnl_pct"),
            "n_observed": val.get("n_observed"),
            "n_censored": val.get("n_censored"),
            "info_ratio": val.get("info_ratio"),
            "max_dd_pct": val.get("max_dd_pct"),
            "val_win_rate": val.get("win_rate"),
            "exit_mix": pt["exit_reason"].value_counts().to_dict(),
        })
        print(f"  {name:<12} fit ${fit.get('total_pnl_dollars')}  "
              f"val ${val.get('total_pnl_dollars')}", flush=True)

    ranking.sort(key=lambda r: (r["val_dollars"] is None, -(r["val_dollars"] or 0)))

    # Lower bound + next-open sensitivity for the leaders.
    print("\nBounds and next-open sensitivity for the leading policies...", flush=True)
    leader_names = [r["policy"] for r in ranking[:SENSITIVITY_TOP_N]]
    bounds = {}
    for name in leader_names:
        policy = POLICY_GRID[name]
        capped = evaluate_policy(entries, panel, policy,
                                 price_exit=pd.Series([False] * len(entries),
                                                      index=entries.index))
        nextopen = evaluate_policy(entries, panel, policy, price_exit=mask,
                                   fill="next_open")
        bounds[name] = {
            "capped_val_dollars": _val(capped).get("total_pnl_dollars"),
            "nextopen_val_dollars": _val(nextopen).get("total_pnl_dollars"),
        }
        print(f"  {name:<12} capped ${bounds[name]['capped_val_dollars']}  "
              f"next-open ${bounds[name]['nextopen_val_dollars']}", flush=True)

    excursions = excursion_stats(entries, panel)
    os.makedirs(REPORT_DIR, exist_ok=True)
    html = build_report(
        gate, ranking, excursions,
        {"split": "fit <=2023-12-31 / validate 2024-2025",
         "dedupe": dup, "bounds": bounds},
    )
    rp = f"{REPORT_DIR}/mqr_exit_replay_{ts}.html"
    with open(rp, "w") as f:
        f.write(html)
    jp = f"{REPORT_DIR}/mqr_exit_replay_{ts}.json"
    with open(jp, "w") as f:
        json.dump({"gate": gate, "ranking": ranking, "dedupe": dup,
                   "bounds": bounds, "entry_sha256": digest,
                   "n_entries": len(entries), "n_price_exits": n_price,
                   "n_rotation_exits": len(entries) - n_price,
                   "mae_median": float(excursions["mae"].median()) if len(excursions) else None,
                   "mfe_median": float(excursions["mfe"].median()) if len(excursions) else None},
                  f, indent=2, default=str)
    print(f"\nWrote {rp}\nWrote {jp}", flush=True)

    if not gate["passed"]:
        print(f"\nGATE FAILED — {gate['verdict']}", flush=True)
        return 1
    print(f"\nGATE PASSED — {gate['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
