#!/bin/bash
# Intraday (1-Minute) Database Update Wrapper — AITrader-2
# Runs backend/scripts/sp1500_database_intraday.py with logging.
# Scheduled daily at 8:00 AM via launchd (com.tradecraft.intraday-updater).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$HOME/Library/Logs/StockScreener"
VENV_PYTHON="$PROJECT_DIR/backend/venv/bin/python"
SCRIPT="$PROJECT_DIR/backend/scripts/sp1500_database_intraday.py"

mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
LOG_FILE="$LOG_DIR/intraday_update_$TIMESTAMP.log"

echo "========================================" | tee -a "$LOG_FILE"
echo "[$(date)] Starting intraday (1m) database update (AITrader-2)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

if "$VENV_PYTHON" "$SCRIPT" 2>&1 | tee -a "$LOG_FILE"; then
    echo "[$(date)] Intraday update completed successfully" | tee -a "$LOG_FILE"
    osascript -e 'display notification "Intraday DB Updated" with title "TradeCraft"'
    exit 0
else
    echo "[$(date)] Intraday update FAILED" | tee -a "$LOG_FILE"
    osascript -e 'display notification "Intraday DB Update FAILED" with title "TradeCraft"'
    exit 1
fi
