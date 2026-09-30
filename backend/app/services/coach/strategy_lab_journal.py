"""Bridge Strategy Lab backtests into the Trade Coach journal + Hypothesis backlog.

When a strategy is backtested in Strategy Lab, we want it to:
  1. Appear as a tracked strategy in the Coach journal (so the Coach badge shows
     real backtest metrics and the strategy is filterable in the Coach).
  2. Appear in the Hypothesis backlog (so it's part of the idea pipeline).

Failure-isolated: never raises, never blocks the backtest. The strategy is
keyed by its file stem (matching `_resolve_strategy`'s stem lookup in
coach/journal.py), so the Coach badge and the Coach overview resolve it the
same way they do for any other strategy.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.coach.journal import upsert_strategy, record_strategy_run

logger = logging.getLogger(__name__)


def _servable_report_url(report_path: Optional[str]) -> Optional[str]:
    """Convert an absolute report filesystem path to a servable /api URL.

    Reports live in docs/reports/ (absolute path from run_viewer_generator).
    They are served by /api/strategy-lab/reports/<filename>. Return None if the
    path is missing/empty so we don't store a broken link.
    """
    if not report_path:
        return None
    try:
        from urllib.parse import quote
        filename = Path(report_path).name
        if not filename:
            return None
        # URL-encode the filename (e.g. spaces -> %20) so the link is directly usable.
        return f"/api/strategy-lab/reports/{quote(filename)}"
    except Exception:
        return None


def journal_strategy_lab_backtest(
    strategy_class_path: str,
    kpis: Optional[Dict[str, Any]],
    as_of: str,
    end_date: str,
    trades: Optional[List[Dict[str, Any]]] = None,
    report_path: Optional[str] = None,
) -> None:
    """Record a Strategy Lab backtest run + hypothesis + per-trade journal.

    strategy_class_path is like "backend/app/services/strategies/daily_golden_cross.py"
    or "strategies/daily_golden_cross.py". The file stem becomes the journal
    strategy name (matching _resolve_strategy's stem lookup).

    `trades` is the backtest's trade list (BUY/SELL dicts from the adapter).
    Each SELL trade is a complete round-trip (entry+exit+P&L) and is journaled
    as a `source='backtest'` trade so the Coach can analyze backtested
    performance separately from live.

    `report_path` is the generated HTML report's absolute filesystem path. It's
    normalized to a servable URL (/api/strategy-lab/reports/<filename>) and
    stored on the strategy so the backtest tab can link to it.
    """
    servable_path = _servable_report_url(report_path)
    try:
        stem = Path(strategy_class_path).stem
        if not stem:
            return
        from app.db.database import SessionLocal
        with SessionLocal() as db:
            strat = upsert_strategy(
                kind="manual",
                name=stem,
                params={"path": strategy_class_path, "origin": "strategy_lab", "report_path": servable_path},
                session=db,
            )
            if strat is None:
                return
            record_strategy_run(
                strategy_id=strat.id,
                started_at=datetime.utcnow(),
                result_summary=kpis or {},
                as_of_date=datetime.strptime(as_of[:10], "%Y-%m-%d").date() if as_of else None,
                session=db,
            )
            _journal_backtest_trades(db, strat.id, trades or [])
            db.commit()
            _ensure_hypothesis(db, stem, strategy_class_path, kpis)
    except Exception as e:
        logger.warning("Strategy Lab journal hook failed: %s", e)


def _journal_backtest_trades(
    db: Any,
    strategy_id: Any,
    trades: List[Dict[str, Any]],
) -> None:
    """Journal complete backtest round-trips (SELL trades) as source='backtest'."""
    from app.models.journal import JournalTrade

    for t in trades:
        if t.get("side") != "SELL":
            continue
        ticker = t.get("ticker")
        entry_px = t.get("entry_price")
        exit_px = t.get("exit_price")
        entry_date = t.get("entry_date")
        exit_date = t.get("exit_date")
        if not ticker or not entry_px or not exit_px or not entry_date or not exit_date:
            continue
        try:
            entry_at = datetime.strptime(str(entry_date)[:10], "%Y-%m-%d")
            exit_at = datetime.strptime(str(exit_date)[:10], "%Y-%m-%d")
        except ValueError:
            continue
        db.add(JournalTrade(
            strategy_id=strategy_id,
            ticker=ticker,
            side="long",
            qty=1,  # backtest trades are unit-sized; P&L is per-share
            entry_px=float(entry_px),
            exit_px=float(exit_px),
            entry_at=entry_at,
            exit_at=exit_at,
            pnl=float(t.get("pnl_dollars", 0.0)),
            pnl_pct=float(t.get("return_pct", 0.0)) / 100.0,
            source="backtest",
            notes=f"backtest:{t.get('exit_reason', '')}",
        ))


def _ensure_hypothesis(
    db: Any,
    stem: str,
    strategy_class_path: str,
    kpis: Optional[Dict[str, Any]],
) -> None:
    """Create an open Hypothesis for a backtested strategy (dedup by stem)."""
    from app.models.hypothesis import Hypothesis, HypothesisSource, HypothesisStatus

    existing = (
        db.query(Hypothesis)
        .filter(
            Hypothesis.why.ilike(f"%{stem}%"),
            Hypothesis.status == HypothesisStatus.open,
        )
        .first()
    )
    if existing is not None:
        return

    ret = (kpis or {}).get("total_return_pct")
    why = f"Backtested in Strategy Lab: {stem}"
    if ret is not None:
        why += f" (total return {ret}%)"

    h = Hypothesis(
        source=HypothesisSource("coach"),
        why=why,
        context={"strategy_class_path": strategy_class_path, "kpis": kpis},
        source_meta={"origin": "strategy_lab_backtest"},
    )
    db.add(h)
    db.commit()
