"""Phase 4 combo sweep for Golden Cross Volume Rotation.

Base config is now the locked-in winner: EMA10/EMA200 crossover + vol_1.0.
Tests exit levers on top of it (each showed promise individually):
  - time_stop_days: 90 (base) vs 120
  - take_profit: 0.25 (base) vs 0.30
  - bear_exposure: 0.0 (base) vs 0.5
  - hard_stop_loss: 0.10 (base) vs 0.0
  - trailing_stop: 0.20 (base) vs 0.25
  - min_hold_days: 10 (base) vs 7
  - hold_rank: 10 (base) vs 15
Plus stacked combos of the best individual levers.
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

# Locked-in base: EMA10/EMA200 + vol_1.0 (defaults now reflect this)
BASE = {}

VARIANTS = {
    "base_EMA10_200": {},
    "time_120": {"time_stop_days": 120},
    "tp_0.30": {"take_profit": 0.30},
    "bear_0.5": {"bear_exposure": 0.5},
    "no_hardstop": {"hard_stop_loss": 0.0},
    "trail_0.25": {"trailing_stop": 0.25},
    "minhold_7": {"min_hold_days": 7},
    "holdrank_15": {"hold_rank": 15},
    # Stacked combos
    "time120_tp30": {"time_stop_days": 120, "take_profit": 0.30},
    "time120_bear05": {"time_stop_days": 120, "bear_exposure": 0.5},
    "tp30_bear05": {"take_profit": 0.30, "bear_exposure": 0.5},
    "time120_tp30_bear05": {"time_stop_days": 120, "take_profit": 0.30, "bear_exposure": 0.5},
}

def run_config(overrides):
    cfg = dict(BASE)
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
print(f"{'variant':<22} {'ret%':>8} {'cagr%':>7} {'alpha%':>7} {'sharpe':>6} {'maxdd%':>6} {'trades':>6} {'win%':>5} {'pf':>5}")
for name, r in results.items():
    if "error" in r:
        print(f"{name:<22} ERROR: {r['error']}")
        continue
    print(f"{name:<22} {r['return']:>8.1f} {r['cagr']:>7.1f} {r['alpha']:>7.1f} {r['sharpe']:>6.2f} {r['max_dd']:>6.1f} {r['trades']:>6} {r['win_rate']:>5.1f} {r['pf']:>5.2f}")

with open("/tmp/gcvr_combo_sweep.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nSaved to /tmp/gcvr_combo_sweep.json")
