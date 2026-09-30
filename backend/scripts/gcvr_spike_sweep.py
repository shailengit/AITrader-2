"""Volume spike-window sweep for Golden Cross Volume Rotation.

Base: EMA10/EMA200 crossover (the locked-in winner).
Reference baseline: vol 1.0x cross-day over 50-day avg = 766.5% ret.

Tests the NEW volume confirmation mode: volume was 1.5x above the 10-day
average volume at ANY point in a recent window (vol_spike_window days),
instead of requiring the spike exactly on the cross day.

Sweeps the spike window (how many days back to look for the spike).
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

# Reference: original best (EMA10/200, vol 1.0x cross-day over 50-day avg)
REFERENCE = {"volume_mult": 1.0, "vol_mode": "cross_day", "vol_avg_window": 50, "ema_fast": 10, "ema_slow": 200}

# Spike-window variants: 1.5x over 10-day avg, spike anywhere in the window
VARIANTS = {
    "ref_1.0x_crossday_50d": REFERENCE,
    "spike_1.5x_10d_win3": {"vol_mode": "spike_window", "volume_mult": 1.5, "vol_avg_window": 10, "vol_spike_window": 3, "ema_fast": 10, "ema_slow": 200},
    "spike_1.5x_10d_win5": {"vol_mode": "spike_window", "volume_mult": 1.5, "vol_avg_window": 10, "vol_spike_window": 5, "ema_fast": 10, "ema_slow": 200},
    "spike_1.5x_10d_win7": {"vol_mode": "spike_window", "volume_mult": 1.5, "vol_avg_window": 10, "vol_spike_window": 7, "ema_fast": 10, "ema_slow": 200},
    "spike_1.5x_10d_win10": {"vol_mode": "spike_window", "volume_mult": 1.5, "vol_avg_window": 10, "vol_spike_window": 10, "ema_fast": 10, "ema_slow": 200},
    # Also test 2.0x and 1.2x multipliers at win5 for sensitivity
    "spike_2.0x_10d_win5": {"vol_mode": "spike_window", "volume_mult": 2.0, "vol_avg_window": 10, "vol_spike_window": 5, "ema_fast": 10, "ema_slow": 200},
    "spike_1.2x_10d_win5": {"vol_mode": "spike_window", "volume_mult": 1.2, "vol_avg_window": 10, "vol_spike_window": 5, "ema_fast": 10, "ema_slow": 200},
}

def run_config(overrides):
    strat = GoldenCrossVolumeRotation(**overrides)
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
print(f"{'variant':<24} {'ret%':>8} {'cagr%':>7} {'alpha%':>7} {'sharpe':>6} {'maxdd%':>6} {'trades':>6} {'win%':>5} {'pf':>5}")
for name, r in results.items():
    if "error" in r:
        print(f"{name:<24} ERROR: {r['error']}")
        continue
    print(f"{name:<24} {r['return']:>8.1f} {r['cagr']:>7.1f} {r['alpha']:>7.1f} {r['sharpe']:>6.2f} {r['max_dd']:>6.1f} {r['trades']:>6} {r['win_rate']:>5.1f} {r['pf']:>5.2f}")

with open("/tmp/gcvr_spike_sweep.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nSaved to /tmp/gcvr_spike_sweep.json")
