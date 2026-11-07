"""Trend-quality RANKING A/B for TrendPullbackResumption.

The fundamental overlay was rejected on data grounds (stock_financials_quarterly
has period-END dates, not filing dates, and only ~9 quarters of history). This
tests the same hypothesis -- improve WHICH 5 names are picked -- with price data
that is available for the whole window.

Quality term: Kaufman efficiency ratio, |net move| / total path length over
`quality_window` sessions, in [0, 1]. It is added to the score with weight
`quality_weight` and the weights are renormalised. 0.0 reproduces the shipped
score exactly (verified).

Each arm changes the score baked into the precomputed signals, so each needs its
own precompute. Same four starts, fixed end, 5bps/side, medians.

Usage (from backend/):  python scripts/tpr_quality_ab.py
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
WEIGHTS = [0.0, 0.2, 0.3]
METRICS = ["cagr_pct", "alpha_per_year_pct", "sharpe_ratio",
           "max_drawdown_pct", "profit_factor", "trades_per_year"]
OUT = os.path.join(REPO, "docs", "reports", "tpr_quality_ab_results.json")


def main():
    with engine.connect() as c:
        spy = pd.read_sql(
            f'SELECT "Date" FROM spy WHERE "Date" >= \'{min(STARTS)}\' '
            f'AND "Date" <= \'{END}\' ORDER BY "Date"', c)
    union = [str(d)[:10] for d in spy["Date"]]

    results = {"end": END, "starts": STARTS, "runs": {}, "arms": {}}

    for w in WEIGHTS:
        strat = TrendPullbackResumption(quality_weight=w)
        adapter = StrategyBacktestAdapter(strat)
        t0 = time.time()
        signals = strat.precompute_signals(union, engine)
        price_cache = strat.get_precomputed_price_cache()
        print(f"\n[quality_weight={w}] precompute {time.time()-t0:.0f}s", flush=True)
        for start in STARTS:
            s = adapter.run(as_of=start, end=END, capital=CAPITAL,
                            precomputed_signals=signals,
                            price_cache=price_cache)["summary"]
            label = f"q{w:g}"
            results["runs"][f"{label}|{start}"] = {k: s.get(k) for k in METRICS}
            print(f"  {start}  cagr={s['cagr_pct']:>7.2f}%  "
                  f"alpha/yr={s['alpha_per_year_pct']:>7.2f}%  "
                  f"sharpe={s['sharpe_ratio']:>5.2f}  dd={s['max_drawdown_pct']:>5.1f}%  "
                  f"pf={s['profit_factor']:>4.2f}  tr/yr={s['trades_per_year']:>5.1f}",
                  flush=True)
            with open(OUT, "w") as f:
                json.dump(results, f, indent=2)

    for w in WEIGHTS:
        results["arms"][f"q{w:g}"] = {
            m: median([results["runs"][f"q{w:g}|{st}"][m] for st in STARTS])
            for m in METRICS
        }

    print()
    print("=" * 100)
    print("MEDIANS ACROSS 4 STARTS — quality weight in the ranking")
    print("=" * 100)
    print(f"{'weight':<10}" + "".join(f"{m[:12]:>14}" for m in METRICS))
    for w in WEIGHTS:
        print(f"q{w:<9}" + "".join(
            f"{results['arms'][f'q{w:g}'][m]:>14.2f}" for m in METRICS))

    print()
    print("Per-start CAGR")
    print(f"{'weight':<10}" + "".join(f"{st:>12}" for st in STARTS))
    for w in WEIGHTS:
        line = f"q{w:<9}"
        for st in STARTS:
            line += f"{results['runs'][f'q{w:g}|{st}']['cagr_pct']:>12.2f}"
        print(line)

    with open(OUT, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
