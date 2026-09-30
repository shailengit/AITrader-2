"""Create backtest_analysis table for AI backtest learnings.

Revision ID: 005
Revises: 004
Create Date: 2026-08-28
"""
from typing import Sequence, Union
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the backtest_analysis table."""
    op.execute("""
        CREATE TABLE backtest_analysis (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            strategy_name TEXT NOT NULL,
            strategy_class_path TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            report_path TEXT NULL,
            run_summary JSONB NULL,
            analysis_md TEXT NOT NULL,
            suggestions JSONB NULL,
            model_id TEXT NOT NULL DEFAULT '',
            n_runs INT NOT NULL DEFAULT 0,
            n_completed INT NOT NULL DEFAULT 0,
            n_trades INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_backtest_analysis_strategy ON backtest_analysis(strategy_name)")
    op.execute("CREATE INDEX idx_backtest_analysis_created ON backtest_analysis(created_at)")


def downgrade() -> None:
    """Drop the backtest_analysis table."""
    op.execute("DROP TABLE IF EXISTS backtest_analysis")
