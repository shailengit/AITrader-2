"""Assemble the data bundle the Coach LLM sees. The bundle is the ONLY
thing the LLM sees — no raw journal, no other context.
"""
from __future__ import annotations
import uuid
from datetime import date as date_cls
from typing import Any, Dict, Optional

from app.services.coach import analytics as A


def build(session, period_start: date_cls, period_end: date_cls, strategy_id: Optional[uuid.UUID], source: Optional[str] = None) -> Dict[str, Any]:
    """Assemble the data bundle. Returns a JSON-serializable dict."""
    warnings: list = []

    # 11 base metrics from the analytics module
    kpis = A.kpis(session, period_start, period_end, strategy_id, source)
    # For backtest source, the journaled dollar P&L is a meaningless cross-run
    # sum (each run is its own $100k). Use per-run % returns from
    # backtest_analysis.run_summary so the LLM critiques real % figures instead
    # of inventing numbers to match absurd dollar values (which caused
    # "Critique Unavailable" / llm_invented_numbers).
    if source == "backtest":
        bk = A.backtest_kpis(session, strategy_id, source)
        if bk is not None:
            kpis = bk
    pnl_by_regime = A.pnl_by_regime(session, period_start, period_end, strategy_id, source)
    win_rate_by_strategy = A.win_rate_by_strategy(session, period_start, period_end, source)
    entry_timing_lag = A.entry_timing_lag(session, period_start, period_end, strategy_id)
    mae_mfe = A.mae_mfe_scatter(session, period_start, period_end, strategy_id, source)
    equity = A.equity_curve(session, period_start, period_end, strategy_id, source)
    drawdown = A.drawdown_curve(session, period_start, period_end, strategy_id, source)
    correlation = A.strategy_correlation_matrix(session, period_start, period_end, source)
    recent = A.recent_trades(session, strategy_id=strategy_id, n=20, source=source)
    regime = A.regime_timeline(session, period_start, period_end)

    # For backtest source, the equity/drawdown/pnl_by_regime figures are
    # cross-run dollar sums (meaningless — each run is its own $100k). Neutralize
    # them in the bundle so the LLM doesn't try to cite absurd dollar values.
    if source == "backtest":
        pnl_by_regime = {}
        equity = []
        drawdown = []

    # Cap regime_timeline at 90 days, surface a warning
    if len(regime) > 90:
        regime = regime[-90:]
        warnings.append("regime_timeline truncated to last 90 days")

    return {
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "strategy_id": str(strategy_id) if strategy_id else None,
        "kpis": kpis,
        "pnl_by_regime": pnl_by_regime,
        "win_rate_by_strategy": win_rate_by_strategy,
        "entry_timing_lag": entry_timing_lag,
        "mae_mfe_summary": _summarize_mae_mfe(mae_mfe),
        "equity_curve_summary": _summarize_equity(equity),
        "drawdown_summary": _summarize_drawdown(drawdown),
        "strategy_correlation": correlation,
        "recent_trades": recent,
        "regime_timeline": regime,
        "warnings": warnings,
    }


def _summarize_mae_mfe(rows):
    if not rows:
        return {"n": 0}
    maes = [r["mae"] for r in rows if r["mae"] is not None]
    mfes = [r["mfe"] for r in rows if r["mfe"] is not None]
    return {
        "n": len(rows),
        "mae_mean": round(sum(maes) / len(maes), 4) if maes else None,
        "mfe_mean": round(sum(mfes) / len(mfes), 4) if mfes else None,
    }


def _summarize_equity(rows):
    if not rows:
        return {"n": 0}
    equities = [r["equity"] for r in rows]
    return {
        "n": len(equities),
        "start": equities[0],
        "end": equities[-1],
        "peak": max(equities),
        "trough": min(equities),
    }


def _summarize_drawdown(rows):
    if not rows:
        return {"n": 0, "max_dd": 0.0}
    dds = [r["dd"] for r in rows]
    return {"n": len(dds), "max_dd": min(dds)}
