#!/bin/bash
# Daily multi-account Alpaca strategy runner.
# Runs the deployed strategies on their respective paper accounts:
#   - daily_golden_cross -> 1 account (ALPACA_1_*) = PA3LE9Y79BU0  (Acct#1)
#   - daily_golden_cross -> 2 account (ALPACA_2_*) = PA33GEZZ5K7Y  (Acct#2)
#   - sector_top5_pegy   -> 3 account (ALPACA_3_*) = PA3CE4ALJ8OJ  (Acct#3) — slot DISABLED, see below
#
# Account display names come from ALPACA_<n>_NAME in the root .env (single source
# of truth), never from a hard-coded strategy name.
#
# There is NO `set -e` here on purpose: one failing slot must not abort the batch.
# That fail-fast behaviour is how a two-week `unauthorized.` outage stayed
# invisible. Every failure is logged, collected, written to
# backend/logs/ALERTS.log and shown as a macOS notification; the batch then exits
# non-zero so the failure surfaces.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/backend/logs"
ALERT_LOG="$LOG_DIR/ALERTS.log"
mkdir -p "$LOG_DIR"

# Load environment
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR/backend"

# Slots that failed this run: "Acct#1: DailyGoldenCross (prefix '1') exit=1"
FAILURES=()

account_name() {
    local prefix="$1"
    local var="ALPACA_${prefix}_NAME"
    local name="${!var}"
    if [ -n "$name" ]; then
        echo "$name"
    else
        echo "Account ${prefix}"
    fi
}

# Run one slot. Records the failure and returns non-zero, but never exits the
# script — the caller keeps going through the remaining slots.
run_one() {
    local module="$1" prefix="$2" strategy="$3"
    local name
    name="$(account_name "$prefix")"
    local log="$LOG_DIR/alpaca_${module}_$(date +%Y%m%d).log"

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ${strategy} on ${name} (${module}, prefix '${prefix}')..." >> "$log"
    ./venv/bin/python -m app.services.alpaca_runner_by_name "$module" "$prefix" >> "$log" 2>&1
    local code=$?

    if [ "$code" -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${strategy} on ${name} complete" >> "$log"
        return 0
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAILED ${strategy} on ${name} (${module}, prefix '${prefix}') exit=${code} — see $log" >> "$log"
    FAILURES+=("${name}: ${strategy} (prefix '${prefix}') exit=${code}")
    return "$code"
}

# Daily Golden Cross on 1 account
run_one daily_golden_cross "1" "DailyGoldenCross"
# Daily Golden Cross on 2 account
run_one daily_golden_cross "2" "DailyGoldenCrossRotation"
# Sector Scanner Top-5 V3 on 3 account
# DISABLED 2026-09-29: this slot traded on its own without an explicit deploy (the
# schedule kept an implicit binding), so restore it only via a deliberate deploy.
# run_one sector_top5_pegy "3" "SectorTop5Pegy"

# Keep only last 30 days
find "$LOG_DIR" -name "alpaca_*.log" -mtime +30 -delete

if [ "${#FAILURES[@]}" -gt 0 ]; then
    summary=""
    for failure in "${FAILURES[@]}"; do
        summary="${summary}${summary:+; }${failure}"
    done
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] BATCH FAILURE: ${summary}" >> "$ALERT_LOG"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] BATCH FAILURE: ${summary}"
    /usr/bin/osascript -e "display notification \"${summary}\" with title \"TradeCraft strategy run failed\"" || true
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] All strategies complete"
exit 0
