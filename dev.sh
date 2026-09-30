#!/bin/bash

# TradeCraft Development Server Script
# Reclaims the ports, then starts the backend and the frontend.
#
# Lessons this script now encodes (2026-09-29):
#   * A dependency check must test what the app actually imports. The old check
#     `[ ! -f "venv/lib/python*/site-packages/fastapi" ]` had a quoted glob that
#     never expanded, so it was always true and every start ran
#     `pip install -r requirements.txt`. One bad line in that file
#     (`torch>=2.0.0ptyprocess`) then made the app unstartable, and the failure
#     surfaced as `ERROR: Invalid requirement` — nothing to do with a dev server.
#   * Never report "started" without checking the port. Both servers wrote to
#     /dev/null, so a failed bind looked exactly like success.
#   * The backend also runs as a launchd agent with KeepAlive. Killing its
#     process only makes launchd start another one, which then wins the port race
#     against the server started here. The agent is stopped for the session and
#     put back on exit.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/backend/venv/bin/python"
LOG_DIR="$SCRIPT_DIR/.dev-logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

# Ports. Overridable, because this app is meant to run alongside AITrader-1
# (which uses 8001 / 5174): VITE_PORT=5174 BACKEND_PORT=8001 ./dev.sh
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${VITE_PORT:-5173}"

# The backend and frontend are the two processes this script owns, and they are
# regularly left running on a port other than the ones above: vite moves to the
# next free port when its default is busy, and a second copy of this app or a
# sibling project uses different ones. So the ports are a starting point, and the
# command line — filtered to this checkout — is the real test.
BACKEND_PORTS=("$BACKEND_PORT" 8000 8001)
FRONTEND_PORTS=("$FRONTEND_PORT" 5173 5174 5175)

# The launchd agent that owns the backend port when this script is not running.
LAUNCHD_LABEL="com.tradecraft.alpaca-backend"
LAUNCHD_DOMAIN="gui/$(id -u)"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist"
# Written while the agent is stopped, and removed when it is put back. If this
# script is killed hard (SIGKILL, or a closed terminal) the trap cannot run, and
# without a marker the backend would simply be missing with no explanation.
LAUNCHD_MARKER="$LOG_DIR/launchd-$LAUNCHD_LABEL.stopped"
LAUNCHD_STOPPED=0

BACKEND_PID=""
FRONTEND_PID=""

log()  { echo -e "${BLUE}$1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}$1${NC}"; }
fail() { echo -e "${RED}$1${NC}"; }

# ------------------------------------------------------------------ processes

children_of() { pgrep -P "$1" 2>/dev/null || true; }

still_alive() { kill -0 "$1" 2>/dev/null; }

# Terminate a process and its children. `npm run dev` spawns vite and uvicorn
# --reload spawns a worker, and an orphaned child keeps the port.
kill_tree() {
    local pid="$1" kid
    for kid in $(children_of "$pid"); do
        kill_tree "$kid"
    done
    kill -TERM "$pid" 2>/dev/null || true
}

kill_tree_hard() {
    local pid="$1" kid
    for kid in $(children_of "$pid"); do
        kill_tree_hard "$kid"
    done
    kill -KILL "$pid" 2>/dev/null || true
}

# True when a process runs with its working directory inside this checkout. It
# keeps the command-line sweep from reaching into another project's vite.
in_this_repo() {
    local cwd
    cwd="$(lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
    case "$cwd" in
        "$SCRIPT_DIR"|"$SCRIPT_DIR"/*) return 0 ;;
        *) return 1 ;;
    esac
}

listening_pids() { lsof -ti:"$1" -sTCP:LISTEN 2>/dev/null || true; }

stop_pid() {
    local pid="$1" why="$2" i=0
    if [ -z "$pid" ]; then return 0; fi
    warn "Stopping $why (pid $pid)…"
    kill_tree "$pid"
    while still_alive "$pid" && [ "$i" -lt 12 ]; do
        sleep 0.25
        i=$((i + 1))
    done
    if still_alive "$pid"; then
        kill_tree_hard "$pid"
        sleep 0.25
    fi
    ok "$why stopped"
}

# Free the given ports, whoever holds them.
reclaim_ports() {
    local label="$1"
    shift
    local port pid
    for port in "$@"; do
        for pid in $(listening_pids "$port"); do
            stop_pid "$pid" "$label on port $port"
        done
    done
}

# Stop this app's backend/frontend wherever they are running — the ports above
# may not be the ones they chose.
reclaim_commands() {
    local pattern pid
    for pattern in "uvicorn app.main:app" "npm run dev" "node.*vite"; do
        for pid in $(pgrep -f "$pattern" 2>/dev/null || true); do
            if [ "$pid" != "$$" ] && in_this_repo "$pid"; then
                stop_pid "$pid" "$pattern"
            fi
        done
    done
}

stop_launchd_backend() {
    if launchctl print "$LAUNCHD_DOMAIN/$LAUNCHD_LABEL" >/dev/null 2>&1; then
        warn "Stopping launchd agent $LAUNCHD_LABEL (KeepAlive would restart it and re-take port $BACKEND_PORT)…"
        launchctl bootout "$LAUNCHD_DOMAIN/$LAUNCHD_LABEL" 2>/dev/null || true
        LAUNCHD_STOPPED=1
        : > "$LAUNCHD_MARKER"
        ok "$LAUNCHD_LABEL stopped for this session"
    fi
}

restore_launchd_backend() {
    if [ "$LAUNCHD_STOPPED" = "1" ] && [ -f "$LAUNCHD_PLIST" ]; then
        # ${...} braces are required here: macOS bash 3.2 swallows part of a
        # multibyte character that directly follows $NAME, so "$LABEL…" printed
        # as a blank label plus a broken byte.
        warn "Restoring launchd agent ${LAUNCHD_LABEL}…"
        launchctl bootstrap "$LAUNCHD_DOMAIN" "$LAUNCHD_PLIST" 2>/dev/null || true
        rm -f "$LAUNCHD_MARKER"
        LAUNCHD_STOPPED=0
        ok "$LAUNCHD_LABEL restored (it needs ~90s to finish starting)"
    fi
}

# ------------------------------------------------------------------ readiness

# Wait for a port to accept connections. The backend needs about 90 seconds on
# this machine — it imports torch, scikit-learn and the screener stack at startup
# — so the old two-second sleep was never enough to tell success from death.
wait_for_port() {
    local port="$1" label="$2" timeout="$3" i=0
    # %b, not %s: printf does not expand the escapes inside a variable, and a
    # literal \033[0;34m in the output is worse than no colour at all.
    printf '%b' "${BLUE}Waiting for $label on port $port (up to ${timeout}s) "
    while [ "$i" -lt "$timeout" ]; do
        if [ -n "$(listening_pids "$port")" ]; then
            printf '%b\n' "${GREEN}ready${NC}"
            return 0
        fi
        printf '.'
        sleep 1
        i=$((i + 1))
    done
    printf '%b\n' "${RED}timed out${NC}"
    return 1
}

show_log_tail() {
    local file="$1"
    if [ -f "$file" ]; then
        echo -e "${YELLOW}--- last 25 lines of $file ---${NC}"
        tail -n 25 "$file"
        echo -e "${YELLOW}--- end ---${NC}"
    fi
}

# ------------------------------------------------------------------- lifecycle

CLEANED_UP=0

cleanup() {
    # Runs from the EXIT trap, so every ending - Ctrl-C, a failed start, a
    # normal exit - goes through one path. Guarded because it can be reached
    # twice (INT then EXIT).
    if [ "$CLEANED_UP" = "1" ]; then return 0; fi
    CLEANED_UP=1
    echo ""
    warn "Shutting down servers…"
    if [ -n "$BACKEND_PID" ]; then stop_pid "$BACKEND_PID" "backend"; fi
    if [ -n "$FRONTEND_PID" ]; then stop_pid "$FRONTEND_PID" "frontend"; fi
    restore_launchd_backend
    ok "Servers stopped"
}

# The EXIT trap does the real work; INT/TERM only have to end the wait loop, or
# Ctrl-C would clean up and then keep running.
trap cleanup EXIT
trap 'exit 130' INT TERM

# ------------------------------------------------------------------------ main

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  TradeCraft Development Server${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""

mkdir -p "$LOG_DIR"

if [ -f "$LAUNCHD_MARKER" ]; then
    warn "A previous run of this script was killed before it could restart $LAUNCHD_LABEL."
    warn "It is restored automatically when this run exits. By hand:"
    warn "  launchctl bootstrap $LAUNCHD_DOMAIN \"$LAUNCHD_PLIST\""
fi

log "Reclaiming ports and leftover processes…"
# The launchd agent first: while it is loaded, killing its process only creates
# another one, and the two would race for the port.
stop_launchd_backend
reclaim_ports "backend" "${BACKEND_PORTS[@]}"
reclaim_ports "frontend" "${FRONTEND_PORTS[@]}"
reclaim_commands
echo ""

log "Starting backend server…"
cd "$SCRIPT_DIR/backend"

# Test what the app imports rather than a path that may not exist. A quoted glob
# in `[ -f ... ]` never expands, which is how every start ended up installing.
if ! "$VENV_PY" -c "import fastapi, uvicorn, sqlalchemy, ptyprocess" >/dev/null 2>&1; then
    warn "Backend dependencies are incomplete — installing…"
    if ! "$VENV_PY" -m pip install -r requirements.txt -q; then
        fail "pip install failed. Fix backend/requirements.txt before starting the app."
        exit 1
    fi
fi

: > "$BACKEND_LOG"
"$VENV_PY" -m uvicorn app.main:app --reload --port "$BACKEND_PORT" >> "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

if ! wait_for_port "$BACKEND_PORT" "backend" 180; then
    fail "Backend did not bind port $BACKEND_PORT."
    show_log_tail "$BACKEND_LOG"
    exit 1
fi
ok "Backend on http://localhost:$BACKEND_PORT"

log "Starting frontend server…"
cd "$SCRIPT_DIR/frontend"

if [ ! -d "node_modules" ]; then
    warn "Installing frontend dependencies…"
    if ! npm install; then
        fail "npm install failed."
        exit 1
    fi
fi

: > "$FRONTEND_LOG"
npm run dev -- --force --port "$FRONTEND_PORT" >> "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

if ! wait_for_port "$FRONTEND_PORT" "frontend" 120; then
    fail "Frontend did not bind port $FRONTEND_PORT."
    show_log_tail "$FRONTEND_LOG"
    exit 1
fi
ok "Frontend on http://localhost:$FRONTEND_PORT"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  All servers running!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BLUE}Frontend:${NC} http://localhost:$FRONTEND_PORT"
echo -e "  ${BLUE}Backend:${NC}  http://localhost:$BACKEND_PORT"
echo -e "  ${BLUE}API Docs:${NC}  http://localhost:$BACKEND_PORT/docs"
echo -e "  ${BLUE}Logs:${NC}      $LOG_DIR/{backend,frontend}.log"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all servers${NC}"
echo -e "${YELLOW}$LAUNCHD_LABEL is stopped while this runs and restored on exit.${NC}"
echo ""

# Stay in the foreground and notice if either server dies, instead of waiting on
# processes whose output nobody can see.
while true; do
    if ! still_alive "$BACKEND_PID"; then
        fail "Backend exited."
        show_log_tail "$BACKEND_LOG"
        exit 1
    fi
    if ! still_alive "$FRONTEND_PID"; then
        fail "Frontend exited."
        show_log_tail "$FRONTEND_LOG"
        exit 1
    fi
    sleep 2
done
