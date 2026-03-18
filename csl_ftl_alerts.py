#!/usr/bin/env python3
"""
csl_ftl_alerts.py — shared email + dedup module for FTL status alerts.
Used by both ftl_monitor.py (cron) and app.py (webhook background task).
Thread-safe dedup via fcntl.flock().
"""
import fcntl
import json
import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

from csl_logging import get_logger

log = get_logger("csl_ftl_alerts")

# ── Config ──────────────────────────────────────────────────────────────────────
SENT_ALERTS_FILE = "/root/csl-bot/ftl_sent_alerts.json"

SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_CC      = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")
EMAIL_FALLBACK = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")


# ── Account rep routing ─────────────────────────────────────────────────────────
ACCOUNT_REPS_PG = {
    "Allround": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Boviet":   {"rep": "",      "email": "Boviet-efj@evansdelivery.com"},
    "Cadi":     {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "CNL":      {"rep": "Janice","email": "Janice.Cortes@evansdelivery.com"},
    "DHL":      {"rep": "John F","email": "John.Feltz@evansdelivery.com"},
    "DSV":      {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "EShipping":{"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "IWS":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Kishco":   {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "Kischo":   {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "Kripke":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MAO":      {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "Mamata":   {"rep": "John F","email": "John.Feltz@evansdelivery.com"},
    "Meiko":    {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MGF":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Mitchell\'s Transport": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Rose":     {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "SEI Acquisition": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Sutton":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Tanera":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Talatrans":{"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "TCR":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Texas International": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Tolead":   {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "USHA":     {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
}


STATUS_TO_DROPDOWN = {
    "Driver Arrived at Pickup": "At Pickup",
    "Departed Pickup - En Route": "In Transit",
    "Arrived at Delivery": "At Delivery",
    "Departed Delivery": "Departed Delivery",
    "Running Late": "Running Behind",
    "Tracking Behind Schedule": "Running Behind",
    "Tracking Waiting for Update": "Tracking Waiting for",
    "Delivered": "Delivered",
    "Driver Phone Unresponsive": "Driver Phone Unresponsive",
    "Tracking Completed Successfully": "Delivered",
    "Tracking Completed": "Delivered",
}


# ── Alert dedup (thread-safe with flock) ────────────────────────────────────────
def load_sent_alerts() -> dict:
    if not os.path.exists(SENT_ALERTS_FILE):
        return {}
    try:
        with open(SENT_ALERTS_FILE) as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except Exception as exc:
        log.warning("Could not read %s: %s", SENT_ALERTS_FILE, exc)
        return {}


def save_sent_alerts(data: dict):
    try:
        tmp = SENT_ALERTS_FILE + ".tmp"
        with open(tmp, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, indent=2)
            fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, SENT_ALERTS_FILE)
    except Exception as exc:
        log.warning("Could not save %s: %s", SENT_ALERTS_FILE, exc)


def already_sent(sent: dict, key: str, status: str) -> bool:
    return status in sent.get(key, [])


def mark_sent(sent: dict, key: str, status: str):
    sent.setdefault(key, [])
    if status not in sent[key]:
        sent[key].append(status)


# ── Email sending ───────────────────────────────────────────────────────────────
def _send_email(to_email: str, cc_email: str | None, subject: str, body: str):
    """Send an HTML email via Gmail SMTP/STARTTLS."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    if cc_email and cc_email != to_email:
        msg["Cc"] = cc_email
    msg.attach(MIMEText(body, "html"))

    recipients = [to_email]
    if cc_email and cc_email != to_email:
        recipients.append(cc_email)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_USER, recipients, msg.as_string())
        log.info("Email sent -> %s  (cc: %s)", to_email, cc_email or "none")
    except Exception as exc:
        log.warning("Email failed: %s", exc)


def send_ftl_email(efj: str, load_num: str, status: str, tab_name: str,
                   account_lookup: dict, mp_load_id: str = None,
                   stop_times: dict = None):
    """Send an FTL status alert email routed to the rep for this account."""
    info      = account_lookup.get(tab_name, {})
    rep_email = info.get("email", "")
    rep_name  = info.get("rep",   "")

    if rep_email:
        to_email = rep_email
        cc_email = None if tab_name.lower() in ("boviet", "tolead") else EMAIL_CC
    else:
        to_email = EMAIL_FALLBACK
        cc_email = None

    now     = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    load_display = mp_load_id or load_num

    # Determine header color: red if BEHIND, green otherwise
    behind = False
    if stop_times:
        for k in ("stop1_eta", "stop2_eta"):
            if stop_times.get(k) and "BEHIND" in stop_times[k].upper():
                behind = True
                break
    is_failure = any(k in status for k in ("Can't Make It", "Phone Unresponsive", "Unresponsive"))
    hdr_color = "#c62828" if (behind or is_failure) else "#1b5e20"

    subject = f"CSL Tracking \u2014 {tab_name} \u2014 {efj} | {load_display} \u2014 {status}"

    rows = ""
    rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Account</td><td style=\"padding:4px 8px;\">{tab_name}</td></tr>"
    if rep_name:
        rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Rep</td><td style=\"padding:4px 8px;\">{rep_name}</td></tr>"
    if mp_load_id:
        rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">MP Load</td><td style=\"padding:4px 8px;\">{mp_load_id}</td></tr>"
    rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Status</td><td style=\"padding:4px 8px;\">{status}</td></tr>"

    timeline = ""
    if stop_times:
        tl_rows = ""
        if stop_times.get("stop1_arrived"):
            tl_rows += f"<tr><td style=\"padding:3px 8px;color:#555;\">Pickup Arrived</td><td style=\"padding:3px 8px;\">{stop_times['stop1_arrived']}</td></tr>"
        elif stop_times.get("stop1_eta"):
            tl_rows += f"<tr><td style=\"padding:3px 8px;color:#555;\">Pickup ETA</td><td style=\"padding:3px 8px;\">{stop_times['stop1_eta']}</td></tr>"
        if stop_times.get("stop1_departed"):
            tl_rows += f"<tr><td style=\"padding:3px 8px;color:#555;\">Pickup Departed</td><td style=\"padding:3px 8px;\">{stop_times['stop1_departed']}</td></tr>"
        if stop_times.get("stop2_arrived"):
            tl_rows += f"<tr><td style=\"padding:3px 8px;color:#555;\">Delivery Arrived</td><td style=\"padding:3px 8px;\">{stop_times['stop2_arrived']}</td></tr>"
        elif stop_times.get("stop2_eta"):
            tl_rows += f"<tr><td style=\"padding:3px 8px;color:#555;\">Delivery ETA</td><td style=\"padding:3px 8px;\">{stop_times['stop2_eta']}</td></tr>"
        if stop_times.get("stop2_departed"):
            tl_rows += f"<tr><td style=\"padding:3px 8px;color:#555;\">Delivery Departed</td><td style=\"padding:3px 8px;\">{stop_times['stop2_departed']}</td></tr>"
        if tl_rows:
            timeline = (
                f"<table style=\"border-collapse:collapse;margin-top:8px;\">"
                f"<tr><td colspan=\"2\" style=\"padding:6px 8px;font-weight:bold;border-bottom:1px solid #ccc;\">Stop Timeline</td></tr>"
                f"{tl_rows}</table>"
            )

    body = (
        f"<div style=\"font-family:Arial,sans-serif;max-width:600px;\">"
        f"<p style=\"color:#888;font-size:12px;\">Tracking Update \u2014 {now}</p>"
        f"<div style=\"background:{hdr_color};color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:16px;\">"
        f"<b>{load_num} / {load_display}</b></div>"
        f"<div style=\"border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:10px;\">"
        f"<table style=\"border-collapse:collapse;\">{rows}</table>"
        f"{timeline}"
        f"</div></div>"
    )

    _send_email(to_email, cc_email, subject, body)


def _send_pod_reminder_ftl(efj, load_num, dest, tab_name, account_lookup, mp_load_id=None):
    """Send POD reminder email when FTL tracking completes."""
    info = account_lookup.get(tab_name, {})
    rep_email = info.get("email", "")
    to_email = rep_email if rep_email else EMAIL_FALLBACK

    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    load_ref = mp_load_id or load_num
    ref = f"{tab_name}--{load_ref}"

    subject = f"POD Needed \u2014 {ref}({dest}) Has Delivered"

    body = f"""<html><body style="font-family:Arial,sans-serif;">
<div style="background:#c62828;color:white;padding:12px 16px;border-radius:6px 6px 0 0;">
  <b>POD Reminder \u2014 {ref}</b>
</div>
<div style="padding:16px;border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;">
  <p style="font-size:15px;margin:0 0 12px;">
    <b>{ref}({dest})</b> has been marked <b style="color:#c62828;">Delivered</b> by Macropoint tracking.
  </p>
  <p style="font-size:15px;margin:0 0 12px;">
    Please obtain the POD from the driver/carrier as soon as possible.
  </p>
  <table style="border-collapse:collapse;margin:12px 0;">
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Account</td><td style="padding:4px 0;"><b>{tab_name}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">EFJ #</td><td style="padding:4px 0;"><b>{efj}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Load #</td><td style="padding:4px 0;"><b>{load_num}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Destination</td><td style="padding:4px 0;">{dest}</td></tr>
  </table>
  <p style="font-size:12px;color:#888;margin:16px 0 0;">
    Status has been auto-set to "Need POD". Update to "POD Received" once obtained.<br>
    Sent at {now}
  </p>
</div>
</body></html>"""

    try:
        cc = None if tab_name.lower() in ("boviet", "tolead") else EMAIL_CC
        _send_email(to_email, cc, subject, body)
        log.info("POD reminder sent for %s to %s", ref, to_email)
    except Exception as exc:
        log.warning("POD reminder email failed for %s: %s", ref, exc)


# ── Convenience wrapper for webhook real-time alerts ────────────────────────────
def send_webhook_alert(efj: str, load_num: str, status: str, account: str,
                       stop_times: dict = None, mp_load_id: str = None):
    """
    One-call wrapper for webhook background task:
    1. Load dedup state (with flock)
    2. Check if already sent
    3. Send email
    4. Mark sent + save
    Returns True if email was sent, False if skipped (dedup).
    """
    key = f"{efj}|{load_num}"
    sent = load_sent_alerts()

    if already_sent(sent, key, status):
        log.info("Webhook alert: already sent %s for %s — skipping", status, key)
        return False

    send_ftl_email(efj, load_num, status, account, ACCOUNT_REPS_PG,
                   mp_load_id=mp_load_id, stop_times=stop_times)
    mark_sent(sent, key, status)
    save_sent_alerts(sent)
    log.info("Webhook alert: sent %s for %s", status, key)

    # POD reminder on Delivered
    if "delivered" in status.lower():
        dest = ""  # webhook doesn't always have dest — email still works without it
        try:
            import psycopg2, psycopg2.extras
            from dotenv import load_dotenv as _ld
            _ld("/root/csl-bot/csl-doc-tracker/.env")
            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "5432")),
                dbname=os.getenv("DB_NAME", "csl_dispatch"),
                user=os.getenv("DB_USER", "csl_user"),
                password=os.getenv("DB_PASSWORD", ""),
            )
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT destination FROM shipments WHERE efj = %s", (efj,))
                row = cur.fetchone()
                if row:
                    dest = row.get("destination", "") or ""
            conn.close()
        except Exception:
            pass
        _send_pod_reminder_ftl(efj, load_num, dest, account, ACCOUNT_REPS_PG,
                               mp_load_id=mp_load_id)

    return True
