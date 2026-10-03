"""Paired multi-start A/B over DailyGoldenCrossRotation signal-rule variants.

Why this exists
---------------
The strategy's MA pair and volume filter were originally chosen from priors
carried over from a *different* strategy (Golden Cross Volume Rotation), and one
of those priors was itself an artifact of a truncated-warmup bug. This script
re-derives them from this strategy's own data.

Measured outcome (6 starts, 2026-10-02). Median CAGR / Sharpe / maxDD:

    E  EMA20/EMA200, no vol       22.4 / 0.98 / 37.9   <- shipped default
    C  EMA10/EMA200, no vol       18.8 / 0.85 / 35.1
    B  EMA20/SMA200, no vol       17.5 / 0.86 / 25.5   <- previous behaviour
    A  EMA10/EMA200 + vol         12.4 / 0.61 / 29.9
    D  EMA10/SMA200, no vol        8.0 / 0.49 / 35.8
    F  EMA20/EMA200 + vol          6.4 / 0.39 / 35.2

  - The EMA slow line is validated: EMA10/EMA200 beat EMA10/SMA200 on
    CAGR/alpha/Sharpe/PF 6/6 starts (p=0.031).
  - fast_span=20 beat 10 in both slow-line contexts (6/6 on SMA200, 4/6 on
    EMA200), so the default is 20.
  - The volume filter removes ~58% of crossovers and cost return in every
    context tested, so it defaults OFF (kept as an available lever).

Method
------
Every arm runs the SAME start dates and the same end date, so a cross-arm
difference at a given start is attributable to the arm's config and nothing
else. A fixed end makes window length vary per start, so comparisons use
length-normalized metrics (cagr_pct, alpha_per_year_pct, sharpe_ratio,
trades_per_year) rather than lifetime totals.

Signals are precomputed once per arm over the union date range and reused for
every start (the daily loop only reads precomputed_signals.get(date)), so the
expensive part is paid once per arm rather than once per run.

Indicator warmup is deliberately FIXED across arms — WARMUP_BARS_REQUIRED is a
module constant, not a config key. The warmup fix is a correctness change, not
a lever, and letting the SMA arm need fewer bars would advantage it.

n=6 has low power: only the 6/6 results reach p<0.05. Treat the rest as
directional. All arms are costless (cost_bps=0.0) — costs would penalize the
higher-turnover arms (C/D trade ~70-75/yr vs B's 64).

Usage (from backend/):
    python scripts/dgc_signal_ab.py                 # run every arm
    python scripts/dgc_signal_ab.py 6 E F           # run only missing arms
Results accumulate in docs/reports/dgc_signal_ab_results.json across runs, so a
missing arm can be added without re-running the others.
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
from app.services.strategies.daily_golden_cross import (
    DEFAULT_CONFIG, DailyGoldenCrossRotation,
)

END = "2026-09-30"
CAPITAL = 100_000.0

# Bump whenever the strategy's SIGNAL math changes. Cached runs carry this, and
# a mismatch discards them, so results can never silently describe older code.
#   1 - original (centred, lookahead-biased crossover angle; SMA-labelled EMA200)
#   2 - causal crossover angle, EMA200 slow line, universe-wide cap bounds
#   3 - arms made fully explicit; v2 runs were invalid (see ARMS note)
SCORER_VERSION = 3

# Fingerprint of the strategy's pinned defaults. Cached runs are reused only if
# both this and SCORER_VERSION match, so a default moving under the arms can
# never leave stale results behind. Defaults changed once before (fast_span
# 10->20, volume filter on->off) and silently collapsed four arms onto one config.
DEFAULTS_FP = json.dumps(DEFAULT_CONFIG, sort_keys=True)

# Fixed start dates, spread across regimes (COVID crash, 2022 bear, 2023-26
# bull). Identical for every arm.
ALL_STARTS = [
    "2019-01-02", "2020-01-02", "2021-01-04",
    "2022-01-03", "2023-01-03", "2024-01-02",
]

# Arms form the 2x2 factorial (fast span) x (slow MA type), all with the volume
# filter off, plus the volume-filter variants and the shipped default:
#
#               SMA200 slow          EMA200 slow
#   fast=20     B                    E (shipped default)
#   fast=10     D                    C
#
# EVERY arm states its full signal config EXPLICITLY. Do not make these
# relative to the strategy's defaults: when the defaults changed (fast_span
# 10->20, volume filter on->off) the previously-relative overrides collapsed
# A, C, E and F onto one config, and the sweep reported "this lever does
# nothing" for four arms that were never actually distinct. _assert_distinct()
# below now fails loudly instead.
ARMS = {
    "A_ema10_200_vol":      {"fast_span": 10, "slow_ma_type": "ema", "use_volume_filter": True},
    "B_ema20_sma200_novol": {"fast_span": 20, "slow_ma_type": "sma", "use_volume_filter": False},
    "C_ema10_200_novol":    {"fast_span": 10, "slow_ma_type": "ema", "use_volume_filter": False},
    "D_ema10_sma200_novol": {"fast_span": 10, "slow_ma_type": "sma", "use_volume_filter": False},
    "E_ema20_200_novol":    {"fast_span": 20, "slow_ma_type": "ema", "use_volume_filter": False},
    "F_ema20_200_vol":      {"fast_span": 20, "slow_ma_type": "ema", "use_volume_filter": True},
}

# Each comparison isolates one lever, so a regression can be attributed.
PAIRS = [
    ("A_ema10_200_vol", "B_ema20_sma200_novol", "SHIPPED CHANGE (all 3 edits)"),
    ("A_ema10_200_vol", "C_ema10_200_novol", "volume filter (on EMA10/EMA200)"),
    ("F_ema20_200_vol", "E_ema20_200_novol", "volume filter (on EMA20/EMA200)"),
    ("C_ema10_200_novol", "E_ema20_200_novol", "fast span 10 vs 20 (on EMA200)"),
    ("D_ema10_sma200_novol", "B_ema20_sma200_novol", "fast span 10 vs 20 (on SMA200)"),
    ("C_ema10_200_novol", "D_ema10_sma200_novol", "slow line EMA vs SMA (at fast=10)"),
    ("E_ema20_200_novol", "B_ema20_sma200_novol", "slow line EMA vs SMA (at fast=20)"),
    ("F_ema20_200_vol", "B_ema20_sma200_novol", "MINIMAL CHANGE: SMA->EMA slow + vol"),
]


def assert_distinct():
    """Fail loudly if two arms resolve to the same config.

    Without this, an arm whose overrides stop mattering (because a default
    moved under it) silently duplicates another arm and the A/B reports that
    its lever does nothing.
    """
    seen = {}
    for code, overrides in ARMS.items():
        key = json.dumps(DailyGoldenCrossRotation(**overrides).config, sort_keys=True)
        seen.setdefault(key, []).append(code)
    dupes = [codes for codes in seen.values() if len(codes) > 1]
    if dupes:
        raise SystemExit(f"arms resolve to identical configs: {dupes}")

METRICS = [
    "cagr_pct", "alpha_per_year_pct", "sharpe_ratio",
    "max_drawdown_pct", "win_rate", "profit_factor", "trades_per_year",
]
# For these, lower is better, so a "win" flips.
LOWER_IS_BETTER = {"max_drawdown_pct"}

OUT = os.path.join(REPO, "docs", "reports", "dgc_signal_ab_results.json")


def spy_dates(start, end):
    with engine.connect() as c:
        df = pd.read_sql(
            f'SELECT "Date" FROM spy WHERE "Date" >= \'{start}\' AND "Date" <= \'{end}\' '
            f'ORDER BY "Date"', c)
    return [str(d)[:10] for d in df["Date"]]


def sign_test(wins, n):
    """Two-sided exact binomial sign test p-value."""
    if n == 0:
        return 1.0
    k = max(wins, n - wins)
    tail = sum(math.comb(n, i) for i in range(k, n + 1))
    return min(1.0, 2.0 * tail / (2 ** n))


def main():
    argv = sys.argv[1:]
    n_starts = len(ALL_STARTS)
    if argv and argv[0].isdigit():
        n_starts = int(argv.pop(0))
    wanted = argv or list(ARMS.keys())
    starts = ALL_STARTS[:n_starts]

    unknown = set(wanted) - set(ARMS)
    if unknown:
        raise SystemExit(f"Unknown arm(s): {sorted(unknown)}. Known: {sorted(ARMS)}")
    assert_distinct()

    results = {
        "scorer_version": SCORER_VERSION,
        "defaults_fingerprint": DEFAULTS_FP,
        "end": END, "starts": starts, "arms": {}, "runs": {},
    }
    if os.path.exists(OUT):
        try:
            with open(OUT) as f:
                prior = json.load(f)
            if prior.get("scorer_version") != SCORER_VERSION:
                print(
                    f"cached runs are scorer_version "
                    f"{prior.get('scorer_version')!r}, this code is "
                    f"{SCORER_VERSION} - discarding and re-running all arms",
                    flush=True,
                )
            elif prior.get("defaults_fingerprint") != DEFAULTS_FP:
                print(
                    "strategy defaults changed since these runs - discarding "
                    "and re-running all arms",
                    flush=True,
                )
            elif prior.get("starts") == starts:
                results["runs"] = prior.get("runs", {})
                print(f"loaded {len(results['runs'])} existing runs from {OUT}", flush=True)
            else:
                print("start set changed; ignoring prior results", flush=True)
        except Exception as e:
            print(f"could not reuse {OUT}: {e}", flush=True)

    todo = [
        c for c in wanted
        if not all(f"{c}|{st}" in results["runs"] for st in starts)
    ]

    if todo:
        union_dates = spy_dates(min(starts), END)
        print(f"union trading dates: {len(union_dates)}", flush=True)
        print(f"starts ({len(starts)}): {starts}", flush=True)
        print(f"running: {todo}", flush=True)

    for code in todo:
        strat = DailyGoldenCrossRotation(**ARMS[code])
        adapter = StrategyBacktestAdapter(strat)
        t0 = time.time()
        signals = strat.precompute_signals(union_dates, engine)
        price_cache = strat.get_precomputed_price_cache()
        print(f"\n[{code}] precompute {time.time()-t0:.1f}s | "
              f"{sum(len(v) for v in (signals or {}).values())} signals", flush=True)
        for start in starts:
            t1 = time.time()
            res = adapter.run(as_of=start, end=END, capital=CAPITAL,
                              precomputed_signals=signals, price_cache=price_cache)
            s = res["summary"]
            results["runs"][f"{code}|{start}"] = {k: s.get(k) for k in METRICS}
            print(f"  {start}  cagr={s['cagr_pct']:>7.2f}%  "
                  f"alpha/yr={s['alpha_per_year_pct']:>7.2f}%  "
                  f"sharpe={s['sharpe_ratio']:>5.2f}  dd={s['max_drawdown_pct']:>5.1f}%  "
                  f"win={s['win_rate']:>4.1f}%  pf={s['profit_factor']:>4.2f}  "
                  f"tr/yr={s['trades_per_year']:>5.1f}  ({time.time()-t1:.0f}s)", flush=True)
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, "w") as f:
                json.dump(results, f, indent=2)

    available = [
        c for c in ARMS
        if all(f"{c}|{st}" in results["runs"] for st in starts)
    ]
    for code in available:
        results["arms"][code] = {
            m: median([results["runs"][f"{code}|{st}"][m] for st in starts])
            for m in METRICS
        }

    print("\n" + "=" * 100)
    print("MEDIANS ACROSS STARTS (length-normalized metrics)")
    print("=" * 100)
    print(f"{'arm':<26}" + "".join(f"{m[:12]:>14}" for m in METRICS))
    for code in available:
        print(f"{code:<26}" + "".join(
            f"{results['arms'][code][m]:>14.2f}" for m in METRICS))

    print("\n" + "=" * 100)
    print("PAIRED SIGN TESTS (per-start win counts; p = two-sided exact binomial, n=6)")
    print("  p<0.05 means the winner won consistently enough to be unlikely by chance.")
    print("=" * 100)
    for a, b, label in PAIRS:
        if a not in available or b not in available:
            print(f"\n{label}\n  [{a} vs {b}] - incomplete, skipped")
            continue
        print(f"\n{label}\n  {a}  vs  {b}")
        for m in METRICS:
            va = [results["runs"][f"{a}|{st}"][m] for st in starts]
            vb = [results["runs"][f"{b}|{st}"][m] for st in starts]
            wins = sum(
                1 for x, y in zip(va, vb)
                if (x < y if m in LOWER_IS_BETTER else x > y)
            )
            p = sign_test(wins, len(starts))
            better = a if wins * 2 >= len(starts) else b
            flag = " *" if p < 0.05 else ""
            print(f"    {m:<22} {wins}/{len(starts)} for {a[:20]:<20} "
                  f"p={p:.3f}{flag}   favors {better[:22]}")

    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
