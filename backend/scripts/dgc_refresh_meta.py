"""Refresh daily_golden_cross.meta.json through the app's own sidecar writer.

The Library table reads CAGR/Sharpe/Return/Win%/Drawdown/Trades from the
co-located `.meta.json`. It is normally written by a Strategy Lab batch, which
means it goes stale whenever the strategy changes but no batch is run — right
now it advertises the behaviour of a previous strategy (before the MA pair was
corrected, the lookahead in the crossover angle was removed, and cost/DC-warning
defaults changed).

Rather than hand-writing numbers, this calls the SAME function the batch flow
calls (`strategy_lab_orchestrator._write_sidecar_meta`), so the sidecar is
produced by the production aggregation — medians across runs — and simply fed
by this harness instead of a batch.

Usage (from backend/):  python scripts/dgc_refresh_meta.py
"""
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

import json

import pandas as pd

from app.db.database import engine
from app.services import strategy_lab_orchestrator as orch
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.daily_golden_cross import DailyGoldenCrossRotation

# Repo-relative, exactly as the batch flow passes it.
STRATEGY_PATH = "backend/app/services/strategies/daily_golden_cross.py"

END = "2026-09-30"
CAPITAL = 100_000.0
STARTS = [
    "2019-01-02", "2020-01-02", "2021-01-04",
    "2022-01-03", "2023-01-03", "2024-01-02",
]


def main():
    with engine.connect() as c:
        spy = pd.read_sql(
            f'SELECT "Date" FROM spy WHERE "Date" >= \'{min(STARTS)}\' '
            f'AND "Date" <= \'{END}\' ORDER BY "Date"', c)
    union_dates = [str(d)[:10] for d in spy["Date"]]

    strat = DailyGoldenCrossRotation()
    adapter = StrategyBacktestAdapter(strat)
    cfg = strat.config
    print(f"config: EMA{cfg['fast_span']}/{cfg['slow_ma_type'].upper()}{cfg['slow_span']} "
          f"vol={cfg['use_volume_filter']} dc={cfg['dc_warning_spread']:g} "
          f"cost={cfg['cost_bps']:g}bps", flush=True)

    t0 = time.time()
    signals = strat.precompute_signals(union_dates, engine)
    price_cache = strat.get_precomputed_price_cache()
    print(f"precompute {time.time()-t0:.1f}s", flush=True)

    results = []
    for start in STARTS:
        res = adapter.run(as_of=start, end=END, capital=CAPITAL,
                          precomputed_signals=signals, price_cache=price_cache)
        s = res["summary"]
        results.append({"status": "completed", "kpis": s})
        print(f"  {start}  cagr={s['cagr_pct']:>7.2f}%  ret={s['total_return_pct']:>8.1f}%  "
              f"sharpe={s['sharpe_ratio']:>5.2f}  dd={s['max_drawdown_pct']:>5.1f}%  "
              f"trades={s['total_trades']}", flush=True)

    orch._write_sidecar_meta(STRATEGY_PATH, results)

    meta_path = os.path.join(
        os.path.dirname(BACKEND), STRATEGY_PATH.replace(".py", ".meta.json"))
    print(f"\nwrote {meta_path}:")
    print(open(meta_path).read())


if __name__ == "__main__":
    main()
