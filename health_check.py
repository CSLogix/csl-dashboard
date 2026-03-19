#!/usr/bin/env python3
"""
health_check.py — Comprehensive CSL Bot health monitor.

Checks:
  1. systemd services (csl-boviet, csl-tolead, csl-upload, csl-dashboard, csl-inbox)
  2. Cron job logs (dray import, dray export, vessel schedules)
  3. Macropoint session cookie freshness
  4. JsonCargo API key validity
  5. Oxylabs proxy reachability
  6. State file integrity (JSON parseable, not stale)
  7. Disk usage

Sends an alert email if any check fails.
Cron: every 15 min, 6 AM-8 PM ET, 7 days/week
"""
import json
import os
import subprocess
import smtplib
import time
import requests
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv("/root/csl-bot/.env")
# Also load dashboard env for DB_* vars
load_dotenv("/root/csl-bot/csl-doc-tracker/.env")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
ALERT_TO = "john.feltz@evansdelivery.com"

ET = ZoneInfo("America/New_York")

# All systemd services that should be running
SERVICES = [
    "csl-boviet",
    "csl-tolead",
    "csl-upload",
    "csl-dashboard",
    "csl-inbox",
]

# State files to monitor: path -> max age in hours before considered stale
STATE_FILES = {
    "/root/csl-bot/last_check.json": 26,          # updated twice daily on weekdays
    "/root/csl-bot/export_state.json": 2,          # updated every hour
    "/root/csl-bot/ftl_sent_alerts.json": 2,       # updated every 10-30 min
    "/root/csl-bot/ftl_tracking_cache.json": 2,
    "/root/csl-bot/boviet_sent_alerts.json": 26,
    "/root/csl-bot/tolead_sent_alerts.json": 26,
    "/root/csl-bot/unresponsive_state.json": 2,
}

MP_COOKIES_FILE = "/root/csl-bot/mp_cookies.json"
JSONCARGO_BASE = "https://api.jsoncargo.com/api/v1"

# Dedup: don't re-alert within this window (seconds)
_DEDUP_FILE = "/tmp/csl_health_last_alert.json"
_DEDUP_WINDOW = 1800  # 30 minutes


# ── Service checks ──────────────────────────────────────────────────────────

def check_service(name):
    """Return (is_active, status_text)."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=10,
        )
        status = result.stdout.strip()
        return status == "active", status
    except Exception as e:
        return False, str(e)


# ── Cron job checks ─────────────────────────────────────────────────────────

def check_cron_jobs():
    """Check cron job logs for failures. Returns list of (name, issue) tuples."""
    try:
        from cron_log_parser import get_all_cron_status
    except ImportError:
        return []

    issues = []
    for key, info in get_all_cron_status().items():
        status = info["status"]
        name = info["name"]
        if status == "failed":
            issues.append((name, f"FAILED — last run {info['last_run'] or 'unknown'}"))
        elif status == "overdue":
            issues.append((name, f"OVERDUE — no successful run today (last: {info['last_run'] or 'never'})"))
    return issues


# ── Macropoint cookie check ─────────────────────────────────────────────────

def check_mp_cookies():
    """Check if Macropoint session cookies exist and aren't expired.
    Returns (ok, message)."""
    if not os.path.exists(MP_COOKIES_FILE):
        return False, "mp_cookies.json not found"

    try:
        with open(MP_COOKIES_FILE) as f:
            cookies = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return False, f"mp_cookies.json unreadable: {e}"

    if not cookies:
        return False, "mp_cookies.json is empty"

    # Check file modification time — if not refreshed in 7 days, warn
    mtime = os.path.getmtime(MP_COOKIES_FILE)
    age_days = (time.time() - mtime) / 86400
    if age_days > 7:
        return False, f"mp_cookies.json is {age_days:.0f} days old — session likely expired"

    # Check individual cookie expiry timestamps
    now_ts = time.time()
    expired_count = 0
    for c in cookies:
        exp = c.get("expires", -1)
        if isinstance(exp, (int, float)) and exp > 0:
            # Normalize large microsecond timestamps
            if exp > 1e12:
                exp = exp / 1e6
            if exp < now_ts:
                expired_count += 1

    if expired_count > 0 and expired_count == len([c for c in cookies if c.get("expires", -1) > 0]):
        return False, f"All {expired_count} cookies with expiry dates are expired"

    return True, f"OK ({len(cookies)} cookies, {age_days:.1f} days old)"


# ── JsonCargo API check ─────────────────────────────────────────────────────

def check_jsoncargo_api():
    """Verify JsonCargo API key is valid with a lightweight call.
    Returns (ok, message)."""
    api_key = os.environ.get("JSONCARGO_API_KEY", "")
    if not api_key:
        return False, "JSONCARGO_API_KEY not set"

    try:
        # Use a known test container to validate API key works
        resp = requests.get(
            f"{JSONCARGO_BASE}/containers/MAEU0000000/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        # 401/403 = bad key; 404 or 200 = key is valid (container may not exist)
        if resp.status_code in (401, 403):
            return False, f"API key rejected (HTTP {resp.status_code})"
        return True, f"OK (HTTP {resp.status_code})"
    except requests.Timeout:
        return False, "API timeout (10s)"
    except requests.ConnectionError:
        return False, "API unreachable"
    except Exception as e:
        return False, f"API error: {e}"


# ── Proxy check ─────────────────────────────────────────────────────────────

def check_proxy():
    """Check Oxylabs proxy connectivity.
    Returns (ok, message)."""
    proxy_server = os.environ.get("PROXY_SERVER", "")
    proxy_user = os.environ.get("PROXY_USERNAME", "")
    proxy_pass = os.environ.get("PROXY_PASSWORD", "")

    if not proxy_server:
        return True, "No proxy configured (skipped)"

    proxy_url = f"http://{proxy_user}:{proxy_pass}@{proxy_server}"
    try:
        resp = requests.get(
            "https://httpbin.org/ip",
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=15,
        )
        if resp.status_code == 200:
            return True, f"OK (IP: {resp.json().get('origin', 'unknown')})"
        return False, f"Proxy returned HTTP {resp.status_code}"
    except requests.Timeout:
        return False, "Proxy timeout (15s) — may be quota exhausted"
    except requests.ConnectionError as e:
        return False, f"Proxy unreachable: {e}"
    except Exception as e:
        return False, f"Proxy error: {e}"


# ── State file checks ───────────────────────────────────────────────────────

def check_state_files():
    """Check state files for corruption and staleness.
    Returns list of (filename, issue) tuples."""
    issues = []
    now = time.time()

    for path, max_age_hours in STATE_FILES.items():
        basename = os.path.basename(path)

        if not os.path.exists(path):
            # Missing state files aren't critical — they get created on first run
            continue

        # Check JSON validity
        try:
            with open(path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            issues.append((basename, f"CORRUPT JSON — {e}"))
            continue
        except OSError as e:
            issues.append((basename, f"UNREADABLE — {e}"))
            continue

        # Check staleness (only on weekdays for daily files)
        mtime = os.path.getmtime(path)
        age_hours = (now - mtime) / 3600
        weekday = datetime.now(ET).weekday()

        # Skip staleness check on weekends for files that only update on weekdays
        if weekday >= 5 and max_age_hours > 4:
            continue

        if age_hours > max_age_hours * 2:  # Alert at 2x expected age
            issues.append((basename, f"STALE — {age_hours:.1f}h old (expected update every {max_age_hours}h)"))

    return issues


# ── Disk check ──────────────────────────────────────────────────────────────

def check_disk():
    """Check disk usage. Returns (ok, message)."""
    try:
        result = subprocess.run(
            ["df", "-h", "/"], capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            pct = int(parts[4].replace("%", ""))
            if pct > 90:
                return False, f"CRITICAL — {parts[4]} used ({parts[3]} free)"
            return True, f"OK — {parts[4]} used ({parts[3]} free)"
    except Exception as e:
        return False, f"Check failed: {e}"
    return True, "OK"


# ── Dedup logic ─────────────────────────────────────────────────────────────

def _load_dedup():
    try:
        with open(_DEDUP_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_dedup(data):
    with open(_DEDUP_FILE, "w") as f:
        json.dump(data, f)


def _should_alert(issue_key):
    """Return True if we should send alert for this issue (not recently alerted)."""
    dedup = _load_dedup()
    last = dedup.get(issue_key, 0)
    return (time.time() - last) > _DEDUP_WINDOW


def _mark_alerted(issue_keys):
    """Mark issues as recently alerted."""
    dedup = _load_dedup()
    now = time.time()
    for key in issue_keys:
        dedup[key] = now
    # Prune old entries
    dedup = {k: v for k, v in dedup.items() if now - v < 86400}
    _save_dedup(dedup)


# ── Email alert ─────────────────────────────────────────────────────────────

def send_alert(issues_by_category):
    """Send HTML alert email with categorized issues.
    issues_by_category: dict of category -> list of (name, detail) tuples
    """
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    total = sum(len(v) for v in issues_by_category.values())
    subject = f"CSL Bot Alert — {total} Issue(s) — {now}"

    td = 'style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;"'
    th = 'style="padding:6px 10px;text-align:left;border-bottom:1px solid #ddd;color:white;font-size:13px;"'

    CATEGORY_COLORS = {
        "Service Down": "#c62828",
        "Cron Job": "#e65100",
        "Macropoint Session": "#6a1b9a",
        "API / External": "#1565c0",
        "State Files": "#ff8f00",
        "Infrastructure": "#455a64",
    }

    rows = ""
    for category, items in issues_by_category.items():
        color = CATEGORY_COLORS.get(category, "#333")
        bg = "#fff8e1" if category != "Service Down" else "#ffebee"
        for name, detail in items:
            rows += (
                f'<tr style="background:{bg};">'
                f'<td {td}><b>{name}</b></td>'
                f'<td {td}>{category}</td>'
                f'<td {td} style="padding:6px 10px;border-bottom:1px solid #eee;'
                f'font-size:13px;color:{color};font-weight:bold;">{detail}</td>'
                f'</tr>'
            )

    body = (
        f'<div style="font-family:Arial,sans-serif;max-width:700px;">'
        f'<div style="background:#c62828;color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:15px;">'
        f'<b>CSL Bot Alert — {total} Issue(s)</b></div>'
        f'<div style="border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:12px;">'
        f'<p style="margin:0 0 8px 0;font-size:12px;color:#888;">{now}</p>'
        f'<table style="border-collapse:collapse;width:100%;border:1px solid #ddd;">'
        f'<tr style="background:#c62828;"><th {th}>Name</th><th {th}>Type</th><th {th}>Status</th></tr>'
        f'{rows}</table>'
        f'<p style="margin:12px 0 0 0;font-size:12px;color:#555;">'
        f'Services: <code>systemctl restart SERVICE_NAME</code><br>'
        f'MP Cookies: <code>http://SERVER:5001/mp-login</code><br>'
        f'Cron logs: <code>/tmp/csl_import.log</code>, <code>/tmp/export_monitor.log</code></p>'
        f'</div></div>'
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_TO
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_USER, [ALERT_TO], msg.as_string())
        print(f"  Alert sent -> {ALERT_TO}")
    except Exception as e:
        print(f"  WARNING: Email failed: {e}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(ET)
    hour = now.hour
    if hour < 6 or hour >= 20:
        return  # Outside monitoring hours

    print(f"[{now.strftime('%Y-%m-%d %H:%M ET')}] Health check...")

    all_issues = {}  # category -> [(name, detail)]

    # 1. Check systemd services
    for svc in SERVICES:
        ok, status = check_service(svc)
        if ok:
            print(f"  {svc}: OK")
        else:
            print(f"  {svc}: DOWN ({status})")
            all_issues.setdefault("Service Down", []).append((svc, status))

    # 2. Check cron jobs (weekdays only)
    if now.weekday() < 5:
        cron_issues = check_cron_jobs()
        if cron_issues:
            for name, issue in cron_issues:
                print(f"  {name}: {issue}")
            all_issues["Cron Job"] = cron_issues
        else:
            print("  Cron jobs: OK")
    else:
        print("  Cron jobs: skipped (weekend)")

    # 3. Macropoint cookies
    mp_ok, mp_msg = check_mp_cookies()
    if mp_ok:
        print(f"  MP cookies: {mp_msg}")
    else:
        print(f"  MP cookies: ISSUE — {mp_msg}")
        all_issues.setdefault("Macropoint Session", []).append(("Macropoint Cookies", mp_msg))

    # 4. JsonCargo API (check once per hour, not every 15 min)
    if now.minute < 15:
        jc_ok, jc_msg = check_jsoncargo_api()
        if jc_ok:
            print(f"  JsonCargo API: {jc_msg}")
        else:
            print(f"  JsonCargo API: ISSUE — {jc_msg}")
            all_issues.setdefault("API / External", []).append(("JsonCargo API", jc_msg))

    # 5. Proxy (check once per hour)
    if now.minute < 15:
        proxy_ok, proxy_msg = check_proxy()
        if proxy_ok:
            print(f"  Proxy: {proxy_msg}")
        else:
            print(f"  Proxy: ISSUE — {proxy_msg}")
            all_issues.setdefault("API / External", []).append(("Oxylabs Proxy", proxy_msg))

    # 6. State files
    state_issues = check_state_files()
    if state_issues:
        for name, issue in state_issues:
            print(f"  {name}: {issue}")
        all_issues["State Files"] = state_issues
    else:
        print("  State files: OK")

    # 7. Disk
    disk_ok, disk_msg = check_disk()
    if disk_ok:
        print(f"  Disk: {disk_msg}")
    else:
        print(f"  Disk: {disk_msg}")
        all_issues.setdefault("Infrastructure", []).append(("Disk Space", disk_msg))

    # Send alert if there are new issues (dedup)
    if all_issues:
        # Build dedup keys from issue names
        issue_keys = []
        for cat, items in all_issues.items():
            for name, _ in items:
                issue_keys.append(f"{cat}:{name}")

        # Filter to only new issues
        new_keys = [k for k in issue_keys if _should_alert(k)]
        if new_keys:
            send_alert(all_issues)
            _mark_alerted(issue_keys)
        else:
            print("  Issues found but already alerted recently — skipping email.")
    else:
        print("  All systems healthy.")


if __name__ == "__main__":
    main()
