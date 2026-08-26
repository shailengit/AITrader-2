#!/bin/bash
# Daily multi-account Alpaca strategy runner.
# Runs all three deployed strategies on their respective accounts:
#   - Momentum Quality Rotation   -> default account (ALPACA_*)
#   - Daily Golden Cross Rotation -> LS account (ALPACA_LS_*) = PA3EW6COMH40
#   - Sector Scanner Top-5        -> 3 account (ALPACA_3_*) = PA3Q31C2WTO3
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/backend/logs"
mkdir -p "$LOG_DIR"

# Load environment
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR/backend"

run_one() {
    local module="$1" prefix="$2" label="$3"
    local log="$LOG_DIR/alpaca_${module}_$(date +%Y%m%d).log"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ${label} (${module}, prefix '${prefix}')..." >> "$log"
    ./venv/bin/python -m app.services.alpaca_runner_by_name "$module" "$prefix" >> "$log" 2>&1
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${label} complete" >> "$log"
}

# MQR on default account
run_one momentum_quality_rotation "" "MomentumQualityRotation"
# Daily Golden Cross on LS account
run_one daily_golden_cross "LS" "DailyGoldenCrossRotation"
# Sector Scanner Top-5 on 3 account
run_one sector_scanner_top5_rotation "3" "SectorScannerTop5Rotation"

# Keep only last 30 days
find "$LOG_DIR" -name "alpaca_*.log" -mtime +30 -delete
echo "[$(date '+%Y-%m-%d %H:%M:%S')] All strategies complete"
