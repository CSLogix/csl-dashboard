#!/usr/bin/env bash
# CSL Document Tracker — stop all services
# Usage: ./stop.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$SCRIPT_DIR/.pids"

echo "=== CSL Document Tracker — Stopping Services ==="

for pidfile in "$PID_DIR"/*.pid; do
    [ -f "$pidfile" ] || continue
    name="$(basename "$pidfile" .pid)"
    pid="$(cat "$pidfile")"

    if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping $name (PID $pid)..."
        kill "$pid"
        # Wait up to 5 seconds for graceful shutdown
        for i in $(seq 1 5); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 1
        done
        # Force kill if still running
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Force killing $name..."
            kill -9 "$pid" 2>/dev/null
        fi
    else
        echo "$name (PID $pid) is not running"
    fi
    rm -f "$pidfile"
done

echo "All services stopped."
