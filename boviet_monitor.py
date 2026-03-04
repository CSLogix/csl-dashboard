#!/usr/bin/env python3
"""
boviet_monitor.py — polls the Boviet/Evans Delivery sheet every 30 minutes,
scrapes Macropoint tracking URLs from each account tab, and sends email
alerts on status changes. When a load is Delivered, writes the actual
pickup/delivery timestamps from Macropoint back to the sheet.

Emails go to Boviet-efj@evansdelivery.com.
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
BOVIET_SHEET_ID  = "1OP-ZDaMCOsPxcxezHSPfN5ftUXlUcOjFgsfCQgDp3wI"
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "/root/csl-credentials.json")
SENT_ALERTS_FILE = "/root/csl-bot/boviet_sent_alerts.json"
POLL_INTERVAL    = 20 * 60  # 20 minutes

# Alert destination
ALERT_EMAIL = "Boviet-efj@evansdelivery.com"

# SMTP
SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USER     = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Skip these statuses — already done or canceled
SKIP_STATUSES = {"Delivered", "Completed", "Canceled", "Cancelled", "Ready to Close"}

# Skip these tabs — not load data
SKIP_TABS = {"POCs", "Boviet Master"}

# These statuses ALWAYS trigger an alert even if driver is on time
ALWAYS_ALERT_STATUSES = {"Delivered"}

# ── Per-tab column mappings (0-based) ────────────────────────────────────────
# Each tab has a different column layout. The Macropoint hyperlink is on
# Column A (EFJ Pro #) across ALL tabs in this sheet.
HYPERLINK_COL = 0  # A — Macropoint URL hyperlinked on EFJ Pro #

TAB_CONFIGS = {
    "DTE Fresh/Stock": {
        "efj_col":       0,   # A — EFJ Pro #
        "load_id_col":   1,   # B — Load ID
        "pickup_col":    3,   # D — Pickup Date/Time
        "delivery_col":  4,   # E — Delivery Date/Time
        "status_col":    5,   # F — Status
    },
    "Sundance": {
        "efj_col":       0,
        "load_id_col":   1,   # B
        "pickup_col":    4,   # E
        "delivery_col":  5,   # F
        "status_col":    6,   # G
    },
    "Renewable Energy": {
        "efj_col":       0,
        "load_id_col":   1,   # B
        "pickup_col":    3,   # D
        "delivery_col":  4,   # E
        "status_col":    5,   # F
    },
    "Radiance Solar": {
        "efj_col":       0,
        "load_id_col":   1,   # B
        "pickup_col":    3,   # D
        "delivery_col":  4,   # E
        "status_col":    5,   # F
    },
    "Piedra": {
        "efj_col":       0,
        "load_id_col":   2,   # C — Load ID is col C for Piedra
        "pickup_col":    5,   # F
        "delivery_col":  6,   # G
        "status_col":    7,   # H
    },
    "Hanson": {
        "efj_col":       0,
        "load_id_col":   1,   # B
        "pickup_col":    4,   # E
        "delivery_col":  5,   # F
        "status_col":    6,   # G
    },
}


# ── Credentials ──────────────────────────────────────────────────────────────
def _load_credentials():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds


# ── Hyperlinks ───────────────────────────────────────────────────────────────
def _get_hyperlinks(creds, tab_name: str) -> list:
    """Fetch hyperlink URL from Column A (EFJ Pro #) for each row via Sheets API v4."""
    encoded_tab = requests.utils.quote(tab_name)
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{BOVIET_SHEET_ID}"
        f"?ranges={encoded_tab}"
        f"&fields=sheets.data.rowData.values.hyperlink"
        f"&includeGridData=true"
    )
    resp = requests.get(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=30)
    resp.raise_for_status()
    rows = resp.json().get("sheets", [{}])[0].get("data", [{}])[0].get("rowData", [])

    links = []
    for row in rows:
        vals = row.get("values", [])
        link = vals[HYPERLINK_COL].get("hyperlink", "") if len(vals) > HYPERLINK_COL else ""
        links.append(link)
    return links


# ── Alert dedup ──────────────────────────────────────────────────────────────
def load_sent_alerts() -> dict:
    if os.path.exists(SENT_ALERTS_FILE):
        try:
            with open(SENT_ALERTS_FILE, "r") as f:
                return json.load(f)
        except Exception as exc:
            print(f"  WARNING: could not read {SENT_ALERTS_FILE}: {exc}")
    return {}


def save_sent_alerts(data: dict):
    try:
        with open(SENT_ALERTS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        print(f"  WARNING: could not save {SENT_ALERTS_FILE}: {exc}")


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


def send_boviet_alert(efj, load_id, status, tab_name, pickup="", delivery="", mp_load_id=None, stop_times=None):
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")

    load_ref = mp_load_id or load_id
    subject = f"Boviet Alert \u2014 {tab_name} \u2014 {load_ref} \u2014 {status}"

    behind = _is_load_behind(stop_times)
    hdr_color = "#c62828" if behind else "#1b5e20"

    rows = ""
    rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Account</td><td style=\"padding:4px 8px;\">{tab_name}</td></tr>"
    if mp_load_id:
        rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">MP Load</td><td style=\"padding:4px 8px;\">{mp_load_id}</td></tr>"
    rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Status</td><td style=\"padding:4px 8px;\">{status}</td></tr>"
    rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Pickup</td><td style=\"padding:4px 8px;\">{pickup}</td></tr>"
    rows += f"<tr><td style=\"padding:4px 8px;color:#555;\">Delivery</td><td style=\"padding:4px 8px;\">{delivery}</td></tr>"

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
        f"<p style=\"color:#888;font-size:12px;\">Boviet FTL Status Update \u2014 {now}</p>"
        f"<div style=\"background:{hdr_color};color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:16px;\">"
        f"<b>{efj} / {load_ref}</b></div>"
        f"<div style=\"border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:10px;\">"
        f"<table style=\"border-collapse:collapse;\">{rows}</table>"
        f"{timeline}"
        f"</div></div>"
    )

    _send_email(ALERT_EMAIL, subject, body)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _safe_get(row, idx):
    """Safely get a cell value by index, return '' if out of range."""
    return row[idx].strip() if len(row) > idx else ""


# ── Main loop ────────────────────────────────────────────────────────────────
def run_once():
    print(f"\n{'='*60}")
    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    print(f"Boviet Monitor — {now_str}")

    creds = _load_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(BOVIET_SHEET_ID)

    # Discover which tabs to process
    all_tabs = [ws.title for ws in sh.worksheets()]
    tabs_to_check = [t for t in all_tabs if t not in SKIP_TABS and t in TAB_CONFIGS]
    print(f"  Tabs to check: {tabs_to_check}")

    sent = load_sent_alerts()
    total_tracked = 0
    total_alerts = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for tab_name in tabs_to_check:
                cfg = TAB_CONFIGS[tab_name]
                print(f"\n  {'─'*50}")
                print(f"  [{tab_name}]")
                time.sleep(2)  # rate-limit between tabs

                try:
                    ws = gc.open_by_key(BOVIET_SHEET_ID).worksheet(tab_name)
                    rows = ws.get_all_values()
                    links = _get_hyperlinks(creds, tab_name)
                except Exception as exc:
                    print(f"    ERROR reading tab: {exc}")
                    continue

                # Collect rows to process
                to_process = []
                for i, row in enumerate(rows):
                    if i == 0:  # skip header
                        continue

                    status = _safe_get(row, cfg["status_col"])
                    if status in SKIP_STATUSES:
                        continue

                    efj     = _safe_get(row, cfg["efj_col"])
                    load_id = _safe_get(row, cfg["load_id_col"])
                    if not efj and not load_id:
                        continue

                    mp_url = links[i] if i < len(links) else ""
                    if not mp_url or "macropoint" not in mp_url.lower():
                        continue

                    pickup   = _safe_get(row, cfg["pickup_col"])
                    delivery = _safe_get(row, cfg["delivery_col"])

                    to_process.append({
                        "sheet_row": i + 1,
                        "efj":       efj,
                        "load_id":   load_id,
                        "pickup":    pickup,
                        "delivery":  delivery,
                        "status":    status,
                        "mp_url":    mp_url,
                        "tab_name":  tab_name,
                    })

                print(f"    Rows: {len(rows)-1}  |  To track: {len(to_process)}")
                total_tracked += len(to_process)

                for item in to_process:
                    alert_key = f"{tab_name}|{item['efj']}|{item['load_id']}"
                    print(f"\n    [{item['sheet_row']}] {item['efj']} / {item['load_id']}")
                    print(f"      Scraping: {item['mp_url'][:60]}...")

                    mp_status, stop1_arrived, stop2_departed, _, _, mp_load_id, _, stop_times = (
                        scrape_macropoint(browser, item["mp_url"])
                    )

                    if not mp_status:
                        print("      No status detected")
                        continue

                    print(f"      Status: {mp_status}")

                    # Check for status change or new stop events
                    last_status, last_events = get_last_state(sent, alert_key)
                    current_events = _get_stop_events(stop_times)
                    new_events = current_events - last_events
                    has_status_change = (mp_status != last_status)

                    if not has_status_change and not new_events:
                        print("      (no change)")
                        continue

                    if new_events:
                        labels = [EVENT_LABELS.get(e, e) for e in sorted(new_events)]
                        print(f"      New events: {', '.join(labels)}")

                    # Decide if this change warrants an email
                    is_critical = (mp_status in ALWAYS_ALERT_STATUSES
                                   or "can't make" in mp_status.lower())
                    is_behind = _is_behind_schedule(stop_times)
                    has_new_stop = bool(new_events)

                    if is_critical or is_behind or has_new_stop:
                        send_boviet_alert(
                            item["efj"], item["load_id"], mp_status, tab_name,
                            pickup=item["pickup"], delivery=item["delivery"],
                            mp_load_id=mp_load_id, stop_times=stop_times,
                        )
                        total_alerts += 1
                    else:
                        print("      On time, no new events — no alert needed")

                    # Always update tracked state
                    update_state(sent, alert_key, mp_status, current_events)

        finally:
            browser.close()

    save_sent_alerts(sent)
    print(f"\n  Done — tracked {total_tracked} load(s), sent {total_alerts} new alert(s).")


def main():
    print("Boviet Monitor started — 6 AM to 8 PM ET, Mon-Fri, every 20 min.")
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
        # Test mode: 1 active row per tab, sends real emails
        print("TEST MODE — 1 row per tab, real emails")
        creds = _load_credentials()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(BOVIET_SHEET_ID)
        all_tabs = [ws.title for ws in sh.worksheets()]
        tabs_to_check = [t for t in all_tabs if t not in SKIP_TABS and t in TAB_CONFIGS]
        sent = load_sent_alerts()
        total = 0

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for tab_name in tabs_to_check:
                    cfg = TAB_CONFIGS[tab_name]
                    print(f"\n  [{tab_name}]")
                    ws = gc.open_by_key(BOVIET_SHEET_ID).worksheet(tab_name)
                    rows = ws.get_all_values()
                    links = _get_hyperlinks(creds, tab_name)

                    found = False
                    for i, row in enumerate(rows):
                        if i == 0:
                            continue
                        status = _safe_get(row, cfg["status_col"])
                        if status in SKIP_STATUSES:
                            continue
                        efj     = _safe_get(row, cfg["efj_col"])
                        load_id = _safe_get(row, cfg["load_id_col"])
                        if not efj and not load_id:
                            continue
                        mp_url = links[i] if i < len(links) else ""
                        if not mp_url or "macropoint" not in mp_url.lower():
                            continue

                        pickup   = _safe_get(row, cfg["pickup_col"])
                        delivery = _safe_get(row, cfg["delivery_col"])

                        print(f"    [{i+1}] {efj} / {load_id}")
                        print(f"      URL: {mp_url[:60]}...")

                        mp_status, stop1_arrived, stop2_departed, _, _, mp_load_id, _, stop_times = (
                            scrape_macropoint(browser, mp_url)
                        )
                        if not mp_status:
                            print("      No status")
                            continue

                        print(f"      Status: {mp_status}")
                        alert_key = f"{tab_name}|{efj}|{load_id}"
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
                            print(f"      New events: {', '.join(labels)}")

                        if not has_status_change and not new_events:
                            print("      (no change from last run)")
                        elif is_critical or is_behind or has_new_stop:
                            print("      ** SENDING ALERT **")
                            send_boviet_alert(
                                efj, load_id, mp_status, tab_name,
                                pickup=pickup, delivery=delivery,
                                mp_load_id=mp_load_id, stop_times=stop_times,
                            )
                        else:
                            print("      On time, no new events — no alert")

                        update_state(sent, alert_key, mp_status, current_events)
                        total += 1
                        found = True
                        break  # 1 row per tab

                    if not found:
                        print("    No active tracked rows")
            finally:
                browser.close()

        save_sent_alerts(sent)
        print(f"\n  Test done — checked {total} load(s)")

    elif "--once" in sys.argv:
        run_once()
    elif "--dry-run" in sys.argv:
        print("DRY RUN — scrape first 3 per tab, no emails")
        creds = _load_credentials()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(BOVIET_SHEET_ID)

        all_tabs = [ws.title for ws in sh.worksheets()]
        tabs_to_check = [t for t in all_tabs if t not in SKIP_TABS and t in TAB_CONFIGS]

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for tab_name in tabs_to_check:
                    cfg = TAB_CONFIGS[tab_name]
                    print(f"\n  [{tab_name}]")
                    ws = gc.open_by_key(BOVIET_SHEET_ID).worksheet(tab_name)
                    rows = ws.get_all_values()
                    links = _get_hyperlinks(creds, tab_name)

                    count = 0
                    for i, row in enumerate(rows):
                        if i == 0:
                            continue
                        status = _safe_get(row, cfg["status_col"])
                        if status in SKIP_STATUSES:
                            continue
                        mp_url = links[i] if i < len(links) else ""
                        if not mp_url or "macropoint" not in mp_url.lower():
                            continue

                        efj     = _safe_get(row, cfg["efj_col"])
                        load_id = _safe_get(row, cfg["load_id_col"])
                        print(f"    [{i+1}] {efj} / {load_id}")
                        print(f"      URL: {mp_url[:60]}...")

                        result = scrape_macropoint(browser, mp_url)
                        print(f"      Result: status={result[0]}, stop1={result[1]}, "
                              f"stop2={result[2]}, mp_load={result[5]}")

                        count += 1
                        if count >= 3:
                            print(f"    (dry-run limit: 3 per tab)")
                            break
            finally:
                browser.close()
    else:
        main()
