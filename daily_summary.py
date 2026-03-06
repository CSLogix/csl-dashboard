#!/usr/bin/env python3
"""
daily_summary.py  —  7 AM ET daily summary of all actively-tracking loads
across FTL, Boviet, and Tolead sheets.

Grouped table format per tab:
  Green  (#1b5e20): On Time
  Red    (#c62828): Behind Schedule / Can't Make It
  Purple (#6a1b9a): Tracking Issues

After sending, syncs state files so monitors only alert on NEW changes.
"""
import os
import json
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

from ftl_monitor import scrape_macropoint

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────────
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "/root/csl-credentials.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USER     = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
EMAIL_CC      = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")

# Sheet IDs
FTL_SHEET_ID    = "19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0"
BOVIET_SHEET_ID = "1OP-ZDaMCOsPxcxezHSPfN5ftUXlUcOjFgsfCQgDp3wI"

# FTL config
FTL_SKIP_TABS = {"Sheet 4", "DTCELNJW", "Account Rep", "Completed Eli", "Completed Radka", "Boviet"}
FTL_SKIP_STATUSES = {"delivered", "completed", "canceled", "ready to close"}
FTL_COL_EFJ      = 0
FTL_COL_LOAD     = 2
FTL_COL_STATUS   = 12
FTL_COL_PICKUP   = 10
FTL_COL_DELIVERY = 11
FTL_HYPERLINK_COL = 2

# Boviet config
BOVIET_SKIP_TABS = {"POCs", "Boviet Master"}
BOVIET_SKIP_STATUSES = {"delivered", "completed", "canceled", "cancelled", "ready to close"}
BOVIET_HYPERLINK_COL = 0
BOVIET_TAB_CONFIGS = {
    "Piedra":          {"efj_col": 0, "load_id_col": 2, "pickup_col": 5, "delivery_col": 6, "status_col": 7, "start_row": 45},
    "Hanson":          {"efj_col": 0, "load_id_col": 1, "pickup_col": 4, "delivery_col": 5, "status_col": 6},
}

# Tolead config — all 4 hubs
TOLEAD_SKIP_STATUSES = {"delivered", "canceled", "cancelled"}
TOLEAD_HUBS = [
    {
        "name": "ORD",
        "sheet_id": "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac",
        "tab": "Schedule",
        "col_load_id": 1, "col_date": 4, "col_origin": 6,
        "col_dest": 7, "col_status": 9, "col_efj": 15,
        "col_phone": 17, "col_trailer": 16,
        "col_delivery": 3, "col_appt_id": 2, "col_loads_j": 8,
        "needs_cover_statuses": {"new"},
        "start_row": 790,
    },
    {
        "name": "JFK",
        "sheet_id": "1mfhEsK2zg6GWTqMDTo5VwCgY-QC1tkNPknurHMxtBhs",
        "tab": "Schedule",
        "col_load_id": 0, "col_date": 3, "col_origin": 6,
        "col_dest": 7, "col_status": 9, "col_efj": 14,
        "col_phone": 16, "col_trailer": 15,
        "col_delivery": 5, "col_loads_j": 9,
        "default_origin": "Garden City, NY",
        "needs_cover_statuses": {"new"},
        "start_row": 184,
    },
    {
        "name": "LAX",
        "sheet_id": "1YLB6z5LdL0kFYTcfq_H5e6acU8-VLf8nN0XfZrJ-bXo",
        "tab": "LAX",
        "col_load_id": 3, "col_date": 4, "col_origin": 6,
        "col_dest": 7, "col_status": 9, "col_efj": 0,
        "col_phone": 12, "col_trailer": 11,
        "col_delivery": 8, "col_loads_j": 9,
        "default_origin": "Vernon, CA",
        "needs_cover_statuses": {"unassigned"},
        "start_row": 755,
    },
    {
        "name": "DFW",
        "sheet_id": "1RfGcq25x4qshlBDWDJD-xBJDlJm6fvDM_w2RTHhn9oI",
        "tab": "DFW",
        "col_load_id": 4, "col_date": 5, "col_origin": None,
        "col_dest": 3, "col_status": 11, "col_efj": 10,
        "col_phone": 13, "col_trailer": 12, "col_delivery_date": 2,
        "col_loads_j": 9, "default_origin": "Irving, TX",
        "start_row": 172,
    },
]

# State files for dedup sync
FTL_STATE_FILE    = "/root/csl-bot/ftl_sent_alerts.json"
BOVIET_STATE_FILE = "/root/csl-bot/boviet_sent_alerts.json"
TOLEAD_STATE_FILE = "/root/csl-bot/tolead_sent_alerts.json"


# ── Helpers ──────────────────────────────────────────────────────────────────
def _load_credentials():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds




def _retry_on_quota(fn, label="", max_retries=3, base_delay=30):
    """Retry on 429 quota errors with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if '429' in str(e) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"    Quota exceeded{' (' + label + ')' if label else ''}, "
                      f"retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                import time
                time.sleep(delay)
            else:
                raise

def _safe_get(row, idx):
    return row[idx].strip() if len(row) > idx else ""


def _get_hyperlinks(creds, sheet_id, tab_name, col_idx):
    encoded_tab = requests.utils.quote(tab_name)
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
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
        link = vals[col_idx].get("hyperlink", "") if len(vals) > col_idx else ""
        links.append(link)
    return links


def _check_on_time(stop_times):
    otp = None
    otd = None
    if not stop_times:
        return None, None

    # Stop 1 (Pickup)
    if stop_times.get("stop1_arrived") or stop_times.get("stop1_departed"):
        parts = []
        if stop_times.get("stop1_arrived"):
            parts.append(f"Arr {stop_times['stop1_arrived']}")
        if stop_times.get("stop1_departed"):
            parts.append(f"Dep {stop_times['stop1_departed']}")
        otp = ", ".join(parts)
    elif stop_times.get("stop1_eta"):
        eta = stop_times["stop1_eta"]
        otp = f"BEHIND &mdash; {eta}" if "BEHIND" in eta.upper() else f"Tracking for OTP &mdash; {eta}"
    else:
        otp = "Tracking for OTP"

    # Stop 2 (Delivery)
    if stop_times.get("stop2_arrived") or stop_times.get("stop2_departed"):
        parts = []
        if stop_times.get("stop2_arrived"):
            parts.append(f"Arr {stop_times['stop2_arrived']}")
        if stop_times.get("stop2_departed"):
            parts.append(f"Dep {stop_times['stop2_departed']}")
        otd = ", ".join(parts)
    elif stop_times.get("stop2_eta"):
        eta = stop_times["stop2_eta"]
        otd = f"BEHIND &mdash; {eta}" if "BEHIND" in eta.upper() else f"Tracking for OTD &mdash; {eta}"
    else:
        otd = "Tracking for OTD"

    return otp, otd


def _send_email(to_email, subject, body, cc_email=None):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    if cc_email:
        msg["Cc"] = cc_email
    msg.attach(MIMEText(body, "html"))
    recipients = [to_email] + ([cc_email] if cc_email else [])
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"    Email sent -> {to_email}" + (f" (cc: {cc_email})" if cc_email else ""))
    except Exception as exc:
        print(f"    WARNING: Email failed: {exc}")


def _get_stop_events(stop_times):
    events = set()
    if not stop_times:
        return events
    if stop_times.get("stop1_arrived"):
        events.add("stop1_arrived")
    if stop_times.get("stop1_departed"):
        events.add("stop1_departed")
    if stop_times.get("stop2_arrived"):
        events.add("stop2_arrived")
    if stop_times.get("stop2_departed"):
        events.add("stop2_departed")
    return events


# ── Classification ───────────────────────────────────────────────────────────
def classify_load(s):
    """Classify a load: 'on_time', 'behind', or 'tracking'."""
    mp = (s.get("mp_status") or "").lower()
    otp = (s.get("otp") or "").upper()
    otd = (s.get("otd") or "").upper()

    # Tracking issues (purple)
    if "waiting for update" in mp or "phone unresponsive" in mp:
        return "tracking"

    # Behind / Can't Make It (red)
    if "can't make" in mp or s.get("cant_make_it") or "BEHIND" in otp or "BEHIND" in otd:
        return "behind"

    return "on_time"


# ── HTML Table Builders ─────────────────────────────────────────────────────

_O = "#e65100"  # Orange for Needs to Cover

def _build_needs_cover_section(needs_cover):
    """Build orange 'Needs to Cover' section for Tolead daily summary."""
    if not needs_cover:
        return ""
    hdrs = ["LINE #", "EFJ #", "Destination", "Pickup Date", "Driver Phone"]
    hdr_cells = "".join(f'<th {_TH}>{h}</th>' for h in hdrs)
    rows_html = ""
    for i, item in enumerate(needs_cover):
        alt = i % 2 == 1
        bg = ' style="background:#f9f9f9;"' if alt else ""
        efj_display = item["efj"] or "&mdash;"
        phone_display = item["phone"] or "(not assigned)"
        rows_html += (
            f'<tr{bg}>'
            f'<td {_TD}><b>{item["load_id"]}</b></td>'
            f'<td {_TD}>{efj_display}</td>'
            f'<td {_TD}>{item["dest"]}</td>'
            f'<td {_TD}>{item["pickup"]}</td>'
            f'<td {_TD}>{phone_display}</td>'
            f'</tr>'
        )
    return (
        f'<div style="background:{_O};color:white;padding:8px 14px;'
        f'border-radius:6px 6px 0 0;font-size:15px;margin-top:20px;">'
        f"<b>Needs to Cover ({len(needs_cover)})</b></div>"
        f'<table style="border-collapse:collapse;width:100%;border:1px solid #ddd;border-top:none;">'
        f'<tr style="background:{_O};">{hdr_cells}</tr>'
        f'{rows_html}</table>'
    )

_G = "#1b5e20"
_R = "#c62828"
_P = "#6a1b9a"

_TH = 'style="padding:6px 10px;text-align:left;border-bottom:1px solid #ddd;color:white;font-size:13px;"'
_TD = 'style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;"'
_TD_R = 'style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;color:#c62828;font-weight:bold;"'
_TD_P = 'style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;color:#6a1b9a;font-weight:bold;"'


def _section(color, title, count, headers, rows_html):
    if not rows_html:
        return ""
    hdr_cells = "".join(f'<th {_TH}>{h}</th>' for h in headers)
    return (
        f'<div style="background:{color};color:white;padding:8px 14px;'
        f'border-radius:6px 6px 0 0;font-size:15px;margin-top:20px;">'
        f"<b>{title} ({count})</b></div>"
        f'<table style="border-collapse:collapse;width:100%;border:1px solid #ddd;border-top:none;">'
        f'<tr style="background:{color};">{hdr_cells}</tr>'
        f"{rows_html}</table>"
    )


def _tr(cells, alt=False):
    bg = ' style="background:#f9f9f9;"' if alt else ""
    return f"<tr{bg}>{''.join(cells)}</tr>"


def _c(val, style=None):
    return f"<td {style or _TD}>{val}</td>"


def _cb(val, style=None):
    return f"<td {style or _TD}><b>{val}</b></td>"


def _build_rows(loads, category, has_lane=False):
    rows = ""
    for i, s in enumerate(loads):
        alt = i % 2 == 1
        efj = s["efj"]
        load_ref = s.get("mp_load_id") or s["load_id"]
        status = s["mp_status"]
        otp = s.get("otp") or "&mdash;"
        otd = s.get("otd") or "&mdash;"

        lane_cell = []
        if has_lane:
            origin = s.get("origin", "")
            dest = s.get("dest", "")
            if origin and dest:
                lane = f"{origin} &#8594; {dest}"
            else:
                lane = origin or dest or "&mdash;"
            lane_cell = [_c(lane)]

        if category == "behind":
            otp_st = _TD_R if "BEHIND" in (s.get("otp") or "").upper() else _TD
            otd_st = _TD_R if "BEHIND" in (s.get("otd") or "").upper() else _TD
            rows += _tr([_cb(efj), _c(load_ref)] + lane_cell + [_c(status), _c(otp, otp_st), _c(otd, otd_st)], alt=alt)
        elif category == "tracking":
            rows += _tr([_cb(efj), _c(load_ref)] + lane_cell + [_c(status, _TD_P), _c(otp, _TD_P), _c(otd, _TD_P)], alt=alt)
        else:
            rows += _tr([_cb(efj), _c(load_ref)] + lane_cell + [_c(status), _c(otp), _c(otd)], alt=alt)
    return rows


def build_summary_body(sheet_label, tab_name, summaries, skipped=0):
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    on_time  = [s for s in summaries if classify_load(s) == "on_time"]
    behind   = [s for s in summaries if classify_load(s) == "behind"]
    tracking = [s for s in summaries if classify_load(s) == "tracking"]

    has_lane = any(s.get("origin") or s.get("dest") for s in summaries)
    hdrs = ["EFJ #", "Load ID"]
    if has_lane:
        hdrs.append("Lane")
    hdrs += ["Status", "Stop 1 (Pickup)", "Stop 2 (Delivery)"]

    sections = ""
    sections += _section(_G, "On Time", len(on_time), hdrs, _build_rows(on_time, "on_time", has_lane=has_lane))
    sections += _section(_R, "Behind Schedule / Can't Make It", len(behind), hdrs, _build_rows(behind, "behind", has_lane=has_lane))
    sections += _section(_P, "Tracking Issues", len(tracking), hdrs, _build_rows(tracking, "tracking", has_lane=has_lane))

    warn = ""
    if skipped > 0:
        warn = (
            f'<div style="background:#ff8f00;color:white;padding:8px 14px;'
            f'border-radius:6px;font-size:13px;margin-top:8px;margin-bottom:4px;">'
            f'&#9888; <b>{skipped} load(s) skipped</b> &mdash; '
            f'Macropoint scrape failed (page timeout or session issue)</div>'
        )

    return (
        f'<div style="font-family:Arial,sans-serif;max-width:900px;">'
        f'<h2 style="margin:0 0 4px 0;color:#333;">{sheet_label} &mdash; {tab_name}</h2>'
        f'<p style="color:#888;font-size:12px;margin:0 0 4px 0;">'
        f'{now} &mdash; {len(summaries)} Active Load(s)</p>'
        f'{warn}'
        f'{sections}'
        f'</div>'
    )


# ── FTL Account Rep lookup ──────────────────────────────────────────────────
def _load_ftl_account_lookup(creds):
    try:
        gc = gspread.authorize(creds)
        ws = _retry_on_quota(
            lambda: gc.open_by_key(FTL_SHEET_ID).worksheet("Account Rep"),
            label="Account Rep")
        rows = _retry_on_quota(
            lambda: ws.get_all_values(),
            label="Account Rep values")
        lookup = {}
        for row in rows:
            if len(row) >= 3 and row[0].strip():
                account = row[0].strip()
                rep = row[1].strip()
                email = row[2].strip()
                if account and email:
                    lookup[account] = {"rep": rep, "email": email}
        return lookup
    except Exception as exc:
        print(f"  WARNING: Could not load FTL Account Rep tab: {exc}")
        return {}


# ── Scan functions ───────────────────────────────────────────────────────────
def scan_ftl(creds, gc):
    print("\n  -- FTL Sheet --")
    sh = gc.open_by_key(FTL_SHEET_ID)
    all_tabs = [ws.title for ws in sh.worksheets()]
    account_lookup = _load_ftl_account_lookup(creds)
    tabs = [t for t in all_tabs if t not in FTL_SKIP_TABS and t in account_lookup]
    print(f"    Tabs: {tabs}")

    results = {}
    for tab_name in tabs:
        time.sleep(3)  # avoid quota spikes
        try:
            ws = _retry_on_quota(
                lambda: gc.open_by_key(FTL_SHEET_ID).worksheet(tab_name),
                label=f"FTL/{tab_name}")
            rows = _retry_on_quota(
                lambda: ws.get_all_values(),
                label=f"FTL/{tab_name} values")
            links = _retry_on_quota(
                lambda: _get_hyperlinks(creds, FTL_SHEET_ID, tab_name, FTL_HYPERLINK_COL),
                label=f"FTL/{tab_name} hyperlinks")
        except Exception as exc:
            print(f"    [{tab_name}] ERROR: {exc}")
            continue

        entries = []
        for i, row in enumerate(rows):
            if i == 0:
                continue
            status = _safe_get(row, FTL_COL_STATUS)
            if status.lower() in FTL_SKIP_STATUSES:
                continue
            efj = _safe_get(row, FTL_COL_EFJ)
            load_id = _safe_get(row, FTL_COL_LOAD)
            if not efj and not load_id:
                continue
            mp_url = links[i] if i < len(links) else ""
            if not mp_url or "macropoint" not in mp_url.lower():
                continue
            entries.append({
                "efj": efj, "load_id": load_id, "mp_url": mp_url,
                "pickup": _safe_get(row, FTL_COL_PICKUP),
                "delivery": _safe_get(row, FTL_COL_DELIVERY),
                "sheet_status": status,
            })

        if entries:
            print(f"    [{tab_name}] {len(entries)} tracked load(s)")
            results[tab_name] = {"entries": entries, "lookup": account_lookup}

    return results


def scan_boviet(creds, gc):
    print("\n  -- Boviet Sheet --")
    sh = gc.open_by_key(BOVIET_SHEET_ID)
    all_tabs = [ws.title for ws in sh.worksheets()]
    tabs = [t for t in all_tabs if t not in BOVIET_SKIP_TABS and t in BOVIET_TAB_CONFIGS]
    print(f"    Tabs: {tabs}")

    results = {}
    for tab_name in tabs:
        cfg = BOVIET_TAB_CONFIGS[tab_name]
        time.sleep(3)  # avoid quota spikes
        try:
            ws = _retry_on_quota(
                lambda: gc.open_by_key(BOVIET_SHEET_ID).worksheet(tab_name),
                label=f"Boviet/{tab_name}")
            rows = _retry_on_quota(
                lambda: ws.get_all_values(),
                label=f"Boviet/{tab_name} values")
            links = _retry_on_quota(
                lambda: _get_hyperlinks(creds, BOVIET_SHEET_ID, tab_name, BOVIET_HYPERLINK_COL),
                label=f"Boviet/{tab_name} hyperlinks")
        except Exception as exc:
            print(f"    [{tab_name}] ERROR: {exc}")
            continue

        bov_start = cfg.get("start_row", 1)
        entries = []
        for i, row in enumerate(rows):
            if i == 0:
                continue
            if i < bov_start:
                continue
            status = _safe_get(row, cfg["status_col"])
            if status.lower() in BOVIET_SKIP_STATUSES:
                continue
            efj = _safe_get(row, cfg["efj_col"])
            load_id = _safe_get(row, cfg["load_id_col"])
            if not efj and not load_id:
                continue
            mp_url = links[i] if i < len(links) else ""
            if not mp_url or "macropoint" not in mp_url.lower():
                continue
            entries.append({
                "efj": efj, "load_id": load_id, "mp_url": mp_url,
                "pickup": _safe_get(row, cfg["pickup_col"]),
                "delivery": _safe_get(row, cfg["delivery_col"]),
                "sheet_status": status,
            })

        if entries:
            print(f"    [{tab_name}] {len(entries)} tracked load(s)")
            results[tab_name] = {"entries": entries}

    return results


def scan_tolead(creds, gc):
    """Scan all Tolead hubs (ORD, JFK, LAX, DFW)."""
    print("\n  -- Tolead Sheets --")
    results = {}
    for hub in TOLEAD_HUBS:
        hub_name = hub["name"]
        sheet_id = hub["sheet_id"]
        tab = hub["tab"]
        col_efj = hub["col_efj"]
        time.sleep(3)  # avoid quota spikes
        try:
            ws = _retry_on_quota(
                lambda sid=sheet_id, t=tab: gc.open_by_key(sid).worksheet(t),
                label=f"Tolead/{hub_name}")
            rows = _retry_on_quota(
                lambda: ws.get_all_values(),
                label=f"Tolead/{hub_name} values")
            links = _retry_on_quota(
                lambda sid=sheet_id, t=tab, c=col_efj: _get_hyperlinks(creds, sid, t, c),
                label=f"Tolead/{hub_name} hyperlinks")
        except Exception as exc:
            print(f"    [{hub_name}] ERROR: {exc}")
            continue

        start_row = hub.get("start_row", 2)
        entries = []
        needs_cover = []  # loads needing coverage
        for i, row in enumerate(rows[1:], start=2):  # skip header
            if i < start_row:
                continue
            if len(row) <= col_efj:
                continue
            status = _safe_get(row, hub["col_status"])
            load_id_val = _safe_get(row, hub["col_load_id"])

            if status and status.lower() in TOLEAD_SKIP_STATUSES:
                continue
            if not load_id_val:
                continue

            # Check if load "Needs to Cover" based on hub-specific logic
            ntc_statuses = hub.get("needs_cover_statuses")
            if ntc_statuses and status.lower() in ntc_statuses:
                # Status indicates uncovered load
                dest = _safe_get(row, hub["col_dest"])
                pickup = _safe_get(row, hub["col_date"])
                phone = _safe_get(row, hub.get("col_phone", -1)) if hub.get("col_phone") else ""
                needs_cover.append({
                    "load_id": load_id_val,
                    "efj": _safe_get(row, col_efj),
                    "dest": dest,
                    "pickup": pickup,
                    "phone": phone,
                })
                continue
            # DFW: derive from col_loads_j (scheduling column separate from status)
            if hub_name == "DFW":
                col_j = _safe_get(row, hub.get("col_loads_j", 9))
                if col_j.lower() not in ("scheduled", "picked"):
                    dest = _safe_get(row, hub["col_dest"])
                    pickup = _safe_get(row, hub["col_date"])
                    phone = _safe_get(row, hub.get("col_phone", 13))
                    needs_cover.append({
                        "load_id": load_id_val,
                        "efj": _safe_get(row, col_efj),
                        "dest": dest,
                        "pickup": pickup,
                        "phone": phone,
                    })
                    continue

            mp_url = links[i - 1] if i - 1 < len(links) else ""
            if not mp_url or "macropoint" not in mp_url.lower():
                continue

            origin = _safe_get(row, hub["col_origin"]) if hub["col_origin"] is not None else ""
            if not origin and hub.get("default_origin"):
                origin = hub["default_origin"]
            entries.append({
                "efj": _safe_get(row, col_efj),
                "load_id": _safe_get(row, hub["col_load_id"]),
                "mp_url": mp_url,
                "pickup": _safe_get(row, hub["col_date"]),
                "delivery": "",
                "origin": origin,
                "dest": _safe_get(row, hub["col_dest"]),
                "sheet_status": status,
                "hub": hub_name,
            })

        tracked_count = len(entries)
        ntc_count = len(needs_cover)
        if entries or needs_cover:
            print(f"    [{hub_name}/{tab}] {tracked_count} tracked, {ntc_count} needs cover")
            results[hub_name] = {"entries": entries, "tab": tab, "needs_cover": needs_cover}

    return results


# ── Scrape & build ───────────────────────────────────────────────────────────
def scrape_and_summarize(browser, entries):
    summaries = []
    skipped = 0
    for item in entries:
        try:
            mp_status, _, _, _, _, mp_load_id, cant_make_it, stop_times = scrape_macropoint(
                browser, item["mp_url"]
            )
        except Exception as exc:
            print(f"      SCRAPE ERROR [{item['efj']}]: {exc}")
            skipped += 1
            continue

        if not mp_status:
            print(f"      SCRAPE SKIP [{item['efj']}]: no status returned")
            skipped += 1
            continue

        otp, otd = _check_on_time(stop_times)
        events = _get_stop_events(stop_times)

        summaries.append({
            "efj": item["efj"],
            "load_id": item["load_id"],
            "mp_load_id": mp_load_id,
            "mp_status": mp_status,
            "cant_make_it": cant_make_it,
            "otp": otp,
            "otd": otd,
            "pickup": item.get("pickup", ""),
            "delivery": item.get("delivery", ""),
            "origin": item.get("origin", ""),
            "dest": item.get("dest", ""),
            "stop_events": events,
            "mp_url": item.get("mp_url", ""),
        })
    return summaries, skipped


# ── State sync ───────────────────────────────────────────────────────────────
def sync_state(state_file, summaries, key_fmt="boviet"):
    """Update state file so monitors don't re-alert on loads already in the summary.
    key_fmt: 'boviet' = {tab}|{efj}|{load_id}, 'tolead' = {load_id}|{efj},
             'ftl' = {efj}|{load_id} with value = [status] (list)
    """
    try:
        with open(state_file, "r") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}

    for s in summaries:
        if key_fmt == "boviet":
            key = f"{s.get('tab_name', '')}|{s['efj']}|{s['load_id']}"
        elif key_fmt == "tolead":
            key = f"{s['load_id']}|{s['efj']}"
        else:
            key = f"{s['efj']}|{s['load_id']}"

        if key_fmt == "ftl":
            # FTL uses [status] list format
            status = s.get("mp_status", "")
            existing = state.get(key, [])
            if status not in existing:
                existing.append(status)
            state[key] = existing
        else:
            state[key] = {
                "status": s.get("mp_status", ""),
                "events": list(s.get("stop_events", set())),
            }

    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
    print(f"    State synced -> {os.path.basename(state_file)} ({len(summaries)} loads)")


# ── Main ─────────────────────────────────────────────────────────────────────
def run():
    print(f"\n{'='*60}")
    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    print(f"Daily Summary — {now_str}")

    creds = _load_credentials()
    gc = gspread.authorize(creds)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            # ── FTL ──────────────────────────────────────────────────
            ftl_data = scan_ftl(creds, gc)
            all_ftl_summaries = []
            for tab_name, data in ftl_data.items():
                entries = data["entries"]
                lookup = data["lookup"]
                print(f"\n    Scraping [{tab_name}] ({len(entries)} loads)...")
                summaries, skipped = scrape_and_summarize(browser, entries)
                if skipped:
                    print(f"    [{tab_name}] {skipped} load(s) skipped (scrape failed)")
                if not summaries:
                    print(f"    [{tab_name}] No actively tracking loads")
                    continue

                all_ftl_summaries.extend(summaries)

                info = lookup.get(tab_name, {})
                rep_email = info.get("email", "")
                to_email = rep_email if rep_email else EMAIL_CC
                cc_email = EMAIL_CC if rep_email else None

                subject = f"FTL Daily Summary \u2014 EFJ Operations \u2014 {tab_name} \u2014 {len(summaries)} Active"
                body = build_summary_body("FTL Daily Summary \u2014 EFJ Operations", tab_name, summaries, skipped=skipped)
                print(f"    [{tab_name}] {len(summaries)} active — sending to {to_email}")
                _send_email(to_email, subject, body, cc_email=cc_email)

            if all_ftl_summaries:
                sync_state(FTL_STATE_FILE, all_ftl_summaries, key_fmt="ftl")

            # ── Boviet ───────────────────────────────────────────────
            boviet_data = scan_boviet(creds, gc)
            all_boviet_summaries = []
            for tab_name, data in boviet_data.items():
                entries = data["entries"]
                print(f"\n    Scraping [{tab_name}] ({len(entries)} loads)...")
                summaries, skipped = scrape_and_summarize(browser, entries)
                if skipped:
                    print(f"    [{tab_name}] {skipped} load(s) skipped (scrape failed)")
                if not summaries:
                    print(f"    [{tab_name}] No actively tracking loads")
                    continue

                for s in summaries:
                    s["tab_name"] = tab_name
                all_boviet_summaries.extend(summaries)

                subject = f"Boviet Daily Summary \u2014 {tab_name} \u2014 {len(summaries)} Active"
                body = build_summary_body("Boviet Daily Summary", tab_name, summaries, skipped=skipped)
                print(f"    [{tab_name}] {len(summaries)} active — sending to Boviet-efj")
                _send_email("Boviet-efj@evansdelivery.com", subject, body)

            if all_boviet_summaries:
                sync_state(BOVIET_STATE_FILE, all_boviet_summaries, key_fmt="boviet")

            # ── Tolead (all hubs) ─────────────────────────────────────
            tolead_data = scan_tolead(creds, gc)
            all_tolead_summaries = []
            for hub_name, data in tolead_data.items():
                entries = data["entries"]
                tab = data["tab"]
                needs_cover = data.get("needs_cover", [])
                print(f"\n    Scraping [{hub_name}/{tab}] ({len(entries)} loads)...")
                summaries, skipped = scrape_and_summarize(browser, entries)
                if skipped:
                    print(f"    [{hub_name}] {skipped} load(s) skipped (scrape failed)")
                if not summaries and not needs_cover:
                    print(f"    [{hub_name}] No actively tracking loads")
                    continue

                all_tolead_summaries.extend(summaries)

                total_active = len(summaries) + len(needs_cover)
                subject = f"{hub_name} Tolead Daily Summary \u2014 Schedule \u2014 {total_active} Active"
                body = build_summary_body(f"{hub_name} Tolead Daily Summary", "Schedule", summaries, skipped=skipped)
                # Append Needs to Cover section if any
                if needs_cover:
                    ntc_html = _build_needs_cover_section(needs_cover)
                    body = body.replace("</div>\n", ntc_html + "</div>\n", 1) if "</div>\n" in body else body[:-6] + ntc_html + "</div>"
                print(f"    [{hub_name}] {len(summaries)} tracked + {len(needs_cover)} needs cover — sending to tolead-efj")
                _send_email("tolead-efj@evansdelivery.com", subject, body)

            if all_tolead_summaries:
                sync_state(TOLEAD_STATE_FILE, all_tolead_summaries, key_fmt="tolead")

        finally:
            browser.close()

    print(f"\nDaily summary complete.")


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        print("TEST MODE — max 2 loads per tab")
        creds = _load_credentials()
        gc = gspread.authorize(creds)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                boviet_data = scan_boviet(creds, gc)
                for tab_name, data in boviet_data.items():
                    entries = data["entries"][:2]
                    print(f"\n    Scraping [{tab_name}] ({len(entries)} loads)...")
                    summaries, skipped = scrape_and_summarize(browser, entries)
                    if summaries:
                        body = build_summary_body("Boviet Daily Summary", tab_name, summaries, skipped=skipped)
                        subject = f"[TEST] Boviet Daily Summary \u2014 {tab_name} \u2014 {len(summaries)} Active"
                        _send_email("Boviet-efj@evansdelivery.com", subject, body)
                    else:
                        print(f"    [{tab_name}] No actively tracking loads")
            finally:
                browser.close()
    else:
        run()
