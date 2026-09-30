"""Multi-start bear_exposure comparison for MQR.

Why multi-start
---------------
Single-run MQR backtests are path-chaotic: varying only `cost_bps` moved CAGR by
+32 points at a 0.30%/yr drag, with bit-identical reproduction
(scripts/mqr_cost_monotonicity.py). So one run per config cannot decide a lever.

This samples several trajectories by varying the START DATE instead of the
perturbation, and compares each bear level on the SAME start dates (paired), so
market conditions cancel out. The per-start sign count is the signal test:
if 0.75 wins on 5-6 of 6 starts it is real; 3 of 6 means chaos.

Metrics are length-normalized (CAGR, alpha/yr, trades/yr). Runs ending on the
same date but starting on different ones have different lengths, so raw
`total_return_pct` and `total_trades` would not be comparable.

Cost is held at 0 for comparability with the published baseline; cost drag is
measured analytically (turnover x bps) rather than by re-simulation, which would
change the trajectory.
"""
import json
import os
import statistics as st
import sys
import warnings

warnings.filterwarnings("ignore")
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(".")), ".env"))
sys.path.insert(0, ".")

from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation

END = "2026-09-28"
CAPITAL = 100_000.0

STARTS = [
    "2020-01-01",  # pre-COVID
    "2020-07-01",  # post-COVID recovery
    "2021-01-01",  # bull
    "2021-07-01",  # bull peak
    "2022-01-01",  # bear market -- most relevant to bear_exposure
    "2023-01-01",  # recovery
]
BEARS = [0.50, 0.75, 1.00]


def run(bear, start):
    s = StrategyBacktestAdapter(
        MomentumQualityRotation(bear_exposure=bear, cost_bps=0.0)
    ).run(as_of=start, end=END, capital=CAPITAL)["summary"]
    return {
        "cagr": s["cagr_pct"],
        "alpha": s["alpha_per_year_pct"],
        "sharpe": s["sharpe_ratio"],
        "max_dd": s["max_drawdown_pct"],
        "trades_per_year": s["trades_per_year"],
        "years": s["num_years"],
    }


def key(start, bear):
    """Single source of truth for grid keys -- f'{bear}' turns 0.50 into '0.5'."""
    return f"{start}|{bear:.2f}"


grid = {}
for start in STARTS:
    for bear in BEARS:
        k = key(start, bear)
        print(f"Running bear={bear} start={start}...", flush=True)
        try:
            grid[k] = run(bear, start)
        except Exception as e:
            grid[k] = {"error": f"{type(e).__name__}: {e}"}
        r = grid[k]
        if "error" in r:
            print(f"  ERROR {r['error']}", flush=True)
        else:
            print(
                f"  cagr {r['cagr']:7.2f}%  alpha {r['alpha']:7.2f}  "
                f"sharpe {r['sharpe']:5.2f}  maxdd {r['max_dd']:5.1f}%  "
                f"trd/yr {r['trades_per_year']:.1f}",
                flush=True,
            )

# Persist BEFORE any analysis so a later crash cannot lose 25 minutes of runs.
with open("/tmp/mqr_bear_multistart.json", "w") as f:
    json.dump(grid, f, indent=2)
print("\nSaved raw grid to /tmp/mqr_bear_multistart.json", flush=True)

print("\n=== per-variant spread across start dates ===")
print(f"{'bear':>6}{'cagr med':>11}{'cagr min':>10}{'cagr max':>10}"
      f"{'sharpe med':>12}{'maxdd med':>11}{'trd/yr med':>12}")
print("-" * 72)
summary = {}
for bear in BEARS:
    rows = [grid[f"{s}|{bear}"] for s in STARTS if "error" not in grid[f"{s}|{bear}"]]
    c = [r["cagr"] for r in rows]
    summary[bear] = {
        "cagr_med": st.median(c), "cagr_min": min(c), "cagr_max": max(c),
        "sharpe_med": st.median([r["sharpe"] for r in rows]),
        "maxdd_med": st.median([r["max_dd"] for r in rows]),
        "tpy_med": st.median([r["trades_per_year"] for r in rows]),
        "n": len(rows),
    }
    s = summary[bear]
    print(f"{bear:>6.2f}{s['cagr_med']:>10.2f}%{s['cagr_min']:>9.2f}%{s['cagr_max']:>9.2f}%"
          f"{s['sharpe_med']:>12.2f}{s['maxdd_med']:>10.1f}%{s['tpy_med']:>12.1f}")

print("\n=== PAIRED deltas vs bear 0.50 (same start date) ===")
print("Signal test: a real edge should win on most starts, not just on average.\n")
for bear in BEARS:
    if bear == 0.50:
        continue
    d_cagr, d_dd, wins = [], [], 0
    print(f"  bear {bear:.2f} vs 0.50:")
    for s in STARTS:
        b = grid[f"{s}|0.50"]
        v = grid[f"{s}|{bear}"]
        if "error" in b or "error" in v:
            continue
        dc = v["cagr"] - b["cagr"]
        dd = v["max_dd"] - b["max_dd"]
        d_cagr.append(dc)
        d_dd.append(dd)
        if dc > 0:
            wins += 1
        print(f"    {s}  cagr {dc:+7.2f} pts   maxdd {dd:+6.2f} pts")
    if d_cagr:
        print(f"    -> median cagr delta {st.median(d_cagr):+.2f} pts, "
              f"median maxdd delta {st.median(d_dd):+.2f} pts, "
              f"wins {wins}/{len(d_cagr)}")
        print(f"    -> spread of cagr deltas: {min(d_cagr):+.2f} to {max(d_cagr):+.2f} "
              f"(if this dwarfs the median, it's noise)\n")

with open("/tmp/mqr_bear_multistart.json", "w") as f:
    json.dump({"grid": grid, "summary": summary}, f, indent=2)
print("Saved to /tmp/mqr_bear_multistart.json")
