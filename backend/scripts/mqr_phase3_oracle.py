"""Phase 3 spike: the upper bound on a better ROTATION policy.

Answers the question the user asked, at the level they asked it: on each day, if we
could have swapped one holding for the best available candidate, how much was on the
table -- and is it in choosing what to SELL or what to BUY?

WHY THIS IS NOT THE PHASE-2 MISTAKE
-----------------------------------
Phase 2's frozen-entry replay overstated loosened exits because it had no SLOT
OPPORTUNITY COST: the alternative to holding a stock longer is holding a DIFFERENT
stock, which it never modelled.

A swap decision prices that cost internally -- the two arms of the counterfactual are
the candidate's forward return and the incumbent's forward return, both from real
prices. So the comparison is legitimate. What would NOT be legitimate is summing
per-decision gains, which assumes every decision gets fresh capital; that is why the
oracle here is a FORWARD SIMULATION competing for the same 5 slots, not a sum.

FOUR ARMS, so the bound decomposes
----------------------------------
  current       the recorded rule: sell a holding that leaves the top-5, top-score buy
  sell_oracle   best possible SELL, top-score buy
  buy_oracle    current SELL, best possible BUY
  perfect       best possible both
If `perfect` barely exceeds `buy_oracle`, the edge is on the buy side; if it barely
exceeds `sell_oracle`, it is on the sell side; if both are close to `current`, there
is nothing here and rotation should be left alone.

The oracle is a hindsight CEILING, not an achievable policy. It is reported as a
ceiling.

Usage: cd backend && ./venv/bin/python scripts/mqr_phase3_oracle.py
"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
from dataclasses import dataclass

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(".")), ".env"))
sys.path.insert(0, ".")

from app.db.database import engine  # noqa: E402
from app.services.exit_replay.entry_set import load_entry_set  # noqa: E402
from app.services.exit_replay.price_panel import PricePanel  # noqa: E402
from app.services.exit_replay.ranking import (  # noqa: E402
    TOP_K_CANDIDATES,
    RankingPanel,
    build_ranking_panel,
    load_universe,
)

ARMS = ("current", "sell_oracle", "buy_oracle", "perfect")
HORIZONS = (10, 20, 40)
MIN_HOLD_DAYS = 14
MAX_SLOTS = 5
MAX_PER_SECTOR = 2
PROTECT_WINNERS = True


@dataclass
class Slot:
    ticker: str
    j: int
    entry_i: int
    entry_px: float


def _fwd(rp: RankingPanel, i: int, j: int, h: int):
    return rp.forward_return(i, j, h)


def _mark(rp, slots, i) -> float:
    """Mark-to-market value of the slots at date i, in units of one slot's notional."""
    v = 0.0
    for s in slots:
        px = rp.closes[i, s.j]
        if np.isfinite(px) and s.entry_px > 0:
            v += float(px / s.entry_px)
    return v


def simulate(rp: RankingPanel, start_i: int, end_i: int, arm: str, horizon: int) -> dict:
    """Forward simulation of one arm. One swap per day at most; 5 equal slots."""
    slots: list[Slot] = []
    equity = []
    swaps = 0

    for i in range(start_i, end_i):
        # ── 1. fill empty slots (identical for every arm: top-ranked names) ──
        if len(slots) < MAX_SLOTS:
            held = {s.ticker for s in slots}
            for t, _ in rp.ranked_on(i, exclude=held, top_k=MAX_SLOTS,
                                     max_per_sector=MAX_PER_SECTOR):
                if len(slots) >= MAX_SLOTS:
                    break
                j = rp.ticker_index(t)
                px = rp.closes[i, j] if j is not None else None
                if j is None or not np.isfinite(px) or px <= 0:
                    continue
                slots.append(Slot(t, j, i, float(px)))
                held.add(t)
            equity.append(_mark(rp, slots, i))
            continue

        date = rp.dates[i]

        # ── 2. who is SELLABLE under the recorded rule? ──
        top5 = [t for t, _ in rp.ranked_on(i, exclude=(), top_k=MAX_SLOTS,
                                           max_per_sector=MAX_PER_SECTOR)]
        sellable = []
        for s in slots:
            hold_days = (date - rp.dates[s.entry_i]).days
            if hold_days < MIN_HOLD_DAYS:
                continue
            if s.ticker in top5:
                continue
            px = rp.closes[i, s.j]
            if PROTECT_WINNERS and np.isfinite(px) and px > s.entry_px:
                continue                      # protect_winners keeps profitable names
            sellable.append(s)

        # ── 3. candidate universe (ranked, excluding what we hold) ──
        held = {s.ticker for s in slots}
        cands = [(t, rp.ticker_index(t))
                 for t, _ in rp.ranked_on(i, exclude=held, top_k=TOP_K_CANDIDATES,
                                          max_per_sector=MAX_PER_SECTOR)]
        cands = [(t, j) for t, j in cands if j is not None]

        # ── 4. choose the swap per arm ──
        sell = None
        if arm in ("current", "buy_oracle"):
            sell = sellable[0] if sellable else None
        elif arm in ("sell_oracle", "perfect"):
            scored = [(s, _fwd(rp, i, s.j, horizon)) for s in sellable]
            scored = [(s, f) for s, f in scored if f is not None]
            sell = min(scored, key=lambda x: x[1])[0] if scored else None

        buy = None
        if sell is not None and cands:
            if arm in ("current", "sell_oracle"):
                buy = cands[0]
            else:                              # buy_oracle / perfect: best forward
                scored = [(c, _fwd(rp, i, c[1], horizon)) for c in cands]
                scored = [(c, f) for c, f in scored if f is not None]
                buy = max(scored, key=lambda x: x[1])[0] if scored else None

        if sell is not None and buy is not None:
            t, j = buy
            if arm in ("buy_oracle", "perfect"):
                fs = _fwd(rp, i, sell.j, horizon)
                fb = _fwd(rp, i, j, horizon)
                if fs is not None and fb is not None and fb <= fs:
                    buy = None                 # swap only if it improves
            if buy is not None:
                slots.remove(sell)
                slots.append(Slot(t, j, i, float(rp.closes[i, j])))
                swaps += 1

        equity.append(_mark(rp, slots, i))

    eq = np.array(equity, dtype=float)
    years = max((rp.dates[end_i - 1] - rp.dates[start_i]).days / 365.25, 1e-9)
    total = float(eq[-1] / MAX_SLOTS - 1.0) if len(eq) else 0.0
    return {
        "arm": arm, "horizon": horizon, "swaps": swaps,
        "final_multiple": float(eq[-1] / MAX_SLOTS) if len(eq) else 1.0,
        "total_return_pct": round(total * 100, 2),
        "cagr_pct": round(((eq[-1] / MAX_SLOTS) ** (1 / years) - 1) * 100, 2) if len(eq) else 0.0,
        "max_dd_pct": round(float(((np.maximum.accumulate(eq) - eq) / np.maximum.accumulate(eq)).max() * 100), 2) if len(eq) else 0.0,
    }


def main() -> int:
    print("Loading universe and building score matrices...", flush=True)
    tickers, sectors, caps = load_universe(engine)
    rp = build_ranking_panel(PricePanel(fetch_since="2017-06-01"), tickers, sectors,
                             market_caps=caps, start="2018-01-01", end="2026-09-28")
    print(f"  {rp.closes.shape[0]:,} dates x {rp.closes.shape[1]:,} tickers", flush=True)

    e = load_entry_set("data/mqr_entry_set.csv")
    start_i = rp.date_index(pd.Timestamp("2020-01-01"))
    end_i = rp.date_index(pd.Timestamp("2026-05-19")) or len(rp.dates) - 1
    print(f"  window {rp.dates[start_i].date()} .. {rp.dates[end_i].date()}", flush=True)

    results = {}
    for h in HORIZONS:
        print(f"\n=== horizon {h} trading days ===", flush=True)
        for arm in ARMS:
            r = simulate(rp, start_i, end_i, arm, h)
            results[f"{arm}|{h}"] = r
            print(f"  {arm:<12} total {r['total_return_pct']:>9.1f}%  "
                  f"cagr {r['cagr_pct']:>6.2f}%  maxdd {r['max_dd_pct']:>5.1f}%  "
                  f"swaps {r['swaps']:>5}", flush=True)

    print("\n" + "=" * 78)
    print("UPPER BOUND: how much is on the table, and on which side?")
    print("=" * 78)
    for h in HORIZONS:
        cur = results[f"current|{h}"]["cagr_pct"]
        so = results[f"sell_oracle|{h}"]["cagr_pct"]
        bo = results[f"buy_oracle|{h}"]["cagr_pct"]
        pf = results[f"perfect|{h}"]["cagr_pct"]
        print(f"\n  horizon {h}:")
        print(f"    current      {cur:>7.2f}% CAGR")
        print(f"    sell_oracle  {so:>7.2f}%   (sell side  {so-cur:+6.2f} pts)")
        print(f"    buy_oracle   {bo:>7.2f}%   (buy side   {bo-cur:+6.2f} pts)")
        print(f"    perfect      {pf:>7.2f}%   (both       {pf-cur:+6.2f} pts)")
        side = "BUY" if (bo - cur) > (so - cur) else "SELL"
        print(f"    -> the larger share of the ceiling is on the {side} side")

    with open("/tmp/mqr_phase3_oracle.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nSaved /tmp/mqr_phase3_oracle.json")
    print("\nNOTE: every oracle arm is a HINDSIGHT CEILING, not an achievable policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
