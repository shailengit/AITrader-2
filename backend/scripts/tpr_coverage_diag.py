"""Reframe the screening bottleneck: regime coverage vs trigger coverage.

The earlier diagnostic reported that 96.9% of top-decile movers never enter the
CORE. That conflates two filters with very different justifications:

  regime  (EMA200 + EMA50 alignment)  -- the validated edge; should NOT be relaxed
  trigger (one-day EMA20 cross-back)  -- an entry TIMING event; fair to broaden

This separates them. It reports, among top-decile movers:
  * how many are regime-eligible at all
  * of those, how many are reachable at trigger_window = 1/3/5/10
and, among regime-eligible stock-days, whether broadening the trigger admits
worse forward returns (dilution).

Usage (from backend/):  python scripts/tpr_coverage_diag.py
"""
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)

os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

import numpy as np
import pandas as pd

from app.db.database import engine
from app.services.strategy_base import get_all_tickers
from app.services.strategies.trend_pullback_resumption import (
    TrendPullbackResumption, required_load_start, WARMUP_BARS_REQUIRED, WARMUP_MAX_ROWS,
)
from app.utils.security import get_safe_table_name

START, END = "2021-01-04", "2026-09-30"
FWD = 60
WINDOWS = [1, 3, 5, 10]
OUT = os.path.join(REPO, "docs", "reports", "tpr_coverage_diag.json")

strat = TrendPullbackResumption()

with engine.connect() as c:
    spy = pd.read_sql(
        f'SELECT "Date" FROM spy WHERE "Date" >= \'{START}\' AND "Date" <= \'{END}\' '
        f'ORDER BY "Date"', c)
all_dates = [str(d)[:10] for d in spy["Date"]]
sample_dates = all_dates[::20]
sample_set = set(sample_dates)
print(f"sampling {len(sample_dates)} dates", flush=True)

rows = []
for ticker in get_all_tickers(engine):
    try:
        safe = get_safe_table_name(ticker)
    except ValueError:
        continue
    try:
        with engine.connect() as conn:
            df = pd.read_sql(
                f'SELECT "Date", "Close", "Volume" FROM "{safe}" '
                f'WHERE "Date" >= \'{required_load_start(sample_dates[0])}\' '
                f'AND "Date" <= \'{END}\' ORDER BY "Date" DESC LIMIT {WARMUP_MAX_ROWS}',
                conn)
    except Exception:
        continue
    if df.empty or len(df) < WARMUP_BARS_REQUIRED:
        continue
    df = df.sort_values("Date").reset_index(drop=True)
    dates = df["Date"].astype(str).str[:10].to_numpy()
    close = df["Close"].astype(float)
    volume = df["Volume"].astype(float)
    cond = strat._conditions(close, volume)
    closev = close.to_numpy()
    ema_fast = cond["ema_fast"].to_numpy()
    cross = cond["cross"].to_numpy()
    above = closev > ema_fast
    reach = {}
    for w in WINDOWS:
        recent = pd.Series(cross.astype(float)).rolling(w).max().to_numpy() > 0
        reach[w] = above & recent
    regime = (cond["trend"].to_numpy() & cond["aligned"].to_numpy()
              & cond["liquid"].to_numpy() & cond["vol_ok"].to_numpy())
    macd_up = cond["macd_up"].to_numpy()

    for i, d in enumerate(dates):
        if d not in sample_set or i + FWD >= len(closev) or (i + 1) < WARMUP_BARS_REQUIRED:
            continue
        a, b = closev[i], closev[i + FWD]
        if not np.isfinite(a) or a <= 0 or not np.isfinite(b):
            continue
        rows.append({
            "date": d, "fwd": b / a - 1.0, "regime": bool(regime[i]),
            "macd_up": bool(macd_up[i]),
            **{f"reach_{w}": bool(reach[w][i]) for w in WINDOWS},
        })

d = pd.DataFrame(rows)
d["top"] = d.groupby("date")["fwd"].transform(lambda s: s >= s.quantile(0.90))
print(f"{len(d):,} stock-days | {int(d.top.sum()):,} top-decile", flush=True)

top = d[d.top]
reg_top = top[top.regime]
print()
print("=" * 90)
print("WHERE THE TOP-DECILE MOVERS ARE LOST")
print("=" * 90)
print(f"  top-decile stock-days:                 {len(top):,}")
print(f"  regime-eligible (trend+aligned+liq+vol): {len(reg_top):,} "
      f"({100*len(reg_top)/len(top):.1f}%)")
print(f"  excluded by the REGIME itself:          "
      f"{len(top)-len(reg_top):,} ({100*(1-len(reg_top)/len(top)):.1f}%)")

print()
print("  within the regime-eligible top-decile, reachable by trigger window:")
for w in WINDOWS:
    n = int(reg_top[f"reach_{w}"].sum())
    print(f"    window {w:>2}: {n:>5,} ({100*n/max(len(reg_top),1):>5.1f}%)")

print()
print("=" * 90)
print("DILUTION CHECK — forward 60d return among regime-eligible stock-days")
print("=" * 90)
reg = d[d.regime]
print(f"{'window':<10}{'reachable n':>13}{'mean fwd':>11}{'median':>10}"
      f"{'not reachable n':>18}{'mean fwd':>11}")
for w in WINDOWS:
    a = reg[reg[f"reach_{w}"]]
    b = reg[~reg[f"reach_{w}"]]
    print(f"w{w:<9}{len(a):>13,}{a.fwd.mean()*100:>10.2f}%"
          f"{a.fwd.median()*100:>9.2f}%{len(b):>18,}{b.fwd.mean()*100:>10.2f}%")

# Same, but requiring MACD up (the surviving optional filter)
reg_macd = reg[reg.macd_up]
print()
print("  restricted to MACD-up (the shipped entry), per window:")
for w in WINDOWS:
    a = reg_macd[reg_macd[f"reach_{w}"]]
    print(f"    window {w:>2}: n={len(a):>5,}  "
          f"mean fwd={a.fwd.mean()*100:>6.2f}%  median={a.fwd.median()*100:>6.2f}%")

summary = {
    "top_decile_n": int(len(top)),
    "regime_eligible_share": 100 * len(reg_top) / max(len(top), 1),
    "reachable_share": {
        str(w): 100 * int(reg_top[f"reach_{w}"].sum()) / max(len(reg_top), 1)
        for w in WINDOWS
    },
}
with open(OUT, "w") as f:
    json.dump(summary, f, indent=2)
print(f"\nwrote {OUT}")
