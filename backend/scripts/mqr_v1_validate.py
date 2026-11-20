"""Validate MomentumQualityRotationV1 against MQR on identical start dates.

Acceptance for V1:
  1. the class reproduces the gate experiment (trail delayed 7 days) — paired
     median delta near +7.56 pts at 10 bps, winning on ~73/100 starts;
  2. no lookahead: ending a run early leaves earlier trades identical;
  3. the trade audit is clean;
  4. costs are explicit at 10 bps.

Usage:
    cd backend && ./venv/bin/python scripts/mqr_v1_validate.py --runs 100
"""
import argparse
import json
import statistics as st
import sys
from datetime import datetime, timezone
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_top5_100run import (  # noqa: E402
    audit_run, build_shared, dist, random_starts,
)

from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation  # noqa: E402
from app.services.strategies.momentum_quality_rotation_v1 import MomentumQualityRotationV1  # noqa: E402
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter  # noqa: E402

CAPITAL = 100_000.0
OUT = Path("/tmp/mqr_exit_gate")
OUT.mkdir(exist_ok=True)


def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)


def sign_p(wins, n):
    return sum(comb(n, i) for i in range(wins, n + 1)) / 2 ** n


def run_all(cls, starts, shared, end, cost_bps):
    full_dates, signals, price_cache, score_map, bars, meta, oc, od = shared
    rows, trades, equity, audits = [], {}, {}, []
    for start in starts:
        strat = cls(cost_bps=cost_bps)
        strat._score_map = score_map
        strat._price_cache = price_cache
        res = StrategyBacktestAdapter(strat).run(
            as_of=start, end=end, capital=CAPITAL,
            precomputed_signals={d: signals.get(d, []) for d in full_dates if d >= start},
            price_cache=price_cache, open_cache=oc, open_dates_cache=od)
        rows.append(res["summary"])
        trades[start] = res["trades"]
        equity[start] = res["daily_equity"]
        audits.append(audit_run(start, end, res["trades"], res["daily_equity"],
                                meta, cost_bps=cost_bps))
    return rows, trades, equity, audits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--cost-bps", type=float, default=10.0)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    from sqlalchemy import text
    from app.db.database import engine
    end = args.end
    if end is None:
        with engine.connect() as c:
            end = str(c.execute(text('SELECT MAX("Date") FROM spy')).scalar())[:10]

    log(f"END={end} runs={args.runs} cost={args.cost_bps}bps")
    shared = build_shared(end)
    starts = random_starts(args.runs)
    log(f"{len(set(starts))} distinct starts")

    log("baseline MQR...")
    base, base_trades, _, _ = run_all(MomentumQualityRotation, starts, shared, end,
                                      args.cost_bps)
    log("MQR_V1...")
    v1, v1_trades, _, audits = run_all(MomentumQualityRotationV1, starts, shared, end,
                                       args.cost_bps)

    d_cagr = [a["cagr_pct"] - b["cagr_pct"] for a, b in zip(v1, base)]
    d_shp = [a["sharpe_ratio"] - b["sharpe_ratio"] for a, b in zip(v1, base)]
    d_dd = [a["max_drawdown_pct"] - b["max_drawdown_pct"] for a, b in zip(v1, base)]
    wins = sum(1 for x in d_cagr if x > 0)

    # Lookahead: end-truncation invariance on three starts.
    cutoff = "2023-12-29"
    full_dates, signals, price_cache, score_map, _, _, oc, od = shared
    trunc_ok, trunc_cases = True, []
    t_starts = [starts[0], starts[len(starts) // 2], starts[-1]]
    t_open = {tk: {d: v for d, v in m.items() if d <= cutoff} for tk, m in oc.items()}
    t_open_d = {tk: [d for d in ds if d <= cutoff] for tk, ds in od.items()}
    for start in t_starts:
        strat = MomentumQualityRotationV1(cost_bps=args.cost_bps)
        strat._score_map = score_map
        strat._price_cache = price_cache
        trunc = StrategyBacktestAdapter(strat).run(
            as_of=start, end=cutoff, capital=CAPITAL,
            precomputed_signals={d: signals.get(d, []) for d in full_dates
                                 if start <= d <= cutoff},
            price_cache=price_cache, open_cache=t_open, open_dates_cache=t_open_d)["trades"]
        a = sorted(tuple(sorted(t.items())) for t in v1_trades[start]
                   if t["side"] == "SELL" and t["exit_date"] < cutoff)
        b = sorted(tuple(sorted(t.items())) for t in trunc
                   if t["side"] == "SELL" and t["exit_date"] < cutoff)
        same = a == b
        trunc_ok = trunc_ok and same
        trunc_cases.append({"start": start, "closed_full": len(a),
                            "closed_trunc": len(b), "identical": same})
        log(f"  truncation {start}: {len(a)} vs {len(b)} identical={same}")

    issues = sum(x["n_issues"] for x in audits)
    result = {
        "config": {"end": end, "runs": args.runs, "cost_bps": args.cost_bps,
                   "generated_at": datetime.now(timezone.utc).isoformat()},
        "baseline": dist(base),
        "v1": dist(v1),
        "delta": {
            "cagr": {"median": round(st.median(d_cagr), 3), "wins": wins,
                     "n": len(d_cagr), "sign_p": round(sign_p(wins, len(d_cagr)), 6),
                     "min": round(min(d_cagr), 2), "max": round(max(d_cagr), 2)},
            "sharpe": {"median": round(st.median(d_shp), 3),
                       "wins": sum(1 for x in d_shp if x > 0)},
            "maxdd": {"median": round(st.median(d_dd), 3),
                      "better": sum(1 for x in d_dd if x < 0)},
        },
        "lookahead": {"end_truncation": trunc_cases, "pass": trunc_ok},
        "trade_audit": {"runs": len(audits), "hard_issues": issues,
                        "clean": issues == 0,
                        "sample": [i for a in audits for i in a["issues"]][:20]},
    }
    log("RESULT " + json.dumps(result["delta"], indent=2))
    log(f"lookahead pass={trunc_ok}  audit clean={issues == 0} ({issues} issues)")
    with open(OUT / "mqr_v1_validation.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    log(f"wrote {OUT/'mqr_v1_validation.json'}")


if __name__ == "__main__":
    main()
