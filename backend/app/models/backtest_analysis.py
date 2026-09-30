"""SQLAlchemy ORM model for AI backtest learnings.

One row per backtest batch, holding the AI-generated analysis (pattern
insights + concrete parameter tweaks) derived from the FULL per-trade data of
that batch's randomized runs.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Text, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BacktestAnalysis(Base):
    __tablename__ = "backtest_analysis"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_name: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_class_path: Mapped[str] = mapped_column(Text, nullable=False)
    batch_id: Mapped[str] = mapped_column(Text, nullable=False)
    report_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Summary stats the AI learned from (per-run KPI aggregates).
    run_summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    # The AI's markdown analysis (pattern insights + concrete parameter tweaks).
    analysis_md: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured suggestions (list of {param, change, expected_impact}) if the
    # LLM returned a parseable JSON list; otherwise empty.
    suggestions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    model_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    n_runs: Mapped[int] = mapped_column(default=0, nullable=False)
    n_completed: Mapped[int] = mapped_column(default=0, nullable=False)
    n_trades: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_backtest_analysis_strategy", "strategy_name"),
        Index("idx_backtest_analysis_created", "created_at"),
    )
