"""
Shared constants, helpers, SheetCache, CSS, and HTML builders.
Extracted from the monolithic app.py to be imported by route modules.
"""

import json
import logging
import os
import re
import subprocess
import smtplib
import threading
import time as _time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from fastapi.templating import Jinja2Templates

import config
import database as db

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

log = logging.getLogger(__name__)

# ── Macropoint tracking constants ──
TRACKING_PHONE = os.getenv("MACROPOINT_TRACKING_PHONE", "4437614954")
DISPATCH_EMAIL = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")

# Account-specific Reply-To routing
_REPLY_TO_MAP = {
    "tolead": "tolead-efj@evansdelivery.com",
    "boviet": "boviet-efj@evansdelivery.com",
}


def _get_reply_to(account: str) -> str:
    acct = (account or "").lower()
    for key, addr in _REPLY_TO_MAP.items():
        if key in acct:
            return addr
    return DISPATCH_EMAIL


# ── Delivery Email Notification ──

JANICE_EMAIL = "Janice.Cortes@evansdelivery.com"
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")


def _has_delivery_email_been_sent(efj: str) -> bool:
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT efj FROM delivery_emails_sent WHERE efj = %s", (efj,))
            return cur.fetchone() is not None
    except Exception:
        return False


def _record_delivery_email(efj: str, account: str):
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute(
                    "INSERT INTO delivery_emails_sent (efj, account) VALUES (%s, %s) ON CONFLICT (efj) DO NOTHING",
                    (efj, account)
                )
    except Exception as e:
        log.error("Failed to record delivery email for %s: %s", efj, e)


def send_delivery_email(shipment: dict):
    efj = shipment.get("efj", "")
    account = shipment.get("account", "")
    if account in ("Tolead", "Boviet"):
        return
    if _has_delivery_email_been_sent(efj):
        log.info("Delivery email already sent for %s — skipping", efj)
        return
    if not SMTP_USER or not SMTP_PASSWORD:
        log.warning("SMTP credentials not configured — skipping delivery email for %s", efj)
        return

    container = shipment.get("container", "") or shipment.get("loadNumber", "")
    carrier = shipment.get("carrier", "")
    origin = shipment.get("origin", "")
    destination = shipment.get("destination", "")
    delivery_date = shipment.get("delivery", "")
    rep = shipment.get("rep", "")

    subject = f"CSL — Delivered: {efj} | {account} | {container}"
    deep_link = f"https://cslogixdispatch.com/app?view=billing&load={efj}"

    body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
      <div style="background: linear-gradient(135deg, #22C55E, #4ADE80); padding: 16px 24px; border-radius: 12px 12px 0 0;">
        <h2 style="color: white; margin: 0; font-size: 18px;">&#10022; Load Delivered</h2>
      </div>
      <div style="background: #141A28; padding: 24px; border: 1px solid #1E293B; border-top: none; border-radius: 0 0 12px 12px;">
        <table style="width: 100%; border-collapse: collapse; color: #F0F2F5; font-size: 14px;">
          <tr><td style="padding: 8px 0; color: #8B95A8; width: 120px;">EFJ #</td><td style="padding: 8px 0; font-weight: 600;">{efj}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Account</td><td style="padding: 8px 0; font-weight: 600;">{account}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Container/Load</td><td style="padding: 8px 0;">{container}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Carrier</td><td style="padding: 8px 0;">{carrier}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Route</td><td style="padding: 8px 0;">{origin} &#8594; {destination}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Delivery Date</td><td style="padding: 8px 0;">{delivery_date}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Rep</td><td style="padding: 8px 0;">{rep}</td></tr>
        </table>
        <div style="margin-top: 20px; text-align: center;">
          <a href="{deep_link}" style="display: inline-block; background: #00D4AA; color: #0A0E17; padding: 10px 28px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 14px;">
            Open in Billing Dashboard
          </a>
        </div>
      </div>
      <p style="color: #64748B; font-size: 11px; margin-top: 12px; text-align: center;">
        CSLogix Dispatch &mdash; Automated delivery notification
      </p>
    </div>
    """

    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = SMTP_USER
            msg["To"] = JANICE_EMAIL
            msg["Cc"] = DISPATCH_EMAIL
            msg["Reply-To"] = _get_reply_to(account)
            msg.attach(MIMEText(body, "html"))
            recipients = [JANICE_EMAIL, DISPATCH_EMAIL]
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(SMTP_USER, SMTP_PASSWORD)
                smtp.sendmail(SMTP_USER, recipients, msg.as_string())
            _record_delivery_email(efj, account)
            log.info("Delivery email sent for %s → %s (cc: %s)", efj, JANICE_EMAIL, DISPATCH_EMAIL)
        except Exception as exc:
            log.error("Failed to send delivery email for %s: %s", efj, exc)

    threading.Thread(target=_send, daemon=True).start()


# ── Tracking cache ──

TRACKING_CACHE_FILE = "/root/csl-bot/ftl_tracking_cache.json"

_MP_PROGRESS_ORDER = [
    "Driver Assigned", "Ready To Track", "Arrived At Origin",
    "Departed Origin", "At Delivery", "Delivered",
]

_STATUS_TO_STEP = {
    "pending": 0, "booked": 0, "assigned": 1, "ready to track": 1,
    "tracking now": 1, "tracking waiting for update": 1,
    "at pickup": 2, "driver arrived at pickup": 2, "arrived at pickup": 2,
    "arrived at origin": 2, "loading": 2,
    "in transit": 3, "departed pickup": 3, "departed pickup - en route": 3,
    "en route": 3, "running late": 3, "tracking behind schedule": 3,
    "driver phone unresponsive": 3,
    "at delivery": 4, "arrived at delivery": 4, "unloading": 4, "out for delivery": 4,
    "delivered": 5, "departed delivery": 5, "completed": 5, "pod received": 5,
}


def _read_tracking_cache() -> dict:
    try:
        with open(TRACKING_CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _find_tracking_entry(cache: dict, efj: str) -> dict:
    if efj in cache:
        return cache[efj]
    stripped = efj.replace("EFJ", "").strip()
    if stripped in cache:
        return cache[stripped]
    prefixed = f"EFJ{efj}" if not efj.startswith("EFJ") else None
    if prefixed and prefixed in cache:
        return cache[prefixed]
    for entry in cache.values():
        e = entry.get("efj", "")
        if e == efj or e == stripped or e.replace("EFJ", "").strip() == stripped:
            return entry
    return {}


def _get_driver_contact(efj: str) -> dict:
    try:
        with db.get_cursor() as cur:
            cur.execute(
                "SELECT driver_name, driver_phone, driver_email, notes, "
                "carrier_email, trailer_number, macropoint_url "
                "FROM driver_contacts WHERE efj = %s",
                (efj,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
    except Exception as e:
        log.warning("Failed to read driver contact for %s: %s", efj, e)
    return {}


def _upsert_driver_contact(efj: str, name: str = None, phone: str = None,
                           email: str = None, notes: str = None,
                           carrier_email: str = None, trailer_number: str = None,
                           macropoint_url: str = None):
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO driver_contacts (efj, driver_name, driver_phone, driver_email, notes, carrier_email, trailer_number, macropoint_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (efj) DO UPDATE SET
                    driver_name    = COALESCE(EXCLUDED.driver_name,    driver_contacts.driver_name),
                    driver_phone   = COALESCE(EXCLUDED.driver_phone,   driver_contacts.driver_phone),
                    driver_email   = COALESCE(EXCLUDED.driver_email,   driver_contacts.driver_email),
                    notes          = COALESCE(EXCLUDED.notes,          driver_contacts.notes),
                    carrier_email  = COALESCE(EXCLUDED.carrier_email,  driver_contacts.carrier_email),
                    trailer_number = COALESCE(EXCLUDED.trailer_number, driver_contacts.trailer_number),
                    macropoint_url = COALESCE(EXCLUDED.macropoint_url, driver_contacts.macropoint_url),
                    updated_at     = NOW()
            """, (efj, name or None, phone or None, email or None, notes or None,
                  carrier_email or None, trailer_number or None, macropoint_url or None))


def _build_macropoint_progress(status_str: str):
    key = (status_str or "").strip().lower()
    step = _STATUS_TO_STEP.get(key, -1)
    if step == -1:
        for k, v in _STATUS_TO_STEP.items():
            if k in key or key in k:
                step = v
                break
    if step == -1:
        step = 0
    return [
        {"label": lbl, "done": i <= step}
        for i, lbl in enumerate(_MP_PROGRESS_ORDER)
    ]


def _classify_mp_display_status(cache_entry, shipment=None):
    """Compute a user-friendly MP display status from tracking data."""
    from datetime import datetime as _dt, timezone as _tz
    from zoneinfo import ZoneInfo as _ZI

    if not cache_entry:
        return ("No MP", "")

    status = (cache_entry.get("status") or "").strip()
    schedule_alert = (cache_entry.get("schedule_alert") or "").strip()
    last_loc = cache_entry.get("last_location") or {}
    last_loc_ts = (last_loc.get("timestamp") or "").strip()

    status_lower = status.lower()
    alert_upper = schedule_alert.upper()

    _last_ev = (cache_entry.get("last_event_at") or cache_entry.get("last_scraped") or "").strip()
    _stale_hours = None
    if _last_ev:
        try:
            _now_s = _dt.now(_ZI("America/New_York"))
            _ts_s = _last_ev.replace(" ET", "").replace(" EST", "").replace(" EDT", "")
            for _fmt_s in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    _ev_dt = _dt.strptime(_ts_s, _fmt_s)
                    _ev_dt = _ev_dt.replace(tzinfo=_ZI("America/New_York"))
                    _stale_hours = (_now_s - _ev_dt).total_seconds() / 3600
                    break
                except ValueError:
                    continue
        except Exception:
            pass

    _ship_status = ""
    if shipment:
        _ship_status = (shipment.get("status") or "").strip().lower()
    _TERMINAL_SHIP = {"delivered", "ready to close", "completed", "billed_closed",
                      "billed/closed", "canceled", "cancelled"}

    _has_mp_data = bool(_last_ev) or bool(cache_entry.get("stop_times", {}))
    if not _has_mp_data and _ship_status in _TERMINAL_SHIP:
        return ("Delivered", "Per shipment status")

    if _stale_hours is not None and _stale_hours > 48 and _ship_status in _TERMINAL_SHIP:
        return ("Delivered", "Per shipment status")

    if not status:
        if cache_entry.get("stop_times", {}).get("stop2_departed"):
            return ("Delivered", "Departed delivery")
        return ("No MP", "")

    if status_lower == "unassigned":
        return ("Unassigned", "")

    if "delivered" in status_lower or "completed" in status_lower:
        return ("Delivered", "")

    if "unresponsive" in status_lower:
        return ("No Signal", "Driver phone unresponsive")

    hours_offset = None
    _m = re.search(r'([\d.]+)\s*Hours?\s*(BEHIND|AHEAD)', alert_upper)
    if _m:
        hours_offset = float(_m.group(1))
        if _m.group(2) == "BEHIND":
            hours_offset = -hours_offset

    is_behind = hours_offset is not None and hours_offset < 0
    is_ahead = hours_offset is not None and hours_offset >= 0

    detail = ""
    if hours_offset is not None:
        abs_h = abs(hours_offset)
        if abs_h >= 1:
            detail = f"{abs_h:.1f}h {'behind' if is_behind else 'ahead'}"
        else:
            mins = int(abs_h * 60)
            detail = f"{mins}m {'behind' if is_behind else 'ahead'}"

    gps_stale = True
    if last_loc_ts:
        try:
            now = _dt.now(_ZI("America/New_York"))
            ts = last_loc_ts.replace(" ET", "").replace(" EST", "").replace(" EDT", "")
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S",
                        "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S"):
                try:
                    loc_dt = _dt.strptime(ts, fmt)
                    if fmt.endswith("Z"):
                        loc_dt = loc_dt.replace(tzinfo=_tz.utc).astimezone(_ZI("America/New_York"))
                    else:
                        loc_dt = loc_dt.replace(tzinfo=_ZI("America/New_York"))
                    age_hours = (now - loc_dt).total_seconds() / 3600
                    gps_stale = age_hours > 2.0
                    break
                except ValueError:
                    continue
        except Exception:
            pass

    if "arrived" in status_lower and "pickup" in status_lower:
        return ("At Pickup", detail)
    if "at pickup" in status_lower:
        return ("At Pickup", detail)
    if "arrived" in status_lower and "delivery" in status_lower:
        return ("At Delivery", detail)
    if "at delivery" in status_lower:
        return ("At Delivery", detail)
    if "departed delivery" in status_lower:
        return ("Delivered", "Departed delivery")

    if any(x in status_lower for x in ("transit", "departed pickup", "en route")):
        if is_behind:
            return ("Behind Schedule", detail)
        if is_ahead:
            return ("On Time", detail)
        if gps_stale:
            return ("Awaiting Update", "GPS stale")
        return ("In Transit", "")

    if "behind" in status_lower or "late" in status_lower:
        return ("Behind Schedule", detail or "Running late")

    if "waiting" in status_lower:
        return ("Awaiting Update", "")

    if "tracking started" in status_lower:
        if is_behind:
            return ("Behind Schedule", detail)
        if is_ahead:
            return ("On Time", detail)
        if not last_loc_ts:
            return ("Assigned", "Awaiting first GPS ping")
        if gps_stale:
            return ("Awaiting Update", "GPS stale")
        return ("On Time", "Tracking active")

    if "on-site" in status_lower or "on site" in status_lower:
        if cache_entry.get("stop_times", {}).get("stop2_departed"):
            return ("Delivered", "Departed delivery")
        if _stale_hours is not None and _stale_hours > 24 and _ship_status in _TERMINAL_SHIP:
            return ("Delivered", "Per shipment status")
        return ("At Delivery", detail or "On site")

    if is_behind:
        return ("Behind Schedule", detail)
    if is_ahead:
        return ("On Time", detail)
    if _stale_hours is not None and _stale_hours > 48 and _ship_status in _TERMINAL_SHIP:
        return ("Delivered", "Per shipment status")
    return (status, "")


def _shorten_address(addr):
    if not addr:
        return addr
    addr = re.sub(r'^\(\w+\)\s*', '', addr).strip()
    addr = re.sub(r'\s*\([^)]*\)\s*$', '', addr).strip()
    m = re.search(r'([A-Za-z][A-Za-z .]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$', addr)
    if m:
        return f"{m.group(1).strip()}, {m.group(2)} {m.group(3)}"
    m = re.search(r'([A-Za-z][A-Za-z .]+),\s*([A-Z]{2})\s*$', addr)
    if m:
        return f"{m.group(1).strip()}, {m.group(2)}"
    m = re.search(r'([A-Za-z][A-Za-z .]+)\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$', addr)
    if m:
        return f"{m.group(1).strip()}, {m.group(2)} {m.group(3)}"
    return addr


# ── Google Sheet configuration ──

SHEET_ID = "19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0"
CREDS_FILE = "/root/csl-credentials.json"
SKIP_TABS = {
    "Sheet 4", "DTCELNJW", "Account Rep", "SSL Links",
    "Completed Eli", "Completed Radka", "Completed John F", "Boviet",
}
CACHE_TTL = 600  # 10 minutes

BOVIET_SHEET_ID = "1OP-ZDaMCOsPxcxezHSPfN5ftUXlUcOjFgsfCQgDp3wI"

COL = {
    "efj": 0, "move_type": 1, "container": 2, "bol": 3,
    "ssl": 4, "carrier": 5, "origin": 6, "destination": 7,
    "eta": 8, "lfd": 9, "pickup": 10, "delivery": 11,
    "status": 12, "notes": 13, "bot_alert": 14, "return_port": 15,
}

BOT_SERVICES = [
    {"unit": "csl-boviet", "name": "Boviet Monitor", "poll_min": 20},
    {"unit": "csl-tolead", "name": "Tolead Monitor", "poll_min": 20},
    {"unit": "csl-upload", "name": "Upload Server", "poll_min": 0},
]

REP_STYLES = {
    "Radka": {"color": "var(--accent-green)", "bg": "linear-gradient(135deg,#22c55e,#16a34a)", "initials": "RK"},
    "John F": {"color": "var(--accent-purple)", "bg": "linear-gradient(135deg,#8b5cf6,#7c3aed)", "initials": "JF"},
    "Janice": {"color": "var(--accent-cyan)", "bg": "linear-gradient(135deg,#06b6d4,#0891b2)", "initials": "JC"},
    "Nancy": {"color": "var(--accent-blue)", "bg": "linear-gradient(135deg,#3b82f6,#2563eb)", "initials": "NF"},
    "Allie": {"color": "var(--accent-pink)", "bg": "linear-gradient(135deg,#ec4899,#db2777)", "initials": "AM"},
    "John N": {"color": "var(--accent-indigo)", "bg": "linear-gradient(135deg,#6366f1,#4f46e5)", "initials": "JN"},
    "Climaco": {"color": "var(--accent-teal)", "bg": "linear-gradient(135deg,#14b8a6,#0d9488)", "initials": "CC"},
    "Boviet": {"color": "var(--accent-amber)", "bg": "linear-gradient(135deg,#f59e0b,#d97706)", "initials": "BV"},
    "Tolead": {"color": "var(--accent-red)", "bg": "linear-gradient(135deg,#ef4444,#dc2626)", "initials": "TL"},
}

# File upload validation
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".xlsx", ".xls", ".doc", ".docx"}
MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25 MB


def _sanitize_filename(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r'[^\w\-.]', '_', name)
    name = re.sub(r'_{2,}', '_', name)
    name = re.sub(r'\.{2,}', '.', name)
    if not name or name.startswith('.'):
        name = f"upload_{int(_time.time())}"
    return name


# Boviet tab configs
BOVIET_SKIP_TABS = {"POCs", "Boviet Master"}
BOVIET_TAB_CONFIGS = {
    "DTE Fresh/Stock":  {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Sundance":         {"efj_col": 0, "load_id_col": 1, "status_col": 6},
    "Renewable Energy": {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Radiance Solar":   {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Piedra":           {"efj_col": 0, "load_id_col": 2, "status_col": 8,
                         "pickup_col": 6, "delivery_col": 7,
                         "phone_col": 11, "trailer_col": 12,
                         "carrier_email_col": 10, "driver_name_col": 13,
                         "default_origin": "Greenville, NC", "default_dest": "Mexia, TX",
                         "start_row": 45},
    "Hanson":           {"efj_col": 0, "load_id_col": 2, "status_col": 8,
                         "pickup_col": 6, "delivery_col": 7,
                         "phone_col": 11, "trailer_col": 13,
                         "carrier_email_col": 10, "driver_name_col": 12,
                         "default_origin": "Houston, TX", "default_dest": "Valera, TX"},
}
BOVIET_DONE_STATUSES = {"delivered", "completed", "canceled", "cancelled", "ready to close"}

# Tolead configs
TOLEAD_SHEET_ID = "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac"
TOLEAD_TAB = "Schedule"
TOLEAD_COL_EFJ = 15
TOLEAD_COL_ORD = 1
TOLEAD_COL_STATUS = 9
TOLEAD_COL_ORIGIN = 6
TOLEAD_COL_DEST = 7
TOLEAD_COL_DATE = 4
TOLEAD_SKIP_STATUSES = {"delivered", "canceled", "cancelled"}

TOLEAD_JFK_SHEET_ID = "1mfhEsK2zg6GWTqMDTo5VwCgY-QC1tkNPknurHMxtBhs"
TOLEAD_JFK_TAB = "Schedule"
TOLEAD_ORD_COLS = {
    "efj": 15, "load_id": 1, "status": 9, "origin": 6,
    "destination": 7, "pickup_date": 4, "pickup_time": 5,
    "delivery": 3, "driver": 16, "phone": 17, "appt_id": 2,
}

TOLEAD_JFK_COLS = {
    "efj": 14, "load_id": 0, "status": 9, "origin": 6,
    "destination": 7, "pickup_date": 3, "pickup_time": 4,
    "delivery": 5, "driver": 15, "phone": 16,
}

TOLEAD_LAX_SHEET_ID = "1YLB6z5LdL0kFYTcfq_H5e6acU8-VLf8nN0XfZrJ-bXo"
TOLEAD_LAX_TAB = "LAX"
TOLEAD_LAX_COLS = {
    "efj": 0, "load_id": 3, "status": 9, "origin": 6,
    "destination": 7, "pickup_date": 4, "pickup_time": 5,
    "delivery": 8, "driver": 11, "phone": 12,
}

TOLEAD_DFW_SHEET_ID = "1RfGcq25x4qshlBDWDJD-xBJDlJm6fvDM_w2RTHhn9oI"
TOLEAD_DFW_TAB = "DFW"
TOLEAD_DFW_COLS = {
    "efj": 10, "load_id": 4, "status": 11, "origin": None,
    "destination": 3, "pickup_date": 5, "pickup_time": 6,
    "delivery": 2, "driver": 12, "phone": 13,
    "appt_id": 1, "equipment": 8,
}

TOLEAD_HUB_CONFIGS = {
    "ORD": {"sheet_id": TOLEAD_SHEET_ID, "tab": TOLEAD_TAB, "cols": TOLEAD_ORD_COLS, "default_origin": "ORD", "start_row": 790},
    "JFK": {"sheet_id": TOLEAD_JFK_SHEET_ID, "tab": TOLEAD_JFK_TAB, "cols": TOLEAD_JFK_COLS, "default_origin": "Garden City, NY", "start_row": 184},
    "LAX": {"sheet_id": TOLEAD_LAX_SHEET_ID, "tab": TOLEAD_LAX_TAB, "cols": TOLEAD_LAX_COLS, "default_origin": "Vernon, CA", "start_row": 755},
    "DFW": {"sheet_id": TOLEAD_DFW_SHEET_ID, "tab": TOLEAD_DFW_TAB, "cols": TOLEAD_DFW_COLS, "default_origin": "Irving, TX", "start_row": 172},
}


def _get_sheet_hyperlinks(creds, sheet_id, tab_name):
    import requests as _requests
    from google.auth.transport.requests import Request as GoogleRequest
    try:
        creds.refresh(GoogleRequest())
        api_url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
            f"?ranges={_requests.utils.quote(tab_name)}"
            f"&fields=sheets.data.rowData.values.hyperlink"
            f"&includeGridData=true"
        )
        resp = _requests.get(api_url, headers={"Authorization": f"Bearer {creds.token}"})
        resp.raise_for_status()
        data = resp.json()
        result = []
        for row_data in data["sheets"][0]["data"][0].get("rowData", []):
            result.append([cell.get("hyperlink") for cell in row_data.get("values", [])])
        return result
    except Exception as e:
        log.warning("Hyperlink fetch failed for %s/%s: %s", sheet_id[:8], tab_name, e)
        return []


# ── SheetCache ──

class SheetCache:
    def __init__(self):
        self.shipments = []
        self.rep_map = {}
        self.stats = {"active": 0, "on_schedule": 0, "eta_changed": 0, "at_risk": 0, "completed_today": 0}
        self.accounts = []
        self.team = {}
        self._lock = threading.Lock()
        self._last = 0

    def refresh_if_needed(self):
        if _time.time() - self._last < CACHE_TTL:
            return
        with self._lock:
            if _time.time() - self._last < CACHE_TTL:
                return
            try:
                self._do_refresh()
            except Exception as e:
                log.error("Sheet refresh failed: %s", e)

    def _do_refresh(self):
        creds = Credentials.from_service_account_file(
            CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)

        try:
            rep_rows = sh.worksheet("Account Rep").get_all_values()
            self.rep_map = {}
            for r in rep_rows[2:]:
                if r[0].strip() and len(r) > 1 and r[1].strip():
                    self.rep_map[r[0].strip()] = r[1].strip()
        except Exception:
            pass

        all_shipments = []
        tabs = [ws.title for ws in sh.worksheets() if ws.title not in SKIP_TABS]
        ranges = [f"'{t}'!A:P" for t in tabs]
        try:
            batch_result = sh.values_batch_get(ranges)
            value_ranges = batch_result.get("valueRanges", [])
            for vr, tab_name in zip(value_ranges, tabs):
                rows = vr.get("values", [])
                if len(rows) < 2:
                    continue
                hdr_idx = 0
                if len(rows) > 1:
                    r0 = sum(1 for c in rows[0] if c.strip())
                    r1 = sum(1 for c in rows[1] if c.strip())
                    if r1 > r0:
                        hdr_idx = 1
                for row in rows[hdr_idx + 1:]:
                    efj = row[COL["efj"]].strip() if len(row) > COL["efj"] else ""
                    ctr = row[COL["container"]].strip() if len(row) > COL["container"] else ""
                    if not efj and not ctr:
                        continue
                    def cell(key, r=row):
                        idx = COL[key]
                        return r[idx].strip() if len(r) > idx else ""
                    all_shipments.append({
                        "account": tab_name,
                        "efj": efj, "move_type": cell("move_type"),
                        "container": ctr, "bol": cell("bol"),
                        "ssl": cell("ssl"), "carrier": cell("carrier"),
                        "origin": cell("origin"), "destination": cell("destination"),
                        "eta": cell("eta"), "lfd": cell("lfd"),
                        "pickup": cell("pickup"), "delivery": cell("delivery"),
                        "status": cell("status"), "notes": cell("notes"),
                        "bot_alert": cell("bot_alert"), "return_port": cell("return_port"),
                        "container_url": "",
                        "rep": self.rep_map.get(tab_name, "Unassigned"),
                    })
        except Exception as e:
            log.warning("Master batch read failed: %s", e)

        _time.sleep(2)

        # Boviet tabs
        try:
            bov_sh = gc.open_by_key(BOVIET_SHEET_ID)
            bov_tabs = [ws.title for ws in bov_sh.worksheets()
                        if ws.title not in BOVIET_SKIP_TABS and ws.title in BOVIET_TAB_CONFIGS]
            bov_ranges = [f"'{t}'!A:Z" for t in bov_tabs]
            bov_batch = bov_sh.values_batch_get(bov_ranges)
            bov_value_ranges = bov_batch.get("valueRanges", [])
            for vr, tab_name in zip(bov_value_ranges, bov_tabs):
                try:
                    cfg = BOVIET_TAB_CONFIGS[tab_name]
                    rows = vr.get("values", [])
                    bov_links = _get_sheet_hyperlinks(creds, BOVIET_SHEET_ID, tab_name)
                    bov_start = cfg.get("start_row", 1)
                    for ri, row in enumerate(rows[1:], start=1):
                        if ri + 1 < bov_start:
                            continue
                        efj = row[cfg["efj_col"]].strip() if len(row) > cfg["efj_col"] else ""
                        load_id = row[cfg["load_id_col"]].strip() if len(row) > cfg["load_id_col"] else ""
                        status = row[cfg["status_col"]].strip() if len(row) > cfg["status_col"] else ""
                        if not efj or status.lower() in BOVIET_DONE_STATUSES:
                            continue
                        bov_mp_url = ""
                        if ri < len(bov_links) and len(bov_links[ri]) > cfg["efj_col"]:
                            bov_mp_url = bov_links[ri][cfg["efj_col"]] or ""
                        bov_pickup = ""
                        bov_delivery = ""
                        bov_phone = ""
                        bov_trailer = ""
                        bov_origin = cfg.get("default_origin", "")
                        bov_dest = cfg.get("default_dest", "")
                        if "pickup_col" in cfg:
                            bov_pickup = row[cfg["pickup_col"]].strip() if len(row) > cfg["pickup_col"] else ""
                        if "delivery_col" in cfg:
                            bov_delivery = row[cfg["delivery_col"]].strip() if len(row) > cfg["delivery_col"] else ""
                        if "phone_col" in cfg:
                            bov_phone = row[cfg["phone_col"]].strip() if len(row) > cfg["phone_col"] else ""
                        if "trailer_col" in cfg:
                            bov_trailer = row[cfg["trailer_col"]].strip() if len(row) > cfg["trailer_col"] else ""
                        bov_carrier_email = ""
                        bov_driver_name = ""
                        if "carrier_email_col" in cfg:
                            bov_carrier_email = row[cfg["carrier_email_col"]].strip() if len(row) > cfg["carrier_email_col"] else ""
                        if "driver_name_col" in cfg:
                            bov_driver_name = row[cfg["driver_name_col"]].strip() if len(row) > cfg["driver_name_col"] else ""
                        all_shipments.append({
                            "account": "Boviet", "efj": efj, "move_type": "FTL",
                            "container": load_id, "bol": "", "ssl": "",
                            "carrier": "", "origin": bov_origin, "destination": bov_dest,
                            "eta": "", "lfd": "",
                            "pickup": bov_pickup, "delivery": bov_delivery,
                            "status": status, "notes": "", "bot_alert": "",
                            "return_port": "", "rep": "Boviet",
                            "container_url": bov_mp_url,
                            "driver": bov_trailer,
                            "driver_phone": bov_phone,
                            "carrier_email": bov_carrier_email,
                            "driver_name": bov_driver_name,
                            "hub": tab_name,
                        })
                    _time.sleep(1)
                except Exception as e:
                    log.warning("Boviet tab %s: %s", tab_name, e)
        except Exception as e:
            log.warning("Boviet sheet read failed: %s", e)

        _time.sleep(2)

        # Tolead hubs
        for hub_name, hub_cfg in TOLEAD_HUB_CONFIGS.items():
            try:
                _time.sleep(1)
                hub_sh = gc.open_by_key(hub_cfg["sheet_id"])
                hub_ws = hub_sh.worksheet(hub_cfg["tab"])
                hub_rows = hub_ws.get_all_values()
                hub_links = _get_sheet_hyperlinks(creds, hub_cfg["sheet_id"], hub_cfg["tab"])
                cols = hub_cfg["cols"]
                hub_count = 0
                hub_start = hub_cfg.get("start_row", 1)
                for ri, row in enumerate(hub_rows[1:], start=1):
                    if ri + 1 < hub_start:
                        continue
                    def _cell(idx, r=row):
                        if idx is None:
                            return ""
                        return r[idx].strip() if len(r) > idx else ""
                    efj = _cell(cols["efj"])
                    load_id = _cell(cols["load_id"])
                    status = _cell(cols["status"])

                    if hub_name == "DFW":
                        if not load_id:
                            continue
                        if status and status.lower() in TOLEAD_SKIP_STATUSES:
                            continue
                        col_j = row[9].strip() if len(row) > 9 else ""
                        if col_j.lower() not in ("scheduled", "picked"):
                            status = "Needs to Cover"
                        elif not status:
                            status = col_j.capitalize()
                    elif hub_name == "ORD":
                        if not load_id:
                            continue
                        if status and status.lower() in TOLEAD_SKIP_STATUSES:
                            continue
                        if status and status.lower() == "new":
                            status = "Needs to Cover"
                        elif not status:
                            continue
                    elif hub_name == "LAX":
                        if not load_id:
                            continue
                        if status and status.lower() in TOLEAD_SKIP_STATUSES:
                            continue
                        if status and status.lower() == "unassigned":
                            status = "Needs to Cover"
                        elif not status:
                            continue
                    elif hub_name == "JFK":
                        if not load_id:
                            continue
                        if status and status.lower() in TOLEAD_SKIP_STATUSES:
                            continue
                        if status and status.lower() == "new":
                            status = "Needs to Cover"
                        elif not status:
                            continue
                    else:
                        if not efj and not load_id:
                            continue
                        if status and status in TOLEAD_SKIP_STATUSES:
                            continue
                        if not status:
                            continue

                    origin = _shorten_address(_cell(cols["origin"]) or hub_cfg["default_origin"])
                    pickup_date = _cell(cols["pickup_date"])
                    pickup_time = _cell(cols["pickup_time"])
                    pickup = f"{pickup_date} {pickup_time}".strip() if pickup_date else ""
                    delivery = _cell(cols["delivery"])
                    driver_trailer = _cell(cols.get("driver")) if cols.get("driver") is not None else ""
                    driver_phone = _cell(cols.get("phone")) if cols.get("phone") is not None else ""

                    _mp_url = ""
                    _efj_col = cols["efj"]
                    if hub_links and ri < len(hub_links):
                        _lr = hub_links[ri]
                        if _efj_col < len(_lr) and _lr[_efj_col]:
                            _mp_url = _lr[_efj_col]

                    all_shipments.append({
                        "account": "Tolead", "efj": efj or load_id,
                        "move_type": "FTL", "container": load_id, "bol": "",
                        "ssl": "", "carrier": "",
                        "origin": origin,
                        "destination": _shorten_address(_cell(cols["destination"])),
                        "eta": pickup_date, "lfd": "",
                        "pickup": pickup, "delivery": delivery,
                        "status": status, "notes": "", "bot_alert": "",
                        "return_port": "", "rep": "Tolead",
                        "container_url": _mp_url,
                        "hub": hub_name,
                        "driver": "",
                        "driver_phone": driver_phone,
                    })
                    hub_count += 1
                log.info("Tolead %s: %d active loads", hub_name, hub_count)
            except Exception as e:
                log.warning("Tolead %s sheet read failed: %s", hub_name, e)

        self.shipments = all_shipments

        try:
            invoiced_map = db.get_invoiced_map()
        except Exception:
            invoiced_map = {}
        for s in self.shipments:
            s["_invoiced"] = invoiced_map.get(s["efj"], False)

        self._compute_stats()
        self._last = _time.time()
        log.info("Sheet cache: %d shipments", len(all_shipments))

    def _compute_stats(self):
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

        active = on_sched = eta_chg = at_risk = done_today = 0
        acct_data = {}
        team_data = {}

        for s in self.shipments:
            sl = s["status"].lower()
            is_done = any(w in sl for w in ("delivered", "completed", "empty return"))
            acct = acct_data.setdefault(s["account"], {"active": 0, "alerts": 0, "done": 0})
            if is_done:
                acct["done"] += 1
                if today in s.get("delivery", ""):
                    done_today += 1
                continue
            active += 1
            acct["active"] += 1
            risk = False
            if s["lfd"] and s["lfd"][:10] <= tomorrow:
                risk = True
            if not s["eta"] and not s["status"]:
                risk = True
            if risk:
                at_risk += 1
                acct["alerts"] += 1
            else:
                on_sched += 1
            if s["bot_alert"] and today in s["bot_alert"]:
                eta_chg += 1
            rep = s.get("rep", "Unassigned")
            td = team_data.setdefault(rep, {"loads": 0, "accounts": set(), "at_risk": 0})
            td["loads"] += 1
            td["accounts"].add(s["account"])
            if risk:
                td["at_risk"] += 1

        self.stats = {
            "active": active, "on_schedule": on_sched,
            "eta_changed": eta_chg, "at_risk": at_risk,
            "completed_today": done_today,
        }
        self.accounts = sorted(
            [{"name": k, **v} for k, v in acct_data.items()],
            key=lambda x: x["active"], reverse=True,
        )
        self.team = {
            rep: {"loads": d["loads"], "accounts": sorted(d["accounts"]), "at_risk": d["at_risk"]}
            for rep, d in team_data.items()
        }


sheet_cache = SheetCache()


# ── Alert generation ──

def _generate_alerts(shipments, limit=10):
    alerts = []
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    for s in shipments:
        sl = s["status"].lower()
        if any(w in sl for w in ("delivered", "completed", "empty return")):
            continue
        alert = None
        label = s["container"] or s["efj"]

        if s["lfd"] and s["lfd"][:10] <= today:
            alert = {
                "title": f"{s['account'].upper()} \u2014 {label}",
                "desc": f"LFD is <span style='color:var(--accent-red);font-weight:700'>TODAY ({s['lfd'][:10]})</span> \u00B7 Status: {s['status'] or 'Unknown'} \u00B7 Carrier: {s['carrier'] or 'TBD'} \u2014 <span style='color:var(--accent-red);font-weight:700'>PICK UP TODAY</span>",
                "type": "urgent", "icon": "\U0001f525",
                "move": s["move_type"], "rep": s["rep"], "efj": s["efj"], "account": s["account"],
            }
        elif s["lfd"] and s["lfd"][:10] <= tomorrow:
            alert = {
                "title": f"{s['account'].upper()} \u2014 {label}",
                "desc": f"LFD is <span style='color:var(--accent-amber);font-weight:700'>TOMORROW ({s['lfd'][:10]})</span> \u00B7 Status: {s['status'] or 'Unknown'} \u00B7 Carrier: {s['carrier'] or 'TBD'} \u2014 <span style='color:var(--accent-amber);font-weight:700'>SCHEDULE PICKUP</span>",
                "type": "warning", "icon": "\u26a0\ufe0f",
                "move": s["move_type"], "rep": s["rep"], "efj": s["efj"], "account": s["account"],
            }
        elif s["bot_alert"] and today in s["bot_alert"]:
            alert = {
                "title": f"{s['account'].upper()} \u2014 {label}",
                "desc": f"ETA: {s['eta'] or 'N/A'} \u00B7 Vessel: {s['ssl'] or 'Unknown'} \u00B7 {s['origin']} \u2192 {s['destination']}",
                "type": "info", "icon": "\U0001f916",
                "move": s["move_type"], "rep": s["rep"], "efj": s["efj"], "account": s["account"],
            }
        elif not s["eta"] and not s["status"] and s["container"]:
            alert = {
                "title": f"{s['account'].upper()} \u2014 {label}",
                "desc": f"No tracking data \u00B7 SSL: {s['ssl'] or 'Unknown'} \u00B7 Container: {s['container']}",
                "type": "info", "icon": "\U0001f4e1",
                "move": s["move_type"], "rep": s["rep"], "efj": s["efj"], "account": s["account"],
            }

        if alert:
            alerts.append(alert)

    priority = {"urgent": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: priority.get(a["type"], 3))
    return alerts[:limit]


# ── Bot status ──

def _get_service_status(unit):
    try:
        r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return "unknown"


def _get_bot_status_detailed():
    results = []
    for svc in BOT_SERVICES:
        unit = svc["unit"]
        status = _get_service_status(unit)
        last_run = next_run = ""
        try:
            r = subprocess.run(
                ["journalctl", "-u", unit, "-n", "1", "--no-pager", "-o", "short"],
                capture_output=True, text=True, timeout=5,
            )
            line = r.stdout.strip().split("\n")[-1] if r.stdout.strip() else ""
            m = re.match(r"(\w+ \d+ \d+:\d+:\d+)", line)
            if m:
                ts = datetime.strptime(f"2026 {m.group(1)}", "%Y %b %d %H:%M:%S")
                mins = int((datetime.now() - ts).total_seconds() / 60)
                last_run = "just now" if mins < 1 else (f"{mins} min ago" if mins < 60 else f"{mins // 60} hr ago")
                if svc["poll_min"] > 0:
                    nm = svc["poll_min"] - mins
                    next_run = "overdue" if nm < 0 else (f"{nm} min" if nm < 60 else f"{nm // 60} hr {nm % 60} min")
        except Exception:
            pass
        results.append({
            "name": svc["name"], "unit": unit, "status": status,
            "last_run": last_run or "unknown",
            "next_run": next_run if svc["poll_min"] > 0 else "",
            "poll_min": svc["poll_min"],
        })
    return results


def _get_recent_actions(limit=8):
    actions = []
    for svc in BOT_SERVICES[:5]:
        try:
            r = subprocess.run(
                ["journalctl", "-u", svc["unit"], "-n", "40", "--no-pager", "-o", "short"],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                tm = re.match(r"\w+ \d+ (\d+:\d+)", line)
                time_str = tm.group(1) if tm else ""
                action = status_badge = None
                if "No changes in" in line:
                    tab = re.search(r"No changes in '(\w+)'", line)
                    if tab:
                        action = f"Scanned {tab.group(1)} \u2014 no updates"
                        status_badge = ("Done", "green")
                elif "Tab:" in line:
                    tab = re.search(r"Tab: (\w+)", line)
                    if tab:
                        action = f"Scanning {tab.group(1)} account"
                        status_badge = ("Active", "cyan")
                elif "[Dray Import]" in line:
                    m = re.search(r"Container: (\w+)", line)
                    if m:
                        action = f"Tracking {m.group(1)}"
                        status_badge = ("Written", "blue")
                elif "email" in line.lower() or "alert" in line.lower() or "Alert" in line:
                    action = line.split("]:")[-1].strip()[:60] if "]:" in line else line[-60:]
                    status_badge = ("Sent", "amber")
                if action and status_badge:
                    try:
                        t = datetime.strptime(time_str, "%H:%M")
                        time_str = t.strftime("%I:%M %p")
                    except Exception:
                        pass
                    actions.append({"time": time_str, "action": action, "status": status_badge[0], "color": status_badge[1]})
        except Exception:
            pass
    return actions[:limit]


# ── CSS ──

GOOGLE_FONTS = '<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">'

DASHBOARD_CSS = """
:root {
  --bg-deep: #0a0d12; --bg-surface: #111822; --bg-card: #161e2c;
  --bg-card-hover: #1a2435; --bg-elevated: #1e2a3d;
  --accent-blue: #3b82f6; --accent-cyan: #06b6d4; --accent-green: #22c55e;
  --accent-amber: #f59e0b; --accent-red: #ef4444; --accent-purple: #8b5cf6;
  --text-primary: #e8ecf4; --text-secondary: #7b8ba3; --text-dim: #4a5568;
  --border: #1e2a3d; --border-subtle: #162030; --glow-blue: rgba(59, 130, 246, 0.15);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: var(--bg-deep); color: var(--text-primary); font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; min-height: 100vh; overflow-x: hidden; }
body::before { content: ''; position: fixed; inset: 0; background-image: linear-gradient(rgba(59,130,246,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(59,130,246,0.03) 1px, transparent 1px); background-size: 60px 60px; pointer-events: none; z-index: 0; }
a { color: var(--accent-blue); text-decoration: none; }
a:hover { text-decoration: underline; }
.sidebar { position: fixed; left: 0; top: 0; bottom: 0; width: 72px; background: var(--bg-surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; align-items: center; padding: 20px 0; z-index: 100; }
.sidebar-logo { width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center; justify-content: center; margin-bottom: 32px; overflow: hidden; box-shadow: 0 0 20px rgba(0,222,180,0.3); }
.sidebar-logo img { width: 42px; height: 42px; border-radius: 12px; object-fit: cover; }
.sidebar-nav { display: flex; flex-direction: column; gap: 8px; flex: 1; }
.nav-item { width: 44px; height: 44px; border-radius: 12px; display: flex; align-items: center; justify-content: center; color: var(--text-dim); cursor: pointer; transition: all 0.2s; position: relative; text-decoration: none; }
.nav-item:hover { background: var(--bg-card); color: var(--text-secondary); text-decoration: none; }
.nav-item.active { background: var(--glow-blue); color: var(--accent-blue); }
.nav-item.active::before { content: ''; position: absolute; left: -14px; width: 3px; height: 20px; background: var(--accent-blue); border-radius: 0 3px 3px 0; }
.nav-item svg { width: 20px; height: 20px; }
.sidebar-bottom { margin-top: auto; }
.main { margin-left: 72px; min-height: 100vh; position: relative; z-index: 1; }
.topbar { padding: 16px 32px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; background: rgba(10,13,18,0.8); backdrop-filter: blur(12px); position: sticky; top: 0; z-index: 50; }
.topbar-left { display: flex; align-items: center; gap: 20px; }
.topbar-title { font-weight: 700; font-size: 20px; letter-spacing: -0.02em; }
.topbar-title span { color: var(--accent-cyan); }
.live-badge { display: flex; align-items: center; gap: 6px; background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.2); padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 600; color: var(--accent-green); text-transform: uppercase; letter-spacing: 0.05em; }
.live-dot { width: 7px; height: 7px; background: var(--accent-green); border-radius: 50%; animation: pulse 2s infinite; }
@keyframes pulse { 0%,100% { opacity:1; box-shadow:0 0 0 0 rgba(34,197,94,0.4); } 50% { opacity:0.7; box-shadow:0 0 0 6px rgba(34,197,94,0); } }
.topbar-right { display: flex; align-items: center; gap: 16px; }
.topbar-time { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-secondary); }
.avatar { width: 34px; height: 34px; border-radius: 10px; background: linear-gradient(135deg, var(--accent-purple), var(--accent-blue)); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px; }
.search-box { position: relative; }
.search-box input { width: 260px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 8px 14px 8px 36px; color: var(--text-primary); font-size: 12px; font-family: 'Plus Jakarta Sans', sans-serif; }
.search-box input::placeholder { color: var(--text-dim); }
.search-box svg { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 14px; height: 14px; color: var(--text-dim); }
.content { padding: 24px 32px; }
.stats-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 24px; }
.stat-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 20px; position: relative; overflow: hidden; transition: all 0.25s; cursor: pointer; }
.stat-card:hover { border-color: rgba(59,130,246,0.3); transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.3); }
.stat-card::after { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; }
.stat-card.blue::after { background: linear-gradient(90deg, var(--accent-blue), var(--accent-cyan)); }
.stat-card.green::after { background: linear-gradient(90deg, var(--accent-green), #34d399); }
.stat-card.amber::after { background: linear-gradient(90deg, var(--accent-amber), #fbbf24); }
.stat-card.red::after { background: linear-gradient(90deg, var(--accent-red), #f87171); }
.stat-card.purple::after { background: linear-gradient(90deg, var(--accent-purple), #a78bfa); }
.stat-label { font-size: 11px; font-weight: 600; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }
.stat-value { font-family: 'JetBrains Mono', monospace; font-size: 28px; font-weight: 700; letter-spacing: -0.03em; }
.stat-card.blue .stat-value { color: var(--accent-blue); }
.stat-card.green .stat-value { color: var(--accent-green); }
.stat-card.amber .stat-value { color: var(--accent-amber); }
.stat-card.red .stat-value { color: var(--accent-red); }
.stat-card.purple .stat-value { color: var(--accent-purple); }
.stat-sub { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
.two-col { display: grid; grid-template-columns: 1fr 380px; gap: 20px; margin-bottom: 24px; }
.panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
.panel-header { padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
.panel-title { font-weight: 700; font-size: 14px; display: flex; align-items: center; gap: 8px; }
.panel-badge { background: rgba(239,68,68,0.15); color: var(--accent-red); font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 6px; }
.panel-badge.green { background: rgba(34,197,94,0.15); color: var(--accent-green); }
.filter-tabs { display: flex; gap: 6px; }
.filter-tab { padding: 5px 14px; border-radius: 8px; font-size: 12px; font-weight: 500; border: 1px solid var(--border); background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.2s; }
.filter-tab.active { background: var(--accent-blue); color: #fff; border-color: var(--accent-blue); }
.alert-list { max-height: 420px; overflow-y: auto; }
.alert-item { padding: 14px 20px; border-bottom: 1px solid var(--border-subtle); display: flex; gap: 12px; transition: background 0.15s; cursor: pointer; }
.alert-item:hover { background: var(--bg-card-hover); }
.alert-icon { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
.alert-icon.urgent { background: rgba(239,68,68,0.15); }
.alert-icon.warning { background: rgba(245,158,11,0.15); }
.alert-icon.info { background: rgba(59,130,246,0.12); }
.alert-body { flex: 1; min-width: 0; }
.alert-title-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 3px; }
.alert-name { font-weight: 600; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.alert-desc { font-size: 12px; color: var(--text-secondary); line-height: 1.5; }
.alert-tags { display: flex; gap: 6px; margin-top: 6px; }
.alert-tag { font-family: 'JetBrains Mono', monospace; font-size: 10px; padding: 2px 8px; border-radius: 4px; background: var(--bg-elevated); color: var(--text-dim); }
.alert-tag.efj { background: rgba(59,130,246,0.15); color: var(--accent-blue); }
.alert-tag.import { background: rgba(6,182,212,0.15); color: var(--accent-cyan); }
.alert-tag.export { background: rgba(34,197,94,0.15); color: var(--accent-green); }
.alert-tag.ftl { background: rgba(139,92,246,0.15); color: var(--accent-purple); }
.alert-tag.rep { background: rgba(245,158,11,0.12); color: var(--accent-amber); }
.account-list { padding: 8px; }
.account-row { display: grid; grid-template-columns: 1fr 55px 55px 55px; gap: 4px; align-items: center; padding: 10px 12px; border-radius: 8px; font-size: 12px; transition: background 0.15s; }
.account-row:hover { background: var(--bg-card-hover); }
.account-row.header { font-weight: 600; color: var(--text-dim); text-transform: uppercase; font-size: 10px; letter-spacing: 0.06em; padding-bottom: 4px; border-bottom: 1px solid var(--border-subtle); }
.account-name { font-weight: 600; display: flex; align-items: center; gap: 6px; }
.account-dot { width: 6px; height: 6px; border-radius: 50%; }
.account-dot.ok { background: var(--accent-green); }
.account-dot.warn { background: var(--accent-amber); }
.account-dot.alert { background: var(--accent-red); }
.cell-count { text-align: center; font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 500; }
.three-col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }
.bot-row { display: flex; align-items: center; justify-content: space-between; padding: 12px 20px; border-bottom: 1px solid var(--border-subtle); }
.bot-info { display: flex; align-items: center; gap: 10px; }
.bot-dot { width: 8px; height: 8px; border-radius: 50%; }
.bot-dot.running { background: var(--accent-green); box-shadow: 0 0 8px rgba(34,197,94,0.5); }
.bot-dot.stopped { background: var(--accent-red); }
.bot-dot.unknown { background: var(--text-dim); }
.bot-name { font-size: 13px; font-weight: 600; }
.bot-detail { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-dim); }
.action-row { display: grid; grid-template-columns: 85px 1fr 80px; gap: 8px; padding: 10px 20px; border-bottom: 1px solid var(--border-subtle); font-size: 12px; align-items: center; }
.action-time { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-dim); }
.action-desc { color: var(--text-secondary); }
.action-status { font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 600; text-align: right; }
.team-row { display: flex; align-items: center; gap: 12px; padding: 12px 20px; border-bottom: 1px solid var(--border-subtle); }
.team-avatar { width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 11px; color: #fff; flex-shrink: 0; }
.team-details { flex: 1; min-width: 0; }
.team-name { font-size: 13px; font-weight: 600; display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.team-count { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 600; }
.team-bar-bg { height: 6px; background: var(--bg-elevated); border-radius: 3px; overflow: hidden; margin-bottom: 4px; }
.team-bar-fill { height: 100%; border-radius: 3px; transition: width 0.6s ease; }
.team-sub { font-size: 10px; color: var(--text-dim); }
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
@keyframes fadeUp { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:translateY(0); } }
.stats-grid { animation: fadeUp 0.4s ease both; }
.two-col { animation: fadeUp 0.5s ease 0.1s both; }
.three-col { animation: fadeUp 0.5s ease 0.2s both; }
@media (max-width: 1200px) { .stats-grid { grid-template-columns: repeat(3, 1fr); } .two-col { grid-template-columns: 1fr; } .three-col { grid-template-columns: 1fr; } }
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
thead th { background: var(--bg-surface); color: var(--text-secondary); font-weight: 600; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.06em; padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
tbody tr { border-bottom: 1px solid var(--border); transition: background 0.1s; }
tbody tr:hover { background: var(--bg-card-hover); }
tbody td { padding: 10px 14px; white-space: nowrap; }
.doc-yes { color: var(--accent-green); }
.doc-no { color: var(--accent-red); }
.table-wrap { padding: 16px 24px; overflow-x: auto; }
.match-form { display: inline-flex; gap: 6px; align-items: center; }
.match-form input { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 6px; color: var(--text-primary); padding: 5px 10px; font-size: 0.8rem; width: 120px; }
.match-form button { background: var(--accent-blue); color: #fff; border: none; border-radius: 6px; padding: 5px 12px; font-size: 0.8rem; cursor: pointer; }
.btn-ignore { background: var(--bg-elevated) !important; color: var(--text-secondary) !important; }
.account-name a { color: var(--text-primary); text-decoration: none; display: flex; align-items: center; gap: 6px; }
.account-name a:hover { color: var(--accent-blue); text-decoration: none; }
.detail-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 200; opacity: 0; pointer-events: none; transition: opacity 0.3s; }
.detail-overlay.open { opacity: 1; pointer-events: auto; }
.detail-panel { position: fixed; top: 0; right: -460px; bottom: 0; width: 440px; background: var(--bg-surface); border-left: 1px solid var(--border); z-index: 201; transition: right 0.3s ease; overflow-y: auto; box-shadow: -8px 0 32px rgba(0,0,0,0.4); }
.detail-panel.open { right: 0; }
.panel-close { position: absolute; top: 16px; right: 16px; width: 32px; height: 32px; border-radius: 8px; background: var(--bg-card); border: 1px solid var(--border); color: var(--text-secondary); cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 18px; transition: all 0.2s; z-index: 10; }
.panel-close:hover { background: var(--bg-elevated); color: var(--text-primary); }
.panel-head { padding: 24px 20px; border-bottom: 1px solid var(--border); background: linear-gradient(180deg, var(--bg-card), var(--bg-surface)); }
.panel-head-title { font-size: 18px; font-weight: 700; margin-bottom: 4px; }
.panel-head-sub { font-size: 12px; color: var(--text-secondary); }
.panel-section { padding: 16px 20px; border-bottom: 1px solid var(--border-subtle); }
.panel-section-title { font-size: 11px; font-weight: 700; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 12px; }
.panel-field { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; font-size: 13px; }
.panel-field-label { color: var(--text-secondary); }
.panel-field-value { font-weight: 600; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
.doc-item { display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-radius: 10px; margin-bottom: 8px; transition: all 0.15s; }
.doc-item.received { background: rgba(34,197,94,0.08); border: 1px solid rgba(34,197,94,0.2); }
.doc-item.missing { background: rgba(239,68,68,0.06); border: 1px solid rgba(239,68,68,0.15); }
.doc-status { width: 28px; height: 28px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; flex-shrink: 0; }
.doc-item.received .doc-status { background: rgba(34,197,94,0.15); color: var(--accent-green); }
.doc-item.missing .doc-status { background: rgba(239,68,68,0.12); color: var(--accent-red); }
.doc-info { flex: 1; min-width: 0; }
.doc-type { font-weight: 600; font-size: 13px; }
.doc-filename { font-size: 11px; color: var(--text-secondary); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.doc-action a, .doc-action label { font-size: 11px; font-weight: 600; padding: 4px 12px; border-radius: 6px; cursor: pointer; transition: all 0.15s; }
.doc-action a { background: rgba(34,197,94,0.15); color: var(--accent-green); text-decoration: none; }
.doc-action a:hover { background: rgba(34,197,94,0.25); text-decoration: none; }
.doc-action label { background: rgba(59,130,246,0.15); color: var(--accent-blue); }
.doc-action label:hover { background: rgba(59,130,246,0.25); }
.doc-action input[type="file"] { display: none; }
.panel-loading { padding: 60px 20px; text-align: center; color: var(--text-dim); }
.highlight-flash { animation: highlightFlash 1.5s ease; }
@keyframes highlightFlash { 0% { background: rgba(59,130,246,0.15); } 100% { background: transparent; } }
.btn-dismiss { background: var(--bg-elevated); color: var(--text-secondary); border: 1px solid var(--border); border-radius: 6px; padding: 4px 10px; font-size: 11px; cursor: pointer; }
.drop-target { cursor: pointer; }
"""


# ── Sidebar, Topbar, Page wrapper ──

SIDEBAR_SVG = {
    "dashboard": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    "shipments": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><path d="M3.27 6.96L12 12.01l8.73-5.05"/><path d="M12 22.08V12"/></svg>',
    "unmatched": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>',
    "docs": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg>',
    "settings": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>',
}

SEARCH_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>'


def _sidebar(active="dashboard"):
    items = [
        ("dashboard", "/", "Dashboard"),
        ("shipments", "/shipments", "Shipments"),
        ("unmatched", "/unmatched", "Unmatched Emails"),
        ("docs", "#", "Documents"),
    ]
    nav = ""
    for key, href, title in items:
        cls = "nav-item active" if key == active else "nav-item"
        nav += f'<a class="{cls}" href="{href}" title="{title}">{SIDEBAR_SVG[key]}</a>'
    return f"""<nav class="sidebar">
  <div class="sidebar-logo"><img src="/logo.svg" alt="CSL" width="42" height="42"></div>
  <div class="sidebar-nav">{nav}</div>
  <div class="sidebar-bottom"><div class="nav-item" title="Settings">{SIDEBAR_SVG["settings"]}</div></div>
</nav>"""


def _topbar(title_main="AI", title_accent="Dispatch", search=True):
    search_html = ""
    if search:
        search_html = f'<div class="search-box">{SEARCH_SVG}<input type="text" placeholder="Search container, pro#, account..."></div>'
    return f"""<header class="topbar">
  <div class="topbar-left">
    <div class="topbar-title">{title_main} <span>{title_accent}</span></div>
    <div class="live-badge"><div class="live-dot"></div> System Live</div>
  </div>
  <div class="topbar-right">
    {search_html}
    <div class="topbar-time" id="live-clock"></div>
    <div class="avatar">JF</div>
  </div>
</header>"""


CLOCK_SCRIPT = """
function updateClock() {
  const now = new Date();
  const days = ['SUN','MON','TUE','WED','THU','FRI','SAT'];
  const months = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  const d = days[now.getDay()];
  const m = months[now.getMonth()];
  const day = now.getDate();
  let h = now.getHours();
  const ampm = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  const min = String(now.getMinutes()).padStart(2, '0');
  document.getElementById('live-clock').textContent = d + ' ' + m + ' ' + day + ' \\u00B7 ' + h + ':' + min + ' ' + ampm + ' ET';
}
updateClock();
setInterval(updateClock, 30000);
"""


def _page(title, body, script=""):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
{GOOGLE_FONTS}
<style>{DASHBOARD_CSS}</style>
</head>
<body>
{body}
<script>{CLOCK_SCRIPT}
{script}
</script>
</body>
</html>"""


# ── Dashboard HTML builders ──

def _build_stats_html(s):
    total = s["active"] + s["completed_today"]
    pct = round(s["on_schedule"] / s["active"] * 100, 1) if s["active"] else 0
    return f"""<div class="stats-grid">
  <div class="stat-card blue"><div class="stat-label">Active Shipments</div><div class="stat-value">{s['active']}</div><div class="stat-sub">Across {len(sheet_cache.accounts)} accounts</div></div>
  <div class="stat-card green"><div class="stat-label">On Schedule</div><div class="stat-value">{s['on_schedule']}</div><div class="stat-sub">{pct}% of active loads</div></div>
  <div class="stat-card amber"><div class="stat-label">ETA Changed</div><div class="stat-value">{s['eta_changed']}</div><div class="stat-sub">Updated today</div></div>
  <div class="stat-card red"><div class="stat-label">At Risk</div><div class="stat-value">{s['at_risk']}</div><div class="stat-sub">LFD soon or no data</div></div>
  <div class="stat-card purple"><div class="stat-label">Completed Today</div><div class="stat-value">{s['completed_today']}</div><div class="stat-sub">{total} total tracked</div></div>
</div>"""


def _build_alerts_html(alerts):
    if not alerts:
        items = '<div style="padding:40px;text-align:center;color:var(--text-dim);">All shipments on schedule</div>'
    else:
        items = ""
        for a in alerts:
            move = a.get("move", "")
            move_tag = "import" if "import" in move.lower() else ("export" if "export" in move.lower() else ("ftl" if "ftl" in move.lower() else ""))
            tags = f'<span class="alert-tag efj">{a["efj"]}</span>' if a.get("efj") else ""
            if move_tag:
                tags += f' <span class="alert-tag {move_tag}">{move}</span>'
            if a.get("rep") and a["rep"] != "Unassigned":
                tags += f' <span class="alert-tag rep">{a["rep"]}</span>'
            efj_attr = f' data-efj="{a["efj"]}"' if a.get("efj") else ""
            acct_attr = f' data-account="{a.get("account", "")}"'
            move_attr = f' data-move="{move}"' if move else ""
            items += f"""<div class="alert-item"{efj_attr}{move_attr}{acct_attr} onclick="openPanel('{a.get('efj','')}')" title="Click for details">
  <div class="alert-icon {a['type']}">{a['icon']}</div>
  <div class="alert-body">
    <div class="alert-title-row"><span class="alert-name">{a['title']}</span></div>
    <div class="alert-desc">{a['desc']}</div>
    <div class="alert-tags">{tags}</div>
  </div>
</div>"""

    badge = f'<span class="panel-badge">{len(alerts)} new</span>' if alerts else '<span class="panel-badge green">0</span>'
    filters = '<div class="filter-tabs"><button class="filter-tab active">All</button><button class="filter-tab">Imports</button><button class="filter-tab">Exports</button><button class="filter-tab">FTL</button><button class="filter-tab">Boviet</button><button class="filter-tab">Tolead</button></div>'

    return f"""<div class="panel">
  <div class="panel-header">
    <div class="panel-title">Live Alerts {badge}</div>
    {filters}
  </div>
  <div class="alert-list">{items}</div>
</div>"""


def _build_accounts_html(accounts):
    rows = ""
    for a in accounts:
        name = a["name"]
        dot_cls = "alert" if a["alerts"] > 2 else ("warn" if a["alerts"] > 0 else "ok")
        alert_style = f' style="color:var(--accent-red)"' if a["alerts"] else ""
        done_style = f' style="color:var(--accent-green)"' if a["done"] else ""
        rows += f"""<div class="account-row">
  <span class="account-name"><a href="/shipments?account={name}"><span class="account-dot {dot_cls}"></span>{name}</a></span>
  <span class="cell-count">{a['active']}</span>
  <span class="cell-count"{alert_style}>{a['alerts']}</span>
  <span class="cell-count"{done_style}>{a['done']}</span>
</div>"""

    toggle = '<div class="filter-tabs"><button class="filter-tab active">Active</button><button class="filter-tab">All</button></div>'
    return f"""<div class="panel">
  <div class="panel-header"><div class="panel-title">Account Overview</div>{toggle}</div>
  <div class="account-list">
    <div class="account-row header">
      <span>Account</span><span style="text-align:center">Active</span><span style="text-align:center">Alerts</span><span style="text-align:center">Done</span>
    </div>
    {rows}
  </div>
</div>"""


def _build_bots_html(bots):
    rows = ""
    for b in bots:
        status = b["status"]
        dot = "running" if status == "active" else ("stopped" if status in ("inactive", "failed") else "unknown")
        detail = f"Last run: {b['last_run']}"
        if b["next_run"]:
            detail += f" \u00B7 Next: {b['next_run']}"
        rows += f"""<div class="bot-row">
  <div class="bot-info">
    <div class="bot-dot {dot}"></div>
    <div><div class="bot-name">{b['name']}</div><div class="bot-detail">{detail}</div></div>
  </div>
</div>"""

    return f"""<div class="panel">
  <div class="panel-header"><div class="panel-title">Bot Status</div></div>
  {rows}
</div>"""


def _build_actions_html(actions):
    if not actions:
        rows = '<div style="padding:20px;text-align:center;color:var(--text-dim);">No recent actions</div>'
    else:
        header = '<div class="action-row" style="border-bottom:1px solid var(--border);"><span class="action-time" style="color:var(--text-dim);font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:0.06em;">Time</span><span style="color:var(--text-dim);font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:0.06em;">Action</span><span style="text-align:right;color:var(--text-dim);font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:0.06em;">Status</span></div>'
        rows = header
        color_map = {"green": "var(--accent-green)", "blue": "var(--accent-blue)", "cyan": "var(--accent-cyan)", "amber": "var(--accent-amber)", "purple": "var(--accent-purple)"}
        for a in actions:
            c = color_map.get(a["color"], "var(--text-dim)")
            rows += f"""<div class="action-row">
  <span class="action-time">{a['time']}</span>
  <span class="action-desc">{a['action']}</span>
  <span class="action-status" style="color:{c};">\u2713 {a['status']}</span>
</div>"""

    return f"""<div class="panel">
  <div class="panel-header"><div class="panel-title">Recent Bot Actions</div></div>
  {rows}
</div>"""


def _build_team_html(team_data):
    max_loads = max((d["loads"] for d in team_data.values()), default=1) or 1
    total = sum(d["loads"] for d in team_data.values())
    rows = ""
    for rep in sorted(team_data, key=lambda r: team_data[r]["loads"], reverse=True):
        d = team_data[rep]
        info = REP_STYLES.get(rep, {"color": "var(--text-dim)", "bg": "linear-gradient(135deg,#4a5568,#374151)", "initials": "??"})
        pct = int((d["loads"] / max_loads) * 100)
        acct_list = ", ".join(d["accounts"][:5])
        sub = f"{d['at_risk']} at risk \u00B7 {acct_list}"
        rows += f"""<div class="team-row">
  <div class="team-avatar" style="background:{info['bg']}">{info['initials']}</div>
  <div class="team-details">
    <div class="team-name"><span><a href="/rep/{rep}" style="color:var(--text-primary);text-decoration:none;" onmouseover="this.style.color='{info['color']}'" onmouseout="this.style.color='var(--text-primary)'">{rep}</a></span><span class="team-count" style="color:{info['color']}">{d['loads']} Loads</span></div>
    <div class="team-bar-bg"><div class="team-bar-fill" style="width:{pct}%;background:{info['color']}"></div></div>
    <div class="team-sub">{sub}</div>
  </div>
</div>"""

    return f"""<div class="panel">
  <div class="panel-header">
    <div class="panel-title">Team Load Distribution</div>
    <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-dim);">{total} total</span>
  </div>
  {rows}
</div>"""


# ── AI extraction helper (used by directory routes) ──

def _extract_with_claude(content):
    """Call Claude API with content blocks and parse JSON response."""
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": content}],
    )
    text_out = resp.content[0].text.strip()
    if text_out.startswith("```"):
        text_out = text_out.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(text_out)


# ── Quick Parse helper ──

def _ai_quick_parse(text: str) -> dict:
    """Extract freight details from freeform text using Claude."""
    api_key = os.getenv("ANTHROPIC_API_KEY") or config.ANTHROPIC_API_KEY
    if not api_key:
        env_path = "/root/csl-bot/.env"
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        return {}

    prompt = f"""Extract freight logistics details from this text. Return ONLY valid JSON — no markdown, no explanation.

TEXT:
{text[:3000]}

Return exactly this structure (use null for missing fields):
{{
  "efj_number": "<EFJ##### or EFJ####### format, null if not found>",
  "rate": <total dollar amount as number, null if not found>,
  "container_number": "<ISO container like MSKU1234567 or null>",
  "carrier": "<trucking company / carrier name or null>",
  "confidence": "<high|medium|low>"
}}

Rules:
- efj_number: look for patterns like EFJ107405, EFJ-107405, or standalone 6-7 digit job numbers preceded by EFJ
- rate: extract all-in flat rate (ignore per-mile rates unless that is the only option)
- container_number: 4 letters + 7 digits format (MAEU1234567, etc.)
- carrier: the trucking company name, not the shipping line
- confidence: high if multiple fields found with clear formatting, low if guessing"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text_out = resp.content[0].text.strip()
        if text_out.startswith("```"):
            text_out = text_out.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(text_out)
        out = {}
        if data.get("efj_number"):
            out["efj_number"] = str(data["efj_number"]).strip()
        if data.get("rate") is not None:
            try:
                out["rate"] = float(data["rate"])
            except (TypeError, ValueError):
                pass
        for f in ("container_number", "carrier", "confidence"):
            if data.get(f):
                out[f] = str(data[f]).strip()
        return out
    except Exception as e:
        log.debug("Quick parse extraction failed: %s", e)
        return {}


# ── Completed-loads cache (used by _archive_shipment_on_close) ──
_completed_cache: dict = {"ts": 0, "data": []}


def _archive_shipment_on_close(efj: str):
    """Archive a shipment in PG + Google Sheet when its unbilled order is closed."""
    import sys as _sys
    _csl_bot_dir = "/root/csl-bot"
    if _csl_bot_dir not in _sys.path:
        _sys.path.insert(0, _csl_bot_dir)
    # PG archive
    try:
        from csl_pg_writer import pg_archive_shipment
        pg_archive_shipment(efj)
        log.info("Unbilled close → PG archived %s", efj)
    except Exception as e:
        log.warning("Unbilled close → PG archive failed for %s: %s", efj, e)
    # Sheet archive (fire-and-forget)
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT account, rep FROM shipments WHERE efj = %s", (efj,))
            ship = cur.fetchone()
        if ship and ship.get("account"):
            from csl_sheet_writer import sheet_archive_row
            sheet_archive_row(efj, ship["account"], ship.get("rep"))
    except Exception as e:
        log.warning("Unbilled close → sheet archive failed for %s: %s", efj, e)
    # Invalidate completed cache
    _completed_cache["ts"] = 0
