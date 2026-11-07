"""Capacity x sizing A/B for TrendPullbackResumption.

Neither max_holdings nor sizing_method changes ENTRY signals, so all six arms
share one precompute. This tests the levers that do NOT widen the entry funnel
(the funnel is correctly narrow -- see tpr_coverage_diag.py):

  max_holdings  5 / 8 / 10   -- act on more of the candidates already selected
  sizing        linear vs score-squared

Same four starts, fixed end, 5bps/side, medians.

Usage (from backend/):  python scripts/tpr_capacity_ab.py
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
HOLDINGS = [5, 8, 10]
SIZINGS = ["linear", "score_squared"]
METRICS = ["cagr_pct", "alpha_per_year_pct", "sharpe_ratio",
           "max_drawdown_pct", "profit_factor", "trades_per_year"]
OUT = os.path.join(REPO, "docs", "reports", "tpr_capacity_ab_results.json")
PROPERTY_KEYS = {"max_holdings", "sizing_pcts"}


def apply_cfg(strat, overrides):
    for k, v in overrides.items():
        strat.config[k] = v
        if k not in PROPERTY_KEYS:
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
    print(f"precompute {time.time()-t0:.0f}s (shared by all arms)", flush=True)

    results = {"end": END, "starts": STARTS, "runs": {}, "arms": {}}

    for h in HOLDINGS:
        for sz in SIZINGS:
            label = f"h{h}_{sz}"
            apply_cfg(strat, {"max_holdings": h, "sizing_method": sz})
            print(f"\n[{label}] held={strat.max_holdings} sizing={strat.sizing_method}",
                  flush=True)
            for start in STARTS:
                res = adapter.run(as_of=start, end=END, capital=CAPITAL,
                                  precomputed_signals=signals,
                                  price_cache=price_cache)
                s = res["summary"]
                avg_hold = (sum(e["n_holdings"] for e in res["daily_equity"])
                            / max(len(res["daily_equity"]), 1))
                results["runs"][f"{label}|{start}"] = {
                    **{k: s.get(k) for k in METRICS}, "avg_holdings": avg_hold,
                }
                print(f"  {start}  cagr={s['cagr_pct']:>7.2f}%  "
                      f"alpha/yr={s['alpha_per_year_pct']:>7.2f}%  "
                      f"sharpe={s['sharpe_ratio']:>5.2f}  dd={s['max_drawdown_pct']:>5.1f}%  "
                      f"pf={s['profit_factor']:>4.2f}  tr/yr={s['trades_per_year']:>5.1f}  "
                      f"held={avg_hold:>4.1f}", flush=True)
                with open(OUT, "w") as f:
                    json.dump(results, f, indent=2)

    labels = [f"h{h}_{sz}" for h in HOLDINGS for sz in SIZINGS]
    for label in labels:
        results["arms"][label] = {
            m: median([results["runs"][f"{label}|{st}"][m] for st in STARTS])
            for m in METRICS + ["avg_holdings"]
        }

    print()
    print("=" * 104)
    print("MEDIANS ACROSS 4 STARTS")
    print("=" * 104)
    print(f"{'arm':<18}" + "".join(f"{m[:12]:>14}" for m in METRICS)
          + f"{'avg held':>10}")
    for label in labels:
        print(f"{label:<18}" + "".join(
            f"{results['arms'][label][m]:>14.2f}" for m in METRICS)
            + f"{results['arms'][label]['avg_holdings']:>10.1f}")

    print()
    print("Per-start CAGR")
    print(f"{'arm':<18}" + "".join(f"{st:>12}" for st in STARTS))
    for label in labels:
        line = f"{label:<18}"
        for st in STARTS:
            line += f"{results['runs'][label + '|' + st]['cagr_pct']:>12.2f}"
        print(line)

    with open(OUT, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
