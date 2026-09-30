"""Add `source` column to journal_trade to separate live vs backtested trades.

Revision ID: 004
Revises: 003
Create Date: 2026-08-27
"""
from typing import Sequence, Union
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add source column (live|backtest), defaulting existing rows to 'live'."""
    op.execute(
        "ALTER TABLE journal_trade "
        "ADD COLUMN source TEXT NOT NULL DEFAULT 'live' "
        "CHECK (source IN ('live', 'backtest'))"
    )
    op.execute("CREATE INDEX idx_journal_trade_source ON journal_trade(source)")


def downgrade() -> None:
    """Drop the source column."""
    op.execute("DROP INDEX IF EXISTS idx_journal_trade_source")
    op.execute("ALTER TABLE journal_trade DROP COLUMN IF EXISTS source")
