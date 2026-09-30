"""End-to-end MQR exit replay: freeze entries, pass the gate, rank policies.

Usage: cd backend && ./venv/bin/python scripts/mqr_exit_replay.py

Writes:
  backend/data/mqr_entry_set.csv            frozen entries (sha256 printed)
  docs/reports/mqr_exit_replay_<ts>.html    the report
  docs/reports/mqr_exit_replay_<ts>.json    machine-readable results

Exits non-zero if the reproduction gate fails: the numbers would be void.
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
    MQR_STRATEGY_ID,
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


def main() -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    os.makedirs("data", exist_ok=True)

    print("Freezing entry set...", flush=True)
    df = extract_entry_set(MQR_STRATEGY_ID)
    digest = freeze_entry_set(df, ENTRY_PATH)
    print(f"  {len(df):,} entries, sha256 {digest[:16]}…", flush=True)
    entries = load_entry_set(ENTRY_PATH)
    panel = PricePanel()

    print("Reproduction gate (exhaustive)...", flush=True)
    gate = run_reproduction_gate(entries, panel)
    print(f"  hard {gate['hard_reproduced']:,}/{gate['hard_total']:,} = {gate['hard_rate']:.4f}",
          flush=True)
    print(f"  soft rate {gate['soft_rate']:.4f} (predicted {gate['predicted_soft_rate']})",
          flush=True)
    print(f"  classes {gate['class_counts']}", flush=True)
    for m in gate["hard_mismatches"][:10]:
        print(f"    mismatch: {m}", flush=True)

    print("Classifying price-rule exits vs rotation exits...", flush=True)
    mask = price_exit_mask(entries, panel)
    n_price = int(mask.sum())
    print(f"  price-rule exits {n_price:,}  rotation exits {len(mask) - n_price:,}",
          flush=True)

    print(f"Evaluating {len(POLICY_GRID)} policies...", flush=True)
    ranking, per_policy = [], {}
    for name, policy in POLICY_GRID.items():
        # rotation held fixed; price-exited trades replay uncapped to the horizon
        pt = evaluate_policy(entries, panel, policy, price_exit=mask)
        per_policy[name] = summarise(pt)
        fit = summarise(pt[pt["bucket"] == "fit"])
        val = summarise(pt[pt["bucket"] == "validate"])
        ranking.append({
            "policy": name,
            "fit_dollars": fit.get("total_pnl_dollars"),
            "val_dollars": val.get("total_pnl_dollars"),
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
    excursions = excursion_stats(entries, panel)

    os.makedirs(REPORT_DIR, exist_ok=True)
    html = build_report(gate, ranking, excursions,
                        {"split": "fit <=2023-12-31 / validate 2024-2025"})
    rp = f"{REPORT_DIR}/mqr_exit_replay_{ts}.html"
    with open(rp, "w") as f:
        f.write(html)
    jp = f"{REPORT_DIR}/mqr_exit_replay_{ts}.json"
    with open(jp, "w") as f:
        json.dump({"gate": gate, "ranking": ranking, "entry_sha256": digest,
                   "n_entries": len(entries),
                   "n_price_exits": n_price,
                   "n_rotation_exits": len(entries) - n_price,
                   "mae_median": float(excursions["mae"].median()) if len(excursions) else None,
                   "mfe_median": float(excursions["mfe"].median()) if len(excursions) else None},
                  f, indent=2, default=str)
    print(f"\nWrote {rp}\nWrote {jp}", flush=True)

    if gate["hard_reproduced"] != gate["hard_total"]:
        print("\nGATE DID NOT FULLY PASS — see the mismatch list above.", flush=True)
        return 1
    print("\nGate PASSED.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
