"""Repeat the TrendPullbackResumption experiment with EMA20/EMA200 alignment.

Usage (from backend/):  python scripts/tpr_ema_alignment_ab.py

Result (2026-11-07): EMA20/EMA200 alignment is clearly WORSE than EMA50/EMA200.
  full arm median CAGR 15.29 vs 24.41; alpha/yr -1.55 vs +6.10; Sharpe 0.75 vs
  1.10. The filter complementarity INVERTS: with EMA20 alignment the extra
  filters hurt (full 15.29 < minimal 20.23), whereas with EMA50 they helped
  (full 24.41 > minimal 13.74). Requiring a fresh EMA20/EMA200 cross is
  catastrophic (-14.88 median CAGR, 690 signals). Against the golden-cross
  strategy on the same six starts: 11.22 vs 20.15 (EMA50 was 21.23 vs 20.15).
  Conclusion: keep ema_mid = 50.

Original docstring follows.

Repeat the TrendPullbackResumption experiment with EMA20/EMA200 alignment.

Change under test: ema_mid 50 -> 20, so the alignment/crossover condition is
EMA20 > EMA200 instead of EMA50 > EMA200. ema_fast stays 20, so the EMA20 is
both the pullback/trigger line and the alignment line. Everything else identical.

Reproduces:
  - the 4-arm paired A/B (full / minimal / no_macd / fresh_cross) on 4 starts
  - the same-six-start comparison against DailyGoldenCrossRotation (arm E)

Signals are precomputed once per arm; the `full` arm is precomputed over the
six-start union and reused for its four-start runs (signals for a date do not
depend on which start set is being simulated).
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
SIX_STARTS = ["2019-01-02", "2020-01-02", "2021-01-04",
              "2022-01-03", "2023-01-03", "2024-01-02"]
# The fours starts used by the previous (EMA50) A/B, kept identical.
FOUR_STARTS = ["2021-01-04", "2022-01-03", "2023-01-02", "2024-01-02"]

BASE = {"ema_mid": 20}
ARMS = {
    "full_ema20": dict(BASE),
    "minimal_ema20": {**BASE, "use_pullback": False,
                      "use_macd_filter": False, "use_rsi_filter": False},
    "no_macd_ema20": {**BASE, "use_macd_filter": False},
    "fresh_cross_ema20": {**BASE, "require_fresh_cross": True},
}
METRICS = ["cagr_pct", "alpha_per_year_pct", "sharpe_ratio",
           "max_drawdown_pct", "profit_factor", "trades_per_year"]

OUT = os.path.join(REPO, "docs", "reports", "tpr_ema20_alignment_results.json")


def spy_dates(start):
    with engine.connect() as c:
        df = pd.read_sql(
            f'SELECT "Date" FROM spy WHERE "Date" >= \'{start}\' '
            f'AND "Date" <= \'{END}\' ORDER BY "Date"', c)
    return [str(d)[:10] for d in df["Date"]]


union_six = spy_dates(min(SIX_STARTS))
union_four = spy_dates(min(FOUR_STARTS))

results = {"end": END, "starts_four": FOUR_STARTS, "starts_six": SIX_STARTS,
           "runs_four": {}, "runs_six": {}}

# ── 4-arm A/B on four starts ───────────────────────────────────────────────
for name, overrides in ARMS.items():
    strat = TrendPullbackResumption(**overrides)
    adapter = StrategyBacktestAdapter(strat)
    union = union_six if name == "full_ema20" else union_four
    t0 = time.time()
    signals = strat.precompute_signals(union, engine)
    price_cache = strat.get_precomputed_price_cache()
    print(f"\n[{name}] ema {strat.ema_fast}/{strat.ema_mid}/{strat.ema_slow} | "
          f"precompute {time.time()-t0:.0f}s | "
          f"{sum(len(v) for v in (signals or {}).values())} signals", flush=True)
    for start in FOUR_STARTS:
        res = adapter.run(as_of=start, end=END, capital=100_000.0,
                          precomputed_signals=signals, price_cache=price_cache)
        s = res["summary"]
        results["runs_four"][f"{name}|{start}"] = {k: s.get(k) for k in METRICS}
        print(f"  {start}  cagr={s['cagr_pct']:>7.2f}%  "
              f"alpha/yr={s['alpha_per_year_pct']:>7.2f}%  "
              f"sharpe={s['sharpe_ratio']:>5.2f}  dd={s['max_drawdown_pct']:>5.1f}%  "
              f"pf={s['profit_factor']:>4.2f}  tr/yr={s['trades_per_year']:>5.1f}",
              flush=True)
        with open(OUT, "w") as f:
            json.dump(results, f, indent=2)

    # full arm also runs the two extra six-start dates (reuse its precompute)
    if name == "full_ema20":
        for start in SIX_STARTS:
            if start in FOUR_STARTS:
                results["runs_six"][f"{name}|{start}"] = results["runs_four"][f"{name}|{start}"]
                continue
            res = adapter.run(as_of=start, end=END, capital=100_000.0,
                              precomputed_signals=signals, price_cache=price_cache)
            s = res["summary"]
            results["runs_six"][f"{name}|{start}"] = {k: s.get(k) for k in METRICS}
            print(f"  [six] {start}  cagr={s['cagr_pct']:>7.2f}%  "
                  f"alpha/yr={s['alpha_per_year_pct']:>7.2f}%  "
                  f"sharpe={s['sharpe_ratio']:>5.2f}  dd={s['max_drawdown_pct']:>5.1f}%",
                  flush=True)
            with open(OUT, "w") as f:
                json.dump(results, f, indent=2)

# ── Report ────────────────────────────────────────────────────────────────
print()
print("=" * 96)
print("4-ARM A/B — medians (same 4 starts as the EMA50 run)")
print("=" * 96)
print(f"{'arm':<20}" + "".join(f"{m[:12]:>14}" for m in METRICS))
for name in ARMS:
    vals = [results["runs_four"][f"{name}|{st}"] for st in FOUR_STARTS]
    print(f"{name:<20}" + "".join(
        f"{median([v[m] for v in vals]):>14.2f}" for m in METRICS))

print()
print("Per-start CAGR (4 starts)")
print(f"{'arm':<20}" + "".join(f"{st:>12}" for st in FOUR_STARTS))
for name in ARMS:
    line = f"{name:<20}"
    for st in FOUR_STARTS:
        line += f"{results['runs_four'][name + '|' + st]['cagr_pct']:>12.2f}"
    print(line)

print()
print("=" * 96)
print("SAME 6 STARTS — TrendPullback(EMA20/200) vs DailyGoldenCross(arm E)")
print("=" * 96)
gc_runs = json.load(open(os.path.join(
    REPO, "docs/reports/dgc_signal_ab_results.json")))["runs"]
gc = {st: gc_runs[f"E_ema20_200_novol|{st}"] for st in SIX_STARTS}
tpr = {st: results["runs_six"][f"full_ema20|{st}"] for st in SIX_STARTS}
print(f"{'strategy':<30}" + "".join(f"{m[:12]:>14}" for m in METRICS))
print(f"{'TPR EMA20/EMA200':<30}" + "".join(
    f"{median([tpr[st][m] for st in SIX_STARTS]):>14.2f}" for m in METRICS))
print(f"{'GoldenCross arm E':<30}" + "".join(
    f"{median([gc[st][m] for st in SIX_STARTS]):>14.2f}" for m in METRICS))
print()
print(f"{'strategy':<30}" + "".join(f"{st:>12}" for st in SIX_STARTS))
print(f"{'TPR EMA20/EMA200':<30}" + "".join(
    f"{tpr[st]['cagr_pct']:>12.2f}" for st in SIX_STARTS))
print(f"{'GoldenCross arm E':<30}" + "".join(
    f"{gc[st]['cagr_pct']:>12.2f}" for st in SIX_STARTS))
print(f"\nwrote {OUT}")
