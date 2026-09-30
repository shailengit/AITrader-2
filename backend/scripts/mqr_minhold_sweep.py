"""Turnover sweep for Momentum Quality Rotation: min_hold_days 14 / 21 / 28.

Audit context
-------------
MQR's sidecar reported 26,891 trades. That was a batch-wide SUM written by
_write_sidecar_meta (100 runs x 269 trades), not churn. Real turnover is ~60
exits per run-year with a ~30-day average holding period, and the exit mix is:

    Trailing Stop (12%)   50.5%
    Rotated Out           34.6%
    Take Profit (+50%)    12.3%
    Time Stop (120d)       2.1%
    Stop Loss (20%)        0.5%

So turnover comes from the tight 12% trailing stop plus rotation. The 20% hard
stop is effectively dead code (a 12% trail from peak always fires first) and
the 120d time stop barely binds.

This sweeps the rotation lever only. Raising min_hold_days should suppress the
34.6% rotation bucket without touching the trailing stop that locks in profit.

Method
------
One full-period backtest per config, same window, same capital -- deterministic
and directly comparable. The 100-run randomized batch measures robustness
across start dates; it is not the right tool for isolating one lever.
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

VARIANTS = {
    "baseline_14": {},                         # current verified baseline
    "minhold_21": {"min_hold_days": 21},
    "minhold_28": {"min_hold_days": 28},
}


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
for name, overrides in VARIANTS.items():
    print(f"Running {name}...", flush=True)
    try:
        results[name] = run_config(overrides)
    except Exception as e:  # keep the sweep going if one config dies
        results[name] = {"error": f"{type(e).__name__}: {e}"}
    print(f"  {name}: {results[name]}", flush=True)

print("\n=== LEVER COMPARISON (min_hold_days) ===")
hdr = f"{'variant':<14}{'ret%':>9}{'cagr%':>8}{'alpha%':>9}{'sharpe':>8}{'maxdd%':>8}{'trades':>8}{'trd/yr':>8}{'win%':>7}{'pf':>6}"
print(hdr)
print("-" * len(hdr))
for name, r in results.items():
    if "error" in r:
        print(f"{name:<14} ERROR: {r['error']}")
        continue
    print(
        f"{name:<14}{r['return']:>9.1f}{r['cagr']:>8.1f}{r['alpha']:>9.1f}"
        f"{r['sharpe']:>8.2f}{r['max_dd']:>8.1f}{r['trades']:>8}"
        f"{r['trades_per_year']:>8.1f}{r['win_rate']:>7.1f}{r['pf']:>6.2f}"
    )

print("\n=== EXIT MIX (does the rotation bucket shrink?) ===")
for name, r in results.items():
    if "error" in r:
        continue
    total = sum(r["exit_reasons"].values()) or 1
    mix = ", ".join(
        f"{k} {v} ({100 * v / total:.1f}%)"
        for k, v in sorted(r["exit_reasons"].items(), key=lambda x: -x[1])
    )
    print(f"  {name:<12} {mix}")

out = "/tmp/mqr_minhold_sweep.json"
with open(out, "w") as f:
    json.dump(results, f, indent=2)
print(f"\nSaved to {out}")
