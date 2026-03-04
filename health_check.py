#!/usr/bin/env python3
"""
health_check.py — Checks that all CSL Bot services are running.
Sends an alert email if any service is down.
Cron: every 15 min, 6 AM–8 PM ET, 7 days/week
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

SERVICES = ["csl-ftl", "csl-boviet", "csl-tolead", "csl-upload", "csl-webhook"]


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


def send_alert(down_services):
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    subject = f"CSL Bot Service Alert — {len(down_services)} Down — {now}"

    td = 'style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;"'
    th = 'style="padding:6px 10px;text-align:left;border-bottom:1px solid #ddd;color:white;font-size:13px;"'

    rows = ""
    for i, (name, status) in enumerate(down_services):
        alt = ' style="background:#f9f9f9;"' if i % 2 == 1 else ''
        rows += (f'<tr{alt}>'
                 f'<td {td}><b>{name}</b></td>'
                 f'<td {td} style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;color:#c62828;font-weight:bold;">{status}</td>'
                 f'</tr>')

    body = (
        f'<div style="font-family:Arial,sans-serif;max-width:700px;">'
        f'<div style="background:#c62828;color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:15px;">'
        f'<b>Service Alert — {len(down_services)} Service(s) Down</b></div>'
        f'<div style="border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:12px;">'
        f'<p style="margin:0 0 8px 0;font-size:12px;color:#888;">{now}</p>'
        f'<table style="border-collapse:collapse;width:100%;border:1px solid #ddd;">'
        f'<tr style="background:#c62828;"><th {th}>Service</th><th {th}>Status</th></tr>'
        f'{rows}</table>'
        f'<p style="margin:12px 0 0 0;font-size:12px;color:#555;">'
        f'SSH in and run: <code>systemctl restart SERVICE_NAME</code></p>'
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
    down = []
    for svc in SERVICES:
        ok, status = check_service(svc)
        if ok:
            print(f"  {svc}: OK")
        else:
            print(f"  {svc}: DOWN ({status})")
            down.append((svc, status))

    if down:
        send_alert(down)
    else:
        print("  All services healthy.")


if __name__ == "__main__":
    main()
