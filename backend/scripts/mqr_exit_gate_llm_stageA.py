"""Stage A for the LLM arm: is a local model's veto decision better than chance,
and better than the simple rule that already won Stage 0.5?

Protocol
--------
1. Run baseline backtests with a RecordingGate to collect the REAL decision
   contexts (the questions the strategy actually faces), deduplicated.
2. Label each context with the slot-aware hindsight answer: would holding have
   beaten buying the best feasible candidate over H trading days?
3. Ask the local model on a stratified sample, with a threshold of 0 so its own
   willingness is measured rather than the gate's.
4. Compare the model's decision with the label, and with `hold_days < 10`
   (the Stage 0.5 winner) on the same sample.

AUC is computed without sklearn to keep this dependency-free.

Usage:
    cd backend && ./venv/bin/python scripts/mqr_exit_gate_llm_stageA.py --n 150
    ... --model qwen3:8b --horizon 20 --starts 20
"""
import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Import first: loads ../.env before any app module reads DB_PASSWORD.
from validate_top5_100run import build_shared, random_starts  # noqa: E402

from app.services.exit_gate.cache import DecisionCache  # noqa: E402
from app.services.exit_gate.llm_gate import LLMExitGate  # noqa: E402
from app.services.exit_gate.ollama import make_completer  # noqa: E402
from app.services.exit_gate.oracle import build_forward_returns  # noqa: E402
from app.services.exit_gate.recording import RecordingGate  # noqa: E402
from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation  # noqa: E402
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter  # noqa: E402

CAPITAL = 100_000.0
VETO_RULES = ("trailing_stop", "take_profit", "time_stop")
CACHE = Path(__file__).resolve().parent.parent / "data" / "exit_gate_llm_cache.sqlite"
OUT = Path("/tmp/mqr_exit_gate")
OUT.mkdir(exist_ok=True)


def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)


def auc(scores, labels):
    """Rank-based AUC: P(score_pos > score_neg), ties counted half."""
    pairs = sorted(zip(scores, labels))
    pos = sum(1 for _, y in pairs if y)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return None
    rank_sum = 0.0
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        rank_sum += avg_rank * sum(1 for k in range(i, j + 1) if pairs[k][1])
        i = j + 1
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--mode", default="exit_confidence",
                    choices=("exit_confidence", "hold_confidence"),
                    help="exit_confidence = proceed only when confident (user's policy)")
    ap.add_argument("--threshold", type=float, default=0.80)
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--starts", type=int, default=20)
    ap.add_argument("--end", default=None)
    ap.add_argument("--offline", action="store_true",
                    help="refuse to call the model; cache misses become errors")
    args = ap.parse_args()

    from app.db.database import engine
    from sqlalchemy import text
    end = args.end
    if end is None:
        with engine.connect() as c:
            end = str(c.execute(text('SELECT MAX("Date") FROM spy')).scalar())[:10]

    log(f"collecting contexts: end={end} starts={args.starts}")
    shared = build_shared(end)
    full_dates, signals, price_cache, score_map, _, _, open_cache, open_dates = shared
    starts = random_starts(args.starts)

    recorder = RecordingGate()
    for start in starts:
        strat = MomentumQualityRotation()
        strat._score_map = score_map
        strat._price_cache = price_cache
        StrategyBacktestAdapter(strat, exit_gate=recorder).run(
            as_of=start, end=end, capital=CAPITAL,
            precomputed_signals={d: signals.get(d, []) for d in full_dates if d >= start},
            price_cache=price_cache,
            open_cache=open_cache, open_dates_cache=open_dates)
    ctxs = recorder.unique_contexts()
    log(f"{len(recorder.contexts)} consultations -> {len(ctxs)} distinct contexts")
    log(f"by rule: {dict(Counter(c.rule for c in ctxs))}")

    fwd = build_forward_returns(price_cache, full_dates, args.horizon)

    def label(ctx):
        hold = fwd.get((ctx.ticker.lower(), ctx.as_of_date))
        if hold is None:
            return None
        repl = 0.0
        for tk, _ in ctx.top_candidates:
            r = fwd.get((tk.lower(), ctx.as_of_date))
            if r is not None and r > repl:
                repl = r
        return 1 if hold > repl else 0

    # Stratified, deduplicated, deterministically SHUFFLED: taking the earliest
    # dates per rule biases the sample towards long-held positions.
    import random as _random
    rng = _random.Random(42)
    by_rule = {r: [c for c in ctxs if c.rule == r] for r in VETO_RULES}
    per = max(1, args.n // len(VETO_RULES))
    sample = []
    for r in VETO_RULES:
        pool = sorted(by_rule[r], key=lambda c: (c.as_of_date, c.ticker))
        if len(pool) > per:
            pool = rng.sample(pool, per)
        sample.extend(pool)
    labelled = [(c, label(c)) for c in sample]
    labelled = [(c, y) for c, y in labelled if y is not None]
    log(f"sample: {len(labelled)} labelled contexts "
        f"(base rate {sum(y for _, y in labelled)/max(1,len(labelled)):.3f})")

    cache = DecisionCache(CACHE)
    complete = make_completer(args.model, think=False, max_tokens=256)
    gate = LLMExitGate(complete, args.model, cache, threshold=args.threshold,
                       prompt_version=f"stageA-{args.mode}-h{args.horizon}",
                       mode=args.mode)

    rows, errors = [], 0
    t0 = time.time()
    for i, (ctx, y) in enumerate(labelled, 1):
        try:
            d = gate.decide(ctx)
            rows.append({"rule": ctx.rule, "label": y, "veto": int(d.veto),
                         "conf": d.confidence, "hold_days": ctx.hold_days,
                         "ret": round(ctx.ret, 4)})
        except Exception as e:  # malformed/empty/timeout -> counted, not hidden
            errors += 1
            if errors <= 3:
                log(f"  error on {ctx.ticker} {ctx.as_of_date}: {type(e).__name__}: {e}")
        if i % 25 == 0:
            log(f"  {i}/{len(labelled)} ({time.time()-t0:.0f}s, errors={errors})")

    cache_stats = cache.stats()
    cache.close()

    n = len(rows)
    if n == 0:
        log("no usable decisions; aborting")
        return
    pos = sum(r["label"] for r in rows)
    vetoes = sum(r["veto"] for r in rows)
    tp = sum(1 for r in rows if r["veto"] and r["label"])
    a = auc([r["conf"] if r["veto"] else 1.0 - r["conf"] for r in rows],
            [r["label"] for r in rows])

    # The Stage 0.5 winner, evaluated on the same sample.
    rule_sel = [1 if r["hold_days"] < 10 else 0 for r in rows]
    rule_tp = sum(1 for r, s in zip(rows, rule_sel) if s and r["label"])
    rule_sel_n = sum(rule_sel)

    result = {
        "config": {"end": end, "model": args.model, "horizon": args.horizon,
                   "requested": args.n, "collected_contexts": len(ctxs),
                   "consultations": len(recorder.contexts),
                   "generated_at": datetime.now(timezone.utc).isoformat()},
        "sample": {"n": n, "positive_rate": round(pos / n, 3),
                   "rules": dict(Counter(r["rule"] for r in rows)),
                   "median_hold_days": sorted(r["hold_days"] for r in rows)[n // 2],
                   "share_hold_lt_10": round(
                       sum(1 for r in rows if r["hold_days"] < 10) / n, 3)},
        "llm": {"veto_rate": round(vetoes / n, 3),
                "precision": round(tp / vetoes, 3) if vetoes else None,
                "recall": round(tp / pos, 3) if pos else None,
                "auc_veto_conf": round(a, 3) if a is not None else None,
                "parse_errors": errors,
                "cache": cache_stats},
        "rule_hold_days_lt_10": {
            "select_rate": round(rule_sel_n / n, 3),
            "precision": round(rule_tp / rule_sel_n, 3) if rule_sel_n else None,
            "recall": round(rule_tp / pos, 3) if pos else None},
    }
    log("RESULT " + json.dumps(result, indent=2))
    with open(OUT / f"llm_stageA_h{args.horizon}.json", "w") as f:
        json.dump(result, f, indent=2, default=str)


if __name__ == "__main__":
    main()
