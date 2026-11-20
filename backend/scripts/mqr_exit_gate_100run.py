"""Stage 0.5: do simple, transparent exit-veto rules beat the MQR baseline?

Method (the only one this repo trusts): the full StrategyBacktestAdapter, 100
distinct start dates with a common end, paired per start, length-normalized
metrics, 0 and 10 bps. Frozen-entry replay is NOT used: it cannot price the
slot opportunity cost of holding instead of rotating.

Usage:
    cd backend && ./venv/bin/python scripts/mqr_exit_gate_100run.py --runs 100
    ... --gates veto_all_trail,veto_trail_if_in_profit   # subset
    ... --costs 0,10
"""
import argparse
import json
import statistics as st
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Import first: loads ../.env before any app module reads DB_PASSWORD.
from validate_top5_100run import build_shared, random_starts  # noqa: E402

from app.services.exit_gate.rules import RuleGate, make_rule_gates  # noqa: E402
from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation  # noqa: E402
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter  # noqa: E402

CAPITAL = 100_000.0
METRICS = ("cagr_pct", "alpha_per_year_pct", "sharpe_ratio",
           "max_drawdown_pct", "trades_per_year")
OUT = Path("/tmp/mqr_exit_gate")
OUT.mkdir(exist_ok=True)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_variant(name, gate_factory, starts, shared, end, cost_bps):
    full_dates, signals, price_cache, score_map, _, _, open_cache, open_dates = shared
    rows, stats_tot = [], {"consultations": 0, "vetoes": 0, "fail_open": 0}
    t0 = time.time()
    for start in starts:
        strat = MomentumQualityRotation(cost_bps=float(cost_bps))
        strat._score_map = score_map
        strat._price_cache = price_cache
        res = StrategyBacktestAdapter(strat, exit_gate=gate_factory()).run(
            as_of=start, end=end, capital=CAPITAL,
            precomputed_signals={d: signals.get(d, []) for d in full_dates if d >= start},
            price_cache=price_cache,
            open_cache=open_cache, open_dates_cache=open_dates,
        )
        rows.append(res["summary"])
        gs = res.get("gate_stats") or {}
        for k in stats_tot:
            stats_tot[k] += gs.get(k, 0) or 0
    log(f"  {name} @ {cost_bps}bps: {len(rows)} runs in {time.time()-t0:.1f}s")
    return {"rows": rows, "gate_stats": stats_tot}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--costs", default="0")
    ap.add_argument("--gates", default="all")
    ap.add_argument("--young-thresholds", default="",
                    help="extra 'no trail before N days' gates, e.g. 5,7,10,14")
    ap.add_argument("--llm-model", default=None,
                    help="add an LLM gate variant, e.g. qwen3:8b")
    ap.add_argument("--llm-mode", default="exit_confidence",
                    choices=("exit_confidence", "hold_confidence"))
    ap.add_argument("--llm-threshold", type=float, default=0.80)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    end = args.end or str(datetime.utcnow().date())
    if args.end is None:
        from app.db.database import engine
        from sqlalchemy import text
        with engine.connect() as c:
            end = str(c.execute(text('SELECT MAX("Date") FROM spy')).scalar())[:10]
    costs = [int(float(c)) for c in args.costs.split(",")]
    gates = make_rule_gates()
    if args.gates == "none":
        gates = {}
    elif args.gates != "all":
        gates = {k: gates[k] for k in args.gates.split(",")}
    for t in [x for x in args.young_thresholds.split(",") if x]:
        days = int(t)
        gates[f"veto_trail_young{days}"] = RuleGate(
            f"rule:veto_trail_young{days}",
            {"trailing_stop": lambda c, _d=days: c.hold_days < _d})

    llm_cache = None
    if args.llm_model:
        from app.services.exit_gate.cache import DecisionCache
        from app.services.exit_gate.llm_gate import LLMExitGate
        from app.services.exit_gate.ollama import make_completer
        llm_cache = DecisionCache(
            Path(__file__).resolve().parent.parent / "data" / "exit_gate_llm_cache.sqlite")
        complete = make_completer(args.llm_model, think=False, max_tokens=256)
        gates[f"llm_{args.llm_mode}"] = LLMExitGate(
            complete, args.llm_model, llm_cache, threshold=args.llm_threshold,
            prompt_version=f"adapter-{args.llm_mode}", mode=args.llm_mode)

    log(f"END={end} runs={args.runs} costs={costs} gates={len(gates)+1}")
    shared = build_shared(end)
    starts = random_starts(args.runs)
    log(f"{len(set(starts))} distinct starts, {min(starts)}..{max(starts)}")

    out = {"config": {"end": end, "runs": args.runs, "costs": costs,
                      "starts": starts,
                      "generated_at": datetime.now(timezone.utc).isoformat()},
           "variants": {}}

    for cost in costs:
        base = run_variant("baseline", lambda: None, starts, shared, end, cost)
        out["variants"][f"baseline@{cost}"] = {
            "gate_stats": base["gate_stats"],
            "median": {m: round(st.median([r[m] for r in base["rows"]]), 3)
                       for m in METRICS},
        }
        base_cagr = [r["cagr_pct"] for r in base["rows"]]

        for name, gate in gates.items():
            res = run_variant(name, lambda g=gate: g, starts, shared, end, cost)
            d_cagr = [r["cagr_pct"] - b for r, b in zip(res["rows"], base_cagr)]
            d_sharpe = [r["sharpe_ratio"] - b["sharpe_ratio"]
                        for r, b in zip(res["rows"], base["rows"])]
            d_dd = [r["max_drawdown_pct"] - b["max_drawdown_pct"]
                    for r, b in zip(res["rows"], base["rows"])]
            d_tpy = [r["trades_per_year"] - b["trades_per_year"]
                     for r, b in zip(res["rows"], base["rows"])]
            entry = {
                "gate_stats": res["gate_stats"],
                "median": {m: round(st.median([r[m] for r in res["rows"]]), 3)
                           for m in METRICS},
                "delta_cagr": {"median": round(st.median(d_cagr), 3),
                               "wins": sum(1 for x in d_cagr if x > 0),
                               "n": len(d_cagr),
                               "min": round(min(d_cagr), 2),
                               "max": round(max(d_cagr), 2)},
                "delta_sharpe": {"median": round(st.median(d_sharpe), 3),
                                 "wins": sum(1 for x in d_sharpe if x > 0)},
                "delta_maxdd": {"median": round(st.median(d_dd), 3),
                                "better": sum(1 for x in d_dd if x < 0)},
                "delta_trades_per_year": round(st.median(d_tpy), 3),
            }
            out["variants"][f"{name}@{cost}"] = entry
            gs = entry["gate_stats"]
            rate = (gs["vetoes"] / gs["consultations"] * 100
                    if gs["consultations"] else 0.0)
            log(f"    cagr {entry['delta_cagr']['median']:+6.2f} pts "
                f"(wins {entry['delta_cagr']['wins']}/{entry['delta_cagr']['n']})  "
                f"sharpe {entry['delta_sharpe']['median']:+.3f}  "
                f"maxdd {entry['delta_maxdd']['median']:+.2f}  "
                f"veto {rate:.1f}%  fail-open {gs['fail_open']}")
        with open(OUT / "stage0_5.json", "w") as f:
            json.dump(out, f, indent=2, default=str)

    log(f"wrote {OUT/'stage0_5.json'}")


if __name__ == "__main__":
    main()
