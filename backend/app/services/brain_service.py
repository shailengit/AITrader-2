"""Trading Brain service: aggregate experiment data, build LLM bundles, chat.

The Brain is a persistent per-strategy knowledge store that:
  1. Aggregates every experiment's full per-trade data (accumulated over time).
  2. Builds a compact data bundle for the LLM based on the question scope
     (a strategy, specific runs, or a cross-strategy comparison).
  3. Answers questions via minimax-m3:cloud and saves the chat history.
  4. Detects patterns across all accumulated data (analyze_strategy).
"""
from __future__ import annotations
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.llm_engine import get_llm_client

logger = logging.getLogger(__name__)

BRAIN_MODEL = "minimax-m3:cloud"

# Cap the per-trade payload sent to the LLM so it never overflows the request
# body, regardless of how many runs/trades have accumulated.
MAX_TOTAL_TRADES = 3000


def strategy_name_from_path(path: Optional[str]) -> Optional[str]:
    """Derive the strategy name from a class path (file stem)."""
    if not path:
        return None
    return Path(path).stem


def _query_experiments(db, strategy_class_path: Optional[str] = None,
                       run_ids: Optional[List[str]] = None) -> List[Any]:
    """Query completed experiments, optionally filtered by strategy/run_ids."""
    from app.models.strategy_lab import StrategyExperiment
    q = db.query(StrategyExperiment).filter(StrategyExperiment.status == "completed")
    if strategy_class_path:
        stem = strategy_name_from_path(strategy_class_path)
        q = q.filter(
            (StrategyExperiment.strategy_class_path == strategy_class_path)
            | (StrategyExperiment.strategy_class_path.like(f"%/{stem}.py"))
        )
    if run_ids:
        # run_ids are run_index values (e.g. "41", "87")
        ints = []
        for r in run_ids:
            try:
                ints.append(int(r))
            except (TypeError, ValueError):
                continue
        if ints:
            q = q.filter(StrategyExperiment.run_index.in_(ints))
    return q.order_by(StrategyExperiment.run_index.asc()).all()


def _sell_trades(exp) -> List[Dict[str, Any]]:
    """Return the complete round-trip (SELL) trades for an experiment."""
    ts = exp.trades_summary or []
    if not isinstance(ts, list):
        return []
    return [t for t in ts if isinstance(t, dict) and t.get("side") == "SELL"]


def _journal_trade_dicts(db, strategy_class_path: Optional[str]) -> List[Dict[str, Any]]:
    """Return accumulated backtest per-trade data for a strategy from the journal.

    Historical per-trade data is stored in journal_trade (source='backtest'),
    linked to a journal_strategy via params.path. It is strategy-level (not
    run-linked), so it cannot be attributed to a specific run — but it is the
    complete accumulated trade history for aggregations like win-rate-by-exit
    or by-holding-days. New experiments store trades_summary per-run too.
    """
    from app.models.journal import JournalTrade, JournalStrategy
    if not strategy_class_path:
        return []
    # Find journal strategy by path (small table; match in Python)
    js_id = None
    for s in db.query(JournalStrategy).all():
        if (s.params or {}).get("path") == strategy_class_path:
            js_id = s.id
            break
    if js_id is None:
        return []
    trades = db.query(JournalTrade).filter(
        JournalTrade.strategy_id == js_id,
        JournalTrade.source == "backtest",
    ).all()
    out = []
    for t in trades:
        entry_dt = t.entry_at
        exit_dt = t.exit_at
        if not exit_dt or not entry_dt:
            continue
        out.append({
            "ticker": t.ticker,
            "side": "SELL",
            "entry_date": entry_dt.date().isoformat(),
            "entry_price": float(t.entry_px) if t.entry_px is not None else None,
            "exit_date": exit_dt.date().isoformat(),
            "exit_price": float(t.exit_px) if t.exit_px is not None else None,
            "exit_reason": "unknown",
            "holding_days": (exit_dt.date() - entry_dt.date()).days,
            "pnl_dollars": float(t.pnl) if t.pnl is not None else 0.0,
            "pnl_pct": float(t.pnl_pct) if t.pnl_pct is not None else 0.0,
        })
    return out


def _all_trades(db, exps: List[Any], strategy_class_path: str) -> List[Dict[str, Any]]:
    """Merge run-linked trades (trades_summary, with exit reasons) with the
    strategy-level journal history, deduplicating by ticker+entry/exit+pnl.

    New experiments store trades_summary per-run (full fields incl. exit_reason).
    Historical trades live in journal_trade (no exit_reason, not run-linked).
    New runs are journaled too, so we skip journal rows that match a
    trades_summary row to avoid double counting.
    """
    run_linked = []
    for e in exps:
        run_linked.extend(_sell_trades(e))
    if not run_linked:
        return _journal_trade_dicts(db, strategy_class_path)

    seen = set()
    for t in run_linked:
        key = (t.get("ticker"), str(t.get("entry_date")), str(t.get("exit_date")),
               round(t.get("pnl_dollars") or 0.0, 2))
        seen.add(key)
    merged = list(run_linked)
    for jt in _journal_trade_dicts(db, strategy_class_path):
        key = (jt.get("ticker"), str(jt.get("entry_date")), str(jt.get("exit_date")),
               round(jt.get("pnl_dollars") or 0.0, 2))
        if key not in seen:
            merged.append(jt)
    return merged


def _run_kpi(exp) -> Dict[str, Any]:
    k = exp.kpis or {}
    return {
        "run_index": exp.run_index,
        "start_date": exp.start_date.isoformat() if exp.start_date else None,
        "end_date": exp.end_date.isoformat() if exp.end_date else None,
        "total_return_pct": k.get("total_return_pct"),
        "alpha_pct": k.get("alpha_pct"),
        "win_rate": k.get("win_rate"),
        "cagr_pct": k.get("cagr_pct"),
        "total_trades": k.get("total_trades"),
        "sharpe_ratio": k.get("sharpe_ratio"),
        "max_drawdown_pct": k.get("max_drawdown_pct"),
        "bull_return_pct": k.get("bull_return_pct"),
        "bear_return_pct": k.get("bear_return_pct"),
    }


def _aggregate_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute aggregate stats across a list of SELL trades."""
    if not trades:
        return {
            "n_trades": 0, "n_winners": 0, "n_losers": 0, "win_rate": 0.0,
            "total_pnl": 0.0, "avg_pnl": 0.0,
            "by_exit_reason": {}, "by_sector": {}, "by_holding_days": {},
            "top_tickers_by_pnl": [],
        }
    n = len(trades)
    winners = [t for t in trades if (t.get("pnl_dollars") or 0) > 0]
    losers = [t for t in trades if (t.get("pnl_dollars") or 0) <= 0]
    total_pnl = sum(t.get("pnl_dollars") or 0 for t in trades)
    avg_pnl = total_pnl / n

    # By exit reason
    by_reason: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        r = t.get("exit_reason") or "unknown"
        d = by_reason.setdefault(r, {"n": 0, "pnl": 0.0, "wins": 0})
        d["n"] += 1
        d["pnl"] += t.get("pnl_dollars") or 0
        if (t.get("pnl_dollars") or 0) > 0:
            d["wins"] += 1
    for r, d in by_reason.items():
        d["avg_pnl"] = round(d["pnl"] / d["n"], 2)
        d["win_rate"] = round(d["wins"] / d["n"] * 100, 1)

    # By sector
    by_sector: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        s = t.get("sector") or "unknown"
        d = by_sector.setdefault(s, {"n": 0, "pnl": 0.0, "wins": 0})
        d["n"] += 1
        d["pnl"] += t.get("pnl_dollars") or 0
        if (t.get("pnl_dollars") or 0) > 0:
            d["wins"] += 1
    for s, d in by_sector.items():
        d["avg_pnl"] = round(d["pnl"] / d["n"], 2)
        d["win_rate"] = round(d["wins"] / d["n"] * 100, 1)

    # By holding-days bucket
    by_hold: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        h = t.get("holding_days") or 0
        bucket = "0-1d" if h <= 1 else "2-5d" if h <= 5 else "6-20d" if h <= 20 else "20d+"
        d = by_hold.setdefault(bucket, {"n": 0, "pnl": 0.0, "wins": 0})
        d["n"] += 1
        d["pnl"] += t.get("pnl_dollars") or 0
        if (t.get("pnl_dollars") or 0) > 0:
            d["wins"] += 1
    for b, d in by_hold.items():
        d["avg_pnl"] = round(d["pnl"] / d["n"], 2)
        d["win_rate"] = round(d["wins"] / d["n"] * 100, 1)

    # Top tickers by net P&L
    by_ticker: Dict[str, float] = {}
    for t in trades:
        tk = t.get("ticker") or "?"
        by_ticker[tk] = by_ticker.get(tk, 0.0) + (t.get("pnl_dollars") or 0)
    top_tickers = sorted(by_ticker.items(), key=lambda kv: kv[1], reverse=True)[:10]

    return {
        "n_trades": n,
        "n_winners": len(winners),
        "n_losers": len(losers),
        "win_rate": round(len(winners) / n * 100, 1) if n else 0.0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "by_exit_reason": by_reason,
        "by_sector": by_sector,
        "by_holding_days": by_hold,
        "top_tickers_by_pnl": top_tickers,
    }


def _sample_trades(trades: List[Dict[str, Any]], max_trades: int = MAX_TOTAL_TRADES) -> List[Dict[str, Any]]:
    """Bound the per-trade list sent to the LLM (top winners, top losers, spread)."""
    if len(trades) <= max_trades:
        return trades
    import random
    sorted_t = sorted(trades, key=lambda t: t.get("pnl_dollars", 0.0))
    n_edge = max_trades // 3
    top_winners = sorted_t[-n_edge:]
    top_losers = sorted_t[:n_edge]
    mid = sorted_t[n_edge:-n_edge]
    random.seed(42)
    n_mid = max_trades - len(top_winners) - len(top_losers)
    sampled_mid = random.sample(mid, min(n_mid, len(mid))) if mid else []
    return top_losers + sampled_mid + top_winners


def build_strategy_bundle(db, strategy_class_path: str,
                          run_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Build a data bundle for one strategy (optionally specific runs).

    Run KPIs come from experiments (run-linked, filterable by run_ids). The
    per-trade history is accumulated at the strategy level (from the journal);
    it cannot be split per-run because historical journal trades are not
    run-linked. New experiments also carry their own trades_summary.
    """
    exps = _query_experiments(db, strategy_class_path, run_ids)
    name = strategy_name_from_path(strategy_class_path) or strategy_class_path
    runs = [_run_kpi(e) for e in exps]
    all_trades = _all_trades(db, exps, strategy_class_path)
    agg = _aggregate_trades(all_trades)
    return {
        "strategy_name": name,
        "strategy_class_path": strategy_class_path,
        "n_runs": len(runs),
        "n_trades": agg["n_trades"],
        "runs": runs,
        "aggregate": agg,
        "sample_trades": _sample_trades(all_trades),
    }


def build_compare_bundle(db, strategy_a: str, strategy_b: str) -> Dict[str, Any]:
    """Build a bundle comparing two strategies."""
    return {
        "comparison": True,
        "strategy_a": build_strategy_bundle(db, strategy_a),
        "strategy_b": build_strategy_bundle(db, strategy_b),
    }


def _call_llm(client, model: str, system: str, user: str) -> Dict[str, Any]:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
        )
        content = resp.choices[0].message.content if resp.choices else None
        usage = getattr(resp, "usage", None)
        pt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        ct = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        return {"content": content, "error": None, "prompt_tokens": pt, "completion_tokens": ct}
    except Exception as e:
        return {"content": None, "error": f"llm_unavailable: {e}", "prompt_tokens": 0, "completion_tokens": 0}


SYSTEM_PROMPT = """You are the Trading Brain, an AI that analyzes a trading strategy's backtest
experiment data and answers the user's questions about it.

You are NOT a financial advisor. You do not recommend taking or avoiding any
specific real security. You only describe what the DATA shows.

Hard rules:
- Use ONLY numbers that appear in the provided JSON bundle. Never invent figures.
- If the data does not contain enough to answer, say so clearly.
- Be concise and structured. Use short paragraphs and bullet lists.
- When comparing runs or strategies, cite the specific run indices and numbers.
- Answer the user's question directly first, then add supporting detail.
- Output valid markdown, no preamble, no postscript."""


def chat(db, question: str, strategy_class_path: Optional[str] = None,
         run_ids: Optional[List[str]] = None,
         compare_strategy: Optional[str] = None,
         model: Optional[str] = None) -> Dict[str, Any]:
    """Answer a question using the accumulated experiment data. Saves chat history."""
    started = time.time()
    client, default_model = get_llm_client()
    used_model = model or BRAIN_MODEL
    if client is None:
        return {"error": "llm_unavailable", "answer": None, "model_id": used_model}

    # Build the bundle based on scope
    if compare_strategy and strategy_class_path:
        bundle = build_compare_bundle(db, strategy_class_path, compare_strategy)
    elif strategy_class_path:
        bundle = build_strategy_bundle(db, strategy_class_path, run_ids)
    else:
        # Global: aggregate across all strategies
        bundle = build_global_bundle(db)

    user_prompt = (
        "Here is the strategy experiment data bundle.\n\n"
        "```json\n" + json.dumps(bundle, indent=2, default=str) + "\n```\n\n"
        f"User question: {question}\n"
    )
    result = _call_llm(client, used_model, SYSTEM_PROMPT, user_prompt)
    if result["error"] or not result["content"]:
        return {"error": result["error"] or "llm_empty_response", "answer": None,
                "model_id": used_model, "bundle": bundle}

    # Save chat history
    _save_message(db, strategy_class_path, "user", question, None, used_model)
    _save_message(db, strategy_class_path, "assistant", result["content"], bundle, used_model)

    return {
        "answer": result["content"],
        "model_id": used_model,
        "duration_ms": int((time.time() - started) * 1000),
        "prompt_tokens": result["prompt_tokens"],
        "completion_tokens": result["completion_tokens"],
        "bundle": bundle,
    }


def build_global_bundle(db) -> Dict[str, Any]:
    """Aggregate across all strategies (global brain)."""
    from app.models.strategy_lab import StrategyExperiment
    exps = db.query(StrategyExperiment).filter(StrategyExperiment.status == "completed").all()
    # Group by strategy
    by_strategy: Dict[str, List[Any]] = {}
    for e in exps:
        key = e.strategy_class_path or "unknown"
        by_strategy.setdefault(key, []).append(e)
    strategies = []
    for path, es in by_strategy.items():
        name = strategy_name_from_path(path) or path
        runs = [_run_kpi(e) for e in es]
        all_trades = _all_trades(db, es, path)
        agg = _aggregate_trades(all_trades)
        strategies.append({
            "strategy_name": name,
            "strategy_class_path": path,
            "n_runs": len(runs),
            "n_trades": agg["n_trades"],
            "runs": runs,
            "aggregate": agg,
        })
    strategies.sort(key=lambda s: s["n_runs"], reverse=True)
    return {"global": True, "n_strategies": len(strategies), "strategies": strategies}


def _save_message(db, strategy_class_path: Optional[str], role: str, content: str,
                  context: Optional[Dict[str, Any]], model_id: str) -> None:
    from app.models.brain import BrainChatMessage
    try:
        name = strategy_name_from_path(strategy_class_path) if strategy_class_path else None
        db.add(BrainChatMessage(
            strategy_name=name,
            role=role,
            content=content,
            context=context,
            model_id=model_id,
        ))
        db.commit()
    except Exception as e:
        logger.warning("Failed to save brain chat message: %s", e)
        db.rollback()


def list_chat(db, strategy_class_path: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    from app.models.brain import BrainChatMessage
    name = strategy_name_from_path(strategy_class_path) if strategy_class_path else None
    q = db.query(BrainChatMessage)
    if name:
        q = q.filter(BrainChatMessage.strategy_name == name)
    else:
        q = q.filter(BrainChatMessage.strategy_name.is_(None))
    rows = q.order_by(BrainChatMessage.created_at.asc()).limit(limit).all()
    return [r.to_dict() for r in rows]


def analyze_strategy(db, strategy_class_path: str) -> Dict[str, Any]:
    """Aggregate all accumulated data for a strategy and detect patterns.

    Updates the strategy_brain row with run/trade stats, best/worst run, and
    an LLM-generated insights summary (what works / what doesn't / tweaks).
    """
    from app.models.brain import StrategyBrain
    exps = _query_experiments(db, strategy_class_path)
    name = strategy_name_from_path(strategy_class_path) or strategy_class_path
    runs = [_run_kpi(e) for e in exps]
    all_trades: List[Dict[str, Any]] = _all_trades(db, exps, strategy_class_path)
    agg = _aggregate_trades(all_trades)

    # Best / worst run by total_return_pct
    best = worst = None
    valid = [r for r in runs if r.get("total_return_pct") is not None]
    if valid:
        best = max(valid, key=lambda r: r["total_return_pct"])
        worst = min(valid, key=lambda r: r["total_return_pct"])

    # LLM insights
    insights = None
    client, _ = get_llm_client()
    if client is not None and runs:
        bundle = {
            "strategy_name": name,
            "n_runs": len(runs),
            "n_trades": agg["n_trades"],
            "runs": runs,
            "aggregate": agg,
            "sample_trades": _sample_trades(all_trades),
        }
        prompt = (
            "Analyze this strategy's accumulated backtest data. Produce a concise markdown "
            "summary with these sections: ## What Works, ## What Doesn't Work, "
            "## Pattern Insights, ## Concrete Tweaks (at most 3, each a single A/B change). "
            "Use ONLY numbers from the bundle.\n\n```json\n"
            + json.dumps(bundle, indent=2, default=str) + "\n```"
        )
        res = _call_llm(client, BRAIN_MODEL, SYSTEM_PROMPT, prompt)
        if res["content"]:
            insights = {"markdown": res["content"], "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}

    # Upsert strategy_brain
    row = db.query(StrategyBrain).filter(StrategyBrain.strategy_name == name).first()
    if row is None:
        row = StrategyBrain(strategy_name=name, strategy_class_path=strategy_class_path)
        db.add(row)
    row.n_runs = len(runs)
    row.n_trades = agg["n_trades"]
    dates = [e.start_date for e in exps if e.start_date]
    if dates:
        row.first_run_date = min(dates)
        row.last_run_date = max(dates)
    row.best_run = best
    row.worst_run = worst
    row.accumulated_insights = insights
    row.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    db.commit()
    db.refresh(row)
    return row.to_dict()


def get_brain(db, strategy_class_path: str) -> Optional[Dict[str, Any]]:
    from app.models.brain import StrategyBrain
    name = strategy_name_from_path(strategy_class_path) or strategy_class_path
    row = db.query(StrategyBrain).filter(StrategyBrain.strategy_name == name).first()
    if row is None:
        return None
    return row.to_dict()


def list_strategies_with_stats(db) -> List[Dict[str, Any]]:
    """List all strategies that have experiments, with accumulated stats."""
    from app.models.strategy_lab import StrategyExperiment
    exps = db.query(StrategyExperiment).filter(StrategyExperiment.status == "completed").all()
    by_path: Dict[str, List[Any]] = {}
    for e in exps:
        key = e.strategy_class_path or "unknown"
        by_path.setdefault(key, []).append(e)
    out = []
    for path, es in by_path.items():
        name = strategy_name_from_path(path) or path
        runs = [_run_kpi(e) for e in es]
        all_trades = _all_trades(db, es, path)
        agg = _aggregate_trades(all_trades)
        valid = [r for r in runs if r.get("total_return_pct") is not None]
        best = max(valid, key=lambda r: r["total_return_pct"]) if valid else None
        out.append({
            "strategy_name": name,
            "strategy_class_path": path,
            "n_runs": len(runs),
            "n_trades": agg["n_trades"],
            "win_rate": agg["win_rate"],
            "avg_pnl": agg["avg_pnl"],
            "best_return_pct": best["total_return_pct"] if best else None,
            "first_run_date": min((e.start_date for e in es if e.start_date), default=None),
            "last_run_date": max((e.start_date for e in es if e.start_date), default=None),
        })
    out.sort(key=lambda s: s["n_runs"], reverse=True)
    return out
