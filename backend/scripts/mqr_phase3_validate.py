"""Phase 3 spike step 1: build the ranking matrices and validate the reconstruction.

Ground truth: on a date when MQR recorded a NEW ENTRY, that ticker must appear in
the reconstructed top-5. A wrong reconstruction would silently corrupt every bound
derived from it, so this runs before any oracle.

Usage: cd backend && ./venv/bin/python scripts/mqr_phase3_validate.py
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(".")), ".env"))
sys.path.insert(0, ".")

import pandas as pd  # noqa: E402

from app.db.database import engine  # noqa: E402
from app.services.exit_replay.entry_set import load_entry_set  # noqa: E402
from app.services.exit_replay.price_panel import PricePanel  # noqa: E402
from app.services.exit_replay.ranking import (  # noqa: E402
    TOP_N,
    build_ranking_panel,
    load_universe,
)


def main() -> int:
    t0 = time.time()
    tickers, sectors, caps = load_universe(engine)
    print(f"universe: {len(tickers)} tickers from stock_metadata", flush=True)
    # Bounded fetch: unbounded whole-history queries stall on pathological tables.
    panel = PricePanel(fetch_since="2015-06-01")
    rp = build_ranking_panel(panel, tickers, sectors, market_caps=caps,
                             start="2016-01-01", end="2026-09-28")
    print(f"matrices: {rp.closes.shape[0]:,} dates x {rp.closes.shape[1]:,} tickers "
          f"({time.time()-t0:.0f}s, {panel.query_count:,} ticker queries)", flush=True)

    e = load_entry_set("data/mqr_entry_set.csv")
    hits = tot = 0
    misses = []
    for row in e.itertuples(index=False):
        i = rp.date_index(row.entry_date)
        if i is None:
            continue
        t = str(row.ticker).upper()
        if rp.ticker_index(t) is None:
            continue
        tot += 1
        top = [x for x, _ in rp.ranked_on(i, top_k=TOP_N)]
        if t in top:
            hits += 1
        elif len(misses) < 8:
            misses.append((str(pd.Timestamp(row.entry_date).date()), t, top))

    print(f"\n=== VALIDATION: recorded entry inside the reconstructed top-{TOP_N} ===",
          flush=True)
    print(f"  {hits:,}/{tot:,} = {100*hits/max(tot,1):.1f}%", flush=True)
    for d, t, top in misses:
        print(f"   miss {d} {t}  reconstructed top5={top}", flush=True)
    print("\nInterpretation: the strategy buys the top 5 after a sector cap and only "
          "when a slot is free, so this is a LOWER bound on correctness — a recorded "
          "entry should nearly always be in the top-5 it was selected from.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
