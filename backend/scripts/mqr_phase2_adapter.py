"""Phase 2c: deployment-realistic confirmation through the FULL adapter.

WHY THIS IS A DIFFERENT MEASUREMENT
----------------------------------
Phase 2a/2b fixed the entry set (2,013 frozen positions) and replayed only exits:
deterministic, no chaos, but NOT how the strategy deploys. The live path runs
StrategyBacktestAdapter, which re-decides entries every day. A lever that exits
later frees slots later, so the taken-entry set drifts -- the entry is NOT fixed
here, by construction, and cannot be.

Therefore this uses MULTI-START: the same candidate rules across several start
dates, compared as paired per-start deltas against the baseline. One run per
config would be meaningless (a 0.30%/yr input once moved CAGR by +32 points).

So there are two numbers for each rule and they are not interchangeable:
  frozen-entry (2a/2b)  what the exit rule is worth on a fixed trade population
  adapter multi-start   what it is worth after entries are allowed to drift

Usage: cd backend && ./venv/bin/python scripts/mqr_phase2_adapter.py
"""
import json
import os
import statistics as st
import sys

import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(".")), ".env"))
sys.path.insert(0, ".")

from app.services.exit_replay.engine import OFF  # noqa: E402
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter  # noqa: E402
from app.services.strategies.momentum_quality_rotation import (  # noqa: E402
    MomentumQualityRotation,
)

END = "2026-09-28"
CAPITAL = 100_000.0
STARTS = ["2020-01-01", "2020-07-01", "2021-01-01", "2021-07-01",
          "2022-01-01", "2023-01-01"]

VARIANTS = {
    "baseline": {},
    "conservative_trail30_act20_tpoff": {
        "trailing_stop": 0.30, "trailing_stop_activation": 0.20, "take_profit": OFF},
    "aggressive_trailoff_act20_tpoff": {
        "trailing_stop": OFF, "trailing_stop_activation": 0.20, "take_profit": OFF},
}


def run(overrides, start):
    s = StrategyBacktestAdapter(
        MomentumQualityRotation(**overrides)
    ).run(as_of=start, end=END, capital=CAPITAL)["summary"]
    return {"cagr": s["cagr_pct"], "return": s["total_return_pct"],
            "sharpe": s["sharpe_ratio"], "max_dd": s["max_drawdown_pct"],
            "trades": s["total_trades"]}


grid = {}
for start in STARTS:
    for name, ov in VARIANTS.items():
        print(f"Running {name} from {start}...", flush=True)
        try:
            grid[f"{start}|{name}"] = run(ov, start)
        except Exception as e:
            grid[f"{start}|{name}"] = {"error": f"{type(e).__name__}: {e}"}
        r = grid[f"{start}|{name}"]
        print("  " + ("ERROR " + r["error"] if "error" in r else
                      f"cagr {r['cagr']:7.2f}%  sharpe {r['sharpe']:5.2f}  "
                      f"maxdd {r['max_dd']:5.1f}%  trades {r['trades']}"), flush=True)

with open("/tmp/mqr_phase2_adapter.json", "w") as f:
    json.dump(grid, f, indent=2, default=str)

print("\n" + "=" * 78)
print("ADAPTER MULTI-START (entries NOT fixed -- slot occupancy drifts)")
print("=" * 78)
print(f"{'variant':<34}{'cagr med':>10}{'sharpe med':>12}{'maxdd med':>11}")
print("-" * 67)
for name in VARIANTS:
    rows = [grid[f"{s}|{name}"] for s in STARTS if "error" not in grid[f"{s}|{name}"]]
    print(f"{name:<34}{st.median([r['cagr'] for r in rows]):>9.2f}%"
          f"{st.median([r['sharpe'] for r in rows]):>12.2f}"
          f"{st.median([r['max_dd'] for r in rows]):>10.1f}%")

for name in VARIANTS:
    if name == "baseline":
        continue
    dc = [grid[f"{s}|{name}"]["cagr"] - grid[f"{s}|baseline"]["cagr"] for s in STARTS]
    dd = [grid[f"{s}|{name}"]["max_dd"] - grid[f"{s}|baseline"]["max_dd"] for s in STARTS]
    ds = [grid[f"{s}|{name}"]["sharpe"] - grid[f"{s}|baseline"]["sharpe"] for s in STARTS]
    print(f"\n  {name} vs baseline (paired, same start dates)")
    for s, a, b, c in zip(STARTS, dc, dd, ds):
        print(f"    {s}   cagr {a:+7.2f}   maxdd {b:+6.2f}   sharpe {c:+5.2f}")
    print(f"    -> cagr   median {st.median(dc):+6.2f}, wins {sum(1 for x in dc if x>0)}/{len(dc)}, "
          f"spread {min(dc):+.2f} to {max(dc):+.2f}")
    print(f"    -> maxdd  median {st.median(dd):+6.2f}, better on {sum(1 for x in dd if x<0)}/{len(dd)}")
    print(f"    -> sharpe median {st.median(ds):+5.2f}, better on {sum(1 for x in ds if x>0)}/{len(ds)}")
print("\nSaved /tmp/mqr_phase2_adapter.json")
