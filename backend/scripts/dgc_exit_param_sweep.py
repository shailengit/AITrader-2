"""Sweep transaction cost and DC-warning spread for DailyGoldenCrossRotation.

Two open items, both exit-side:

  cost_bps          the strategy was originally measured with costless fills.
                    ~65 trades/yr at top-5 sizing is real turnover, so every
                    return on this stack is overstated until a cost is charged.
  dc_warning_spread exits a holding when the fast/slow spread falls below this
                    AND price is under the fast line. It was tuned at 0.001
                    against an EMA20/SMA200 pair; the shipped pair is
                    EMA20/EMA200, so the spread distribution it was tuned
                    against has changed.

Both are EXIT parameters: they do not touch entry signals, so one precompute is
shared by every cell. Warmup, starts and metrics match dgc_signal_ab.py.
"""
import json
import math
import os
import sys
import time
import warnings
from statistics import median

warnings.filterwarnings("ignore")

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
from app.services.strategies.daily_golden_cross import DailyGoldenCrossRotation

END = "2026-09-30"
CAPITAL = 100_000.0
ALL_STARTS = [
    "2019-01-02", "2020-01-02", "2021-01-04",
    "2022-01-03", "2023-01-03", "2024-01-02",
]

SHIPPED_COST = 5.0
SHIPPED_DC = 0.005

# (label, overrides) — cost sweep at the shipped DC, then DC sweep at the
# shipped cost. EVERY cell states BOTH levers explicitly. Do not leave one to
# the strategy's default: dc_warning_spread moved once (0.001 -> 0.005) and
# would have silently re-labelled the cost rows without changing their names.
CELLS = (
    [(f"cost={c:g}bps@dc{SHIPPED_DC:g}",
      {"cost_bps": c, "dc_warning_spread": SHIPPED_DC})
     for c in (0.0, 5.0, 10.0, 20.0)]
    + [(f"cost={SHIPPED_COST:g}bps@dc{d:g}",
        {"cost_bps": SHIPPED_COST, "dc_warning_spread": d})
       for d in (0.001, 0.01, 0.02)]
)
BASE_LABEL = f"cost={SHIPPED_COST:g}bps@dc{SHIPPED_DC:g}"
CELLS_FP = json.dumps(CELLS, sort_keys=True)

METRICS = [
    "cagr_pct", "alpha_per_year_pct", "sharpe_ratio",
    "max_drawdown_pct", "win_rate", "profit_factor", "trades_per_year",
]
LOWER_IS_BETTER = {"max_drawdown_pct"}

OUT = os.path.join(REPO, "docs", "reports", "dgc_exit_param_sweep.json")


def sign_test(wins, n):
    if n == 0:
        return 1.0
    k = max(wins, n - wins)
    tail = sum(math.comb(n, i) for i in range(k, n + 1))
    return min(1.0, 2.0 * tail / (2 ** n))


def apply_cfg(strat, overrides):
    """Keep the config dict and the instance attributes in sync."""
    for k, v in overrides.items():
        strat.config[k] = v
        setattr(strat, k, v)


def main():
    with engine.connect() as c:
        spy = pd.read_sql(
            f'SELECT "Date" FROM spy WHERE "Date" >= \'{min(ALL_STARTS)}\' '
            f'AND "Date" <= \'{END}\' ORDER BY "Date"', c)
    union_dates = [str(d)[:10] for d in spy["Date"]]

    strat = DailyGoldenCrossRotation()
    adapter = StrategyBacktestAdapter(strat)

    t0 = time.time()
    signals = strat.precompute_signals(union_dates, engine)
    price_cache = strat.get_precomputed_price_cache()
    print(f"precompute {time.time()-t0:.1f}s | "
          f"{sum(len(v) for v in (signals or {}).values())} signals "
          f"(shared by all {len(CELLS)} cells)", flush=True)

    results = {"end": END, "starts": ALL_STARTS, "cells_fingerprint": CELLS_FP,
               "cells": {}, "runs": {}}
    if os.path.exists(OUT):
        try:
            with open(OUT) as f:
                prior = json.load(f)
            if prior.get("cells_fingerprint") == CELLS_FP:
                print(f"note: {OUT} exists but will be overwritten", flush=True)
            else:
                print("cell definitions changed since the cached runs - "
                      "re-running everything", flush=True)
        except Exception:
            pass
    for label, overrides in CELLS:
        apply_cfg(strat, overrides)
        print(f"\n[{label}]", flush=True)
        for start in ALL_STARTS:
            t1 = time.time()
            res = adapter.run(as_of=start, end=END, capital=CAPITAL,
                              precomputed_signals=signals, price_cache=price_cache)
            s = res["summary"]
            results["runs"][f"{label}|{start}"] = {k: s.get(k) for k in METRICS}
            print(f"  {start}  cagr={s['cagr_pct']:>7.2f}%  "
                  f"alpha/yr={s['alpha_per_year_pct']:>7.2f}%  "
                  f"sharpe={s['sharpe_ratio']:>5.2f}  dd={s['max_drawdown_pct']:>5.1f}%  "
                  f"tr/yr={s['trades_per_year']:>5.1f}  ({time.time()-t1:.0f}s)", flush=True)
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, "w") as f:
                json.dump(results, f, indent=2)
        results["cells"][label] = {
            m: median([results["runs"][f"{label}|{st}"][m] for st in ALL_STARTS])
            for m in METRICS
        }

    print("\n" + "=" * 100)
    print("MEDIANS ACROSS STARTS")
    print("=" * 100)
    print(f"{'cell':<18}" + "".join(f"{m[:12]:>14}" for m in METRICS))
    for label, _ in CELLS:
        print(f"{label:<18}" + "".join(
            f"{results['cells'][label][m]:>14.2f}" for m in METRICS))

    base_label = BASE_LABEL
    print("\n" + "=" * 100)
    print(f"PAIRED SIGN TESTS vs baseline [{base_label}]  (n=6, p<0.05 marked *)")
    print("  'cost=X' cells show the DRAG from charging X bps per side.")
    print("=" * 100)
    for label, _ in CELLS:
        if label == base_label:
            continue
        print(f"\n{label}  vs  {base_label}")
        for m in METRICS:
            va = [results["runs"][f"{label}|{st}"][m] for st in ALL_STARTS]
            vb = [results["runs"][f"{base_label}|{st}"][m] for st in ALL_STARTS]
            wins = sum(1 for x, y in zip(va, vb)
                       if (x < y if m in LOWER_IS_BETTER else x > y))
            p = sign_test(wins, len(ALL_STARTS))
            flag = " *" if p < 0.05 else ""
            print(f"    {m:<22} {wins}/{len(ALL_STARTS)} p={p:.3f}{flag}")

    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
