"""Exit-lever A/B for TrendPullbackResumption.

Motivated by the diagnostics (docs/strategies/trend-pullback-resumption-spec.md):
  - the 10% hard stop cut recoveries: post-exit excess vs SPY +9.0% mean
    (+5.04% median, 66.7% positive) over the next 60 sessions
  - the 40% take profit left alpha: +4.05% mean excess
  - pullback and RSI never bind (0 of 3,587 core stock-days), so removing them
    should be behaviour-identical

Design:
  * All STOP/TP arms are exit-side only, so they share ONE precompute.
  * `dead_off` changes the entry mask, so it needs its own precompute. It is
    expected to reproduce `base` exactly — that is the check on the diagnostic.
  * Same four starts, fixed end, 5bps/side, medians across starts.

Usage (from backend/):  python scripts/tpr_exit_ab.py
"""
import json
import os
import sys
import time
from statistics import median

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)

os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

import pandas as pd

from app.db.database import engine
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.trend_pullback_resumption import TrendPullbackResumption

END = "2026-09-30"
STARTS = ["2021-01-04", "2022-01-03", "2023-01-02", "2024-01-02"]
CAPITAL = 100_000.0

# Exit-side arms (share the base precompute).
EXIT_ARMS = {
    "base_10_40": {},
    "stop15": {"hard_stop_loss": 0.15},
    "stop20": {"hard_stop_loss": 0.20},
    "no_stop": {"hard_stop_loss": 0.0},
    "tp80": {"take_profit": 0.80},
    "no_tp": {"take_profit": 0.0},
}
# Entry-side arm (separate precompute).
DEAD_ARM = ("dead_off", {"use_pullback": False, "use_rsi_filter": False})

METRICS = ["cagr_pct", "alpha_per_year_pct", "sharpe_ratio",
           "max_drawdown_pct", "profit_factor", "trades_per_year"]

OUT = os.path.join(REPO, "docs", "reports", "tpr_exit_ab_results.json")


def apply_cfg(strat, overrides):
    for k, v in overrides.items():
        strat.config[k] = v
        setattr(strat, k, v)


def main():
    with engine.connect() as c:
        spy = pd.read_sql(
            f'SELECT "Date" FROM spy WHERE "Date" >= \'{min(STARTS)}\' '
            f'AND "Date" <= \'{END}\' ORDER BY "Date"', c)
    union = [str(d)[:10] for d in spy["Date"]]

    strat = TrendPullbackResumption()
    adapter = StrategyBacktestAdapter(strat)
    t0 = time.time()
    signals = strat.precompute_signals(union, engine)
    price_cache = strat.get_precomputed_price_cache()
    print(f"base precompute {time.time()-t0:.0f}s", flush=True)

    results = {"end": END, "starts": STARTS, "runs": {}, "arms": {}}

    for name, overrides in EXIT_ARMS.items():
        # reset to the shipped defaults, then apply this arm
        apply_cfg(strat, {"hard_stop_loss": 0.10, "take_profit": 0.40})
        apply_cfg(strat, overrides)
        print(f"\n[{name}] stop={strat.hard_stop_loss:g} tp={strat.take_profit:g}",
              flush=True)
        for start in STARTS:
            s = adapter.run(as_of=start, end=END, capital=CAPITAL,
                            precomputed_signals=signals,
                            price_cache=price_cache)["summary"]
            results["runs"][f"{name}|{start}"] = {k: s.get(k) for k in METRICS}
            print(f"  {start}  cagr={s['cagr_pct']:>7.2f}%  "
                  f"alpha/yr={s['alpha_per_year_pct']:>7.2f}%  "
                  f"sharpe={s['sharpe_ratio']:>5.2f}  dd={s['max_drawdown_pct']:>5.1f}%  "
                  f"pf={s['profit_factor']:>4.2f}  tr/yr={s['trades_per_year']:>5.1f}",
                  flush=True)
            with open(OUT, "w") as f:
                json.dump(results, f, indent=2)

    # Dead-condition arm: own precompute, expected identical to base.
    name, overrides = DEAD_ARM
    dead = TrendPullbackResumption(**overrides)
    dead_adapter = StrategyBacktestAdapter(dead)
    t0 = time.time()
    dead_signals = dead.precompute_signals(union, engine)
    dead_cache = dead.get_precomputed_price_cache()
    print(f"\n[{name}] precompute {time.time()-t0:.0f}s", flush=True)
    for start in STARTS:
        s = dead_adapter.run(as_of=start, end=END, capital=CAPITAL,
                             precomputed_signals=dead_signals,
                             price_cache=dead_cache)["summary"]
        results["runs"][f"{name}|{start}"] = {k: s.get(k) for k in METRICS}
        print(f"  {start}  cagr={s['cagr_pct']:>7.2f}%  "
              f"sharpe={s['sharpe_ratio']:>5.2f}  tr/yr={s['trades_per_year']:>5.1f}",
              flush=True)
        with open(OUT, "w") as f:
            json.dump(results, f, indent=2)

    all_arms = list(EXIT_ARMS) + [DEAD_ARM[0]]
    for name in all_arms:
        results["arms"][name] = {
            m: median([results["runs"][f"{name}|{st}"][m] for st in STARTS])
            for m in METRICS
        }

    print()
    print("=" * 100)
    print("MEDIANS ACROSS 4 STARTS")
    print("=" * 100)
    print(f"{'arm':<14}" + "".join(f"{m[:12]:>14}" for m in METRICS))
    for name in all_arms:
        print(f"{name:<14}" + "".join(
            f"{results['arms'][name][m]:>14.2f}" for m in METRICS))

    print()
    print("Per-start CAGR")
    print(f"{'arm':<14}" + "".join(f"{st:>12}" for st in STARTS))
    for name in all_arms:
        line = f"{name:<14}"
        for st in STARTS:
            line += f"{results['runs'][name + '|' + st]['cagr_pct']:>12.2f}"
        print(line)

    # Does removing the dead filters change anything at all?
    same = all(
        abs(results["runs"][f"dead_off|{st}"][m] - results["runs"][f"base_10_40|{st}"][m]) < 1e-9
        for st in STARTS for m in METRICS
    )
    print()
    print("dead-filter removal identical to base:", same)

    with open(OUT, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
