"""AI backtest learning — consume full per-trade data from a batch and produce
pattern insights + concrete parameter tweaks.

The user's requirement: after each multi-run backtest batch, the AI should learn
from the FULL per-trade data (every buy/sell with dates, prices, P&L) — not just
summary KPIs — and produce precise suggestions for tweaking the strategy.

Flow (failure-isolated, never blocks the backtest):
  1. Aggregate the batch's completed runs' trades + KPIs into a compact bundle.
  2. Ask the LLM to analyze it: pattern-level insights first, then concrete,
     testable parameter tweaks with expected impact.
  3. Persist the analysis to the `backtest_analysis` table, linked to the
     strategy and its HTML report.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Backtest Analyst, an AI that reviews the per-trade results of a
multi-run trading-strategy backtest and produces actionable learnings.

You are NOT a financial advisor and you do NOT recommend taking or avoiding any
specific real security. You only describe what the backtest DATA shows.

Hard rules:
- Use ONLY numbers that appear in the provided JSON bundle. Never invent figures.
- Structure your markdown with EXACTLY these top-level headers, in this order:
  ## Performance Summary
  ## What Works
  ## What Doesn't Work
  ## Pattern Insights
  ## Concrete Tweaks
- Begin with a `# Backtest Results Analysis` title, then a `## Overview` section
  (1-2 sentences describing the strategy and the batch: number of runs, date
  range, style). Then include a `## Key Performance Metrics Summary` markdown
  table with columns `Metric | Range | Median | Best Run` covering Total Return,
  CAGR, Sharpe Ratio, Max Drawdown, Win Rate, and Profit Factor. Then the five
  required analysis sections above.
- Use markdown tables, bullet lists, and bold emphasis liberally to make the
  analysis scannable and visually structured (like a professional research
  report). Use emoji sparingly (e.g. ✅ strengths, ⚠️ weaknesses) for emphasis.
- Under "What Works" / "What Doesn't Work", cite specific tickers, exit reasons,
  holding durations, and sectors when the data supports it.
- Under "Pattern Insights", describe correlations/patterns in the per-trade data
  (e.g. which exit reasons win, which sectors/regimes underperform, how holding
  time relates to P&L).
- Under "Concrete Tweaks", propose at most 5 concrete, testable parameter changes
  (e.g. 'raise TRAILING_STOP from 20 to 25', 'add a min-hold of 12 days', 'cap
  sector exposure at 3'). Each MUST be a single A/B change the user can run.
- Output valid markdown with no preamble or postscript."""


def _build_trade_bundle(results: List[Dict[str, Any]], strategy_class_path: str, report_path: Optional[str]) -> Dict[str, Any]:
    """Aggregate the batch's completed runs' trades + KPIs into a compact bundle.

    Keeps the payload small enough for the LLM while preserving full per-trade
    signal (ticker, entry/exit dates, prices, holding days, exit reason, P&L).

    For very large batches (e.g. 100 runs x thousands of trades), the full raw
    per-trade list would exceed the LLM's request-body limit and the call fails
    with "failed to read request body". So we CAP the per-run trade list sent to
    the LLM to a bounded, representative sample (top winners, top losers, and a
    spread of the rest) while ALWAYS sending the full per-run KPI stats. This
    keeps the analysis rich without blowing the context limit.
    """
    import random

    # Keep the total per-trade payload bounded so it never overflows the LLM
    # request-body limit, regardless of batch size. All runs' KPI stats are
    # always included in full; only the raw trade lists are sampled. A ~6.5k-trade
    # bundle (~1MB) worked; ~86k (~20MB) failed — target well under that.
    MAX_TOTAL_TRADES = 4000
    n_completed = len([r for r in results if r.get("status") == "completed"])
    MAX_PER_RUN = max(50, MAX_TOTAL_TRADES // max(n_completed, 1))

    completed = [r for r in results if r.get("status") == "completed"]

    runs = []
    for r in completed:
        trades = r.get("trades") or []
        # Only SELL trades are complete round-trips with P&L.
        sells = [t for t in trades if t.get("side") == "SELL"]
        sampled = sells
        if len(sells) > MAX_PER_RUN:
            # Keep the most informative trades: the biggest winners and losers
            # (where the signal lives), plus a random spread of the rest.
            sorted_sells = sorted(sells, key=lambda t: t.get("pnl_dollars", 0.0))
            n_edge = MAX_PER_RUN // 3
            top_winners = sorted_sells[-n_edge:]
            top_losers = sorted_sells[:n_edge]
            mid = sorted_sells[n_edge:-n_edge]
            random.seed(42 + r.get("run_index", 0))
            n_mid = MAX_PER_RUN - len(top_losers) - len(top_winners)
            sampled = top_losers + top_winners + (random.sample(mid, n_mid) if mid else [])
        runs.append({
            "run_index": r.get("run_index"),
            "start_date": r.get("start_date"),
            "end_date": r.get("end_date"),
            "kpis": r.get("kpis") or {},
            "trades": sampled,
            "trades_total": len(sells),  # tell the LLM how many trades the run actually had
        })

    n_trades = sum(len(ra.get("trades", [])) for ra in runs)

    return {
        "strategy_class_path": strategy_class_path,
        "report_path": report_path,
        "n_runs": len(results),
        "n_completed": n_completed,
        "n_trades": n_trades,
        "runs": runs,
    }


def _call_llm(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Call the LLM to analyze the bundle. Returns {analysis_md, model_id} or raises."""
    from app.services.llm_engine import get_llm_client

    client, default_model = get_llm_client()
    if client is None:
        raise RuntimeError("llm_unavailable")

    user_msg = (
        "Here is the backtest batch data (full per-trade list per run).\n\n"
        "Produce your analysis using ONLY the 6 required section headers, citing "
        "only values present in the JSON.\n\n"
        "```json\n" + json.dumps(bundle, indent=2, default=str) + "\n```"
    )

    resp = client.chat.completions.create(
        model=default_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
    )
    content = resp.choices[0].message.content if resp.choices else None
    if not content:
        raise RuntimeError("llm_empty_response")
    return {"analysis_md": content, "model_id": default_model}


def _build_run_summary(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate per-run KPIs into a compact summary for the list view.

    Computes best/worst/median total return AND CAGR (annualized return), win
    rate, and the date range spanned by the batch's completed runs. The CAGR
    fields let the experiment table show annualized returns instead of the
    (often huge) cumulative returns.
    """
    import statistics

    runs = bundle.get("runs", [])
    returns = []
    cagrs = []
    win_rates = []
    start_dates = []
    end_dates = []
    # Per-year / annualized cross-run aggregates (runs have arbitrary lengths,
    # so per-year metrics are the only comparable cross-run numbers).
    tpy = []
    avg_wins = []
    avg_losses = []
    pfs = []
    for r in runs:
        k = r.get("kpis") or {}
        tr = k.get("total_return_pct")
        if tr is not None:
            returns.append(float(tr))
        cagr = k.get("cagr_pct")
        if cagr is not None:
            cagrs.append(float(cagr))
        wr = k.get("win_rate")
        if wr is not None:
            win_rates.append(float(wr))
        if k.get("trades_per_year") is not None:
            tpy.append(float(k["trades_per_year"]))
        if k.get("avg_winner") is not None:
            avg_wins.append(float(k["avg_winner"]))
        if k.get("avg_loser") is not None:
            avg_losses.append(float(k["avg_loser"]))
        if k.get("profit_factor") is not None:
            pfs.append(float(k["profit_factor"]))
        if r.get("start_date"):
            start_dates.append(str(r["start_date"])[:10])
        if r.get("end_date"):
            end_dates.append(str(r["end_date"])[:10])

    def _fmt(v):
        return round(v, 2) if v is not None else None

    return {
        "n_runs": bundle["n_runs"],
        "n_completed": bundle["n_completed"],
        "n_trades": bundle["n_trades"],
        "best_return_pct": _fmt(max(returns)) if returns else None,
        "worst_return_pct": _fmt(min(returns)) if returns else None,
        "median_return_pct": _fmt(statistics.median(returns)) if returns else None,
        "best_cagr_pct": _fmt(max(cagrs)) if cagrs else None,
        "worst_cagr_pct": _fmt(min(cagrs)) if cagrs else None,
        "median_cagr_pct": _fmt(statistics.median(cagrs)) if cagrs else None,
        "median_trades_per_year": _fmt(statistics.median(tpy)) if tpy else None,
        "median_avg_winner_pct": _fmt(statistics.median(avg_wins)) if avg_wins else None,
        "median_avg_loser_pct": _fmt(statistics.median(avg_losses)) if avg_losses else None,
        "median_profit_factor": _fmt(statistics.median(pfs)) if pfs else None,
        "mean_win_rate_pct": _fmt(statistics.mean(win_rates)) if win_rates else None,
        "start_date": min(start_dates) if start_dates else None,
        "end_date": max(end_dates) if end_dates else None,
    }


def _persist_analysis(
    bundle: Dict[str, Any],
    analysis_md: str,
    model_id: str,
    strategy_class_path: str,
    report_path: Optional[str],
    batch_id: str = "",
) -> None:
    """Persist the analysis row. Failure-isolated."""
    from app.db.database import SessionLocal
    from app.models.backtest_analysis import BacktestAnalysis
    from app.services.coach.strategy_lab_journal import _servable_report_url

    stem = Path(strategy_class_path).stem or strategy_class_path
    with SessionLocal() as db:
        db.add(BacktestAnalysis(
            strategy_name=stem,
            strategy_class_path=strategy_class_path,
            batch_id=batch_id,
            report_path=_servable_report_url(report_path),
            run_summary=_build_run_summary(bundle),
            analysis_md=analysis_md,
            suggestions={},
            model_id=model_id,
            n_runs=bundle["n_runs"],
            n_completed=bundle["n_completed"],
            n_trades=bundle["n_trades"],
        ))
        db.commit()


def analyze_backtest_batch(
    results: List[Dict[str, Any]],
    strategy_class_path: str,
    report_path: Optional[str] = None,
    batch_id: str = "",
) -> Optional[Dict[str, Any]]:
    """Generate + persist AI learnings for a completed backtest batch.

    Returns a summary dict, or None if there's nothing to analyze or it fails.
    Failure-isolated — never raises, never blocks the batch.
    """
    try:
        bundle = _build_trade_bundle(results, strategy_class_path, report_path)
        if bundle["n_completed"] == 0 or bundle["n_trades"] == 0:
            logger.info("No completed runs/trades to analyze for %s", strategy_class_path)
            return None

        started = time.time()
        out = _call_llm(bundle)
        _persist_analysis(bundle, out["analysis_md"], out["model_id"], strategy_class_path, report_path, batch_id)
        logger.info("Backtest analysis generated for %s in %.1fs (%d trades)",
                    strategy_class_path, time.time() - started, bundle["n_trades"])
        return {"analysis_md": out["analysis_md"], "model_id": out["model_id"], "n_trades": bundle["n_trades"]}
    except Exception as e:
        logger.warning("Backtest analysis failed for %s: %s", strategy_class_path, e)
        return None
