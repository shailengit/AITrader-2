#!/bin/bash
# TradeCraft Golden Cross Rotation — Daily Alpaca Strategy Runner
# Runs weekdays at 8:00 PM ET via cron (after database update at 6 PM)
#
# Add to crontab:
#   0 20 * * 1-5 /path/to/scripts/run_alpaca_strategy.sh
#
# Logs:   backend/logs/alpaca_strategy_YYYYMMDD.log
# Heartbeat: backend/logs/alpaca_strategy_heartbeat.log (last run timestamp + status)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/backend/logs"
LOG_FILE="$LOG_DIR/alpaca_strategy_$(date +%Y%m%d).log"
HEARTBEAT_FILE="$LOG_DIR/alpaca_strategy_heartbeat.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

mkdir -p "$LOG_DIR"

# Load environment variables
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR/backend"
source venv/bin/activate

echo "[${TIMESTAMP}] Starting daily strategy run..." | tee -a "$LOG_FILE"

# Run the strategy and capture exit code
EXIT_CODE=0
python -m app.services.alpaca_runner >> "$LOG_FILE" 2>&1 || EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Daily strategy run completed successfully" | tee -a "$LOG_FILE"
    echo "${TIMESTAMP} SUCCESS exit=0" > "$HEARTBEAT_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ Daily strategy run FAILED (exit code: ${EXIT_CODE})" | tee -a "$LOG_FILE"
    echo "${TIMESTAMP} FAILED exit=${EXIT_CODE}" > "$HEARTBEAT_FILE"
fi

# Keep only last 30 days of logs
find "$LOG_DIR" -name "alpaca_strategy_*.log" -mtime +30 -delete

exit "$EXIT_CODE"
