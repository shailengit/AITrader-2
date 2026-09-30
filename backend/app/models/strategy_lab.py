"""SQLAlchemy ORM models for the AI Strategy Builder (Phase 1).

Four tables:
  - strategy_sessions: one per "session" (one strategy idea)
  - strategy_experiments: one per backtest run within a batch
  - strategy_batch_summaries: LLM-generated digest of a batch
  - strategy_deployments: history of Alpaca pluggable class deploys
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Optional, Dict, List

from sqlalchemy import (
    String, Text, Integer, Date, DateTime, ForeignKey, Index, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def text_default_uuid():
    return text("gen_random_uuid()")


def text_default_now():
    return text("now()")


class StrategySession(Base):
    __tablename__ = "strategy_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    plan_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    code_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())

    chat_messages: Mapped[List[StrategyChatMessage]] = relationship(
        "StrategyChatMessage", back_populates="session", cascade="all, delete-orphan"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "prompt": self.prompt,
            "plan_text": self.plan_text,
            "code_text": self.code_text,
            "model_id": self.model_id,
            "tags": self.tags or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class StrategyChatMessage(Base):
    __tablename__ = "strategy_chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # "user" | "assistant" | "system"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    critique_of: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_chat_messages.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())

    session: Mapped[StrategySession] = relationship("StrategySession", back_populates="chat_messages")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id),
            "role": self.role,
            "content": self.content,
            "model_id": self.model_id,
            "critique_of": str(self.critique_of) if self.critique_of else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class StrategyExperiment(Base):
    __tablename__ = "strategy_experiments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_sessions.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    strategy_class_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    run_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[Any] = mapped_column(Date, nullable=False)
    end_date: Mapped[Any] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kpis: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    equity_curve: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    trades_summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    report_html_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_experiments_session_batch", "session_id", "batch_id"),
        Index("idx_experiments_kpis", "kpis", postgresql_using="gin"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id),
            "batch_id": str(self.batch_id),
            "strategy_class_path": self.strategy_class_path,
            "run_index": self.run_index,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "status": self.status,
            "error_message": self.error_message,
            "kpis": self.kpis,
            "trades_summary": self.trades_summary,
            "report_html_path": self.report_html_path,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class StrategyBatchSummary(Base):
    __tablename__ = "strategy_batch_summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_sessions.id", ondelete="CASCADE"), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    winner_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_experiments.id"), nullable=True)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "batch_id": str(self.batch_id),
            "session_id": str(self.session_id),
            "summary_text": self.summary_text,
            "winner_run_id": str(self.winner_run_id) if self.winner_run_id else None,
            "model_id": self.model_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class StrategyDeployment(Base):
    __tablename__ = "strategy_deployments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_sessions.id"), nullable=False)
    experiment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_experiments.id"), nullable=True)
    class_name: Mapped[str] = mapped_column(Text, nullable=False)
    class_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())
    rolled_back_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id),
            "experiment_id": str(self.experiment_id) if self.experiment_id else None,
            "class_name": self.class_name,
            "class_file_path": self.class_file_path,
            "is_active": self.is_active,
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
            "rolled_back_at": self.rolled_back_at.isoformat() if self.rolled_back_at else None,
        }
