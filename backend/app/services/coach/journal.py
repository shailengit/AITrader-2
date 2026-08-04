"""Trade-journal write helpers for the Coach agent.

Failure-isolated: every function catches DB exceptions, logs a warning,
and returns None so the user's primary flow is never blocked.
"""
from __future__ import annotations
import logging
from datetime import datetime, date as date_cls
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid

from sqlalchemy.exc import SQLAlchemyError

from app.db.database import SessionLocal
from app.models.journal import JournalStrategy, JournalStrategyRun, JournalSignal, JournalTrade

logger = logging.getLogger(__name__)


def record_journal_failure(operation: str, exc: Exception) -> None:
    """Log a journal write failure at WARNING. Never raises."""
    logger.warning("Coach journal %s failed: %s", operation, exc, exc_info=False)


def upsert_strategy(
    kind: str,
    name: str,
    params: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
    session: Optional[Any] = None,
) -> Optional[JournalStrategy]:
    """Insert or update a strategy by (kind, name). Returns the row, or None on failure."""
    op = "upsert_strategy"
    own_session = session is None
    try:
        s = session or SessionLocal()
        try:
            row = s.query(JournalStrategy).filter_by(kind=kind, name=name).one_or_none()
            if row is None:
                row = JournalStrategy(kind=kind, name=name, params=params or {}, notes=notes)
                s.add(row)
            else:
                if params is not None:
                    row.params = params
                if notes is not None:
                    row.notes = notes
            if own_session:
                s.commit()
                s.refresh(row)
            else:
                s.flush()
            return row
        finally:
            if own_session:
                s.close()
    except SQLAlchemyError as e:
        record_journal_failure(op, e)
        return None


def record_strategy_run(
    strategy_id: uuid.UUID,
    started_at: datetime,
    result_summary: Optional[Dict[str, Any]] = None,
    as_of_date: Optional[date_cls] = None,
    regime_at_run: Optional[str] = None,
    finished_at: Optional[datetime] = None,
    session: Optional[Any] = None,
) -> Optional[JournalStrategyRun]:
    """Insert a strategy_run row. Returns the row, or None on failure."""
    op = "record_strategy_run"
    own_session = session is None
    try:
        s = session or SessionLocal()
        try:
            row = JournalStrategyRun(
                strategy_id=strategy_id,
                started_at=started_at,
                finished_at=finished_at or datetime.utcnow(),
                result_summary=result_summary or {},
                as_of_date=as_of_date,
                regime_at_run=regime_at_run,
            )
            s.add(row)
            if own_session:
                s.commit()
                s.refresh(row)
            else:
                s.flush()
            return row
        finally:
            if own_session:
                s.close()
    except SQLAlchemyError as e:
        record_journal_failure(op, e)
        return None


def record_signal(
    run_id: uuid.UUID,
    ticker: str,
    signal_type: str,
    as_of_date: date_cls,
    signal_strength: Optional[float] = None,
    payload: Optional[Dict[str, Any]] = None,
    session: Optional[Any] = None,
) -> Optional[JournalSignal]:
    """Insert a single signal. Returns the row, or None on failure."""
    op = "record_signal"
    own_session = session is None
    try:
        s = session or SessionLocal()
        try:
            row = JournalSignal(
                strategy_run_id=run_id,
                ticker=ticker,
                signal_type=signal_type,
                as_of_date=as_of_date,
                signal_strength=signal_strength,
                payload=payload or {},
            )
            s.add(row)
            if own_session:
                s.commit()
                s.refresh(row)
            else:
                s.flush()
            return row
        finally:
            if own_session:
                s.close()
    except SQLAlchemyError as e:
        record_journal_failure(op, e)
        return None


# ---------------------------------------------------------------------------
# Read helpers for the per-strategy Coach summary endpoint.
#
# strategy_path -> JournalStrategy mapping (project decision, Task 4.1):
#   A strategy_path such as "strategies/golden_cross.py" maps to the
#   JournalStrategy whose `name` equals the path's file stem ("golden_cross").
#   `kind` is not filtered here so the mapping is stable regardless of where
#   the strategy was created (screener / quantgen / strategy-lab). We look up
#   the (kind, name) unique row by name only; in the (rare) event of duplicate
#   names across kinds we resolve to the most recently created row.
# ---------------------------------------------------------------------------


def _strategy_stem(strategy_path: str) -> str:
    """Reduce a strategy path (e.g. 'strategies/golden_cross.py') to its file stem."""
    return Path(strategy_path).stem


def _resolve_strategy(strategy_path: str, db: Any) -> Optional[JournalStrategy]:
    """Resolve a strategy_path to a JournalStrategy row (by file-stem name)."""
    name = _strategy_stem(strategy_path)
    if not name:
        return None
    return (
        db.query(JournalStrategy)
        .filter(JournalStrategy.name == name)
        .order_by(JournalStrategy.created_at.desc())
        .first()
    )


def list_fills_for_strategy(
    strategy_path: str,
    db: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Return live fills (trades) for a strategy as dicts for the summary.

    Each fill dict carries `pnl` and `regime` keys (regime = exit regime,
    falling back to entry regime), plus the fields the badge shows in
    `last_5_trades`. Returns [] on failure or if the strategy is not tracked.
    """
    op = "list_fills_for_strategy"
    own_session = db is None
    try:
        s = db or SessionLocal()
        try:
            row = _resolve_strategy(strategy_path, s)
            if row is None:
                return []
            trades = (
                s.query(JournalTrade)
                .filter(JournalTrade.strategy_id == row.id)
                .order_by(JournalTrade.entry_at.desc())
                .all()
            )
            return [
                {
                    "ticker": t.ticker,
                    "side": t.side,
                    "entry_at": t.entry_at.isoformat() if t.entry_at else None,
                    "exit_at": t.exit_at.isoformat() if t.exit_at else None,
                    "pnl": float(t.pnl) if t.pnl is not None else 0.0,
                    "pnl_pct": float(t.pnl_pct) if t.pnl_pct is not None else None,
                    "regime": t.regime_at_exit or t.regime_at_entry or "UNKNOWN",
                }
                for t in trades
            ]
        finally:
            if own_session:
                s.close()
    except SQLAlchemyError as e:
        record_journal_failure(op, e)
        return []


def list_runs_for_strategy(
    strategy_path: str,
    db: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Return strategy-lab runs for a strategy as dicts for the summary.

    Each run dict carries a `summary` key (the run's `result_summary`), the
    backtested-fallback payload. Most recent run first. Returns [] on failure.
    """
    op = "list_runs_for_strategy"
    own_session = db is None
    try:
        s = db or SessionLocal()
        try:
            row = _resolve_strategy(strategy_path, s)
            if row is None:
                return []
            runs = (
                s.query(JournalStrategyRun)
                .filter(JournalStrategyRun.strategy_id == row.id)
                .order_by(JournalStrategyRun.started_at.desc())
                .all()
            )
            return [
                {
                    "summary": r.result_summary,
                    "as_of_date": r.as_of_date.isoformat() if r.as_of_date else None,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "regime_at_run": r.regime_at_run,
                }
                for r in runs
            ]
        finally:
            if own_session:
                s.close()
    except SQLAlchemyError as e:
        record_journal_failure(op, e)
        return []
