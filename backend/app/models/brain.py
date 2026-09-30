"""Trading Brain models: persistent per-strategy knowledge + chat history.

Two tables:
  - strategy_brain: one row per strategy, accumulating run/trade stats and
    detected insights over time (the "brain" of a strategy).
  - brain_chat_messages: chat history for the Trading Brain Q&A (per-strategy
    or global when strategy_name is NULL).
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Optional, Dict, List

from sqlalchemy import String, Text, Integer, Date, DateTime, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def text_default_uuid():
    return text("gen_random_uuid()")


def text_default_now():
    return text("now()")


class StrategyBrain(Base):
    __tablename__ = "strategy_brain"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    strategy_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    strategy_class_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    n_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_run_date: Mapped[Optional[Any]] = mapped_column(Date, nullable=True)
    last_run_date: Mapped[Optional[Any]] = mapped_column(Date, nullable=True)
    best_run: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    worst_run: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    accumulated_insights: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "strategy_name": self.strategy_name,
            "strategy_class_path": self.strategy_class_path,
            "n_runs": self.n_runs,
            "n_trades": self.n_trades,
            "first_run_date": self.first_run_date.isoformat() if self.first_run_date else None,
            "last_run_date": self.last_run_date.isoformat() if self.last_run_date else None,
            "best_run": self.best_run,
            "worst_run": self.worst_run,
            "accumulated_insights": self.accumulated_insights,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BrainChatMessage(Base):
    __tablename__ = "brain_chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text_default_uuid())
    strategy_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # NULL = global
    role: Mapped[str] = mapped_column(Text, nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    model_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text_default_now())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "strategy_name": self.strategy_name,
            "role": self.role,
            "content": self.content,
            "context": self.context,
            "model_id": self.model_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
