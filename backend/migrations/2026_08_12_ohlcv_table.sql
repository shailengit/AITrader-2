-- 2026_08_12_ohlcv_table.sql
-- Consolidate the ~1,500 per-ticker OHLCV tables into a single `ohlcv` table.
--
-- This is ADDITIVE: the per-ticker tables are left in place so existing
-- direct queries keep working. New code should read from `ohlcv` (see
-- data_service.get_ohlcv_data). Once all readers are migrated, the
-- per-ticker tables can be dropped.
--
-- Run: psql -d sp1500_1d -f 2026_08_12_ohlcv_table.sql
--      (or: cd backend && ./venv/bin/python -m app.db.migrations.run_ohlcv)

CREATE TABLE IF NOT EXISTS ohlcv (
    ticker  VARCHAR(10)  NOT NULL,
    "Date"  DATE         NOT NULL,
    "Open"  NUMERIC(20, 6),
    "High"  NUMERIC(20, 6),
    "Low"   NUMERIC(20, 6),
    "Close" NUMERIC(20, 6),
    "Volume" BIGINT,
    PRIMARY KEY (ticker, "Date")
);

-- Fast per-ticker range scans (the common access pattern).
CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON ohlcv (ticker, "Date");
