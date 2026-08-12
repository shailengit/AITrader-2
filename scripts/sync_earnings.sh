#!/bin/bash
# TradeCraft Earnings Calendar Sync
# Runs daily at 6:30 PM via cron

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/backend/logs"
LOG_FILE="$LOG_DIR/earnings_sync.log"

mkdir -p "$LOG_DIR"

# Load DB + API credentials from the project .env (authoritative; required
# under launchd where the clean environment has no shell exports).
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Load Finnhub key from zshrc if available
if [ -f "$HOME/.zshrc" ]; then
    export FINNHUB_API_KEY=$(grep 'FINNHUB_API_KEY=' "$HOME/.zshrc" | tail -1 | cut -d'=' -f2-)
fi

cd "$PROJECT_DIR/backend"
source venv/bin/activate

TODAY=$(date +%Y-%m-%d)
FUTURE=$(date -v+90d +%Y-%m-%d 2>/dev/null || date -d '+90 days' +%Y-%m-%d)

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting earnings sync: $TODAY to $FUTURE" >> "$LOG_FILE"

python -c "
import sys, json, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO)
from app.services.earnings_sync import sync_earnings_calendar
result = sync_earnings_calendar('$TODAY', '$FUTURE')
print(json.dumps(result, indent=2))
" >> "$LOG_FILE" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Earnings sync complete" >> "$LOG_FILE"
