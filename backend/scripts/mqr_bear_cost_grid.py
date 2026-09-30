"""bear_exposure x transaction-cost grid for Momentum Quality Rotation.

Two changes landed before this sweep:

1. A transaction-cost model (cost_bps per side). The adapter previously filled
   at the next open with NO costs, overstating every return on this stack by
   ~1.2%/yr at 5bps and ~4.9%/yr at 20bps given ~24x annual portfolio turnover.
2. bear_exposure was 0.50 (half size when SPY < SMA200). The request was to
   raise it to 0.75 -- i.e. stay MORE invested in downtrends.

Running the grid rather than a single config because the two questions interact:
raising bear exposure should help return but hurt drawdown, and costs scale with
turnover, so the ranking could flip once costs are charged.

Method: one full-period backtest per cell, identical window and capital.
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

BEAR_LEVELS = [0.50, 0.75, 1.00]
COST_LEVELS = [0.0, 5.0, 10.0]


def run_config(overrides):
    strategy = MomentumQualityRotation(**overrides)
    result = StrategyBacktestAdapter(strategy).run(
        as_of=AS_OF, end=END, capital=CAPITAL
    )
    s = result["summary"]
    return {
        "return": s["total_return_pct"],
        "cagr": s["cagr_pct"],
        "spy_cagr": s["spy_cagr_pct"],
        "alpha": s["alpha_per_year_pct"],
        "sharpe": s["sharpe_ratio"],
        "max_dd": s["max_drawdown_pct"],
        "trades": s["total_trades"],
        "trades_per_year": s["trades_per_year"],
        "win_rate": s["win_rate"],
        "pf": s["profit_factor"],
        "exit_reasons": s["exit_reasons"],
    }


results = {}
for bear in BEAR_LEVELS:
    for cost in COST_LEVELS:
        name = f"bear_{bear:.2f}__cost_{cost:.0f}bps"
        print(f"Running {name}...", flush=True)
        try:
            results[name] = run_config(
                {"bear_exposure": bear, "cost_bps": cost}
            )
        except Exception as e:
            results[name] = {"error": f"{type(e).__name__}: {e}"}
        r = results[name]
        if "error" in r:
            print(f"  ERROR {r['error']}", flush=True)
        else:
            print(
                f"  ret {r['return']:.1f}%  cagr {r['cagr']:.1f}%  "
                f"sharpe {r['sharpe']:.2f}  maxdd {r['max_dd']:.1f}%  "
                f"trades {r['trades']}  pf {r['pf']:.2f}",
                flush=True,
            )

for cost in COST_LEVELS:
    print(f"\n=== bear_exposure comparison at {cost:.0f}bps per side ===")
    hdr = (
        f"{'variant':<10}{'ret%':>9}{'cagr%':>8}{'alpha%':>9}{'sharpe':>8}"
        f"{'maxdd%':>8}{'trades':>8}{'trd/yr':>8}{'win%':>7}{'pf':>6}"
    )
    print(hdr)
    print("-" * len(hdr))
    for bear in BEAR_LEVELS:
        name = f"bear_{bear:.2f}__cost_{cost:.0f}bps"
        r = results.get(name)
        if not r or "error" in r:
            print(f"{name:<10} ERROR")
            continue
        print(
            f"{'bear ' + format(bear, '.2f'):<10}{r['return']:>9.1f}{r['cagr']:>8.1f}"
            f"{r['alpha']:>9.1f}{r['sharpe']:>8.2f}{r['max_dd']:>8.1f}"
            f"{r['trades']:>8}{r['trades_per_year']:>8.1f}{r['win_rate']:>7.1f}"
            f"{r['pf']:>6.2f}"
        )

print("\n=== cost sensitivity of the baseline (bear 0.50) ===")
base = results["bear_0.50__cost_0bps"]
for cost in COST_LEVELS:
    r = results[f"bear_0.50__cost_{cost:.0f}bps"]
    dcagr = r["cagr"] - base["cagr"]
    print(f"  {cost:>4.0f}bps -> CAGR {r['cagr']:6.2f}%  ({dcagr:+.2f} pts)")

out = "/tmp/mqr_bear_cost_grid.json"
with open(out, "w") as f:
    json.dump(results, f, indent=2)
print(f"\nSaved to {out}")
