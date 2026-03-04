#!/usr/bin/env python3
"""
ftl_monitor.py — polls all account tabs every 30 minutes for FTL rows,
uses Playwright to scrape Macropoint tracking status, sends email alerts
routed to the rep assigned to each account tab, and writes pickup/delivery
dates to the sheet.
"""
import json

# ── Unresponsive driver state tracking ──
UNRESPONSIVE_STATE_FILE = "/root/csl-bot/unresponsive_state.json"

def load_unresponsive_state():
    try:
        with open(UNRESPONSIVE_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_unresponsive_state(state):
    tmp = UNRESPONSIVE_STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, UNRESPONSIVE_STATE_FILE)

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
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

load_dotenv()


def _retry_on_quota(func, *args, max_retries=3, **kwargs):
    """Retry a function call on Google Sheets 429 quota errors."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if "429" in str(exc) and attempt < max_retries - 1:
                wait = 60 * (attempt + 1)
                print(f"    QUOTA HIT (429) — waiting {wait}s before retry {attempt+2}/{max_retries}...")
                time.sleep(wait)
            else:
                raise
    return None

# ── Config ──────────────────────────────────────────────────────────────────────
SHEET_ID         = os.environ["SHEET_ID"]
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "/root/csl-credentials.json")
SENT_ALERTS_FILE = "/root/csl-bot/ftl_sent_alerts.json"
TRACKING_CACHE_FILE = "/root/csl-bot/ftl_tracking_cache.json"
MP_COOKIES_FILE    = "/root/csl-bot/mp_cookies.json"

# Only send email alerts for loads with pickup on or after this date.
# Prevents stale notifications after scraper outages.
ALERT_CUTOFF_DATE  = "2026-03-01"
MP_PORTAL_URL      = "https://visibility.macropoint.com"
POLL_INTERVAL    = 30 * 60  # seconds
DEBUG            = False    # save Macropoint inner_text to /tmp/mp_debug_[load_num].txt

# ── SMTP / email ─────────────────────────────────────────────────────────────────
SMTP_HOST      = "smtp.gmail.com"
SMTP_PORT      = 587
SMTP_USER      = os.environ["SMTP_USER"]
SMTP_PASSWORD  = os.environ["SMTP_PASSWORD"]
EMAIL_CC       = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")
EMAIL_FALLBACK = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")

# ── Tab config ───────────────────────────────────────────────────────────────────
ACCOUNT_LOOKUP_TAB = "Account Rep"
SKIP_TABS = {
    "Sheet 4", "DTCELNJW", "Account Rep", "Completed Eli", "Completed Radka", "Completed John F",
}

# Columns — 0-based (list access from get_all_values)
COL_EFJ        = 0   # A — EFJ reference number
COL_MOVE_TYPE  = 1   # B — filter: 'FTL'
COL_TRACKING   = 2   # C — Macropoint URL (hyperlink); display text = Container/Load#
COL_LOAD       = 2   # C — Container/Load# (display text of same cell)
COL_PICKUP_R   = 10  # K — existing pickup date (0-based)
COL_DELIVERY_R = 11  # L — existing delivery date (0-based)
COL_STATUS_R   = 12  # M — existing status value (0-based)
COL_NOTES_R    = 14  # O — existing bot notes

# Columns — 1-based (gspread write calls)
GCOL_PICKUP    = 11  # K
GCOL_DELIVERY  = 12  # L
GCOL_STATUS    = 13  # M
GCOL_NOTES     = 15  # O

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ── Date / datetime helpers ──────────────────────────────────────────────────────
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


# ── Google Sheets ────────────────────────────────────────────────────────────────
def _load_credentials():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds


def _get_hyperlinks(creds, tab_name: str) -> list:
    """Fetch raw hyperlink URLs via Sheets API v4 for the given tab."""
    api_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
        f"?ranges={requests.utils.quote(tab_name)}"
        f"&fields=sheets.data.rowData.values.hyperlink"
        f"&includeGridData=true"
    )
    resp = requests.get(
        api_url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=20
    )
    resp.raise_for_status()
    result = []
    for row_data in resp.json()["sheets"][0]["data"][0].get("rowData", []):
        result.append([cell.get("hyperlink") for cell in row_data.get("values", [])])
    return result


def load_account_lookup(creds) -> dict:
    """Read 'Account Rep' tab → dict mapping account_name → {rep, email}."""
    try:
        gc   = gspread.authorize(creds)
        ws   = gc.open_by_key(SHEET_ID).worksheet(ACCOUNT_LOOKUP_TAB)
        rows = ws.get_all_values()
        lookup = {}
        for row in rows:
            if len(row) >= 3 and row[0].strip():
                account = row[0].strip()
                rep     = row[1].strip()
                email   = row[2].strip()
                if account and email:
                    lookup[account] = {"rep": rep, "email": email}
        print(f"  Loaded {len(lookup)} account(s) from '{ACCOUNT_LOOKUP_TAB}'")
        return lookup
    except Exception as exc:
        print(f"  WARNING: Could not load '{ACCOUNT_LOOKUP_TAB}' tab: {exc}")
        return {}


def get_account_tabs(sheet, account_lookup: dict) -> list:
    """Return tab titles that are in account_lookup and not in SKIP_TABS."""
    all_tabs = [ws.title for ws in sheet.worksheets()]
    return [t for t in all_tabs if t not in SKIP_TABS and t in account_lookup]


def get_ftl_rows(creds, gc, tab_name: str, sent_alerts: dict = None, account_lookup: dict = None):
    """
    Returns (ws, ftl_rows) for the given tab.
    ftl_rows contains ALL rows where Col B = 'FTL'.
    """
    ws       = gc.open_by_key(SHEET_ID).worksheet(tab_name)
    all_rows = ws.get_all_values()
    time.sleep(1)  # avoid Sheets quota burst
    links    = _get_hyperlinks(creds, tab_name)

    if sent_alerts is None:
        sent_alerts = {}
    if account_lookup is None:
        account_lookup = {}

    ftl_rows = []
    for i, row in enumerate(all_rows):
        if len(row) <= COL_MOVE_TYPE:
            continue
        if row[COL_MOVE_TYPE].strip().upper() != "FTL":
            continue

        efj      = row[COL_EFJ].strip()  if len(row) > COL_EFJ  else ""
        load_num = row[COL_LOAD].strip() if len(row) > COL_LOAD else ""
        if not efj:
            pro_key = f"pro_alert:{tab_name}:{load_num}:{row[COL_TRACKING].strip() if len(row)>COL_TRACKING else i}"
            last    = sent_alerts.get(pro_key, "")
            today   = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
            if last != today:
                send_pro_alert(list(row), tab_name, account_lookup)
                sent_alerts[pro_key] = today
                save_sent_alerts(sent_alerts)
            continue

        link_row = links[i] if i < len(links) else []
        url = (
            (link_row[COL_TRACKING] if len(link_row) > COL_TRACKING else None)
            or (row[COL_TRACKING].strip() if len(row) > COL_TRACKING else "")
        )
        if not url:
            continue

        existing_pickup   = row[COL_PICKUP_R].strip()   if len(row) > COL_PICKUP_R   else ""
        existing_delivery = row[COL_DELIVERY_R].strip() if len(row) > COL_DELIVERY_R else ""
        existing_status   = row[COL_STATUS_R].strip()   if len(row) > COL_STATUS_R   else ""
        existing_notes    = row[COL_NOTES_R].strip()    if len(row) > COL_NOTES_R    else ""

        ftl_rows.append({
            "sheet_row":         i + 1,
            "efj":               efj,
            "load_num":          load_num,
            "url":               url,
            "key":               f"{efj}|{load_num}",
            "tab_name":          tab_name,
            "existing_pickup":   existing_pickup,
            "existing_delivery": existing_delivery,
            "existing_status":   existing_status,
            "existing_notes":    existing_notes,
            "row_data":          list(row),
        })

    return ws, ftl_rows


# ── Sheet write helpers ──────────────────────────────────────────────────────────
def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _build_note(existing_notes: str, new_part: str) -> str:
    today    = datetime.now(ZoneInfo("America/New_York")).strftime("%m-%d")
    base     = re.sub(r"\s*—\s*updated\s*\d{2}-\d{2}\s*$", "", existing_notes).strip()
    combined = f"{base}, {new_part}".lstrip(", ") if base else new_part
    return f"{combined} — updated {today}"


# ── Alert dedup ──────────────────────────────────────────────────────────────────
def load_sent_alerts() -> dict:
    if os.path.exists(SENT_ALERTS_FILE):
        try:
            with open(SENT_ALERTS_FILE) as f:
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


def already_sent(sent: dict, key: str, status: str) -> bool:
    return status in sent.get(key, [])


def mark_sent(sent: dict, key: str, status: str):
    sent.setdefault(key, [])
    if status not in sent[key]:
        sent[key].append(status)



# ── Tracking cache (for dashboard) ──────────────────────────────────────
def load_tracking_cache() -> dict:
    """Load the tracking cache from disk."""
    try:
        with open(TRACKING_CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_tracking_cache(cache: dict):
    """Atomically write tracking cache to disk."""
    tmp = TRACKING_CACHE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, TRACKING_CACHE_FILE)


def update_tracking_cache(efj: str, load_num: str, status, mp_load_id,
                          cant_make_it, stop_times: dict, url: str, cache: dict,
                          driver_phone: str = None, mp_status=None):
    """Update a single load entry in the tracking cache dict."""
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")
    cache[efj] = {
        "efj": efj,
        "load_num": load_num,
        "status": status,
        "mp_load_id": mp_load_id,
        "cant_make_it": cant_make_it,
        "stop_times": stop_times or {},
        "macropoint_url": url,
        "mp_status": mp_status or "",
        "last_scraped": now,
        "driver_phone": driver_phone or cache.get(efj, {}).get("driver_phone"),
    }


# ── EFJ Pro alert ───────────────────────────────────────────────────────────────

# ── Unresponsive driver alert ────────────────────────────────────────────

def send_unresponsive_alert(efj, load_num, account, carrier, driver_phone,
                            carrier_email, rep_email, escalation=False):
    """Send email alert when driver phone is unresponsive."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_user = os.getenv("SMTP_USER", "jfeltzjr@gmail.com")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    cc_addr = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")

    if not rep_email:
        rep_email = cc_addr

    prefix = "ESCALATION: " if escalation else ""
    subject = f"{prefix}Driver Phone Unresponsive — {efj} {load_num}"

    bg_color = "#c62828" if escalation else "#e65100"
    body = f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;">
<div style="background:{bg_color};color:white;padding:12px 20px;border-radius:8px 8px 0 0;">
<h3 style="margin:0;">{'ESCALATION: ' if escalation else ''}Driver Phone Unresponsive</h3>
</div>
<div style="padding:16px 20px;background:#fafafa;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px;">
<table style="border-collapse:collapse;width:100%;">
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">EFJ #</td><td style="padding:6px 12px;">{efj}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Load #</td><td style="padding:6px 12px;">{load_num}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Account</td><td style="padding:6px 12px;">{account}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Carrier</td><td style="padding:6px 12px;">{carrier}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Driver Phone</td><td style="padding:6px 12px;">{driver_phone or 'N/A'}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Carrier Email</td><td style="padding:6px 12px;">{carrier_email or 'N/A'}</td></tr>
</table>
{'<p style="color:#c62828;font-weight:bold;margin-top:12px;">This load has been unresponsive for over 1.5 hours. Please contact carrier directly.</p>' if escalation else '<p style="color:#e65100;margin-top:12px;">Macropoint cannot reach the driver phone. The system will retry automatically.</p>'}
</div>
</body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = rep_email
        msg["Cc"] = cc_addr
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(smtp_user, smtp_pass)
            recipients = [rep_email]
            if cc_addr and cc_addr != rep_email:
                recipients.append(cc_addr)
            smtp.sendmail(smtp_user, recipients, msg.as_string())
        log.info("Sent %sunresponsive alert for %s to %s",
                 "ESCALATION " if escalation else "", efj, rep_email)
    except Exception as e:
        log.warning("Failed to send unresponsive alert for %s: %s", efj, e)


def check_unresponsive(efj, load_num, mp_load_status, account, carrier,
                       driver_phone, carrier_email, rep_email, tracking_cache):
    """Check and handle unresponsive driver status with escalation."""
    state = load_unresponsive_state()
    key = efj

    if mp_load_status and "unresponsive" in mp_load_status.lower():
        entry = state.get(key, {"count": 0, "last_alert": None})
        entry["count"] = entry.get("count", 0) + 1
        count = entry["count"]

        # First detection or every 4 polls (2 hours) — send alert
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()
        last_alert = entry.get("last_alert")

        should_alert = False
        if count == 1:
            should_alert = True
        elif last_alert:
            try:
                last_dt = datetime.fromisoformat(last_alert)
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if elapsed >= 7200:  # 2 hours
                    should_alert = True
            except (ValueError, TypeError):
                should_alert = True

        if should_alert:
            escalation = count >= 3  # 3+ consecutive = 1.5+ hours
            send_unresponsive_alert(efj, load_num, account, carrier,
                                   driver_phone, carrier_email, rep_email,
                                   escalation=escalation)
            entry["last_alert"] = now_str

        # After 6 consecutive (3 hours) — flag cantMakeIt
        if count >= 6:
            if efj in tracking_cache:
                tracking_cache[efj]["cant_make_it"] = "Driver Phone Unresponsive (3+ hrs)"
                log.warning("Flagged %s as cantMakeIt (6+ unresponsive polls)", efj)

        state[key] = entry
        save_unresponsive_state(state)
        log.info("Unresponsive count for %s: %d", efj, count)

    else:
        # Status is NOT unresponsive — reset counter
        if key in state:
            if state[key].get("count", 0) > 0:
                log.info("Unresponsive cleared for %s (was %d polls)", efj, state[key]["count"])
            del state[key]
            save_unresponsive_state(state)


def send_pro_alert(row: list, tab_name: str, account_lookup: dict):
    """Email rep daily when a row has no EFJ# pro number."""
    info      = account_lookup.get(tab_name, {})
    rep_email = info.get("email", "")
    rep_name  = info.get("rep", "")
    to_email  = rep_email if rep_email else EMAIL_FALLBACK
    cc_email  = EMAIL_CC if rep_email else None
    headers   = ["EFJ#","Move Type","Container/Load#","BOL/Booking#","SSL/Vessel",
                 "Carrier","Origin","Destination","ETA/ERD","LFD/Cutoff",
                 "Pickup Date","Delivery Date","Status","Driver/Truck","Notes"]
    detail_rows = ""
    for i, val in enumerate(row):
        if val and val.strip():
            label = headers[i] if i < len(headers) else f"Col {i+1}"
            detail_rows += f"<tr><td style=\"padding:3px 8px;color:#555;\">{label}</td><td style=\"padding:3px 8px;\">{val.strip()}</td></tr>"
    container = row[2].strip() if len(row) > 2 and row[2].strip() else "Unknown"
    vessel    = row[4].strip() if len(row) > 4 and row[4].strip() else "Unknown"
    origin    = row[6].strip() if len(row) > 6 and row[6].strip() else ""
    dest      = row[7].strip() if len(row) > 7 and row[7].strip() else ""
    extra = " | ".join(filter(None, [container, vessel, origin, dest]))
    subject = f"Please Pro Load ASAP: Load Needs EFJ Pro - {extra}"
    body = (
        f"<div style=\"font-family:Arial,sans-serif;max-width:600px;\">"
        f"<div style=\"background:#e65100;color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:16px;\">"
        f"<b>Please Pro Load ASAP</b></div>"
        f"<div style=\"border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:10px;\">"
        f"<table style=\"border-collapse:collapse;\">"
        f"<tr><td style=\"padding:4px 8px;color:#555;\">Account</td><td style=\"padding:4px 8px;\">{tab_name}</td></tr>"
        + (f"<tr><td style=\"padding:4px 8px;color:#555;\">Rep</td><td style=\"padding:4px 8px;\">{rep_name}</td></tr>" if rep_name else "")
        + f"</table>"
        f"<div style=\"margin-top:8px;border-top:1px solid #eee;padding-top:8px;\">"
        f"<b>Load Details</b></div>"
        f"<table style=\"border-collapse:collapse;\">{detail_rows}</table>"
        f"</div></div>"
    )
    _send_email(to_email, cc_email, subject, body)

# ── Email notification ───────────────────────────────────────────────────────────
def _send_email(to_email: str, cc_email: str | None, subject: str, body: str):
    """Send a plain-text email via Gmail SMTP/STARTTLS."""
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
        print(f"    Email sent → {to_email}  (cc: {cc_email or 'none'})")
    except Exception as exc:
        print(f"    WARNING: Email failed: {exc}")


def send_ftl_email(efj: str, load_num: str, status: str, tab_name: str, account_lookup: dict, mp_load_id: str = None, stop_times: dict = None):
    """Send an FTL status alert email routed to the rep for this account tab."""
    info      = account_lookup.get(tab_name, {})
    rep_email = info.get("email", "")
    rep_name  = info.get("rep",   "")

    if rep_email:
        to_email = rep_email
        cc_email = None if tab_name.lower() == "boviet" else EMAIL_CC
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
    hdr_color = "#c62828" if behind else "#1b5e20"

    subject = f"FTL Alert \u2014 {tab_name} \u2014 {load_display} \u2014 {status}"

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
        f"<p style=\"color:#888;font-size:12px;\">FTL Status Update \u2014 {now}</p>"
        f"<div style=\"background:{hdr_color};color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:16px;\">"
        f"<b>{load_num} / {load_display}</b></div>"
        f"<div style=\"border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:10px;\">"
        f"<table style=\"border-collapse:collapse;\">{rows}</table>"
        f"{timeline}"
        f"</div></div>"
    )

    _send_email(to_email, cc_email, subject, body)


# ── Archive helpers ──────────────────────────────────────────────────────────────
def _ftl_completed_tab_for(tab_name: str, account_lookup: dict) -> str | None:
    """Return 'Completed Eli', 'Completed Radka', or None based on rep name."""
    rep_name = account_lookup.get(tab_name, {}).get("rep", "")
    rl = rep_name.lower()
    if "eli" in rl:
        return "Completed Eli"
    if "radka" in rl:
        return "Completed Radka"
    if "john" in rl:
        return "Completed John F"
    return None


def archive_ftl_row(gc, tab_name: str, sheet_row: int, row_data: list,
                    url: str, efj: str, load_num: str,
                    pickup_val: str, delivery_val: str, notes_val: str,
                    account_lookup: dict) -> bool:
    """
    Copy a Delivered FTL row to the rep's Completed tab, then delete it.
    Performs a duplicate EFJ# check before appending.
    Sends an archive email to the rep, or writes a note to Col O if no email.
    Returns True on success, False on skip or failure.
    """
    rep_info  = account_lookup.get(tab_name, {})
    rep_name  = rep_info.get("rep", "unknown")
    rep_email = rep_info.get("email", "")
    dest_tab  = _ftl_completed_tab_for(tab_name, account_lookup)

    # ── No completed tab — write note to Col O on source tab, bail ───────────
    if not dest_tab:
        note = f"No completed tab for rep '{rep_name}' — manual archive needed"
        print(f"  WARNING: {note} (account '{tab_name}', row {sheet_row})")
        try:
            ws = gc.open_by_key(SHEET_ID).worksheet(tab_name)
            ws.update_cell(sheet_row, GCOL_NOTES, note)
        except Exception as exc:
            print(f"  WARNING: Could not write fallback note: {exc}")
        return False

    try:
        dest_ws = gc.open_by_key(SHEET_ID).worksheet(dest_tab)
    except Exception as exc:
        print(f"  WARNING: Could not open '{dest_tab}': {exc}")
        return False

    # ── Duplicate check — skip if EFJ# already in completed tab ──────────────
    if efj:
        try:
            existing_efjs = dest_ws.col_values(1)  # Col A
            if efj in existing_efjs:
                dup_note = (f"WARNING: EFJ# {efj} already in '{dest_tab}' "
                            f"— archive skipped")
                print(f"  {dup_note}")
                try:
                    ws = gc.open_by_key(SHEET_ID).worksheet(tab_name)
                    ws.update_cell(sheet_row, GCOL_NOTES, dup_note)
                except Exception:
                    pass
                return False
        except Exception as exc:
            print(f"  WARNING: Duplicate EFJ# check failed: {exc}")

    # ── Build archive row — patch with freshly written values ────────────────
    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    row = list(row_data)
    while len(row) < GCOL_NOTES:
        row.append("")
    row[COL_PICKUP_R]   = pickup_val   or ""
    row[COL_DELIVERY_R] = delivery_val or ""
    row[COL_STATUS_R]   = "Delivered"
    # Col O: notes + timestamp if emailing, fallback note otherwise
    if rep_email:
        row[COL_NOTES_R] = notes_val or timestamp
    else:
        row[COL_NOTES_R] = "No rep email found — alert not sent"

    # Reconstruct Col C as =HYPERLINK so the link is preserved
    if url and len(row) > COL_TRACKING:
        display      = (row_data[COL_LOAD] if len(row_data) > COL_LOAD else "") or ""
        safe_url     = url.replace('"', '%22')
        safe_display = str(display).replace('"', "'")
        row[COL_TRACKING] = f'=HYPERLINK("{safe_url}","{safe_display}")'

    # ── Append to completed tab ───────────────────────────────────────────────
    try:
        dest_ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"  Archived FTL row {sheet_row} ({efj}|{load_num}) → '{dest_tab}'")
    except Exception as exc:
        print(f"  WARNING: Archive append failed for row {sheet_row}: {exc}")
        return False

    # ── Send archive email ────────────────────────────────────────────────────
    if rep_email:
        subject = f"CSL Archived | {load_num} | {efj} | Delivered"
        body = (
            f"FTL load {efj} (EFJ# {load_num}) has been archived.\n\n"
            f"Account:  {tab_name}\n"
            f"Rep:      {rep_name}\n\n"
            f"Pickup:   {pickup_val or '—'}\n"
            f"Delivery: {delivery_val or '—'}\n"
            f"Status:   Delivered\n"
            f"Archived: {timestamp}\n"
        )
        _send_email(rep_email, None if tab_name.lower() == "boviet" else EMAIL_CC, subject, body)

    # ── Delete from source tab ────────────────────────────────────────────────
    try:
        ws = gc.open_by_key(SHEET_ID).worksheet(tab_name)
        ws.delete_rows(sheet_row)
        print(f"  Deleted FTL row {sheet_row} from '{tab_name}'")
    except Exception as exc:
        print(f"  WARNING: Delete failed for row {sheet_row} in '{tab_name}': {exc}")
        return False

    return True


# ── One-time cleanup ─────────────────────────────────────────────────────────────
def clear_incorrect_pickup_dates(creds, gc, account_tabs: list):
    """
    Clear '02-22' pickup dates written incorrectly to Col K by a previous
    script version, across all account tabs.
    """
    print("\nRunning one-time cleanup: clearing incorrect '02-22' dates from Col K...")
    for tab_name in account_tabs:
        try:
            ws       = gc.open_by_key(SHEET_ID).worksheet(tab_name)
            all_rows = ws.get_all_values()
        except Exception as exc:
            print(f"  WARNING: could not read '{tab_name}' for cleanup: {exc}")
            continue

        updates = []
        for i, row in enumerate(all_rows):
            if len(row) <= COL_MOVE_TYPE:
                continue
            if row[COL_MOVE_TYPE].strip().upper() != "FTL":
                continue
            pickup_val = row[COL_PICKUP_R].strip() if len(row) > COL_PICKUP_R else ""
            if pickup_val == "02-22":
                sheet_row = i + 1
                updates.append(
                    {"range": f"{_col_letter(GCOL_PICKUP)}{sheet_row}", "values": [[""]]}
                )
                efj      = row[COL_EFJ].strip()  if len(row) > COL_EFJ  else "?"
                load_num = row[COL_LOAD].strip() if len(row) > COL_LOAD else "?"
                print(f"  [{tab_name}] Clearing K{sheet_row} ({efj}|{load_num})")

        if updates:
            try:
                ws.batch_update(updates, value_input_option="RAW")
                print(f"  [{tab_name}] Cleared {len(updates)} incorrect date(s).")
            except Exception as exc:
                print(f"  WARNING: cleanup write failed for '{tab_name}': {exc}")

    print("  Cleanup complete.")


# ── One-time planned-time backfill ───────────────────────────────────────────────
_BARE_DATE_RE = re.compile(r"^\d{2}-\d{2}$")


def backfill_planned_times(creds, gc, account_tabs: list, mp_cookies: list = None):
    """
    One-time backfill: upgrade bare MM-DD values in K/L to MM-DD HH:MM using
    planned start times from Macropoint, across all account tabs.
    """
    print("\nRunning one-time backfill: upgrading bare MM-DD dates in K/L to MM-DD HH:MM...")
    if mp_cookies is None:
        mp_cookies = _load_mp_cookies()
    all_needs_update = []
    ws_map = {}

    for tab_name in account_tabs:
        try:
            ws, ftl_rows = get_ftl_rows(creds, gc, tab_name, sent_alerts=sent, account_lookup=account_lookup)
            ws_map[tab_name] = ws
        except Exception as exc:
            print(f"  WARNING: could not read '{tab_name}' for backfill: {exc}")
            continue

        needs = [
            row for row in ftl_rows
            if _BARE_DATE_RE.match(row["existing_pickup"])
            or _BARE_DATE_RE.match(row["existing_delivery"])
        ]
        all_needs_update.extend(needs)

    if not all_needs_update:
        print("  Nothing to backfill.")
        return

    print(f"  Found {len(all_needs_update)} row(s) with bare MM-DD values")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for row in all_needs_update:
            tab_name = row["tab_name"]
            print(f"  [{tab_name}] → {row['key']}")
            _, _, _, stop1_planned, stop2_planned, *_ = scrape_macropoint(browser, row["url"], mp_cookies=mp_cookies)
            updates = []

            if _BARE_DATE_RE.match(row["existing_pickup"]):
                if stop1_planned:
                    updates.append({"range": f"K{row['sheet_row']}", "values": [[stop1_planned]]})
                    print(f"    K{row['sheet_row']}: {row['existing_pickup']!r} → {stop1_planned!r}")
                else:
                    print(f"    K{row['sheet_row']}: no planned time — leaving {row['existing_pickup']!r}")

            if _BARE_DATE_RE.match(row["existing_delivery"]):
                if stop2_planned:
                    updates.append({"range": f"L{row['sheet_row']}", "values": [[stop2_planned]]})
                    print(f"    L{row['sheet_row']}: {row['existing_delivery']!r} → {stop2_planned!r}")
                else:
                    print(f"    L{row['sheet_row']}: no planned time — leaving {row['existing_delivery']!r}")

            if updates:
                try:
                    ws_map[tab_name].batch_update(updates, value_input_option="RAW")
                except Exception as exc:
                    print(f"    WARNING: sheet write failed: {exc}")

        save_tracking_cache(tracking_cache)
        browser.close()
    print("  Backfill complete.")


# ── Poll cycle ───────────────────────────────────────────────────────────────────
def run_once(account_lookup: dict):
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    print(f"\n[{now}] Starting FTL poll cycle...")

    creds = _load_credentials()
    gc    = gspread.authorize(creds)
    try:
        sheet = _retry_on_quota(gc.open_by_key, SHEET_ID)
    except Exception as exc:
        print(f"  ERROR opening sheet: {exc}")
        print(f"  Will retry next poll cycle.")
        return

    account_tabs = get_account_tabs(sheet, account_lookup)
    if not account_tabs:
        print("  No account tabs found.")
        return

    print(f"  Account tabs: {account_tabs}")
    sent = load_sent_alerts()
    tracking_cache = load_tracking_cache()
    mp_cookies = _load_mp_cookies()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        for tab_name in account_tabs:
            print(f"\n  {'─'*50}")
            print(f"  Checking '{tab_name}'...")
            time.sleep(5)  # rate-limit between tabs (3 API calls per tab)

            try:
                ws, ftl_rows = _retry_on_quota(get_ftl_rows, creds, gc, tab_name, sent_alerts=sent, account_lookup=account_lookup)
            except Exception as exc:
                print(f"  ERROR reading '{tab_name}': {exc}")
                continue

            print(f"  Found {len(ftl_rows)} FTL row(s)")

            archive_jobs_ftl = []

            for row in ftl_rows:
                key = row["key"]
                print(f"  → {key}")

                status, stop1_date, stop2_date, stop1_planned, stop2_planned, mp_load_id, cant_make_it, stop_times = (
                    scrape_macropoint(browser, row["url"], mp_cookies=mp_cookies)
                )
                print(
                    f"    Status: {status}  |  stop1={stop1_date!r}  stop2={stop2_date!r}"
                    f"  |  planned1={stop1_planned!r}  planned2={stop2_planned!r}"
                    f"  |  mp_load_id={mp_load_id!r}"
                )

                # Try to get driver's tracking phone from authenticated MP portal
                driver_phone = None
                if mp_load_id and mp_cookies:
                    driver_phone = scrape_driver_phone(
                        browser, mp_load_id, row["load_num"], mp_cookies
                    )

                update_tracking_cache(
                    row["efj"], row["load_num"], status,
                    mp_load_id, cant_make_it, stop_times,
                    row["url"], tracking_cache,
                    driver_phone=driver_phone,
                    mp_status=status)


                # Auto-transition: Tracking Completed → Need POD
                if status and "tracking completed" in status.lower():
                    current_status = (row_data.get("status") or "").strip().lower() if isinstance(row_data, dict) else ""
                    if current_status not in ("need pod", "pod received", "pod rc'd", "driver paid"):
                        try:
                            ws.update_cell(row_number, STATUS_COL + 1, "Need POD")
                            log.info("Auto-status: %s -> Need POD (tracking completed)", efj)
                        except Exception as e:
                            log.warning("Failed to auto-status %s to Need POD: %s", efj, e)

                if status == "Delivered":
                    missing_cols = []
                    if not stop1_date and not row["existing_pickup"]:
                        missing_cols.append("K")
                    if not stop2_date and not row["existing_delivery"]:
                        missing_cols.append("L")
                    if missing_cols:
                        print(
                            f"    WARNING: Date not available from Macropoint — "
                            f"manual entry may be needed for {'/'.join(missing_cols)} "
                            f"on row {row['sheet_row']}"
                        )

                sheet_updates  = []
                note_parts     = []
                final_pickup   = row["existing_pickup"]
                final_delivery = row["existing_delivery"]
                final_notes    = row["existing_notes"]

                if stop1_date and not row["existing_pickup"]:
                    k_val = stop1_planned if stop1_planned else stop1_date
                    sheet_updates.append(
                        {"range": f"K{row['sheet_row']}", "values": [[k_val]]}
                    )
                    note_parts.append(f"Pickup {k_val}")
                    final_pickup = k_val
                    print(f"    Writing Stop 1 → K{row['sheet_row']} = {k_val!r}")
                elif stop1_date and row["existing_pickup"]:
                    print(f"    K{row['sheet_row']} already has {row['existing_pickup']!r} — not overwriting")

                if stop2_date and not row["existing_delivery"]:
                    l_val = stop2_planned if stop2_planned else stop2_date
                    sheet_updates.append(
                        {"range": f"L{row['sheet_row']}", "values": [[l_val]]}
                    )
                    note_parts.append(f"Delivery {l_val}")
                    final_delivery = l_val
                    print(f"    Writing Stop 2 → L{row['sheet_row']} = {l_val!r}")
                elif stop2_date and row["existing_delivery"]:
                    print(f"    L{row['sheet_row']} already has {row['existing_delivery']!r} — not overwriting")

                # Map bot statuses to Column M dropdown values
                STATUS_TO_DROPDOWN = {
                    "Driver Arrived at Pickup": "At Pickup",
                    "Departed Pickup - En Route": "In Transit",
                    "Arrived at Delivery": "At Delivery",
                    "Departed Delivery": "Departed Delivery",
                    "Running Late": "Running Behind",
                    "Tracking Behind Schedule": "Running Behind",
                    "Tracking Waiting for Update": "Tracking Waiting for",
                    "Delivered": "Delivered",
                }
                dropdown_val = STATUS_TO_DROPDOWN.get(status)
                if dropdown_val and row["existing_status"] != dropdown_val:
                    sheet_updates.append(
                        {"range": f"M{row['sheet_row']}", "values": [[dropdown_val]]}
                    )
                    note_parts.append(dropdown_val)
                    print(f"    Writing '{dropdown_val}' → M{row['sheet_row']}")
                elif dropdown_val and row["existing_status"] == dropdown_val:
                    print(f"    M{row['sheet_row']} already '{dropdown_val}' — not overwriting")

                if sheet_updates:
                    note = _build_note(row["existing_notes"], ", ".join(note_parts))
                    sheet_updates.append(
                        {"range": f"O{row['sheet_row']}", "values": [[note]]}
                    )
                    final_notes = note
                    try:
                        ws.batch_update(sheet_updates, value_input_option="RAW")
                        print(f"    Sheet updated — note → O{row['sheet_row']}")
                    except Exception as exc:
                        print(f"    WARNING: sheet write failed: {exc}")

                if not status:
                    print(f"    No trigger detected")
                    continue

                # Skip alerts for loads with pickup before cutoff date
                _skip_old = False
                _date_src = stop1_planned or row["existing_pickup"]
                if ALERT_CUTOFF_DATE and _date_src:
                    try:
                        import re as _re
                        _m = _re.search(r"(\d{2})[-/](\d{2})", _date_src)
                        if _m:
                            _pickup_dt = datetime.strptime(
                                f"{datetime.now().year}-{_m.group(1)}-{_m.group(2)}", "%Y-%m-%d"
                            )
                            _cutoff_dt = datetime.strptime(ALERT_CUTOFF_DATE, "%Y-%m-%d")
                            if _pickup_dt < _cutoff_dt:
                                _skip_old = True
                    except (ValueError, IndexError):
                        pass
                if _skip_old:
                    print(f"    Pickup {_date_src} before cutoff {ALERT_CUTOFF_DATE} — skipping email")
                    continue

                # Only alert on actual status CHANGES — skip if sheet already shows this status
                _existing = row["existing_status"].strip().lower()
                _new = status.strip().lower()
                if _existing == _new:
                    print(f"    Status unchanged ('{status}') — skipping email")
                    mark_sent(sent, key, status)  # record it so dedup won't re-check
                    continue

                if already_sent(sent, key, status):
                    print(f"    Already alerted for '{status}' — skipping")
                else:
                    send_ftl_email(row["efj"], row["load_num"], status, tab_name, account_lookup, mp_load_id=mp_load_id, stop_times=stop_times)
                    mark_sent(sent, key, status)

                # ── CAN'T MAKE IT alert ──────────────────────────────────
                if cant_make_it:
                    cmi_status = f"Can't Make It - {cant_make_it}"
                    if not already_sent(sent, key, cmi_status):
                        print(f"    CAN'T MAKE IT detected: {cant_make_it}")
                        send_ftl_email(row["efj"], row["load_num"], cmi_status, tab_name, account_lookup, mp_load_id=mp_load_id)
                        mark_sent(sent, key, cmi_status)

                # Queue for archiving after all rows processed
                if status == "Delivered":
                    archive_jobs_ftl.append({
                        "sheet_row":    row["sheet_row"],
                        "row_data":     row["row_data"],
                        "url":          row["url"],
                        "efj":          row["efj"],
                        "load_num":     row["load_num"],
                        "pickup_val":   final_pickup,
                        "delivery_val": final_delivery,
                        "notes_val":    final_notes,
                    })

            # ── Archive delivered rows bottom-to-top to keep row numbers valid ─
            if archive_jobs_ftl:
                print(f"\n  Archiving {len(archive_jobs_ftl)} delivered FTL row(s)...")
                for aj in sorted(archive_jobs_ftl, key=lambda j: j["sheet_row"], reverse=True):
                    archive_ftl_row(
                        gc, tab_name, aj["sheet_row"], aj["row_data"],
                        aj["url"], aj["efj"], aj["load_num"],
                        aj["pickup_val"], aj["delivery_val"], aj["notes_val"],
                        account_lookup,
                    )

        save_tracking_cache(tracking_cache)
        browser.close()

    save_sent_alerts(sent)


# ── Entry point ──────────────────────────────────────────────────────────────────
def main():
    print("FTL Monitor started — polling every 30 minutes.")
    creds = _load_credentials()
    account_lookup = load_account_lookup(creds)

    gc    = gspread.authorize(creds)
    sheet = gc.open_by_key(SHEET_ID)
    account_tabs = get_account_tabs(sheet, account_lookup)
    print(f"Account tabs: {account_tabs}")

    # cleanup and backfill removed — no longer needed, saves API quota

    while True:
        run_once(account_lookup)
        print(f"\n  Sleeping {POLL_INTERVAL // 60} minutes...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
