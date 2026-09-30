"""Re-verify best config on FIXED code (2008 warmup).

The earlier sweeps (EMA10/200 = 766.5%) were measured on the unfixed code
(2018 warmup). The corrected baseline is 441.4%. Re-run the key MA/volume
levers on the fixed code to re-establish the true best config.
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

# MA combos (all with vol 1.0x cross-day over 50d avg)
MA_VARIANTS = {
    "EMA10/EMA200": {"ema_fast": 10, "ema_slow": 200},
    "EMA20/EMA200": {"ema_fast": 20, "ema_slow": 200},
    "EMA5/EMA200": {"ema_fast": 5, "ema_slow": 200},
    "EMA20/SMA200": {"ema_fast": 20, "ema_slow": 200, "slow_ma_type": "sma"},
    "SMA10/SMA200": {"ema_fast": 10, "ema_slow": 200, "fast_ma_type": "sma", "slow_ma_type": "sma"},
    "EMA10/EMA50": {"ema_fast": 10, "ema_slow": 50},
}

def run_config(overrides):
    strat = GoldenCrossVolumeRotation(**overrides)
    s = StrategyBacktestAdapter(strat).run(as_of=AS_OF, end=END, capital=CAPITAL)["summary"]
    return {
        "return": s["total_return_pct"], "cagr": s["cagr_pct"],
        "alpha": s["alpha_per_year_pct"], "sharpe": s["sharpe_ratio"],
        "max_dd": s["max_drawdown_pct"], "trades": s["total_trades"],
        "win_rate": s["win_rate"], "pf": s["profit_factor"],
    }

results = {}
for name, ov in MA_VARIANTS.items():
    print(f"Running {name}...", flush=True)
    try:
        results[name] = run_config(ov)
    except Exception as e:
        results[name] = {"error": str(e)}
    print(f"  {name}: {results[name]}", flush=True)

print("\n=== MA SWEEP (FIXED CODE) ===")
print(f"{'variant':<16} {'ret%':>8} {'cagr%':>7} {'alpha%':>7} {'sharpe':>6} {'maxdd%':>6} {'trades':>6} {'win%':>5} {'pf':>5}")
for name, r in results.items():
    if "error" in r:
        print(f"{name:<16} ERROR: {r['error']}"); continue
    print(f"{name:<16} {r['return']:>8.1f} {r['cagr']:>7.1f} {r['alpha']:>7.1f} {r['sharpe']:>6.2f} {r['max_dd']:>6.1f} {r['trades']:>6} {r['win_rate']:>5.1f} {r['pf']:>5.2f}")

with open("/tmp/gcvr_ma_fixed.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nSaved to /tmp/gcvr_ma_fixed.json")
