"""Phase 4 experiment sweep for Golden Cross Volume Rotation.

Tests the key levers against the baseline (which underperformed SPY):
  - bear_exposure: 0.0 (baseline) vs 0.5 vs 1.0
  - volume_mult: 1.5 (baseline) vs 1.0 (drop volume confirmation) vs 0.0 (no volume filter)
  - hard_stop_loss: 0.10 (baseline) vs 0.0 (drop hard stop)
  - trailing_stop: 0.20 (baseline) vs 0.25 vs 0.30
  - take_profit: 0.25 (baseline) vs 0.30 vs 0.50
  - time_stop_days: 90 (baseline) vs 120
  - min_hold_days: 10 (baseline) vs 7 vs 14
  - hold_rank: 10 (baseline) vs 15 vs 20

Each config is run on the full period 2020-01-01 to 2026-09-04.
"""
import os, sys, json, warnings
warnings.filterwarnings("ignore")
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath('.')), '.env'))
sys.path.insert(0, '.')

from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.golden_cross_volume_rotation import GoldenCrossVolumeRotation

AS_OF = "2020-01-01"
END = "2026-09-04"
CAPITAL = 100_000.0

# Baseline config (matches the current spec)
BASELINE = {
    "bear_exposure": 0.0,
    "volume_mult": 1.5,
    "hard_stop_loss": 0.10,
    "trailing_stop": 0.20,
    "take_profit": 0.25,
    "time_stop_days": 90,
    "min_hold_days": 10,
    "hold_rank": 10,
}

# One-at-a-time variations
VARIANTS = {
    "baseline": {},
    "bear_0.5": {"bear_exposure": 0.5},
    "bear_1.0": {"bear_exposure": 1.0},
    "vol_1.0": {"volume_mult": 1.0},
    "vol_0.0": {"volume_mult": 0.0},
    "no_hardstop": {"hard_stop_loss": 0.0},
    "trail_0.25": {"trailing_stop": 0.25},
    "trail_0.30": {"trailing_stop": 0.30},
    "tp_0.30": {"take_profit": 0.30},
    "tp_0.50": {"take_profit": 0.50},
    "time_120": {"time_stop_days": 120},
    "minhold_7": {"min_hold_days": 7},
    "minhold_14": {"min_hold_days": 14},
    "holdrank_15": {"hold_rank": 15},
    "holdrank_20": {"hold_rank": 20},
}

def run_config(overrides):
    cfg = dict(BASELINE)
    cfg.update(overrides)
    strat = GoldenCrossVolumeRotation(**cfg)
    adapter = StrategyBacktestAdapter(strat)
    result = adapter.run(as_of=AS_OF, end=END, capital=CAPITAL)
    s = result["summary"]
    return {
        "return": s["total_return_pct"],
        "cagr": s["cagr_pct"],
        "spy_cagr": s["spy_cagr_pct"],
        "alpha": s["alpha_per_year_pct"],
        "sharpe": s["sharpe_ratio"],
        "max_dd": s["max_drawdown_pct"],
        "trades": s["total_trades"],
        "win_rate": s["win_rate"],
        "pf": s["profit_factor"],
    }

results = {}
for name, overrides in VARIANTS.items():
    print(f"Running {name}...", flush=True)
    try:
        results[name] = run_config(overrides)
    except Exception as e:
        results[name] = {"error": str(e)}
    print(f"  {name}: {results[name]}", flush=True)

print("\n=== SUMMARY ===")
print(f"{'variant':<14} {'ret%':>8} {'cagr%':>7} {'spy%':>6} {'alpha%':>7} {'sharpe':>6} {'maxdd%':>6} {'trades':>6} {'win%':>5} {'pf':>5}")
for name, r in results.items():
    if "error" in r:
        print(f"{name:<14} ERROR: {r['error']}")
        continue
    print(f"{name:<14} {r['return']:>8.1f} {r['cagr']:>7.1f} {r['spy_cagr']:>6.1f} {r['alpha']:>7.1f} {r['sharpe']:>6.2f} {r['max_dd']:>6.1f} {r['trades']:>6} {r['win_rate']:>5.1f} {r['pf']:>5.2f}")

with open("/tmp/gcvr_sweep.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nSaved to /tmp/gcvr_sweep.json")
