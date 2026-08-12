"""
Backfill the consolidated `ohlcv` table from the per-ticker OHLCV tables.

Run from backend/:
    ./venv/bin/python scripts/backfill_ohlcv.py [--limit N]

This is idempotent (uses INSERT ... ON CONFLICT DO NOTHING) and safe to
re-run. It does NOT drop the per-ticker tables.
"""
import argparse
import logging
import os
import sys
import time

# Allow running as `python scripts/backfill_ohlcv.py` from backend/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from app.db.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Tables that are NOT per-ticker price tables.
SKIP = {
    "stock_metadata", "stock_financials_quarterly", "stock_financials_yearly",
    "ohlcv", "earnings_calendar", "alembic_version",
    "strategy_experiments", "strategy_sessions", "strategy_batch_summaries",
    "strategy_deployments", "strategy_chat_messages",
    "hypotheses", "journal_strategy", "journal_strategy_run", "journal_signal",
    "journal_trade", "journal_market_regime", "journal_coach_report",
    "deployments",
    # sector ETFs are also price tables but live in ohlcv too; include them.
}


def main(limit: int | None = None):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                ticker  VARCHAR(10)  NOT NULL,
                "Date"  DATE         NOT NULL,
                "Open"  NUMERIC(20, 6),
                "High"  NUMERIC(20, 6),
                "Low"   NUMERIC(20, 6),
                "Close" NUMERIC(20, 6),
                "Volume" BIGINT,
                PRIMARY KEY (ticker, "Date")
            )
        """))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON ohlcv (ticker, "Date")'))

    with engine.connect() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ))]
    ticker_tables = [t for t in tables if t not in SKIP]

    if limit:
        ticker_tables = ticker_tables[:limit]

    total_rows = 0
    t0 = time.time()
    for i, tbl in enumerate(ticker_tables, 1):
        try:
            with engine.begin() as conn:
                res = conn.execute(text(f"""
                    INSERT INTO ohlcv (ticker, "Date", "Open", "High", "Low", "Close", "Volume")
                    SELECT :t, "Date", "Open", "High", "Low", "Close", "Volume"
                    FROM "{tbl}"
                    ON CONFLICT (ticker, "Date") DO NOTHING
                """), {"t": tbl})
                n = res.rowcount
            total_rows += n
            if i % 100 == 0 or i == len(ticker_tables):
                logger.info("Processed %d/%d tables (%d rows so far, %.1fs)",
                            i, len(ticker_tables), total_rows, time.time() - t0)
        except Exception as e:
            logger.warning("Skipped table %s: %s", tbl, e)

    logger.info("Done. Backfilled %d rows from %d tables in %.1fs",
                total_rows, len(ticker_tables), time.time() - t0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Only backfill first N tables (for testing)")
    args = ap.parse_args()
    main(args.limit)
