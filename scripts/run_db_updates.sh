#!/bin/bash
# Daily (1-Day) Database Update Wrapper — AITrader-2
# Runs the proven StockScreener_2 daily update batch (technical, metadata,
# fundamentals) which writes to the sp1500_1d database.
# Scheduled daily at 6:00 PM via launchd (com.tradecraft.db-updater).
#
# The original AITrader-1/data_updates/run_db_updates.sh was deleted, which
# silently broke the daily update. This wrapper restores it by delegating to
# the working hardened batch in StockScreener_2.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HOME/Library/Logs/StockScreener"
HARDENED_SCRIPT="/Users/shailendrakaushik/Documents/Python/AlgoTrading/StockScreener_2/scripts/run_db_updates_hardened.sh"

mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
LOG_FILE="$LOG_DIR/db_update_wrapper_$TIMESTAMP.log"

echo "========================================" | tee -a "$LOG_FILE"
echo "[$(date)] Starting daily (1d) database update (AITrader-2 wrapper)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

if [ ! -x "$HARDENED_SCRIPT" ]; then
    echo "[$(date)] ERROR: hardened script not found/executable: $HARDENED_SCRIPT" | tee -a "$LOG_FILE"
    osascript -e 'display notification "Daily DB Update FAILED: hardened script missing" with title "TradeCraft"' 2>/dev/null
    exit 1
fi

if "$HARDENED_SCRIPT" 2>&1 | tee -a "$LOG_FILE"; then
    echo "[$(date)] Daily update completed successfully" | tee -a "$LOG_FILE"
    osascript -e 'display notification "Daily DB Updated" with title "TradeCraft"' 2>/dev/null
    exit 0
else
    echo "[$(date)] Daily update FAILED" | tee -a "$LOG_FILE"
    osascript -e 'display notification "Daily DB Update FAILED" with title "TradeCraft"' 2>/dev/null
    exit 1
fi
