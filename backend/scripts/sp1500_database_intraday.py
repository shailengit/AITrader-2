"""S&P 1500 Intraday (1-Minute) Database Manager — AITrader-2 version.

Downloads and maintains 1-minute OHLCV data for all S&P 1500 stocks plus
11 sector ETFs in the dedicated `sp1500_1m` PostgreSQL database.

This is the AITrader-2 copy of the updater. It is the SAME logic as the
StockScreener_2 version but lives in this project so the TradeCraft launchd
agent can point at it. It writes to the `Date` column (matching the schema
after backend/scripts/rename_datetime_column.py), which fixes the
"column Datetime does not exist" failure.

NOTE: yfinance caps 1-minute history at 7 calendar days per request, so this
script must run DAILY (via launchd) to accumulate a rolling window. Data older
than `retention_days` (default 60) is purged each run to bound disk usage.

Run from backend/:
    ./venv/bin/python scripts/sp1500_database_intraday.py
"""

import os
import pandas as pd
import yfinance as yf
from tqdm import tqdm
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta


def clean_symbols(string):
    return string.replace('.', '-')


class SP1500IntradayDB:
    def __init__(self):
        self.user = os.getenv("DB_USER", "postgres")
        self.password = os.getenv("DB_PASSWORD", "sarina00")
        self.host = os.getenv("DB_HOST", "127.0.0.1")
        self.port = os.getenv("DB_PORT", "5431")
        self.db_name = "sp1500_1m"
        self.tickers = []
        self.engine = None
        self.ETF_LIST = ['XLK', 'XLV', 'XLF', 'XLY', 'XLI',
                         'XLC', 'XLP', 'XLE', 'XLB', 'XLRE', 'XLU']

    def setup_database(self):
        """Create the sp1500_1m database and enable TimescaleDB."""
        main_url = f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/postgres"
        main_engine = create_engine(main_url)
        with main_engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": self.db_name},
            ).fetchone()
            if not exists:
                print(f"Creating database '{self.db_name}'...")
                conn.execute(text(f'CREATE DATABASE "{self.db_name}"'))
        main_engine.dispose()

        db_url = f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}"
        self.engine = create_engine(db_url)
        with self.engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            print("TimescaleDB extension enabled.")

    def fetch_tickers(self):
        """Discover tickers from the database; fall back to Wikipedia."""
        print(f"Checking database '{self.db_name}' for existing tickers...")
        if self.engine is None:
            db_url = f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}"
            self.engine = create_engine(db_url)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT table_name FROM information_schema.tables "
                         "WHERE table_schema = 'public'")
                )
                db_tickers = [row[0].upper() for row in result]
            if db_tickers:
                self.tickers = sorted(set(db_tickers) | set(self.ETF_LIST))
                print(f"Found {len(db_tickers)} tables in database "
                      f"(+ {len(self.ETF_LIST)} ETFs = {len(self.tickers)} total)")
                return
        except Exception as e:
            print(f"Database not yet accessible: {e}")

        print("Database empty. Fetching S&P 1500 tickers from Wikipedia...")
        urls = {
            "S&P 500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            "S&P 400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
            "S&P 600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
        }
        all_symbols = []
        headers = {"User-Agent": "Mozilla/5.0"}
        for name, url in urls.items():
            try:
                tables = pd.read_html(url, storage_options=headers)
                df = tables[0]
                col = "Symbol" if "Symbol" in df.columns else "Ticker"
                symbols = df[col].astype(str).apply(clean_symbols).tolist()
                all_symbols.extend(symbols)
                print(f"  {name}: {len(symbols)} tickers")
            except Exception as e:
                print(f"  {name} failed: {e}")
        self.tickers = sorted(set(all_symbols) | set(self.ETF_LIST))
        print(f"Total unique tickers: {len(self.tickers)}")

    def _ensure_hypertable(self, table_name):
        """Create table as a TimescaleDB hypertable if it does not exist."""
        with self.engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            exists = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                     "WHERE table_schema = 'public' AND table_name = :tbl)"),
                {"tbl": table_name},
            ).fetchone()[0]
            if exists:
                return
            conn.execute(text(f"""
                CREATE TABLE {table_name} (
                    "Date"      TIMESTAMPTZ NOT NULL,
                    "Open"      DOUBLE PRECISION,
                    "High"      DOUBLE PRECISION,
                    "Low"       DOUBLE PRECISION,
                    "Close"     DOUBLE PRECISION,
                    "Volume"    BIGINT
                )
            """))
            conn.execute(text(
                f"SELECT create_hypertable('{table_name}', 'Date', "
                f"chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
            ))
            conn.execute(text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table_name}_date "
                f"ON {table_name} (\"Date\")"
            ))

    def run_update(self):
        """Process every ticker: initial download or incremental append."""
        if self.engine is None:
            raise ValueError("Engine not initialized. Call setup_database() first.")
        if not self.tickers:
            print("No tickers to process.")
            return

        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        success = skipped = failed = 0

        print(f"Updating database '{self.db_name}'...")
        print(f"Today: {today} | Target: append new rows if last stored < {yesterday}")

        for symbol in tqdm(self.tickers, desc="Processing"):
            table_name = symbol.lower()
            try:
                self._ensure_hypertable(table_name)
                with self.engine.connect() as conn:
                    result = conn.execute(
                        text(f'SELECT MAX("Date") FROM {table_name}')
                    ).fetchone()
                    max_dt = result[0] if result else None

                if max_dt is None:
                    df = self._download_1m(symbol, period="7d")
                    if df.empty:
                        print(f"  [{symbol}] No data returned (delisted/error)")
                        failed += 1
                        continue
                    self._store_new_table(table_name, df)
                    print(f"  [{symbol}] Initial: {len(df)} rows (last 7 days)")
                    success += 1
                    continue

                if hasattr(max_dt, "tzinfo") and max_dt.tzinfo is not None:
                    max_dt = max_dt.replace(tzinfo=None)
                last_date = max_dt.date() if hasattr(max_dt, "date") else max_dt

                if last_date < yesterday:
                    df = self._download_1m(symbol, period="5d")
                    if df.empty:
                        skipped += 1
                        continue
                    new_rows = df[df.index > max_dt]
                    if new_rows.empty:
                        skipped += 1
                        continue
                    self._append_rows(table_name, new_rows)
                    success += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"  [{symbol}] Error: {e}")
                failed += 1

        print(f"\nDone: {success} updated | {skipped} skipped | {failed} failed "
              f"(total: {len(self.tickers)})")

    def run_cleanup(self, retention_days=60):
        """Drop TimescaleDB chunks older than retention_days."""
        print(f"\nRunning data retention cleanup (keeping last {retention_days} days)...")
        cutoff = datetime.now() - timedelta(days=retention_days)
        dropped = failed = 0
        for table_name in tqdm(self.tickers, desc="Cleanup"):
            tname = table_name.lower()
            try:
                with self.engine.connect() as conn:
                    conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                    result = conn.execute(text(
                        f"SELECT drop_chunks('{tname}', "
                        f"older_than => TIMESTAMP '{cutoff.isoformat()}')"
                    ))
                    if result.rowcount and result.rowcount > 0:
                        dropped += 1
            except Exception as e:
                print(f"  [{tname}] Cleanup error: {e}")
                failed += 1
        print(f"Cleanup done: {dropped} tables had old chunks dropped | {failed} failed")

    def _download_1m(self, symbol, period):
        """Download 1-minute data for *symbol*. yfinance caps 1m at 7 days."""
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(interval="1m", period=period)
            if df.empty:
                return df
            df.index = pd.to_datetime(df.index)
            if hasattr(df.index, "tz") and df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            cols = ["Open", "High", "Low", "Close", "Volume"]
            df = df[[c for c in cols if c in df.columns]]
            # CRITICAL FIX: yfinance names the index "Datetime", but sp1500_1m
            # tables use a "Date" column. Rename so df.to_sql() inserts into
            # "Date" instead of failing with "column Datetime does not exist".
            df.index.name = "Date"
            return df
        except Exception:
            return pd.DataFrame()

    def _store_new_table(self, table_name, df):
        """Store initial data and ensure TimescaleDB setup is complete."""
        df.to_sql(table_name, self.engine, if_exists="replace",
                  method="multi", chunksize=5000)
        with self.engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            conn.execute(text(
                f"SELECT create_hypertable('{table_name}', 'Date', "
                f"chunk_time_interval => INTERVAL '1 day', "
                f"migrate_data => true, if_not_exists => TRUE)"
            ))
            conn.execute(text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table_name}_date "
                f"ON {table_name} (\"Date\")"
            ))

    def _append_rows(self, table_name, df):
        """Append only new rows to an existing hypertable."""
        df.to_sql(table_name, self.engine, if_exists="append",
                  method="multi", chunksize=5000)


if __name__ == "__main__":
    import time
    db = SP1500IntradayDB()
    db.setup_database()
    db.fetch_tickers()
    t0 = time.time()
    db.run_update()
    db.run_cleanup(retention_days=60)
    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed:.1f}s")
