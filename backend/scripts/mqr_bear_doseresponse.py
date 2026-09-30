"""bear_exposure dose-response for MQR (lower exposure).

The 0.75 test (mqr_bear_multistart.py) found return differences indistinguishable
from chaos but max drawdown consistently WORSE on 5/6 starts at higher exposure.
So the drawdown evidence points the other way: test LOWER exposure.

Design: 4 levels x the same 6 start dates, paired. A monotonic response --
drawdown improving steadily as exposure falls -- is a dose-response signal and
therefore real evidence; an erratic one is more path chaos.

bear 0.00 (full cash when SPY < SMA200) is included because the strategy's own
history claims full cash "misses the recovery" (skill empirical notes, on the
GCVR base). This tests that claim on MQR's base.

Length-normalized metrics only (starts differ, so raw totals are not comparable).
Cost held at 0; cost drag is measured analytically, not by re-simulation.

Raw grid is saved BEFORE analysis so a late crash cannot lose the runs.
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
    "2022-01-01",  # bear market
    "2023-01-01",  # recovery
]
BEARS = [0.00, 0.25, 0.35, 0.50]  # 0.50 = current baseline
BASELINE = 0.50


def key(start, bear):
    return f"{start}|{bear:.2f}"


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
    }


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
        print(
            f"  ERROR {r['error']}" if "error" in r else
            f"  cagr {r['cagr']:7.2f}%  sharpe {r['sharpe']:5.2f}  "
            f"maxdd {r['max_dd']:5.1f}%  trd/yr {r['trades_per_year']:.1f}",
            flush=True,
        )

with open("/tmp/mqr_bear_doseresponse.json", "w") as f:
    json.dump(grid, f, indent=2)
print("\nSaved raw grid to /tmp/mqr_bear_doseresponse.json", flush=True)

print("\n=== per-level spread across start dates ===")
print(f"{'bear':>6}{'cagr med':>10}{'cagr min':>10}{'cagr max':>10}{'sharpe med':>12}{'maxdd med':>11}")
print("-" * 60)
for b in BEARS:
    v = [grid[key(s, b)] for s in STARTS if "error" not in grid[key(s, b)]]
    c = [x["cagr"] for x in v]
    print(f"{b:>6.2f}{st.median(c):>9.2f}%{min(c):>9.2f}%{max(c):>9.2f}%"
          f"{st.median([x['sharpe'] for x in v]):>12.2f}"
          f"{st.median([x['max_dd'] for x in v]):>10.1f}%")

print(f"\n=== PAIRED deltas vs bear {BASELINE:.2f} (same start dates) ===")
for b in BEARS:
    if b == BASELINE:
        continue
    dc = [grid[key(s, b)]["cagr"] - grid[key(s, BASELINE)]["cagr"] for s in STARTS]
    dd = [grid[key(s, b)]["max_dd"] - grid[key(s, BASELINE)]["max_dd"] for s in STARTS]
    ds = [grid[key(s, b)]["sharpe"] - grid[key(s, BASELINE)]["sharpe"] for s in STARTS]
    print(f"\n  bear {b:.2f} vs {BASELINE:.2f}:")
    for s, a, m, h in zip(STARTS, dc, dd, ds):
        print(f"    {s}   cagr {a:+7.2f}   maxdd {m:+6.2f}   sharpe {h:+5.2f}")
    print(f"    -> cagr  : median {st.median(dc):+6.2f}, wins {sum(1 for x in dc if x > 0)}/{len(dc)}, "
          f"spread {min(dc):+.2f} to {max(dc):+.2f}")
    print(f"    -> maxdd : median {st.median(dd):+6.2f}, IMPROVED on {sum(1 for x in dd if x < 0)}/{len(dd)}")
    print(f"    -> sharpe: median {st.median(ds):+5.2f}, better on {sum(1 for x in ds if x > 0)}/{len(ds)}")

print("\n=== dose-response monotonicity (is drawdown ordered by exposure?) ===")
med_dd = [st.median([grid[key(s, b)]["max_dd"] for s in STARTS]) for b in BEARS]
med_cagr = [st.median([grid[key(s, b)]["cagr"] for s in STARTS]) for b in BEARS]
for b, d, c in zip(BEARS, med_dd, med_cagr):
    print(f"  bear {b:.2f}  median maxdd {d:5.1f}%   median cagr {c:6.2f}%")
mono = all(med_dd[i] <= med_dd[i + 1] for i in range(len(med_dd) - 1))
print(f"  drawdown strictly ordered by exposure (lower exposure -> lower drawdown): {mono}")
