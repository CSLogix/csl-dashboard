#!/usr/bin/env python3
"""
tolead_monitor.py — polls Tolead hub sheets (ORD, JFK, LAX, DFW) every 20 min,
scrapes Macropoint tracking URLs, and sends email alerts on status changes.
Alert-only: does NOT write back to the sheets.

For "Tracking Waiting for Update" and "Driver Phone Unresponsive" statuses,
emails tolead-efj@evansdelivery.com with subject = hub + status + MP load reference.
"""
import json
import os
import re
import smtplib
import time
import requests
import gspread
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Reuse Macropoint scraper from ftl_monitor
from ftl_monitor import scrape_macropoint

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────────
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "/root/csl-credentials.json")
SENT_ALERTS_FILE = "/root/csl-bot/tolead_sent_alerts.json"
POLL_INTERVAL    = 20 * 60  # 20 minutes

# Alert destination
ALERT_EMAIL = "tolead-efj@evansdelivery.com"

# SMTP
SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USER     = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]

# ── Hub configs ─────────────────────────────────────────────────────────────
HUBS = [
    {
        "name": "ORD",
        "sheet_id": "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac",
        "tab": "Schedule",
        "col_load_id": 1, "col_date": 4, "col_time": 5,
        "col_origin": 6, "col_dest": 7, "col_status": 9,
        "col_efj": 15, "col_trailer": 16,
    },
    {
        "name": "JFK",
        "sheet_id": "1mfhEsK2zg6GWTqMDTo5VwCgY-QC1tkNPknurHMxtBhs",
        "tab": "Schedule",
        "col_load_id": 0, "col_date": 3, "col_time": 4,
        "col_origin": 6, "col_dest": 7, "col_status": 9,
        "col_efj": 14, "col_trailer": 15,
    },
    {
        "name": "LAX",
        "sheet_id": "1YLB6z5LdL0kFYTcfq_H5e6acU8-VLf8nN0XfZrJ-bXo",
        "tab": "LAX",
        "col_load_id": 3, "col_date": 4, "col_time": 5,
        "col_origin": None, "col_dest": 6, "col_status": 8,
        "col_efj": 0, "col_trailer": 10,
    },
    {
        "name": "DFW",
        "sheet_id": "1RfGcq25x4qshlBDWDJD-xBJDlJm6fvDM_w2RTHhn9oI",
        "tab": "DFW",
        "col_load_id": 4, "col_date": 5, "col_time": 6,
        "col_origin": None, "col_dest": 3, "col_status": 11,
        "col_efj": 10, "col_trailer": 12,
    },
]

# Skip statuses (case-insensitive)
SKIP_STATUSES = {"delivered", "canceled", "cancelled"}

# These statuses ALWAYS trigger an alert even if driver is on time
ALWAYS_ALERT_STATUSES = {"Delivered"}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


# ── Credentials ──────────────────────────────────────────────────────────────
def _load_credentials():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds


# ── Hyperlinks ───────────────────────────────────────────────────────────────
def _get_hyperlinks(creds, sheet_id, tab, col_efj) -> list:
    """Fetch hyperlinks from the EFJ column via Sheets API v4."""
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        f"?ranges={tab}&fields=sheets.data.rowData.values.hyperlink"
    )
    resp = requests.get(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=30)
    data = resp.json()
    rows = data.get("sheets", [{}])[0].get("data", [{}])[0].get("rowData", [])

    links = []
    for row in rows:
        vals = row.get("values", [])
        link = vals[col_efj].get("hyperlink", "") if len(vals) > col_efj else ""
        links.append(link)
    return links


# ── Alert dedup ──────────────────────────────────────────────────────────────
def load_sent_alerts() -> dict:
    if os.path.exists(SENT_ALERTS_FILE):
        with open(SENT_ALERTS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_sent_alerts(data: dict):
    import shutil
    if os.path.exists(SENT_ALERTS_FILE):
        shutil.copy2(SENT_ALERTS_FILE, SENT_ALERTS_FILE + ".bak")
    tmp = SENT_ALERTS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, SENT_ALERTS_FILE)


def _is_behind_schedule(stop_times: dict) -> bool:
    """Check if any ETA indicates the driver is behind schedule."""
    if not stop_times:
        return False
    for eta_key in ("stop1_eta", "stop2_eta"):
        eta = stop_times.get(eta_key) or ""
        if "BEHIND" in eta.upper():
            return True
    return False


def _get_stop_events(stop_times: dict) -> set:
    """Return set of stop event keys that have timestamps."""
    if not stop_times:
        return set()
    events = set()
    for key in ("stop1_arrived", "stop1_departed", "stop2_arrived", "stop2_departed"):
        if stop_times.get(key):
            events.add(key)
    return events


EVENT_LABELS = {
    "stop1_arrived":  "Arrived at Pickup",
    "stop1_departed": "Departed Pickup",
    "stop2_arrived":  "Arrived at Delivery",
    "stop2_departed": "Departed Delivery",
}


def get_last_state(sent: dict, key: str) -> tuple:
    """Get last status and events for a load. Handles old format migration."""
    val = sent.get(key)
    if val is None:
        return None, set()
    if isinstance(val, str):
        return val, set()
    return val.get("status"), set(val.get("events", []))


def update_state(sent: dict, key: str, status: str, events: set):
    """Record the latest status and stop events."""
    sent[key] = {"status": status, "events": sorted(events)}


# ── Email ────────────────────────────────────────────────────────────────────
def _send_email(to_email, subject, body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_USER, [to_email], msg.as_string())
        print(f"    Email sent -> {to_email}")
    except Exception as exc:
        print(f"    WARNING: Email failed: {exc}")


def _is_load_behind(stop_times):
    """Check if any stop ETA shows BEHIND."""
    if not stop_times:
        return False
    for k in ("stop1_eta", "stop2_eta"):
        if stop_times.get(k) and "BEHIND" in stop_times[k].upper():
            return True
    return False


def send_tolead_alert(hub_name, load_id, efj, status, dest, pickup_date="", mp_load_id=None, stop_times=None):
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")

    load_ref = mp_load_id or load_id
    subject = f"{hub_name} Tolead \u2014 {status} \u2014 {load_ref}"

    behind = _is_load_behind(stop_times)
    hdr_color = "#c62828" if behind else "#1b5e20"

    rows = ""
    rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Load #</td><td style=\"padding:4px 8px;\">{load_id}</td></tr>"
    if mp_load_id:
        rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">MP Load</td><td style=\"padding:4px 8px;\">{mp_load_id}</td></tr>"
    rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Hub</td><td style=\"padding:4px 8px;\">{hub_name}</td></tr>"
    rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Status</td><td style=\"padding:4px 8px;\">{status}</td></tr>"
    rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Destination</td><td style=\"padding:4px 8px;\">{dest}</td></tr>"
    rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Pickup Date</td><td style=\"padding:4px 8px;\">{pickup_date}</td></tr>"

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
        f"<p style=\"color:#888;font-size:12px;\">Tolead FTL Status Update \u2014 {now}</p>"
        f"<div style=\"background:{hdr_color};color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:16px;\">"
        f"<b>{efj} / {load_ref}</b></div>"
        f"<div style=\"border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:10px;\">"
        f"<table style=\"border-collapse:collapse;\">{rows}</table>"
        f"{timeline}"
        f"</div></div>"
    )

    _send_email(ALERT_EMAIL, subject, body)


# ── Helper: safe column read ────────────────────────────────────────────────
def _col(row, idx):
    """Read a column value safely, returns '' if idx is None or out of range."""
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()


# ── Per-hub processing ───────────────────────────────────────────────────────
def run_once_hub(hub, creds, gc, browser, sent, dry_run=False):
    """Process a single hub sheet. Returns number of alerts sent."""
    name = hub["name"]
    print(f"\n  --- {name} Hub ---")

    try:
        sh = gc.open_by_key(hub["sheet_id"])
        ws = sh.worksheet(hub["tab"])
        rows = ws.get_all_values()
        links = _get_hyperlinks(creds, hub["sheet_id"], hub["tab"], hub["col_efj"])
    except Exception as exc:
        print(f"  ERROR reading {name} sheet: {exc}")
        return 0

    col_efj = hub["col_efj"]
    col_status = hub["col_status"]

    to_process = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) <= col_efj:
            continue
        status = _col(row, col_status)
        if not status or status.lower() in SKIP_STATUSES:
            continue
        mp_url = links[i - 1] if i - 1 < len(links) else ""
        if not mp_url or "macropoint" not in mp_url.lower():
            continue
        to_process.append((i, row, mp_url))

    print(f"  Total rows: {len(rows) - 1}  |  To track: {len(to_process)}")

    if not to_process:
        return 0

    changes = 0
    for sheet_row, row, mp_url in to_process:
        load_id     = _col(row, hub["col_load_id"])
        efj         = _col(row, col_efj)
        dest        = _col(row, hub["col_dest"])
        pickup_date = _col(row, hub["col_date"])
        alert_key   = f"{load_id}|{efj}"

        print(f"\n  [{sheet_row}] {load_id} / {efj}")
        print(f"    Scraping: {mp_url[:60]}...")

        mp_status, stop1_arrived, stop2_departed, _, _, mp_load_id, cant_make_it, stop_times = scrape_macropoint(browser, mp_url)

        if not mp_status and not cant_make_it:
            print("    No status detected")
            continue

        print(f"    Status: {mp_status}")

        if dry_run:
            print(f"    (dry-run — skipping alerts)")
            continue

        # Check for status change or new stop events
        last_status, last_events = get_last_state(sent, alert_key)
        current_events = _get_stop_events(stop_times)
        new_events = current_events - last_events
        has_status_change = (mp_status != last_status)

        if not has_status_change and not new_events:
            print("    (no change)")
            # Still check for Can't Make It even if status unchanged
            if cant_make_it:
                cmi_key = f"{alert_key}|CMI"
                cmi_last, _ = get_last_state(sent, cmi_key)
                if cmi_last != cant_make_it:
                    cmi_status = f"Can't Make It - {cant_make_it}"
                    print(f"    CAN'T MAKE IT detected: {cant_make_it}")
                    send_tolead_alert(name, load_id, efj, cmi_status, dest, pickup_date, mp_load_id, stop_times=stop_times)
                    update_state(sent, cmi_key, cant_make_it, set())
                    changes += 1
            continue

        if new_events:
            labels = [EVENT_LABELS.get(e, e) for e in sorted(new_events)]
            print(f"    New events: {', '.join(labels)}")

        # Decide if this change warrants an email
        is_critical = (mp_status in ALWAYS_ALERT_STATUSES
                       or "can't make" in mp_status.lower())
        is_behind = _is_behind_schedule(stop_times)
        has_new_stop = bool(new_events)

        if is_critical or is_behind or has_new_stop:
            send_tolead_alert(name, load_id, efj, mp_status, dest, pickup_date, mp_load_id, stop_times=stop_times)
            changes += 1
        else:
            print("    On time, no new events — no alert needed")

        # Always update tracked state
        update_state(sent, alert_key, mp_status, current_events)

        # ── CAN'T MAKE IT alert ──
        if cant_make_it:
            cmi_key = f"{alert_key}|CMI"
            cmi_last, _ = get_last_state(sent, cmi_key)
            if cmi_last != cant_make_it:
                cmi_status = f"Can't Make It - {cant_make_it}"
                print(f"    CAN'T MAKE IT detected: {cant_make_it}")
                send_tolead_alert(name, load_id, efj, cmi_status, dest, pickup_date, mp_load_id, stop_times=stop_times)
                update_state(sent, cmi_key, cant_make_it, set())
                changes += 1

    return changes


# ── Main loop ────────────────────────────────────────────────────────────────
def run_once(dry_run=False):
    print(f"\n{'='*60}")
    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    print(f"Tolead Monitor — {now_str}")

    creds = _load_credentials()
    gc = gspread.authorize(creds)
    sent = load_sent_alerts()

    total_changes = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for hub in HUBS:
                try:
                    changes = run_once_hub(hub, creds, gc, browser, sent, dry_run=dry_run)
                    total_changes += changes
                except Exception as exc:
                    print(f"  ERROR in {hub['name']}: {exc}")
        finally:
            browser.close()

    if not dry_run:
        save_sent_alerts(sent)
    print(f"\n  Done — {total_changes} new alert(s) sent across all hubs.")


def main():
    hubs_str = ", ".join(h["name"] for h in HUBS)
    print(f"Tolead Monitor started — hubs: {hubs_str} — 6 AM to 8 PM ET, Mon-Fri, every 20 min.")
    while True:
        now_et = datetime.now(ZoneInfo("America/New_York"))
        hour = now_et.hour
        weekday = now_et.weekday()  # 0=Mon, 6=Sun

        if weekday >= 5 or hour < 6 or hour >= 20:
            # Outside operating window — sleep until next Mon-Fri 6 AM
            wake = now_et.replace(hour=6, minute=0, second=0, microsecond=0)
            if hour >= 20 or weekday >= 5:
                wake += __import__("datetime").timedelta(days=1)
            # Skip to Monday if wake lands on weekend
            while wake.weekday() >= 5:
                wake += __import__("datetime").timedelta(days=1)
            sleep_secs = (wake - now_et).total_seconds()
            print(f"  Outside hours ({now_et.strftime('%a %H:%M ET')}). Sleeping until {wake.strftime('%a 6 AM')} ({int(sleep_secs // 60)} min)...")
            time.sleep(max(sleep_secs, 60))
            continue

        try:
            run_once()
        except Exception as exc:
            print(f"  ERROR in run_once: {exc}")
        print(f"  Sleeping {POLL_INTERVAL // 60} min...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        # Test mode: 1 row per hub, sends real emails
        print("TEST MODE — 1 row per hub, real emails")
        creds = _load_credentials()
        gc = gspread.authorize(creds)
        sent = load_sent_alerts()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for hub in HUBS:
                    name = hub["name"]
                    col_efj = hub["col_efj"]
                    col_status = hub["col_status"]
                    print(f"\n  --- {name} Hub ---")

                    try:
                        sh = gc.open_by_key(hub["sheet_id"])
                        ws = sh.worksheet(hub["tab"])
                        rows = ws.get_all_values()
                        links = _get_hyperlinks(creds, hub["sheet_id"], hub["tab"], col_efj)
                    except Exception as exc:
                        print(f"  ERROR reading {name}: {exc}")
                        continue

                    to_process = []
                    for i, row in enumerate(rows[1:], start=2):
                        if len(row) <= col_efj:
                            continue
                        status = _col(row, col_status)
                        if not status or status.lower() in SKIP_STATUSES:
                            continue
                        mp_url = links[i - 1] if i - 1 < len(links) else ""
                        if not mp_url or "macropoint" not in mp_url.lower():
                            continue
                        to_process.append((i, row, mp_url))

                    print(f"  Total rows: {len(rows) - 1}  |  To track: {len(to_process)}")

                    if to_process:
                        sheet_row, row, mp_url = to_process[0]
                        load_id = _col(row, hub["col_load_id"])
                        efj = _col(row, col_efj)
                        dest = _col(row, hub["col_dest"])
                        pickup_date = _col(row, hub["col_date"])
                        alert_key = f"{load_id}|{efj}"

                        print(f"\n  [{sheet_row}] {load_id} / {efj}")
                        print(f"    URL: {mp_url[:60]}...")

                        mp_status, _, _, _, _, mp_load_id, cant_make_it, stop_times = scrape_macropoint(browser, mp_url)
                        if mp_status:
                            print(f"    Status: {mp_status}")
                            last_status, last_events = get_last_state(sent, alert_key)
                            current_events = _get_stop_events(stop_times)
                            new_events = current_events - last_events
                            has_status_change = (mp_status != last_status)
                            is_critical = (mp_status in ALWAYS_ALERT_STATUSES
                                           or "can't make" in mp_status.lower())
                            is_behind = _is_behind_schedule(stop_times)
                            has_new_stop = bool(new_events)

                            if new_events:
                                labels = [EVENT_LABELS.get(e, e) for e in sorted(new_events)]
                                print(f"    New events: {', '.join(labels)}")

                            if not has_status_change and not new_events:
                                print("    (no change from last run)")
                            elif is_critical or is_behind or has_new_stop:
                                print("    ** SENDING ALERT **")
                                send_tolead_alert(name, load_id, efj, mp_status, dest, pickup_date, mp_load_id, stop_times=stop_times)
                            else:
                                print("    On time, no new events — no alert")
                            update_state(sent, alert_key, mp_status, current_events)
                        else:
                            print("    No status")
                    else:
                        print("  No active tracked rows")
            finally:
                browser.close()

        save_sent_alerts(sent)
        print("\n  Test done")

    elif "--once" in sys.argv:
        run_once()
    elif "--dry-run" in sys.argv:
        print("DRY RUN — scrape all hubs but no emails")
        run_once(dry_run=True)
    else:
        main()
