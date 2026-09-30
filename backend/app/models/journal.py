"""SQLAlchemy ORM models for the trade journal (Trade Coach agent).

These map to the six tables created by migration 003_trade_journal.py.
"""
from __future__ import annotations
import uuid
from datetime import datetime, date as date_cls
from typing import Any, Optional, Dict

from sqlalchemy import (
    String, Text, Integer, Numeric, Date, DateTime, ForeignKey, Index, CheckConstraint, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def text_default_uuid():
    return text("uuid_generate_v4()")


def text_default_now():
    return text("now()")


class JournalStrategy(Base):
    __tablename__ = "journal_strategy"
    __table_args__ = (
        UniqueConstraint("kind", "name", name="uq_journal_strategy_kind_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    runs: Mapped[list["JournalStrategyRun"]] = relationship(back_populates="strategy", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "kind": self.kind,
            "name": self.name,
            "params": self.params,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "retired_at": self.retired_at.isoformat() if self.retired_at else None,
            "notes": self.notes,
        }


class JournalStrategyRun(Base):
    __tablename__ = "journal_strategy_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("journal_strategy.id", ondelete="CASCADE"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    result_summary: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    as_of_date: Mapped[Optional[date_cls]] = mapped_column(Date, nullable=True)
    regime_at_run: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())

    strategy: Mapped["JournalStrategy"] = relationship(back_populates="runs")
    signals: Mapped[list["JournalSignal"]] = relationship(back_populates="run", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "strategy_id": str(self.strategy_id),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "result_summary": self.result_summary,
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "regime_at_run": self.regime_at_run,
        }


class JournalSignal(Base):
    __tablename__ = "journal_signal"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    strategy_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("journal_strategy_run.id", ondelete="CASCADE"), nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    signal_strength: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    as_of_date: Mapped[date_cls] = mapped_column(Date, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())

    run: Mapped["JournalStrategyRun"] = relationship(back_populates="signals")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "strategy_run_id": str(self.strategy_run_id),
            "ticker": self.ticker,
            "signal_type": self.signal_type,
            "signal_strength": float(self.signal_strength) if self.signal_strength is not None else None,
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "payload": self.payload,
        }


class JournalTrade(Base):
    __tablename__ = "journal_trade"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    strategy_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("journal_strategy.id", ondelete="SET NULL"), nullable=True)
    signal_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("journal_signal.id", ondelete="SET NULL"), nullable=True)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[float] = mapped_column(Numeric, nullable=False)
    entry_px: Mapped[float] = mapped_column(Numeric, nullable=False)
    exit_px: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_px: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    target_px: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    pnl: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    mae: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    mfe: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    regime_at_entry: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    regime_at_exit: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="live", server_default=text("'live'"))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "strategy_id": str(self.strategy_id) if self.strategy_id else None,
            "signal_id": str(self.signal_id) if self.signal_id else None,
            "ticker": self.ticker,
            "side": self.side,
            "qty": float(self.qty) if self.qty is not None else None,
            "entry_px": float(self.entry_px) if self.entry_px is not None else None,
            "exit_px": float(self.exit_px) if self.exit_px is not None else None,
            "entry_at": self.entry_at.isoformat() if self.entry_at else None,
            "exit_at": self.exit_at.isoformat() if self.exit_at else None,
            "stop_px": float(self.stop_px) if self.stop_px is not None else None,
            "target_px": float(self.target_px) if self.target_px is not None else None,
            "pnl": float(self.pnl) if self.pnl is not None else None,
            "pnl_pct": float(self.pnl_pct) if self.pnl_pct is not None else None,
            "mae": float(self.mae) if self.mae is not None else None,
            "mfe": float(self.mfe) if self.mfe is not None else None,
            "regime_at_entry": self.regime_at_entry,
            "regime_at_exit": self.regime_at_exit,
            "source": self.source,
            "notes": self.notes,
        }


class JournalMarketRegime(Base):
    __tablename__ = "journal_market_regime"

    date: Mapped[date_cls] = mapped_column(Date, primary_key=True)
    regime: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    by_sector: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))


class JournalCoachReport(Base):
    __tablename__ = "journal_coach_report"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())
    period_start: Mapped[date_cls] = mapped_column(Date, nullable=False)
    period_end: Mapped[date_cls] = mapped_column(Date, nullable=False)
    strategy_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("journal_strategy.id", ondelete="SET NULL"), nullable=True)
    bundle: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    report_md: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
