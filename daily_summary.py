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
import re
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

from playwright.sync_api import TimeoutError as PlaywrightTimeout

load_dotenv()


# ── Date filter: only scrape loads with pickup/delivery this week ──
def _is_this_week(date_str):
    """Return True if date_str falls within the current Mon-Sun week."""
    if not date_str or not date_str.strip():
        return False
    import re
    from datetime import datetime, timedelta
    s = date_str.strip()
    today = datetime.now()
    # Monday of this week
    week_start = today - timedelta(days=today.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    # Sunday end of this week
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    # Try common date formats
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m/%d", "%Y-%m-%d", "%m/%d/%Y %H:%M", "%m/%d/%y %H:%M"):
        try:
            dt = datetime.strptime(s.split()[0] if " " in s else s, fmt.split()[0] if " " in fmt else fmt)
            # If no year parsed (m/d format), assume current year
            if dt.year == 1900:
                dt = dt.replace(year=today.year)
            return week_start <= dt <= week_end
        except ValueError:
            continue
    return False

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



# ── Macropoint page parser (self-contained, restored from ftl_monitor backup) ──
DEBUG = False
_DATE_RE = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},?\s+\d{4}\b",
    re.I,
)

_DATETIME_RE = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?\s*[AP]M)(?:\s*[A-Z]{2,3})?",
    re.I,
)

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5,  "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _to_mmdd(date_str: str) -> str | None:
    s = date_str.strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/\d{2,4}", s)
    if m:
        return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.match(r"\d{4}-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+\d{4}", s, re.I)
    if m:
        mo = _MONTH_MAP.get(m.group(1)[:3].lower())
        if mo:
            return f"{mo:02d}-{int(m.group(2)):02d}"
    return None


def _parse_planned_dt(dt_str: str) -> datetime | None:
    s = re.sub(r"\s+[A-Z]{2,3}$", "", dt_str.strip())
    for fmt in ["%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M"]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ── Macropoint page parser ───────────────────────────────────────────────────────
def _split_stops(text: str) -> tuple[str, str]:
    # Try "Stop Order" table header first — split after Stop 1 / Stop 2 content
    s1 = re.search(r"\bStop\s+Order\b", text, re.I)
    if s1:
        after_header = text[s1.start():]
        # Find the standalone "1" and "2" that mark stop sections after the header
        stops = list(re.finditer(r"(?:^|\n)\s*([12])\s*\n", after_header))
        stop1_pos = None
        stop2_pos = None
        for m in stops:
            if m.group(1) == "1" and stop1_pos is None:
                stop1_pos = s1.start() + m.start()
            elif m.group(1) == "2" and stop1_pos is not None and stop2_pos is None:
                stop2_pos = s1.start() + m.start()
        if stop1_pos is not None and stop2_pos is not None:
            return text[stop1_pos:stop2_pos], text[stop2_pos:]
        if stop1_pos is not None:
            return text[stop1_pos:], ""
    # Fallback: look for "Stop 1" / "Stop 2" literally
    s1 = re.search(r"\bStop\s*1\b", text, re.I)
    s2 = re.search(r"\bStop\s*2\b", text, re.I)
    if s1:
        if s2 and s2.start() > s1.start():
            return text[s1.start():s2.start()], text[s2.start():]
        return text[s1.start():], ""
    return "", ""


def _find_event_date(section: str, event: str) -> str | None:
    # Only match confirmed events with @ timestamp:
    # "Arrived @ 02/24 13:12 - ET" or "Departed @ 02/24 07:40 - CT"
    # Do NOT match bare "Arrived"/"Departed" toggle labels near unrelated dates.
    m = re.search(
        rf"\b{re.escape(event)}\s*@\s*(\d{{1,2}}/\d{{1,2}})",
        section, re.I,
    )
    if m:
        parts = m.group(1).split("/")
        return f"{int(parts[0]):02d}-{int(parts[1]):02d}"

    lines = [l.strip() for l in section.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        if re.search(rf"\b{re.escape(event)}\s*@", line, re.I):
            m = re.search(r"(\d{1,2})/(\d{1,2})", line)
            if m:
                return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def _find_event_timestamp(section: str, event: str) -> str | None:
    """Extract full timestamp like '02/25 10:27 CT' for an Arrived/Departed event."""
    m = re.search(
        rf"\b{re.escape(event)}\s*@\s*(\d{{1,2}}/\d{{1,2}})\s+(\d{{1,2}}:\d{{2}})\s*-\s*([A-Z]{{2,3}})",
        section, re.I,
    )
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}"
    return None


def _find_planned_start(section: str) -> str | None:
    m = re.search(
        r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}:\d{2})\s*-\s*\d{1,2}:\d{2}",
        section,
    )
    if m:
        return f"{int(m.group(1)):02d}-{int(m.group(2)):02d} {m.group(3)}"
    return None


def _find_planned_dt(section: str) -> datetime | None:
    lines = [l.strip() for l in section.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        if re.search(r"\bPlanned\b", line, re.I):
            context = " ".join(lines[i:i + 3])
            m = _DATETIME_RE.search(context)
            if m:
                return _parse_planned_dt(f"{m.group(1)} {m.group(2)}")
    return None


def _has_events(section: str) -> bool:
    if not section:
        return False
    if re.search(r"\b(Arrived|Departed)\s*@\s*\d{1,2}/\d{1,2}\b", section, re.I):
        return True
    lines = [l.strip() for l in section.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        if re.search(r"\b(Arrived|Departed)\b", line, re.I):
            context = " ".join(lines[i:i + 3])
            if _DATE_RE.search(context):
                return True
    return False



def _extract_stop_eta(section: str) -> str | None:
    """Extract ETA + behind/ahead info from a stop section.
    Returns e.g. 'ETA: 2/25/2026 11:11 PM CT — 20.7 Hours BEHIND' or None."""
    parts = []
    # Look for "X.X Hours BEHIND" or "X.X Hours AHEAD"
    m_behind = re.search(
        r"(\d+\.?\d*)\s+Hours?\s+(BEHIND|AHEAD)",
        section, re.I,
    )
    if m_behind:
        parts.append(f"{m_behind.group(1)} Hours {m_behind.group(2).upper()}")
    # Look for "ETA: M/D/YYYY H:MM AM/PM TZ"
    m_eta = re.search(
        r"ETA:\s*(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M\s*[A-Z]{1,3})",
        section, re.I,
    )
    if m_eta:
        parts.append(f"ETA: {m_eta.group(1).strip()}")
    return " — ".join(parts) if parts else None


def _parse_macropoint(
    text: str,
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    stop1_text, stop2_text = _split_stops(text)
    stop1_arrived       = _find_event_date(stop1_text,   "Arrived")  if stop1_text else None
    stop1_departed      = _find_event_date(stop1_text,   "Departed") if stop1_text else None
    stop2_arrived       = _find_event_date(stop2_text,   "Arrived")  if stop2_text else None
    stop2_departed      = _find_event_date(stop2_text,   "Departed") if stop2_text else None
    stop1_planned_start = _find_planned_start(stop1_text)             if stop1_text else None
    stop2_planned_start = _find_planned_start(stop2_text)             if stop2_text else None

    # Full timestamps for email alerts (e.g. '02/25 10:27 CT')
    # ETAs for stops that haven't been timestamped yet
    stop1_eta = _extract_stop_eta(stop1_text) if stop1_text and not stop1_arrived else None
    stop2_eta = _extract_stop_eta(stop2_text) if stop2_text and not stop2_arrived else None
    stop_times = {
        "stop1_arrived":  _find_event_timestamp(stop1_text, "Arrived")  if stop1_text else None,
        "stop1_departed": _find_event_timestamp(stop1_text, "Departed") if stop1_text else None,
        "stop2_arrived":  _find_event_timestamp(stop2_text, "Arrived")  if stop2_text else None,
        "stop2_departed": _find_event_timestamp(stop2_text, "Departed") if stop2_text else None,
        "stop1_eta":      stop1_eta,
        "stop2_eta":      stop2_eta,
    }

    # Detect "CAN'T MAKE IT" — only alert if the stop has NOT been timestamped yet
    _cmi_parts = []
    if stop1_text and not stop1_arrived and re.search(r"CAN['’]?T\s+MAKE\s+IT", stop1_text, re.I):
        eta1 = _extract_stop_eta(stop1_text)
        _cmi_parts.append("Driver Won't Make PU in Time" + (f" [{eta1}]" if eta1 else ""))
    if stop2_text and not stop2_arrived and re.search(r"CAN['’]?T\s+MAKE\s+IT", stop2_text, re.I):
        eta2 = _extract_stop_eta(stop2_text)
        _cmi_parts.append("Driver Won't Make Delivery in Time" + (f" [{eta2}]" if eta2 else ""))
    cant_make_it = " & ".join(_cmi_parts) if _cmi_parts else None

    # Extract Macropoint Load ID
    load_id_match = re.search(r"Load\s+Id\s*\n\s*(\S+)", text)
    if not load_id_match:
        load_id_match = re.search(r"\bLoad\s+([A-Z0-9][\w\-]+\d)", text)
    mp_load_id = load_id_match.group(1) if load_id_match else None

    # Statuses we IGNORE — no alert needed
    IGNORE_STATUSES = {"ready to track", "tracking now"}
    text_lower = text.lower()

    # ── FraudGuard / phone issues ─────────────────────────────────────────
    if re.search(
        r"FraudGuard"
        r"|phone\s*(unresponsive|unreachable|not\s*respond)"
        r"|unable\s+to\s+(locate|reach|contact).{0,20}(driver|phone)"
        r"|driver.{0,20}(unreachable|unresponsive)",
        text, re.I,
    ):
        return "Driver Phone Unresponsive", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start, mp_load_id, cant_make_it, stop_times

    # ── Tracking completed = Delivered ────────────────────────────────────
    if re.search(r"Tracking\s*Completed\s*Successfully", text, re.I):
        return "Delivered", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start, mp_load_id, cant_make_it, stop_times

    # ── Stop 2 Departed = left delivery ───────────────────────────────────
    if stop2_departed:
        return "Departed Delivery", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start, mp_load_id, cant_make_it, stop_times

    # ── Stop 2 Arrived = at delivery ──────────────────────────────────────
    if stop2_arrived:
        return "Arrived at Delivery", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start, mp_load_id, cant_make_it, stop_times

    # ── Stop 1 Departed = left pickup, en route ───────────────────────────
    if stop1_departed:
        return "Departed Pickup - En Route", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start, mp_load_id, cant_make_it, stop_times

    # ── Stop 1 Arrived = at pickup ────────────────────────────────────────
    if stop1_arrived:
        return "Driver Arrived at Pickup", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start, mp_load_id, cant_make_it, stop_times

    # ── Running late — past planned pickup time, no arrival ───────────────
    planned_dt = _find_planned_dt(stop1_text)
    if planned_dt:
        now = datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
        if now > planned_dt:
            return "Running Late", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start, mp_load_id, cant_make_it, stop_times

    # ── Tracking behind / falling behind schedule ─────────────────────────
    if re.search(r"(tracking\s+behind|behind\s+schedule|falling\s+behind)", text, re.I):
        return "Tracking Behind Schedule", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start, mp_load_id, cant_make_it, stop_times

    # ── No events yet = waiting for update ────────────────────────────────
    if stop1_text and not _has_events(stop1_text) and not _has_events(stop2_text):
        # Check if this is just "Ready to Track" or "Tracking Now" — skip those
        if any(s in text_lower for s in IGNORE_STATUSES):
            return None, stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start, mp_load_id, cant_make_it, stop_times
        return "Tracking Waiting for Update", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start, mp_load_id, cant_make_it, stop_times

    return None, stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start, mp_load_id, cant_make_it, stop_times


# ── Playwright scraper ───────────────────────────────────────────────────────────

def _load_mp_cookies():
    """Load Macropoint portal session cookies, or None if unavailable."""
    try:
        with open(MP_COOKIES_FILE) as f:
            cookies = json.load(f)
        # Fix expires: Playwright rejects large microsecond timestamps
        for c in cookies:
            exp = c.get("expires", -1)
            if isinstance(exp, (int, float)) and exp > 1e12:
                c["expires"] = int(exp / 1e6)
            elif exp == 0 or exp is None:
                c["expires"] = -1
        return cookies
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def scrape_driver_phone(browser, mp_load_id: str, load_ref: str, mp_cookies: list = None) -> str | None:
    """
    Open the Macropoint portal shipment detail page and extract
    the driver's tracking phone number.
    Returns the phone string or None.
    """
    if not mp_cookies or not mp_load_id:
        return None

    page = browser.new_page()
    try:
        ctx = page.context
        ctx.add_cookies(mp_cookies)

        # Try the shipment search/detail page
        # Macropoint portal shipment URLs: /shipments or search by load number
        search_url = f"{MP_PORTAL_URL}/shipments?search={load_ref}"
        page.goto(search_url, wait_until="domcontentloaded", timeout=20_000)
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(2000)

        # Check if session expired (redirected to login)
        if "auth.gln.com" in page.url or "login" in page.url.lower():
            print("    MP portal session expired — skipping driver phone lookup")
            return None

        text = page.inner_text("body")

        # Try to find phone number patterns in the shipment detail
        # Macropoint shows tracking phone near "Phone" or "Tracking Phone" labels
        phone_patterns = [
            # "Tracking Phone\n(443) 555-1234" or "Phone\n+14435551234"
            r"(?:Tracking\s+)?Phone[:\s]*\n?\s*(\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})",
            # Generic US phone in the page
            r"(\(\d{3}\)\s*\d{3}[-.]?\d{4})",
            r"(\d{3}[-.]?\d{3}[-.]?\d{4})",
        ]

        # First try clicking into the shipment detail if we're on a list page
        try:
            # Click the first shipment row/link that matches our load
            link = page.locator(f'a:has-text("{load_ref}"), tr:has-text("{load_ref}")').first
            if link.is_visible(timeout=3000):
                link.click(timeout=5000)
                page.wait_for_load_state("networkidle", timeout=10_000)
                page.wait_for_timeout(2000)
                text = page.inner_text("body")
        except Exception:
            pass  # Already on detail page or couldn't click — use current text

        # Extract phone numbers from the page
        found_phones = []
        for pattern in phone_patterns:
            matches = re.findall(pattern, text, re.I)
            found_phones.extend(matches)

        if not found_phones:
            return None

        # Filter out the Evans dispatch phone (we don't want that)
        dispatch_digits = "4437614954"
        for phone in found_phones:
            digits = re.sub(r"\D", "", phone)
            if digits.startswith("1") and len(digits) == 11:
                digits = digits[1:]
            if digits != dispatch_digits and len(digits) == 10:
                # Format nicely
                formatted = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
                print(f"    Driver phone found: {formatted}")
                return formatted

        return None

    except PlaywrightTimeout:
        print("    MP portal timeout — skipping driver phone")
        return None
    except Exception as exc:
        print(f"    MP portal error: {exc}")
        return None
    finally:
        page.close()


def scrape_macropoint(
    browser, url: str, mp_cookies: list = None
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    page = browser.new_page()
    try:
        # Inject authenticated cookies — Macropoint now requires auth
        if mp_cookies:
            page.context.add_cookies(mp_cookies)

        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except PlaywrightTimeout:
            pass

        # Blazor WASM Control Tower needs time to render tracking data
        # Wait up to 20s for tracking content to appear
        for _wait in range(10):
            page.wait_for_timeout(2_000)
            text = page.inner_text("body")
            if any(kw in text for kw in ["Arrived", "Departed", "In Transit",
                                          "Stop Order", "Tracking Completed",
                                          "FraudGuard", "Ready To Track",
                                          "Tracking Now", "Load Status"]):
                break
        else:
            text = page.inner_text("body")
    except PlaywrightTimeout as exc:
        print(f"    TIMEOUT: {exc}")
        return None, None, None, None, None, None, None, {}
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return None, None, None, None, None, None, None, {}
    finally:
        page.close()

    if DEBUG:
        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", url.rstrip("/").split("/")[-1])
        debug_path = f"/tmp/mp_debug_{safe_name}.txt"
        try:
            with open(debug_path, "w") as f:
                f.write(text)
            print(f"    DEBUG: inner_text saved → {debug_path}")
        except Exception as exc:
            print(f"    DEBUG WARNING: could not save debug file: {exc}")

    return _parse_macropoint(text)



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


def build_summary_body(sheet_label, tab_name, summaries, skipped=0, needs_cover_html="", needs_cover_count=0):
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
    sections += needs_cover_html

    # Status ribbon
    ribbon_parts = []
    if on_time:
        ribbon_parts.append(f'<span style="color:#2e7d32;font-weight:bold;">{len(on_time)} On Time</span>')
    if behind:
        ribbon_parts.append(f'<span style="color:#c62828;font-weight:bold;">{len(behind)} Behind</span>')
    if needs_cover_count:
        ribbon_parts.append(f'<span style="color:#e65100;font-weight:bold;">{needs_cover_count} Needs Cover</span>')
    if tracking:
        ribbon_parts.append(f'<span style="color:#6a1b9a;font-weight:bold;">{len(tracking)} Tracking Issues</span>')
    if skipped:
        ribbon_parts.append(f'<span style="color:#ff8f00;font-weight:bold;">{skipped} Skipped</span>')
    ribbon_html = ' &nbsp;|&nbsp; '.join(ribbon_parts) if ribbon_parts else '&mdash;'

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
        f'<p style="color:#888;font-size:12px;margin:0 0 8px 0;">{now}</p>'
        f'<div style="background:#f5f5f5;border-left:4px solid #1565c0;padding:8px 14px;'
        f'border-radius:0 6px 6px 0;font-size:13px;margin-bottom:12px;">{ribbon_html}</div>'
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

        # Filter to loads picking up or delivering this week
        before = len(entries)
        entries = [e for e in entries if _is_this_week(e.get("pickup")) or _is_this_week(e.get("delivery"))]
        if before > len(entries):
            print(f"    [{tab_name}] Filtered {before} -> {len(entries)} (this week only)")

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

        # Filter to loads picking up or delivering this week
        before = len(entries)
        entries = [e for e in entries if _is_this_week(e.get("pickup")) or _is_this_week(e.get("delivery")) or _is_this_week(e.get("dest"))]
        if before > len(entries):
            print(f"    [{hub_name}/{tab}] Filtered {before} -> {len(entries)} (this week only)")

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

        if mp_status and mp_status.lower() in {"delivered", "completed", "tracking completed"}:
            print(f"      SKIP DELIVERED [{item['efj']}]: mp_status={mp_status}")
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
