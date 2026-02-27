#!/usr/bin/env bash
# CSL Document Tracker — start all services
# Usage: ./start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$SCRIPT_DIR/.pids"
LOG_DIR="$SCRIPT_DIR"

mkdir -p "$PID_DIR"

echo "=== CSL Document Tracker — Starting Services ==="

# 1. Sheets Sync
echo "Starting sheets_sync..."
cd "$SCRIPT_DIR"
python3 sheets_sync.py >> "$LOG_DIR/sheets_sync.log" 2>&1 &
echo $! > "$PID_DIR/sheets_sync.pid"
echo "  PID $(cat "$PID_DIR/sheets_sync.pid")"

# 2. Gmail Monitor
echo "Starting gmail_monitor..."
python3 gmail_monitor.py >> "$LOG_DIR/gmail_monitor.log" 2>&1 &
echo $! > "$PID_DIR/gmail_monitor.pid"
echo "  PID $(cat "$PID_DIR/gmail_monitor.pid")"

# 3. FastAPI Dashboard
echo "Starting dashboard on port ${DASHBOARD_PORT:-8080}..."
python3 app.py >> "$LOG_DIR/dashboard.log" 2>&1 &
echo $! > "$PID_DIR/dashboard.pid"
echo "  PID $(cat "$PID_DIR/dashboard.pid")"

echo ""
echo "All services started. PIDs stored in $PID_DIR/"
echo "Logs:"
echo "  Sheets sync:   $LOG_DIR/sheets_sync.log"
echo "  Gmail monitor:  $LOG_DIR/gmail_monitor.log"
echo "  Dashboard:      $LOG_DIR/dashboard.log"
echo ""
echo "To stop: ./stop.sh"
