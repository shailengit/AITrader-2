#!/bin/bash
# TradeCraft VIX Data Sync
# Downloads VIX data from Yahoo Finance and upserts it into sp1500_1d.vix.
# Runs daily after market close from com.tradecraft.vix-sync (6:45 PM).
# Can also be run by hand: scripts/sync_vix.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/backend/logs"
LOG_FILE="$LOG_DIR/vix_sync.log"
VENV_PYTHON="$PROJECT_DIR/backend/venv/bin/python"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR/backend"

# Load DB credentials from the repo-root .env (single source of truth).
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$PROJECT_DIR/.env"
    set +a
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting VIX sync..." >> "$LOG_FILE"

"$VENV_PYTHON" - >> "$LOG_FILE" 2>&1 <<'PY'
import os
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine, text

user = os.environ.get("DB_USER", "postgres")
password = os.environ["DB_PASSWORD"]
host = os.environ.get("DB_HOST", "127.0.0.1")
port = os.environ.get("DB_PORT", "5431")
name = os.environ.get("DB_NAME", "sp1500_1d")

engine = create_engine(f"postgresql://{user}:{password}@{host}:{port}/{name}")

with engine.connect() as conn:
    latest = conn.execute(text('SELECT MAX("Date") FROM vix')).scalar()

start = (latest + timedelta(days=1)) if latest else date(1990, 1, 1)
end = date.today() + timedelta(days=1)

if start >= end:
    print(f"VIX already current through {latest}; nothing to do.")
    raise SystemExit(0)

print(f"VIX: fetching {start} -> {end} (latest in DB: {latest})")
raw = yf.download(
    "^VIX",
    start=start.isoformat(),
    end=end.isoformat(),
    auto_adjust=True,
    progress=False,
)
if raw is None or raw.empty:
    print("VIX: no data returned by Yahoo Finance.")
    raise SystemExit(0)

if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)

raw = raw.reset_index()
raw.columns = [str(c) for c in raw.columns]
raw = raw.rename(columns={raw.columns[0]: "Date"})
for column in ("Open", "High", "Low", "Close", "Volume"):
    if column not in raw.columns:
        raw[column] = None

raw["Date"] = pd.to_datetime(raw["Date"]).dt.date
raw = raw.dropna(subset=["Close"])

upserted = 0
with engine.begin() as conn:
    for _, row in raw.iterrows():
        conn.execute(text("""
            INSERT INTO vix ("Date", "Open", "High", "Low", "Close", "Volume")
            VALUES (:date, :open, :high, :low, :close, :volume)
            ON CONFLICT ("Date") DO UPDATE SET
                "Open" = EXCLUDED."Open",
                "High" = EXCLUDED."High",
                "Low" = EXCLUDED."Low",
                "Close" = EXCLUDED."Close",
                "Volume" = EXCLUDED."Volume"
        """), {
            "date": row["Date"],
            "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
            "high": float(row["High"]) if pd.notna(row["High"]) else None,
            "low": float(row["Low"]) if pd.notna(row["Low"]) else None,
            "close": float(row["Close"]),
            "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else 0,
        })
        upserted += 1

print(f"VIX sync: {upserted} rows upserted, latest {raw['Date'].max()}")
PY

echo "[$(date '+%Y-%m-%d %H:%M:%S')] VIX sync complete" >> "$LOG_FILE"
