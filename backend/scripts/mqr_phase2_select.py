"""Phase 2: select an exit rule on FIT, confirm on a held-out bucket.

Phase 1 ranked policies by validate-bucket P&L, so validate was contaminated by
selection. This re-does it honestly:

  1. SELECT   rank the 27 policies on the FIT bucket (2020-2023) alone.
  2. CONFIRM  take the single fit-selected winner and measure it on the VALIDATE
              bucket (2024-2025), which the selection never touched.
  3. SHAPE    check the DOSE-RESPONSE per lever family in both buckets. A monotone
              response to a lever is far more robust evidence than an argmax pick,
              because it cannot be produced by picking the luckiest single config.

Entries are FROZEN, so this is deterministic: the same stocks on the same dates,
only the lever varies (the user's standing A/B rule).

Usage: cd backend && ./venv/bin/python scripts/mqr_phase2_select.py
"""
import json
import os
import sys

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
from app.services.exit_replay.policies import POLICY_GRID  # noqa: E402
from app.services.exit_replay.price_panel import PricePanel  # noqa: E402

ENTRY_PATH = "data/mqr_entry_set.csv"
# Each family listed TIGHTEST -> LOOSEST, with the numeric lever value so a rank
# correlation can be computed. "off" is mapped to a value beyond the loosest
# setting in each family. The previous version listed them in the opposite order
# while labelling it "least -> most permissive", so its monotonicity flags were
# computed against the wrong direction and read False for a real dose-response.
LEVER_FAMILIES = {
    "trailing stop (tight -> none)": [
        ("0.08", 0.08, "trail_0.08"), ("0.10", 0.10, "trail_0.10"),
        ("0.12 base", 0.12, "baseline"), ("0.15", 0.15, "trail_0.15"),
        ("0.20", 0.20, "trail_0.20"), ("0.25", 0.25, "trail_0.25"),
        ("0.30", 0.30, "trail_0.30"), ("off", 1.00, "trail_off"),
    ],
    "trailing activation (immediate -> late)": [
        ("0.00 base", 0.00, "act_off"), ("0.05", 0.05, "act_0.05"),
        ("0.10", 0.10, "act_0.10"), ("0.15", 0.15, "act_0.15"),
        ("0.20", 0.20, "act_0.20"),
    ],
    "take profit (tight -> none)": [
        ("0.25", 0.25, "tp_0.25"), ("0.35", 0.35, "tp_0.35"),
        ("0.50 base", 0.50, "baseline"), ("0.75", 0.75, "tp_0.75"),
        ("1.00", 1.00, "tp_1.00"), ("off", 9.99, "tp_off"),
    ],
    "time stop (short -> none)": [
        ("40", 40, "time_40"), ("60", 60, "time_60"), ("90", 90, "time_90"),
        ("120 base", 120, "baseline"), ("180", 180, "time_180"),
        ("off", 9999, "time_off"),
    ],
    "hard stop (tight -> none)": [
        ("0.10", 0.10, "hard_0.10"), ("0.15", 0.15, "hard_0.15"),
        ("0.20 base", 0.20, "baseline"), ("0.30", 0.30, "hard_0.30"),
        ("off", 9.99, "hard_off"),
    ],
}


def spearman(xs, ys) -> float:
    """Rank correlation without a scipy dependency."""
    rx = pd.Series(xs).rank().tolist()
    ry = pd.Series(ys).rank().tolist()
    return round(float(pd.Series(rx).corr(pd.Series(ry))), 3)


def main() -> int:
    if os.path.exists(ENTRY_PATH):
        entries = load_entry_set(ENTRY_PATH)
        print(f"loaded frozen entry set: {len(entries):,} positions", flush=True)
    else:
        entries = extract_entry_set(MQR_STRATEGY_ID)
        print(f"froze {len(entries):,} positions "
              f"(sha256 {freeze_entry_set(entries, ENTRY_PATH)[:16]}…)", flush=True)

    panel = PricePanel()
    mask = price_exit_mask(entries)

    results = {}
    for name, policy in POLICY_GRID.items():
        pt = evaluate_policy(entries, panel, policy, price_exit=mask)
        results[name] = {
            "fit": summarise(pt[pt["bucket"] == "fit"]),
            "validate": summarise(pt[pt["bucket"] == "validate"]),
        }
        print(f"  {name:<12} fit {results[name]['fit'].get('sum_pnl_pct')}  "
              f"val {results[name]['validate'].get('sum_pnl_pct')}", flush=True)

    fit_rank = sorted(POLICY_GRID, key=lambda n: -(results[n]["fit"]["sum_pnl_pct"] or -9e9))
    val_rank = sorted(POLICY_GRID, key=lambda n: -(results[n]["validate"]["sum_pnl_pct"] or -9e9))
    winner = fit_rank[0]

    print("\n" + "=" * 78)
    print("STEP 1 — SELECT on fit only (2020-2023, 1,360 positions)")
    print("=" * 78)
    for i, n in enumerate(fit_rank[:8], 1):
        print(f"  {i}. {n:<12} fit {results[n]['fit']['sum_pnl_pct']:>9.4f}")

    print("\n" + "=" * 78)
    print("STEP 2 — CONFIRM the fit-selected winner on held-out validate")
    print("=" * 78)
    base_fit = results["baseline"]["fit"]["sum_pnl_pct"]
    base_val = results["baseline"]["validate"]["sum_pnl_pct"]
    w_fit = results[winner]["fit"]["sum_pnl_pct"]
    w_val = results[winner]["validate"]["sum_pnl_pct"]
    val_pos = val_rank.index(winner) + 1
    print(f"  winner selected on fit : {winner}")
    print(f"    fit      baseline {base_fit:>9.4f} -> winner {w_fit:>9.4f}  "
          f"({100*(w_fit-base_fit)/abs(base_fit):+.1f}%)")
    print(f"    validate baseline {base_val:>9.4f} -> winner {w_val:>9.4f}  "
          f"({100*(w_val-base_val)/abs(base_val):+.1f}%)")
    print(f"    the winner ranks #{val_pos} of {len(POLICY_GRID)} on validate")
    n_val = results[winner]["validate"]["n_observed"]
    print(f"    (validate n = {n_val}; the selection never saw these trades)")

    print("\n" + "=" * 78)
    print("STEP 3 — DOSE-RESPONSE per family (tightest -> loosest)")
    print("=" * 78)
    shape = {}
    for family, rows in LEVER_FAMILIES.items():
        labels = [r[0] for r in rows]
        nums = [r[1] for r in rows]
        policies = [r[2] for r in rows]
        f = [results[n]["fit"]["sum_pnl_pct"] for n in policies]
        v = [results[n]["validate"]["sum_pnl_pct"] for n in policies]
        rho_f, rho_v = spearman(nums, f), spearman(nums, v)
        agree = (rho_f > 0.7 and rho_v > 0.7)
        shape[family] = {"fit_rho": rho_f, "validate_rho": rho_v,
                         "same_direction": bool(rho_f * rho_v > 0),
                         "labels": labels, "fit": f, "validate": v}
        print(f"\n  {family}")
        print(f"    {'label':>10} {'fit':>10} {'validate':>10}")
        for lb, a, b in zip(labels, f, v):
            print(f"    {lb:>10} {a:>10.3f} {b:>10.3f}")
        print(f"    rank corr with permissiveness: fit rho={rho_f:+.3f}  "
              f"validate rho={rho_v:+.3f}  -> {'LOOSER IS BETTER, both buckets' if agree else 'weak/mixed'}")

    out = {
        "winner_selected_on_fit": winner,
        "winner_validate_rank": val_pos,
        "results": {n: {"fit_sum_pct": results[n]["fit"]["sum_pnl_pct"],
                        "val_sum_pct": results[n]["validate"]["sum_pnl_pct"],
                        "val_n": results[n]["validate"]["n_observed"],
                        "val_censored": results[n]["validate"]["n_censored"]}
                    for n in POLICY_GRID},
        "dose_response": shape,
    }
    with open("/tmp/mqr_phase2_select.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nSaved /tmp/mqr_phase2_select.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
