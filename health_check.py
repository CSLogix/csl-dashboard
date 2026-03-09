#!/usr/bin/env python3
"""
health_check.py — Checks that all CSL Bot services are running
and cron jobs have completed successfully.
Sends an alert email if any service is down or cron job failed.
Cron: every 15 min, 6 AM-8 PM ET, 7 days/week
"""
import os
import subprocess
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv("/root/csl-bot/.env")

SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USER     = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
ALERT_TO      = "john.feltz@evansdelivery.com"

SERVICES = ["csl-boviet", "csl-tolead", "csl-upload"]


def check_service(name):
    """Return (is_active, status_text)."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=10
        )
        status = result.stdout.strip()
        return status == "active", status
    except Exception as e:
        return False, str(e)


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
        # "partial", "idle", "pending", "no_data" are not alert-worthy
    return issues


def send_alert(down_services, cron_issues):
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    total = len(down_services) + len(cron_issues)
    subject = f"CSL Bot Alert — {total} Issue(s) — {now}"

    td = 'style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;"'
    th = 'style="padding:6px 10px;text-align:left;border-bottom:1px solid #ddd;color:white;font-size:13px;"'

    rows = ""
    for name, status in down_services:
        rows += (f'<tr>'
                 f'<td {td}><b>{name}</b></td>'
                 f'<td {td}>Service</td>'
                 f'<td {td} style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;color:#c62828;font-weight:bold;">{status}</td>'
                 f'</tr>')
    for name, issue in cron_issues:
        rows += (f'<tr style="background:#fff8e1;">'
                 f'<td {td}><b>{name}</b></td>'
                 f'<td {td}>Cron Job</td>'
                 f'<td {td} style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;color:#e65100;font-weight:bold;">{issue}</td>'
                 f'</tr>')

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


def main():
    now = datetime.now(ZoneInfo("America/New_York"))
    hour = now.hour
    if hour < 6 or hour >= 20:
        return  # Outside monitoring hours

    print(f"[{now.strftime('%Y-%m-%d %H:%M ET')}] Health check...")

    # Check systemd services
    down = []
    for svc in SERVICES:
        ok, status = check_service(svc)
        if ok:
            print(f"  {svc}: OK")
        else:
            print(f"  {svc}: DOWN ({status})")
            down.append((svc, status))

    # Check cron jobs (weekdays only)
    cron_issues = []
    if now.weekday() < 5:
        cron_issues = check_cron_jobs()
        if cron_issues:
            for name, issue in cron_issues:
                print(f"  {name}: {issue}")
        else:
            print("  Cron jobs: OK")
    else:
        print("  Cron jobs: skipped (weekend)")

    if down or cron_issues:
        send_alert(down, cron_issues)
    else:
        print("  All systems healthy.")


if __name__ == "__main__":
    main()
