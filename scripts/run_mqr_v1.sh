#!/bin/bash
# MQR_V1 daily runner — Alpaca PAPER account 3 only.
#
# Deliberately separate from run_all_strategies.sh: enabling this schedule must
# NOT resume accounts 1 and 2 (DailyGoldenCrossRotation), which have been
# dormant since 2026-09-28. The shared launcher and its launchd agent stay
# disabled.
#
# Scheduled by ~/Library/LaunchAgents/com.tradecraft.alpaca-strategy-mqrv1.plist
# at 20:00, Monday-Friday (after the 18:00 database update).
#
# Logs:      backend/logs/alpaca_mqrv1_YYYYMMDD.log
# Heartbeat: backend/logs/alpaca_mqrv1_heartbeat.log
# Alerts:    backend/logs/ALERTS.log

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/backend/logs"
LOG_FILE="$LOG_DIR/alpaca_mqrv1_$(date +%Y%m%d).log"
HEARTBEAT_FILE="$LOG_DIR/alpaca_mqrv1_heartbeat.log"
ALERT_LOG="$LOG_DIR/ALERTS.log"

MODULE="momentum_quality_rotation_v1"
PREFIX="3"

mkdir -p "$LOG_DIR"

# Load environment (credentials, DB settings)
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR/backend" || exit 1
# shellcheck disable=SC1091
source venv/bin/activate

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ${MODULE} on account prefix '${PREFIX}'" | tee -a "$LOG_FILE"

python -m app.services.alpaca_runner_by_name "$MODULE" "$PREFIX" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS" | tee -a "$LOG_FILE"
    echo "$(date '+%Y-%m-%d %H:%M:%S') SUCCESS exit=0" > "$HEARTBEAT_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAILED exit=${EXIT_CODE}" | tee -a "$LOG_FILE"
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAILED exit=${EXIT_CODE}" > "$HEARTBEAT_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] MQR_V1 on account ${PREFIX} FAILED exit=${EXIT_CODE} — see $LOG_FILE" >> "$ALERT_LOG"
    osascript -e 'display notification "MQR_V1 run FAILED on account 3" with title "TradeCraft"' 2>/dev/null || true
fi

# Keep 30 days of this strategy's logs
find "$LOG_DIR" -name "alpaca_mqrv1_*.log" -mtime +30 -delete 2>/dev/null

exit "$EXIT_CODE"
