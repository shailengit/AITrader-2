"""Diagnostic: is MQR's single-run result path-dependent?

The bear x cost grid produced an IMPOSSIBLE result: 5bps per side gave a HIGHER
CAGR (70.42%) than costless fills (64.18%), and 10bps collapsed to 53.54%. Costs
cannot monotonically raise returns, and 5bps is only ~1.22%/yr of drag at this
turnover, so it cannot explain a +6 point CAGR swing.

The cost model itself checks out (sells deduct proceeds, buys deduct cost+fee,
round-trip P&L includes both fees). The suspicion is trajectory dependence:

    fee -> less cash -> lower portfolio_value -> smaller target_value
        -> int() truncation flips a share count -> a different path entirely

If that is the mechanism, then even a NEGLIGIBLE cost (0.1bps, ~0.0002%/yr)
will swing the result by whole CAGR points, and the strategy's single-run
comparisons are dominated by path chaos rather than by the lever.

A repeat of the 5bps cell also checks the harness is deterministic -- if it does
not reproduce exactly, the swings are run-to-run noise instead.
"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(".")), ".env"))
sys.path.insert(0, ".")

from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation

AS_OF = "2020-01-01"
END = "2026-09-28"
CAPITAL = 100_000.0

# bear 0.50 fixed; vary cost from negligible to real
COSTS = [0.0, 0.1, 0.5, 1.0, 2.0, 5.0, 5.0]  # last entry repeats 5bps


def run(cost):
    strategy = MomentumQualityRotation(bear_exposure=0.50, cost_bps=cost)
    s = StrategyBacktestAdapter(strategy).run(
        as_of=AS_OF, end=END, capital=CAPITAL
    )["summary"]
    return {
        "cagr": s["cagr_pct"],
        "return": s["total_return_pct"],
        "final": s["final_portfolio"],
        "sharpe": s["sharpe_ratio"],
        "max_dd": s["max_drawdown_pct"],
        "trades": s["total_trades"],
    }


results = []
for i, cost in enumerate(COSTS):
    label = f"cost={cost}bps" + (" (repeat)" if i == len(COSTS) - 1 else "")
    print(f"Running {label}...", flush=True)
    r = run(cost)
    r["cost_bps"] = cost
    r["label"] = label
    results.append(r)
    print(
        f"  cagr {r['cagr']:6.2f}%  ret {r['return']:8.1f}%  "
        f"final ${r['final']:,.0f}  sharpe {r['sharpe']:.2f}  trades {r['trades']}",
        flush=True,
    )

print("\n=== monotonicity check (bear 0.50) ===")
print(f"{'cost/side':>12}{'expected drag':>15}{'CAGR':>9}{'delta vs 0':>12}{'trades':>8}")
print("-" * 56)
base = results[0]["cagr"]
for r in results:
    drag = 60.5 * r["cost_bps"] / 10_000 * 100  # turnover/yr * bps, as %
    print(
        f"{r['label']:>12}{drag:>14.2f}%{r['cagr']:>8.2f}%"
        f"{r['cagr'] - base:>+11.2f}{r['trades']:>8}"
    )

reps = [r for r in results if r["label"].endswith("(repeat)")]
orig = [r for r in results if r["label"] == "cost=5.0bps"]
if reps and orig:
    same = reps[0]["cagr"] == orig[0]["cagr"]
    print(f"\ndeterminism: 5bps reproduced exactly = {same}")
    if not same:
        print(f"  {orig[0]['cagr']} vs {reps[0]['cagr']}  -> run-to-run NOISE, not path dependence")

with open("/tmp/mqr_cost_monotonicity.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nSaved to /tmp/mqr_cost_monotonicity.json")
