"""Trailing-stop activation threshold sweep for Momentum Quality Rotation.

Why
---
The min_hold_days sweep (mqr_minhold_sweep.py) showed rotation is NOT the
turnover lever: suppressing rotation exits just handed them to the 12% trailing
stop, which is already 50.5% of all exits. Total turnover fell only ~10%.

A 12% trail on a position that never got going is simply a stop loss on ordinary
volatility -- the position exits and gets re-bought. This sweep arms the trail
only once the position has been up by `activation` at its PEAK, which should cut
the trailing-stop bucket without weakening the trail for genuine winners.

Thresholds chosen around the observed noise floor: MQR's 14-day return std
filter admits up to 5% daily vol, so a +5% arm is reachable in days and a +10%
arm requires a real move.

Method
------
One full-period backtest per config -- deterministic and directly comparable.
Same window, same capital as the min_hold sweep so the two are comparable.
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
    "baseline_armed_at_entry": {},                                   # activation 0.0
    "arm_at_+5pct": {"trailing_stop_activation": 0.05},
    "arm_at_+10pct": {"trailing_stop_activation": 0.10},
    "arm_at_+15pct": {"trailing_stop_activation": 0.15},
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

print("\n=== LEVER COMPARISON (trailing_stop_activation) ===")
hdr = (
    f"{'variant':<24}{'ret%':>9}{'cagr%':>8}{'alpha%':>9}{'sharpe':>8}"
    f"{'maxdd%':>8}{'trades':>8}{'trd/yr':>8}{'win%':>7}{'pf':>6}"
)
print(hdr)
print("-" * len(hdr))
for name, r in results.items():
    if "error" in r:
        print(f"{name:<24} ERROR: {r['error']}")
        continue
    print(
        f"{name:<24}{r['return']:>9.1f}{r['cagr']:>8.1f}{r['alpha']:>9.1f}"
        f"{r['sharpe']:>8.2f}{r['max_dd']:>8.1f}{r['trades']:>8}"
        f"{r['trades_per_year']:>8.1f}{r['win_rate']:>7.1f}{r['pf']:>6.2f}"
    )

print("\n=== EXIT MIX ===")
for name, r in results.items():
    if "error" in r:
        continue
    total = sum(r["exit_reasons"].values()) or 1
    mix = ", ".join(
        f"{k} {v} ({100 * v / total:.1f}%)"
        for k, v in sorted(r["exit_reasons"].items(), key=lambda x: -x[1])
    )
    print(f"  {name:<24} {mix}")

out = "/tmp/mqr_activation_sweep.json"
with open(out, "w") as f:
    json.dump(results, f, indent=2)
print(f"\nSaved to {out}")
