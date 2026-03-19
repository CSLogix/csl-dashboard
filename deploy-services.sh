#!/usr/bin/env bash
# deploy-services.sh — Install systemd units + nginx config on the server
#
# Usage: sudo ./deploy-services.sh
#
# What this does:
#   1. Copies all .service and .timer files to /etc/systemd/system/
#   2. Disables old duplicate services (ftl-monitor, webhook)
#   3. Enables and starts all services and timers
#   4. Removes old crontab entries (replaced by systemd timers)
#   5. Installs nginx config (if nginx is installed)
#
# After running, the old start.sh/stop.sh scripts are no longer needed.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: run as root (sudo ./deploy-services.sh)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYSTEMD_DIR="$SCRIPT_DIR/systemd"
NGINX_DIR="$SCRIPT_DIR/nginx"

echo "=== CSL Services — Deploying ==="

# ─── 1. Install systemd units ───────────────────────────────────────────────
echo ""
echo "Installing systemd unit files..."
cp "$SYSTEMD_DIR"/*.service /etc/systemd/system/
cp "$SYSTEMD_DIR"/*.timer /etc/systemd/system/
systemctl daemon-reload
echo "  Done."

# ─── 2. Disable old duplicate services ──────────────────────────────────────
echo ""
echo "Disabling old duplicate services..."
for old_svc in ftl-monitor webhook; do
    if systemctl list-unit-files "${old_svc}.service" &>/dev/null; then
        systemctl disable --now "${old_svc}.service" 2>/dev/null || true
        echo "  Disabled: ${old_svc}.service"
    fi
done

# ─── 3. Stop old PID-based dashboard processes ──────────────────────────────
echo ""
echo "Stopping old PID-based processes..."
PID_DIR="/root/csl-bot/csl-doc-tracker/.pids"
if [ -d "$PID_DIR" ]; then
    for pidfile in "$PID_DIR"/*.pid; do
        [ -f "$pidfile" ] || continue
        name="$(basename "$pidfile" .pid)"
        pid="$(cat "$pidfile")"
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Stopping $name (PID $pid)..."
            kill "$pid" 2>/dev/null || true
        fi
        rm -f "$pidfile"
    done
fi

# ─── 4. Enable and start long-running services ──────────────────────────────
echo ""
echo "Enabling long-running services..."
SERVICES=(
    csl-ftl
    csl-export
    csl-boviet
    csl-tolead
    csl-webhook
    csl-upload
    csl-dashboard
    csl-sheets-sync
    csl-gmail-monitor
)
for svc in "${SERVICES[@]}"; do
    systemctl enable --now "${svc}.service"
    echo "  Enabled: ${svc}.service"
done

# ─── 5. Enable timers (replace cron) ────────────────────────────────────────
echo ""
echo "Enabling timers..."
TIMERS=(
    csl-import
    csl-health-check
    csl-lfd-watchdog
    csl-daily-summary
    csl-backup
)
for tmr in "${TIMERS[@]}"; do
    systemctl enable --now "${tmr}.timer"
    echo "  Enabled: ${tmr}.timer"
done

# ─── 6. Show what to remove from crontab ────────────────────────────────────
echo ""
echo "── Crontab cleanup ──"
echo "The following cron entries are now handled by systemd timers."
echo "Run 'crontab -e' and remove these lines:"
echo ""
echo "  # csl_bot.py → csl-import.timer"
echo "  30 7 * * 1-5  cd /root/csl-bot && python3 csl_bot.py ..."
echo "  30 13 * * 1-5 cd /root/csl-bot && python3 csl_bot.py ..."
echo ""
echo "  # health_check.py → csl-health-check.timer"
echo "  # lfd_watchdog.py → csl-lfd-watchdog.timer"
echo "  # daily_summary.py → csl-daily-summary.timer"
echo "  # backup_state.py → csl-backup.timer"
echo ""

# ─── 7. Install nginx config (optional) ─────────────────────────────────────
if command -v nginx &>/dev/null; then
    echo "── Nginx ──"
    cp "$NGINX_DIR/csl-dashboard.conf" /etc/nginx/sites-available/csl-dashboard
    ln -sf /etc/nginx/sites-available/csl-dashboard /etc/nginx/sites-enabled/csl-dashboard

    # Remove default site if it exists
    rm -f /etc/nginx/sites-enabled/default

    if nginx -t 2>&1; then
        systemctl reload nginx
        echo "  Nginx config installed and reloaded."
        echo ""
        echo "  For TLS, run:"
        echo "    sudo apt install certbot python3-certbot-nginx"
        echo "    sudo certbot --nginx -d your-domain.com"
    else
        echo "  WARNING: nginx config test failed. Check /etc/nginx/sites-available/csl-dashboard"
    fi
else
    echo "── Nginx not installed ──"
    echo "  To install: sudo apt install nginx"
    echo "  Then re-run this script, or manually:"
    echo "    sudo cp nginx/csl-dashboard.conf /etc/nginx/sites-available/csl-dashboard"
    echo "    sudo ln -s /etc/nginx/sites-available/csl-dashboard /etc/nginx/sites-enabled/"
    echo "    sudo nginx -t && sudo systemctl reload nginx"
fi

# ─── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Check status:"
echo "  systemctl status csl-ftl csl-export csl-boviet csl-tolead"
echo "  systemctl status csl-dashboard csl-sheets-sync csl-gmail-monitor"
echo "  systemctl status csl-webhook csl-upload"
echo "  systemctl list-timers 'csl-*'"
echo ""
echo "View logs:"
echo "  journalctl -u csl-dashboard -f"
echo "  journalctl -u csl-import --since today"
