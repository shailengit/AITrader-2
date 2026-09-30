"""Phase 2b: combinations of the one-lever winners, selected on FIT only.

Spec 8 asks for combinations of the winners after the one-at-a-time sweep. The
honest protocol is unchanged: rank the combos on the FIT bucket, then report the
fit-selected one on the HELD-OUT validate bucket, which the selection never saw.

Note `trail_off` (no trailing stop at all) is the fit-winner among singles, but it
removes protection entirely and sits on a plateau (0.25 / 0.30 / off are within
~2% of each other on both buckets). The combos below keep a stop, so they are a
less extreme extrapolation; both are reported.

Usage: cd backend && ./venv/bin/python scripts/mqr_phase2_combo.py
"""
import json
import os
import sys

import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(".")), ".env"))
sys.path.insert(0, ".")

from app.services.exit_replay.engine import ExitPolicy, OFF  # noqa: E402
from app.services.exit_replay.entry_set import load_entry_set  # noqa: E402
from app.services.exit_replay.evaluate import (  # noqa: E402
    evaluate_policy,
    price_exit_mask,
    summarise,
)
from app.services.exit_replay.policies import POLICY_GRID  # noqa: E402
from app.services.exit_replay.price_panel import PricePanel  # noqa: E402

ENTRY_PATH = "data/mqr_entry_set.csv"

# Combinations, keeping a trailing stop in most so the result is not an
# extrapolation to "no protection at all".
COMBOS = {
    "base": ExitPolicy(),
    "trail30+act20": ExitPolicy(trailing_stop=0.30, trailing_stop_activation=0.20),
    "trail25+act20": ExitPolicy(trailing_stop=0.25, trailing_stop_activation=0.20),
    "trail30+act20+tp75": ExitPolicy(trailing_stop=0.30, trailing_stop_activation=0.20,
                                     take_profit=0.75),
    "trail30+act20+tp_off": ExitPolicy(trailing_stop=0.30, trailing_stop_activation=0.20,
                                       take_profit=OFF),
    "trail30+act20+time_off": ExitPolicy(trailing_stop=0.30, trailing_stop_activation=0.20,
                                         time_stop_days=OFF),
    "trail30+act20+tp_off+time_off": ExitPolicy(trailing_stop=0.30,
                                                trailing_stop_activation=0.20,
                                                take_profit=OFF, time_stop_days=OFF),
    "trail_off+act20": ExitPolicy(trailing_stop=OFF, trailing_stop_activation=0.20),
    "trail_off+act20+tp_off": ExitPolicy(trailing_stop=OFF, trailing_stop_activation=0.20,
                                         take_profit=OFF),
}


def main() -> int:
    entries = load_entry_set(ENTRY_PATH)
    panel, mask = PricePanel(), None
    mask = price_exit_mask(entries)
    print(f"frozen entries: {len(entries):,} positions", flush=True)

    res = {}
    for name, policy in {**COMBOS, "singles:trail_0.30": POLICY_GRID["trail_0.30"],
                         "singles:trail_off": POLICY_GRID["trail_off"],
                         "singles:act_0.20": POLICY_GRID["act_0.20"]}.items():
        pt = evaluate_policy(entries, panel, policy, price_exit=mask)
        res[name] = {
            "fit": summarise(pt[pt["bucket"] == "fit"]),
            "validate": summarise(pt[pt["bucket"] == "validate"]),
        }
        print(f"  {name:<30} fit {res[name]['fit']['sum_pnl_pct']:>8.3f}  "
              f"val {res[name]['validate']['sum_pnl_pct']:>8.3f}", flush=True)

    combos_only = list(COMBOS)
    fit_rank = sorted(combos_only, key=lambda n: -(res[n]["fit"]["sum_pnl_pct"] or -9e9))
    val_rank = sorted(combos_only, key=lambda n: -(res[n]["validate"]["sum_pnl_pct"] or -9e9))
    winner = fit_rank[0]
    b_fit = res["base"]["fit"]["sum_pnl_pct"]
    b_val = res["base"]["validate"]["sum_pnl_pct"]

    print("\n" + "=" * 78)
    print("COMBINATIONS — selected on FIT (1,360 positions), confirmed on validate (545)")
    print("=" * 78)
    print(f"  baseline (current MQR rules): fit {b_fit:.3f}  validate {b_val:.3f}\n")
    print(f"  {'combo':<30} {'fit':>9} {'vs base':>9} {'validate':>10} {'vs base':>9}")
    for n in fit_rank:
        f, v = res[n]["fit"]["sum_pnl_pct"], res[n]["validate"]["sum_pnl_pct"]
        star = "  <-- fit-selected" if n == winner else ""
        print(f"  {n:<30} {f:>9.3f} {100*(f-b_fit)/abs(b_fit):>+8.1f}% "
              f"{v:>10.3f} {100*(v-b_val)/abs(b_val):>+8.1f}%{star}")

    wf, wv = res[winner]["fit"]["sum_pnl_pct"], res[winner]["validate"]["sum_pnl_pct"]
    print(f"\n  fit-selected combo : {winner}")
    print(f"    fit      {100*(wf-b_fit)/abs(b_fit):+.1f}%   validate {100*(wv-b_val)/abs(b_val):+.1f}%")
    print(f"    ranks #{val_rank.index(winner)+1} of {len(combos_only)} on held-out validate")

    with open("/tmp/mqr_phase2_combo.json", "w") as f:
        json.dump({"winner": winner, "validate_rank": val_rank.index(winner) + 1,
                   "results": {n: {"fit": res[n]["fit"]["sum_pnl_pct"],
                                   "validate": res[n]["validate"]["sum_pnl_pct"]}
                               for n in res}}, f, indent=2, default=str)
    print("\nSaved /tmp/mqr_phase2_combo.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
