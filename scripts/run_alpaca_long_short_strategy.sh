#!/bin/bash
# TradeCraft Golden Cross Rotation — Long/Short Alpaca Strategy Runner
# Runs weekdays at 8:00 PM ET via cron (after database update at 6 PM)
# Designed for a separate Alpaca account from the long-only strategy.
#
# Add to crontab:
#   0 20 * * 1-5 /path/to/scripts/run_alpaca_long_short_strategy.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/backend/logs"
LOG_FILE="$LOG_DIR/alpaca_long_short_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

# Load environment variables
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR/backend"
source venv/bin/activate

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting long/short strategy run..." >> "$LOG_FILE"

python -m app.services.alpaca_runner_long_short >> "$LOG_FILE" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Long/short strategy run complete" >> "$LOG_FILE"

# Keep only last 30 days of logs
find "$LOG_DIR" -name "alpaca_long_short_*.log" -mtime +30 -delete
