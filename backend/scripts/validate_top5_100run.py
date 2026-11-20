"""Validate two Strategy Lab strategies: 100-run multi-start batch + lookahead audit.

Strategies (the first two in the Strategy Classes list):
  1. SectorScannerTop5Rotation
  2. MomentumQualityRotation   (same signal engine, different exits/regime)

What this does
--------------
PHASE A  Shared precompute: one trading calendar, one signal cache, one price
         cache, one score map, and an INDEPENDENT bars cache read straight from
         Postgres (used to verify fills without trusting the adapter).
PHASE B  100 backtests per strategy. Same end date, 100 different start dates
         (seed 42, so both strategies share the same 100 starts -> paired).
PHASE C  Lookahead / causality tests:
         T1 end-truncation invariance -- trades before a cutoff must be
            identical when the run is ended at the cutoff instead of END.
         T2 signal prefix stability -- signals for dates <= cutoff must be
            identical whether or not later bars are loaded.
         T3 per-day vs precomputed signal parity.
         T4 score_holding causality (cached map vs per-day SQL).
         T5 fill verification -- every fill price must equal the real next
            session's OPEN from the DB.
PHASE D  Trade validity audit on every run (dates, ordering, overlap, slot
         count, sector cap, cash, accounting identities, churn artefacts).
PHASE E  Per-strategy HTML run viewers.

Method notes
------------
Runs have DIFFERENT lengths (same end, different starts), so lifetime totals
(total_return_pct, total_trades) are not comparable. Everything is compared on
length-normalized metrics: CAGR, alpha/yr, Sharpe, maxDD, trades/yr.

T2/T3/T4 test the SHARED signal engine once: `precompute_signals`, `get_signals`
and `score_holding` are inherited unchanged by MomentumQualityRotation (asserted
below), so the result applies to both classes.

Usage:
    cd backend && ./venv/bin/python scripts/validate_top5_100run.py --runs 100
"""

import argparse
import json
import random
import statistics as st
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
load_dotenv(REPO / ".env")

from app.db.database import engine as db_engine  # noqa: E402
from app.services.strategies.momentum_quality_rotation import (  # noqa: E402
    MomentumQualityRotation,
)
from app.services.strategies.sector_scanner_top5_rotation import (  # noqa: E402
    SectorScannerTop5Rotation,
)
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter  # noqa: E402
from app.utils.security import get_safe_table_name  # noqa: E402

CAPITAL = 100_000.0
SEED = 42
START_MIN = "2010-01-01"
START_MAX = "2024-01-01"
OUT_DIR = Path("/tmp/top5_validate")
OUT_DIR.mkdir(exist_ok=True)

STRATEGIES = {
    "SectorScannerTop5Rotation": SectorScannerTop5Rotation,
    "MomentumQualityRotation": MomentumQualityRotation,
}
ALLOWED_REASONS = {"Stop Loss", "Trailing Stop", "Take Profit", "Time Stop",
                   "Rotated Out", "New Entry"}
METRICS = ["cagr_pct", "alpha_per_year_pct", "sharpe_ratio", "max_drawdown_pct",
           "trades_per_year", "win_rate", "profit_factor"]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def dump(name, obj):
    p = OUT_DIR / f"{name}.json"
    with open(p, "w") as f:
        json.dump(obj, f, indent=2, default=str)
    log(f"wrote {p}")


# ─────────────────────────────────────────────────────────────────────
# PHASE A — shared artifacts
# ─────────────────────────────────────────────────────────────────────
def build_shared(end):
    t0 = time.time()
    with db_engine.connect() as conn:
        spy = pd.read_sql(
            f'SELECT "Date" FROM spy WHERE "Date" >= \'{START_MIN}\' '
            f'AND "Date" <= \'{end}\' ORDER BY "Date"',
            conn,
        )
    full_dates = [str(d)[:10] for d in spy["Date"]]
    log(f"calendar: {len(full_dates)} trading days {full_dates[0]}..{full_dates[-1]} "
        f"({time.time()-t0:.1f}s)")

    # Structural precondition for sharing one signal cache. If this ever fails,
    # the batch would silently feed one strategy the other's signals.
    assert (MomentumQualityRotation.precompute_signals
            is SectorScannerTop5Rotation.precompute_signals), (
        "MomentumQualityRotation overrides precompute_signals; a shared signal "
        "cache would be wrong")
    assert (MomentumQualityRotation.get_signals
            is SectorScannerTop5Rotation.get_signals)
    assert (MomentumQualityRotation.score_holding
            is SectorScannerTop5Rotation.score_holding)

    t0 = time.time()
    engine_strategy = SectorScannerTop5Rotation()
    signals = engine_strategy.precompute_signals(full_dates, db_engine)
    assert signals is not None, "precompute_signals returned None"
    price_cache = engine_strategy.get_precomputed_price_cache()
    log(f"precompute_signals: {time.time()-t0:.1f}s  tickers={len(price_cache)}  "
        f"dates_with_candidates={sum(1 for v in signals.values() if v)}/{len(full_dates)}")

    t0 = time.time()
    score_map = engine_strategy.precompute_scores(full_dates, db_engine)
    log(f"precompute_scores: {time.time()-t0:.1f}s  tickers={len(score_map or {})}")

    t0 = time.time()
    bars, lookback = {}, (pd.Timestamp(START_MIN) - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    open_cache, open_dates_cache = {}, {}
    for tk in list(price_cache.keys()):
        try:
            safe = get_safe_table_name(tk)
            with db_engine.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Open", "Close" FROM "{safe}" '
                    f'WHERE "Date" >= \'{lookback}\' AND "Date" <= \'{end}\' '
                    f'ORDER BY "Date" ASC', conn)
            if df.empty:
                continue
            dates = df["Date"].astype(str).str[:10].tolist()
            opens = df["Open"].astype(float).tolist()
            bars[tk] = {"dates": dates, "open": opens,
                        "close": df["Close"].astype(float).tolist()}
            # Shared next-open cache: built once for the whole batch instead of
            # once per run (the adapter otherwise re-queries every ticker).
            open_cache[tk] = dict(zip(dates, opens))
            open_dates_cache[tk] = dates
        except Exception:
            continue
    log(f"independent bars + shared open cache: {len(bars)} tickers "
        f"({time.time()-t0:.1f}s)")

    with db_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT ticker, sector, market_cap FROM stock_metadata")).fetchall()
    meta = {str(r[0]).lower(): {"sector": r[1], "market_cap": r[2]} for r in rows}
    return (full_dates, signals, price_cache, score_map, bars, meta,
            open_cache, open_dates_cache)


# ─────────────────────────────────────────────────────────────────────
# Fill helpers (independent of the adapter)
# ─────────────────────────────────────────────────────────────────────
def next_open_after(bars_t, date_str):
    """First bar strictly after date_str with a positive Open, else None."""
    if not bars_t:
        return None
    dates, opens = bars_t["dates"], bars_t["open"]
    pos = int(np.searchsorted(np.array(dates), date_str, side="right"))
    for i in range(pos, len(dates)):
        o = opens[i]
        if o is not None and np.isfinite(o) and o > 0:
            return float(o)
    return None


def close_on_or_before(bars_t, date_str, max_back_days=10):
    """Last close on/before date_str within max_back_days (mirrors the adapter)."""
    if not bars_t:
        return None
    dates, closes = bars_t["dates"], bars_t["close"]
    pos = int(np.searchsorted(np.array(dates), date_str, side="right")) - 1
    if pos < 0:
        return None
    if (pd.Timestamp(date_str) - pd.Timestamp(dates[pos])).days > max_back_days:
        return None
    c = closes[pos]
    return float(c) if np.isfinite(c) and c > 0 else None


# ─────────────────────────────────────────────────────────────────────
# PHASE B — the batch
# ─────────────────────────────────────────────────────────────────────
def random_starts(n):
    """n DISTINCT random start dates (sampled without replacement).

    The historical harness used random.randint per run, which occasionally drew
    the same date twice (100 draws -> 99 unique). Both strategies are given the
    same list, so their comparison stays paired.
    """
    random.seed(SEED)
    a = datetime.strptime(START_MIN, "%Y-%m-%d")
    b = datetime.strptime(START_MAX, "%Y-%m-%d")
    span = (b - a).days
    offsets = random.sample(range(span + 1), n)
    return [(a + timedelta(days=o)).strftime("%Y-%m-%d") for o in offsets]


def downsample(curve, max_points=500):
    if len(curve) <= max_points:
        return curve
    n = len(curve)
    step = n / (max_points - 2)
    idx = [0] + [min(int(i * step), n - 1) for i in range(1, max_points - 1)] + [n - 1]
    return [curve[i] for i in sorted(set(idx))]


def run_batch(name, cls, full_dates, signals, price_cache, score_map, starts, end,
              capital, meta, open_cache, open_dates_cache):
    strategy = cls()
    strategy._score_map = score_map          # fast causal score lookups
    strategy._price_cache = price_cache
    experiments, raw, trades_by_start, audits = [], [], {}, []
    t_all = time.time()
    for i, start in enumerate(starts):
        run_signals = {d: signals.get(d, []) for d in full_dates if d >= start}
        t0 = time.time()
        try:
            res = StrategyBacktestAdapter(strategy).run(
                as_of=start, end=end, capital=capital,
                precomputed_signals=run_signals, price_cache=price_cache,
                open_cache=open_cache, open_dates_cache=open_dates_cache,
            )
            k = res["summary"]
            experiments.append({
                "run_index": i + 1, "status": "completed", "kpis": k,
                "equity_curve": downsample(res.get("daily_equity", [])),
                "start_date": start, "end_date": end,
            })
            raw.append(k)
            trades_by_start[start] = res["trades"]
            # Audit while the full equity curve is in hand (not stored: 200 runs
            # of daily equity would be hundreds of MB).
            audits.append({"strategy": name,
                           **audit_run(start, end, res["trades"],
                                       res["daily_equity"], meta)})
            log(f"  {name[:12]} {i+1:3d}/{len(starts)} {start} "
                f"cagr={k['cagr_pct']:7.2f}% shp={k['sharpe_ratio']:5.2f} "
                f"dd={k['max_drawdown_pct']:5.1f}% trd={k['total_trades']:4d} "
                f"({time.time()-t0:.1f}s)")
        except Exception as e:
            experiments.append({
                "run_index": i + 1, "status": "failed",
                "error_message": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                "start_date": start, "end_date": end,
            })
            log(f"  {name[:12]} {i+1:3d} {start} FAILED: {e}")
    log(f"{name}: batch done in {time.time()-t_all:.1f}s")
    return experiments, raw, trades_by_start, audits


# ─────────────────────────────────────────────────────────────────────
# PHASE C — lookahead / causality tests
# ─────────────────────────────────────────────────────────────────────
def _trade_key(t):
    return (t["ticker"], t["side"], t["entry_date"], t["exit_date"],
            t["entry_price"], t["exit_price"], t["return_pct"],
            t["pnl_dollars"], t["exit_reason"])


def t1_end_truncation(cls, name, full_dates, signals, price_cache, score_map,
                      starts, cutoff, end, open_cache, open_dates_cache):
    """Trades decided before `cutoff` must not change when the run ends at `cutoff`."""
    out = {"test": "T1_end_truncation_invariance", "applies_to": name,
           "cutoff": cutoff, "cases": []}
    # The truncated run must not be able to fill beyond its own end date, so give
    # it a cutoff-bounded open cache rather than the full-range one.
    trunc_open = {tk: {d: v for d, v in m.items() if d <= cutoff}
                  for tk, m in open_cache.items()}
    trunc_open_dates = {tk: [d for d in ds if d <= cutoff]
                        for tk, ds in open_dates_cache.items()}
    for start in starts:
        strategy = cls()
        strategy._score_map = score_map
        strategy._price_cache = price_cache
        full = StrategyBacktestAdapter(strategy).run(
            as_of=start, end=end, capital=CAPITAL,
            precomputed_signals={d: signals.get(d, []) for d in full_dates if d >= start},
            price_cache=price_cache,
            open_cache=open_cache, open_dates_cache=open_dates_cache)["trades"]
        trunc = StrategyBacktestAdapter(strategy).run(
            as_of=start, end=cutoff, capital=CAPITAL,
            precomputed_signals={d: signals.get(d, []) for d in full_dates
                                 if start <= d <= cutoff},
            price_cache=price_cache,
            open_cache=trunc_open, open_dates_cache=trunc_open_dates)["trades"]
        a = sorted(_trade_key(t) for t in full
                   if t["side"] == "SELL" and t["exit_date"] < cutoff)
        b = sorted(_trade_key(t) for t in trunc
                   if t["side"] == "SELL" and t["exit_date"] < cutoff)
        a2 = sorted(_trade_key(t) for t in full
                    if t["side"] == "BUY" and t["entry_date"] < cutoff)
        b2 = sorted(_trade_key(t) for t in trunc
                    if t["side"] == "BUY" and t["entry_date"] < cutoff)
        diff = sorted(set(a) ^ set(b) | set(a2) ^ set(b2))
        out["cases"].append({
            "start": start,
            "closed_full": len(a), "closed_trunc": len(b),
            "buys_full": len(a2), "buys_trunc": len(b2),
            "n_symmetric_diff": len(diff),
            "first_diff": diff[:1],
        })
        log(f"  T1 {name[:12]} start={start} closed {len(a)}/{len(b)} "
            f"buys {len(a2)}/{len(b2)} diffs={len(diff)}")
    out["pass"] = all(c["n_symmetric_diff"] == 0 for c in out["cases"])
    return out


def t2_signal_prefix(cls, name, end):
    """Signals for dates <= cutoff must be identical with/without later bars."""
    cutoff, first = "2023-12-29", "2020-01-02"
    with db_engine.connect() as conn:
        spy = pd.read_sql(
            f'SELECT "Date" FROM spy WHERE "Date" >= \'{first}\' AND "Date" <= \'{end}\' '
            f'ORDER BY "Date"', conn)
    all_dates = [str(d)[:10] for d in spy["Date"]]
    short_dates = [d for d in all_dates if d <= cutoff]

    s_full = cls().precompute_signals(all_dates, db_engine)
    s_trunc = cls().precompute_signals(short_dates, db_engine)

    def sig_list(sigs):
        return [(s.ticker, s.score, round(float(s.price), 4)) for s in sigs]

    diffs, examples = 0, []
    for d in short_dates:
        a, b = sig_list(s_full.get(d, [])), sig_list(s_trunc.get(d, []))
        if a != b:
            diffs += 1
            if len(examples) < 3:
                sa, sb = set(a), set(b)
                examples.append({"date": d, "n_full": len(a), "n_trunc": len(b),
                                 "only_full": sorted(sa - sb)[:5],
                                 "only_trunc": sorted(sb - sa)[:5]})
    log(f"  T2 {name}: {len(short_dates) - diffs}/{len(short_dates)} dates identical")
    return {"test": "T2_signal_prefix_stability", "applies_to": name,
            "cutoff": cutoff, "first_date": first,
            "dates_checked": len(short_dates), "dates_differing": diffs,
            "examples": examples, "pass": diffs == 0}


def t3_perday_parity(cls, name, signals, sample_dates):
    """get_signals(d) must equal precomputed_signals[d] (ticker, score, price)."""
    strat = cls()
    cases = []
    for d in sample_dates:
        if d not in signals:
            continue
        live = strat.get_signals(d, db_engine)
        lv = sorted((s.ticker, s.score, round(float(s.price), 4)) for s in live)
        pv = sorted((s.ticker, s.score, round(float(s.price), 4)) for s in signals[d])
        sl, sp = set(lv), set(pv)
        cases.append({"date": d, "n_live": len(lv), "n_precomputed": len(pv),
                      "only_live": sorted(sl - sp)[:5],
                      "only_pre": sorted(sp - sl)[:5],
                      "identical": lv == pv})
        log(f"  T3 {d} live={len(lv)} pre={len(pv)} identical={lv == pv}")
    return {"test": "T3_perday_vs_precomputed", "applies_to": name,
            "cases": cases, "pass": all(c["identical"] for c in cases)}


def t4_score_causality(cls, name, score_map, sample):
    """Cached score must equal the per-day SQL score for the same date."""
    strat = cls()
    cases = []
    for tk, d in sample:
        strat._score_map = score_map
        cached = strat.score_holding(tk, d, db_engine, 0.0, 0.0, "Unknown")
        strat._score_map = None
        live = strat.score_holding(tk, d, db_engine, 0.0, 0.0, "Unknown")
        cases.append({"ticker": tk, "date": d, "cached": cached, "live": live,
                      "delta": abs(cached - live)})
    strat._score_map = score_map
    ok = all(c["delta"] < 1e-9 for c in cases)
    log(f"  T4 {name}: {sum(c['delta'] < 1e-9 for c in cases)}/{len(cases)} match")
    return {"test": "T4_score_holding_causality", "applies_to": name,
            "cases": cases, "pass": ok}


def t5_fill_verification(named_trades, bars):
    """Every fill price must equal the real next-session OPEN from Postgres."""
    out = {"test": "T5_fill_price_verification", "runs_checked": 0,
           "fills_checked": 0, "mismatches": [], "close_fallbacks": 0,
           "same_day_close_fills": 0, "next_open_fills": 0}
    for label, trades in named_trades:
        out["runs_checked"] += 1
        for t in trades:
            tk = t["ticker"].lower()
            bt = bars.get(tk)
            ref = t["entry_date"] if t["side"] == "BUY" else t["exit_date"]
            nopen = next_open_after(bt, ref)
            if nopen is not None:
                expected = round(nopen, 2)
                out["next_open_fills"] += 1
            else:
                expected = round(close_on_or_before(bt, ref) or 0.0, 2)
                out["close_fallbacks"] += 1
            actual = t["entry_price"] if t["side"] == "BUY" else t["exit_price"]
            out["fills_checked"] += 1
            if abs(actual - expected) > 0.011:
                out["mismatches"].append({
                    "run": label, "side": t["side"], "ticker": t["ticker"],
                    "ref_date": ref, "recorded": actual, "expected": expected})
            same_close = close_on_or_before(bt, ref)
            if (nopen is None and same_close is not None
                    and abs(actual - round(same_close, 2)) < 0.011):
                out["same_day_close_fills"] += 1
    out["pass"] = len(out["mismatches"]) == 0
    out["mismatches"] = out["mismatches"][:20]
    log(f"  T5 fills={out['fills_checked']} next_open={out['next_open_fills']} "
        f"mismatches={len(out['mismatches'])} fallbacks={out['close_fallbacks']}")
    return out


# ─────────────────────────────────────────────────────────────────────
# PHASE D — trade validity audit
# ─────────────────────────────────────────────────────────────────────
def audit_run(start, end, trades, equity, meta, max_holdings=5, sector_cap=2,
              cost_bps=0.0):
    issues = []
    sells = [t for t in trades if t["side"] == "SELL"]
    buys = [t for t in trades if t["side"] == "BUY"]
    # Recorded returns are net of both fills; the audit must use the same cost
    # model or every trade in a costed run looks inconsistent.
    c = float(cost_bps) / 10_000.0

    for t in trades:
        if t["side"] not in ("BUY", "SELL"):
            issues.append(f"bad side {t['side']}")
        if t["exit_reason"] not in ALLOWED_REASONS:
            issues.append(f"unknown exit_reason {t['exit_reason']}")
        if t["side"] == "BUY":
            if t["exit_date"] != "" or t["exit_price"] != 0:
                issues.append(f"BUY carries exit fields {t['ticker']} {t['entry_date']}")
        else:
            if t["entry_price"] <= 0 or t["exit_price"] <= 0:
                issues.append(f"nonpositive price {t['ticker']} {t['entry_date']}")
            if t["exit_date"] < t["entry_date"]:
                issues.append(f"exit before entry {t['ticker']} {t['entry_date']}")
            exp_hd = (pd.Timestamp(t["exit_date"]) - pd.Timestamp(t["entry_date"])).days
            if t["holding_days"] != exp_hd:
                issues.append(f"holding_days {t['holding_days']} != {exp_hd} "
                              f"({t['ticker']} {t['entry_date']}->{t['exit_date']})")
            exp_ret = (t["exit_price"] / t["entry_price"] - 1.0
                       - c * (1.0 + t["exit_price"] / t["entry_price"])) * 100.0
            # entry/exit prices are rounded to 2dp independently, so a return
            # recomputed from them differs by at most half a cent per leg --
            # plus a small epsilon for the cost cross-term and the 2dp rounding
            # of the recorded percentage itself. This is a tolerance, not a
            # proof: `shares` is not in the trade record, so the identity can
            # only be checked to within price rounding.
            tol = max(0.10,
                      0.5 / t["entry_price"]
                      + 0.5 * t["exit_price"] / t["entry_price"] ** 2
                      + 0.05)
            if abs(exp_ret - t["return_pct"]) > tol:
                issues.append(f"return_pct {t['return_pct']} != implied {exp_ret:.2f} "
                              f"(tol {tol:.2f}) "
                              f"({t['ticker']} {t['entry_date']}->{t['exit_date']})")
        if not (start <= t["entry_date"] <= end):
            issues.append(f"entry_date {t['entry_date']} outside run")
        if t["side"] == "SELL" and not (start <= t["exit_date"] <= end):
            issues.append(f"exit_date {t['exit_date']} outside run")

    # FIFO open/close matching
    open_pos, overlap, orphan_sells = {}, 0, 0
    for t in trades:
        if t["side"] == "BUY":
            if t["ticker"] in open_pos:
                overlap += 1
            open_pos[t["ticker"]] = t["entry_date"]
        else:
            if t["ticker"] not in open_pos:
                orphan_sells += 1
            else:
                if open_pos[t["ticker"]] != t["entry_date"]:
                    issues.append(f"close does not match open {t['ticker']}")
                open_pos.pop(t["ticker"], None)
    if overlap:
        issues.append(f"{overlap} BUY(s) while already holding that ticker")
    if orphan_sells:
        issues.append(f"{orphan_sells} SELL(s) with no open position")

    # Chronological slot / sector concurrency (exits processed before entries,
    # mirroring the adapter's within-day order).
    by_date = {}
    for t in trades:
        side = "sell" if t["side"] == "SELL" else "buy"
        key = t["exit_date"] if side == "sell" else t["entry_date"]
        by_date.setdefault(key, {"buy": [], "sell": []})[side].append(t)
    held, max_conc, max_sector_conc, excess, churn = {}, 0, 0, [], 0
    equity_by_date = {e["date"]: e for e in equity}
    for d in sorted(by_date):
        sold_today = set()
        for t in by_date[d]["sell"]:
            held.pop(t["ticker"], None)
            sold_today.add(t["ticker"])
        for t in by_date[d]["buy"]:
            if t["ticker"] in sold_today:
                churn += 1
            held[t["ticker"]] = t["ticker"]
        n = len(held)
        max_conc = max(max_conc, n)
        if n > max_holdings:
            excess.append((d, n))
        sec_counts = {}
        for tk in held:
            s = (meta.get(tk.lower()) or {}).get("sector") or "Unknown"
            sec_counts[s] = sec_counts.get(s, 0) + 1
        if sec_counts:
            max_sector_conc = max(max_sector_conc, max(sec_counts.values()))
        eq = equity_by_date.get(d)
        if eq is not None and eq["n_holdings"] != n:
            issues.append(f"equity n_holdings {eq['n_holdings']} != reconstructed {n} on {d}")

    if max_conc > max_holdings:
        issues.append(f"max concurrent holdings {max_conc} > {max_holdings} on "
                      f"{len(excess)} date(s)")

    # SOFT findings: the sector cap is a cap on SELECTION, not a portfolio
    # invariant. min_hold_days can keep a same-sector name that has left the
    # hold band, while a fresh same-sector name is bought from top_n, so up to
    # 2 held + 2 new = 4 can coexist. Reported, not counted as a defect.
    soft = []
    if max_sector_conc > sector_cap:
        soft.append(f"max concurrent per-sector {max_sector_conc} > {sector_cap} "
                    f"(min_hold can hold names the cap would exclude; sector from "
                    f"CURRENT metadata)")

    for e in equity:
        if e["cash"] < -0.01:
            issues.append(f"negative cash {e['cash']} on {e['date']}")
        if abs((e["cash"] + e["holdings"]) - e["value"]) > 0.05:
            issues.append(f"equity identity broken on {e['date']}")

    return {"start": start, "end": end, "n_buys": len(buys), "n_sells": len(sells),
            "open_at_end": len(open_pos), "max_concurrent": max_conc,
            "max_sector_concurrent": max_sector_conc,
            "same_day_exit_reentry": churn,
            "issues": issues[:25], "n_issues": len(issues),
            "soft_findings": soft}


# ─────────────────────────────────────────────────────────────────────
# Distribution stats
# ─────────────────────────────────────────────────────────────────────
def dist(raw):
    out = {}
    for m in METRICS:
        vals = [r[m] for r in raw if r.get(m) is not None]
        if not vals:
            continue
        a = np.array(vals, dtype=float)
        out[m] = {"n": len(vals), "mean": round(float(a.mean()), 3),
                  "median": round(float(np.median(a)), 3),
                  "p10": round(float(np.percentile(a, 10)), 3),
                  "p25": round(float(np.percentile(a, 25)), 3),
                  "p75": round(float(np.percentile(a, 75)), 3),
                  "p90": round(float(np.percentile(a, 90)), 3),
                  "min": round(float(a.min()), 3), "max": round(float(a.max()), 3)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--end", default=None, help="default: latest SPY bar in DB")
    ap.add_argument("--skip-heavy", action="store_true",
                    help="skip T2 (two mid-range precomputes)")
    args = ap.parse_args()

    if args.end:
        end = args.end
    else:
        with db_engine.connect() as conn:
            end = str(conn.execute(text('SELECT MAX("Date") FROM spy')).scalar())[:10]
    log(f"END = {end}   runs = {args.runs}   seed = {SEED}")

    (full_dates, signals, price_cache, score_map, bars, meta,
     open_cache, open_dates_cache) = build_shared(end)
    starts = random_starts(args.runs)
    log(f"start dates: {len(set(starts))} unique, {min(starts)} .. {max(starts)}")

    report = {
        "config": {"end": end, "start_min": START_MIN, "start_max": START_MAX,
                   "n_runs": args.runs, "seed": SEED, "capital": CAPITAL,
                   "ends_identical_for_all_runs": True,
                   "starts": starts,
                   "generated_at": datetime.now(timezone.utc).isoformat()},
        "shared": {"trading_days": len(full_dates),
                   "tickers_in_price_cache": len(price_cache),
                   "dates_with_candidates": sum(1 for v in signals.values() if v),
                   "signal_engine_shared_by_both": True},
    }

    # ── PHASE B
    log("=== PHASE B: batch ===")
    batch, all_audits = {}, []
    for name, cls in STRATEGIES.items():
        exps, raw, trades_by_start, audits = run_batch(
            name, cls, full_dates, signals, price_cache, score_map, starts,
            end, CAPITAL, meta, open_cache, open_dates_cache)
        batch[name] = {"experiments": exps, "raw": raw, "trades": trades_by_start}
        all_audits.extend(audits)
        report.setdefault("batch", {})[name] = {
            "n_runs": len(raw),
            "n_failed": sum(1 for e in exps if e["status"] == "failed"),
            "distribution": dist(raw)}
        dump(f"batch_{name}", {"experiments": exps})
        dump(f"trades_{name}", trades_by_start)

    paired = {"note": "same 100 starts; only exits/regime differ"}
    a, b = batch["SectorScannerTop5Rotation"]["raw"], batch["MomentumQualityRotation"]["raw"]
    if len(a) == len(b):
        keys = {"cagr_pct": "delta_cagr", "sharpe_ratio": "delta_sharpe",
                "max_drawdown_pct": "delta_maxdd"}
        for mk, dk in keys.items():
            d = [round(y[mk] - x[mk], 3) for x, y in zip(a, b)]
            paired[dk] = {"median": round(st.median(d), 3),
                          "wins_mqr": sum(1 for z in d if z > 0), "n": len(d),
                          "min": min(d), "max": max(d)}
    report["paired_mqr_vs_scanner"] = paired
    dump("report_partial_after_batch", report)

    # ── PHASE C
    log("=== PHASE C: lookahead / causality ===")
    cutoff = "2023-12-29"
    t1_starts = [starts[0], starts[len(starts) // 2], starts[-1]]
    report["lookahead"] = []
    for name, cls in STRATEGIES.items():
        report["lookahead"].append(
            t1_end_truncation(cls, name, full_dates, signals, price_cache,
                              score_map, t1_starts, cutoff, end,
                              open_cache, open_dates_cache))
        dump("report_partial_after_t1", report)

    if not args.skip_heavy:
        report["lookahead"].append(
            t2_signal_prefix(SectorScannerTop5Rotation, "shared signal engine", end))
        dump("report_partial_after_t2", report)

    sample_dates = [d for d in ["2012-06-01", "2015-06-01", "2018-06-01",
                                "2020-06-01", "2022-06-01", "2024-06-03"]
                    if d in signals]
    report["lookahead"].append(
        t3_perday_parity(SectorScannerTop5Rotation, "shared signal engine",
                         signals, sample_dates))

    sample = []
    for d in sample_dates:
        for s in signals.get(d, [])[:2]:
            sample.append((s.ticker, d))
    report["lookahead"].append(
        t4_score_causality(SectorScannerTop5Rotation, "shared signal engine",
                           score_map, sample[:12]))

    named = []
    for name, payload in batch.items():
        for start in (starts[0], starts[len(starts) // 2], starts[-1]):
            if start in payload["trades"]:
                named.append((f"{name}@{start}", payload["trades"][start]))
    report["lookahead"].append(t5_fill_verification(named, bars))
    dump("report_partial_after_lookahead", report)

    # ── PHASE D
    log("=== PHASE D: trade validity audit ===")
    audits = all_audits
    by_strat = {}
    for name in STRATEGIES:
        rows = [x for x in audits if x["strategy"] == name]
        by_strat[name] = {
            "n_runs": len(rows),
            "runs_with_issues": sum(1 for r in rows if r["n_issues"]),
            "total_issues": sum(r["n_issues"] for r in rows),
            "sector_cap_max_concurrent": max(r["max_sector_concurrent"] for r in rows),
            "max_concurrent_holdings": max(r["max_concurrent"] for r in rows),
            "same_day_exit_reentry_total": sum(r["same_day_exit_reentry"] for r in rows),
            "same_day_exit_reentry_runs": sum(1 for r in rows if r["same_day_exit_reentry"]),
            "same_day_reentry_per_100_sells": round(
                100.0 * sum(r["same_day_exit_reentry"] for r in rows)
                / max(1, sum(r["n_sells"] for r in rows)), 2),
            "buy_count": sum(r["n_buys"] for r in rows),
            "sell_count": sum(r["n_sells"] for r in rows),
            "open_at_end_total": sum(r["open_at_end"] for r in rows),
            "sample_issues": [i for r in rows for i in r["issues"]][:30],
            "sample_soft_findings": sorted({s for r in rows for s in r["soft_findings"]})[:5]}
    report["trade_audit"] = by_strat
    report["trade_audit_runs"] = audits
    dump("report_partial_after_audit", report)

    # ── PHASE E
    log("=== PHASE E: HTML run viewers ===")
    try:
        from app.services.run_viewer_generator import generate_run_viewer
        paths = {}
        for name, cls in STRATEGIES.items():
            src = Path(sys.modules[cls.__module__].__file__).read_text()
            paths[name] = generate_run_viewer(
                batch[name]["experiments"],
                strategy_name=f"{name} -- {args.runs}-run validation",
                strategy_code=src,
                strategy_params={
                    "End (same for all runs)": end,
                    "Start range": f"{START_MIN} .. {START_MAX} (random, seed {SEED})",
                    "Runs": args.runs, "Capital": CAPITAL,
                    "Signal engine": "shared precompute",
                    "Fills": "next session OPEN",
                    "Cost": "0 bps per side (baseline)"},
            )
            log(f"report: {paths[name]}")
        report["html_reports"] = paths
    except Exception as e:
        report["html_reports"] = {"error": f"{type(e).__name__}: {e}"}
        log(f"report generation failed: {e}")

    # ── verdict
    la = report["lookahead"]
    report["verdict"] = {
        "T1_end_truncation": all(x.get("pass") for x in la
                                 if x["test"].startswith("T1")),
        "T2_signal_prefix": next((x["pass"] for x in la
                                  if x["test"].startswith("T2")), None),
        "T3_perday_parity": next((x["pass"] for x in la
                                  if x["test"].startswith("T3")), None),
        "T4_score_causality": next((x["pass"] for x in la
                                    if x["test"].startswith("T4")), None),
        "T5_fills": next((x["pass"] for x in la
                          if x["test"].startswith("T5")), None),
        "trade_audit_clean": all(v["total_issues"] == 0
                                 for v in report["trade_audit"].values()),
    }
    dump("VALIDATION_REPORT", report)
    log("verdict: " + json.dumps(report["verdict"]))
    log("DONE")


if __name__ == "__main__":
    main()
