#!/usr/bin/env python3
"""
ftl_monitor.py — polls all account tabs every 30 minutes for FTL rows,
uses Playwright to scrape Macropoint tracking status, sends email alerts
routed to the rep assigned to each account tab, and writes pickup/delivery
dates to the sheet.
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
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Config ──────────────────────────────────────────────────────────────────────
SHEET_ID         = "19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0"
CREDENTIALS_FILE = "/root/csl-credentials.json"
SENT_ALERTS_FILE = "/root/csl-bot/ftl_sent_alerts.json"
POLL_INTERVAL    = 30 * 60  # seconds
DEBUG            = False    # save Macropoint inner_text to /tmp/mp_debug_[load_num].txt

# ── SMTP / email ─────────────────────────────────────────────────────────────────
SMTP_HOST      = "smtp.office365.com"
SMTP_PORT      = 587
SMTP_USER      = "efj-operations@evansdelivery.com"
SMTP_PASSWORD  = "9rWWcm-9kEbs"
EMAIL_CC       = "efj-operations@evansdelivery.com"
EMAIL_FALLBACK = "efj-operations@evansdelivery.com"

# ── Tab config ───────────────────────────────────────────────────────────────────
ACCOUNT_LOOKUP_TAB = "Account Rep"
SKIP_TABS = {
    "Sheet 4", "DTCELNJW", "Account Rep", "Completed Eli", "Completed Radka",
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
    s1 = re.search(r"\bStop\s*1\b", text, re.I)
    s2 = re.search(r"\bStop\s*2\b", text, re.I)
    if not s1:
        s1 = re.search(r"(?:^|\n)[ \t]*1[ \t]*\n", text)
        s2 = re.search(r"(?:^|\n)[ \t]*2[ \t]*\n", text)
    if not s1:
        return "", ""
    if s2 and s2.start() > s1.start():
        return text[s1.start():s2.start()], text[s2.start():]
    return text[s1.start():], ""


def _find_event_date(section: str, event: str) -> str | None:
    m = re.search(
        rf"\b{re.escape(event)}\s*@\s*(\d{{1,2}}/\d{{1,2}})\b",
        section, re.I,
    )
    if m:
        parts = m.group(1).split("/")
        return f"{int(parts[0]):02d}-{int(parts[1]):02d}"

    lines = [l.strip() for l in section.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        if re.search(rf"\b{re.escape(event)}\b", line, re.I):
            context = " ".join(lines[i:i + 3])
            m = _DATE_RE.search(context)
            if m:
                return _to_mmdd(m.group(0))
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


def _parse_macropoint(
    text: str,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    stop1_text, stop2_text = _split_stops(text)
    stop1_arrived       = _find_event_date(stop1_text,   "Arrived")  if stop1_text else None
    stop2_departed      = _find_event_date(stop2_text,   "Departed") if stop2_text else None
    stop1_planned_start = _find_planned_start(stop1_text)             if stop1_text else None
    stop2_planned_start = _find_planned_start(stop2_text)             if stop2_text else None

    if re.search(
        r"FraudGuard"
        r"|phone\s*(unresponsive|unreachable|not\s*respond)"
        r"|unable\s+to\s+(locate|reach|contact).{0,20}(driver|phone)"
        r"|driver.{0,20}(unreachable|unresponsive)",
        text, re.I,
    ):
        return "Driver Phone Unresponsive", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start

    if re.search(r"Tracking\s+Completed\s+Successfully", text, re.I):
        return "Delivered", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start

    if stop1_arrived:
        return "Driver Arrived at Pickup", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start

    planned_dt = _find_planned_dt(stop1_text)
    if planned_dt:
        now = datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
        if now > planned_dt:
            return "Running Late", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start

    if stop1_text and not _has_events(stop1_text) and not _has_events(stop2_text):
        return "Tracking Waiting for Update", stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start

    return None, stop1_arrived, stop2_departed, stop1_planned_start, stop2_planned_start


# ── Playwright scraper ───────────────────────────────────────────────────────────
def scrape_macropoint(
    browser, url: str
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    page = browser.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(2_000)
        text = page.inner_text("body")
    except PlaywrightTimeout as exc:
        print(f"    TIMEOUT: {exc}")
        return None, None, None, None, None
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return None, None, None, None, None
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


def get_ftl_rows(creds, gc, tab_name: str):
    """
    Returns (ws, ftl_rows) for the given tab.
    ftl_rows contains ALL rows where Col B = 'FTL'.
    """
    ws       = gc.open_by_key(SHEET_ID).worksheet(tab_name)
    all_rows = ws.get_all_values()
    links    = _get_hyperlinks(creds, tab_name)

    ftl_rows = []
    for i, row in enumerate(all_rows):
        if len(row) <= COL_MOVE_TYPE:
            continue
        if row[COL_MOVE_TYPE].strip().upper() != "FTL":
            continue

        efj      = row[COL_EFJ].strip()  if len(row) > COL_EFJ  else ""
        load_num = row[COL_LOAD].strip() if len(row) > COL_LOAD else ""

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


# ── Email notification ───────────────────────────────────────────────────────────
def _send_email(to_email: str, cc_email: str | None, subject: str, body: str):
    """Send a plain-text email via Office 365 SMTP/STARTTLS."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    if cc_email and cc_email != to_email:
        msg["Cc"] = cc_email
    msg.attach(MIMEText(body, "plain"))

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


def send_ftl_email(efj: str, load_num: str, status: str, tab_name: str, account_lookup: dict):
    """Send an FTL status alert email routed to the rep for this account tab."""
    info      = account_lookup.get(tab_name, {})
    rep_email = info.get("email", "")
    rep_name  = info.get("rep",   "")

    if rep_email:
        to_email = rep_email
        cc_email = EMAIL_CC
    else:
        to_email = EMAIL_FALLBACK
        cc_email = None

    now     = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    subject = f"FTL Alert — {tab_name} — {efj} | {load_num} — {status}"
    body    = (
        f"FTL Status Update — {now}\n\n"
        f"Account:  {tab_name}\n"
        + (f"Rep:      {rep_name}\n" if rep_name else "")
        + f"EFJ #:    {efj}\n"
          f"Load #:   {load_num}\n"
          f"Status:   {status}\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    if cc_email and cc_email != to_email:
        msg["Cc"] = cc_email
    msg.attach(MIMEText(body, "plain"))

    recipients = [to_email]
    if cc_email and cc_email != to_email:
        recipients.append(cc_email)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"    Email sent → {to_email}: {subject}")
    except Exception as exc:
        print(f"    WARNING: Email failed: {exc}")


# ── Archive helpers ──────────────────────────────────────────────────────────────
def _ftl_completed_tab_for(tab_name: str, account_lookup: dict) -> str | None:
    """Return 'Completed Eli', 'Completed Radka', or None based on rep name."""
    rep_name = account_lookup.get(tab_name, {}).get("rep", "")
    rl = rep_name.lower()
    if "eli" in rl:
        return "Completed Eli"
    if "radka" in rl:
        return "Completed Radka"
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
        subject = f"CSL Archived | {efj} | {load_num} | Delivered"
        body = (
            f"FTL load {load_num} (EFJ# {efj}) has been archived.\n\n"
            f"Account:  {tab_name}\n"
            f"Rep:      {rep_name}\n\n"
            f"Pickup:   {pickup_val or '—'}\n"
            f"Delivery: {delivery_val or '—'}\n"
            f"Status:   Delivered\n"
            f"Archived: {timestamp}\n"
        )
        _send_email(rep_email, EMAIL_CC, subject, body)

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


def backfill_planned_times(creds, gc, account_tabs: list):
    """
    One-time backfill: upgrade bare MM-DD values in K/L to MM-DD HH:MM using
    planned start times from Macropoint, across all account tabs.
    """
    print("\nRunning one-time backfill: upgrading bare MM-DD dates in K/L to MM-DD HH:MM...")
    all_needs_update = []
    ws_map = {}

    for tab_name in account_tabs:
        try:
            ws, ftl_rows = get_ftl_rows(creds, gc, tab_name)
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
            _, _, _, stop1_planned, stop2_planned = scrape_macropoint(browser, row["url"])
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

        browser.close()
    print("  Backfill complete.")


# ── Poll cycle ───────────────────────────────────────────────────────────────────
def run_once(account_lookup: dict):
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    print(f"\n[{now}] Starting FTL poll cycle...")

    creds = _load_credentials()
    gc    = gspread.authorize(creds)
    sheet = gc.open_by_key(SHEET_ID)

    account_tabs = get_account_tabs(sheet, account_lookup)
    if not account_tabs:
        print("  No account tabs found.")
        return

    print(f"  Account tabs: {account_tabs}")
    sent = load_sent_alerts()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        for tab_name in account_tabs:
            print(f"\n  {'─'*50}")
            print(f"  Checking '{tab_name}'...")

            try:
                ws, ftl_rows = get_ftl_rows(creds, gc, tab_name)
            except Exception as exc:
                print(f"  ERROR reading '{tab_name}': {exc}")
                continue

            print(f"  Found {len(ftl_rows)} FTL row(s)")

            archive_jobs_ftl = []

            for row in ftl_rows:
                key = row["key"]
                print(f"  → {key}")

                status, stop1_date, stop2_date, stop1_planned, stop2_planned = (
                    scrape_macropoint(browser, row["url"])
                )
                print(
                    f"    Status: {status}  |  stop1={stop1_date!r}  stop2={stop2_date!r}"
                    f"  |  planned1={stop1_planned!r}  planned2={stop2_planned!r}"
                )

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

                if status == "Delivered" and row["existing_status"] != "Delivered":
                    sheet_updates.append(
                        {"range": f"M{row['sheet_row']}", "values": [["Delivered"]]}
                    )
                    note_parts.append("Delivered")
                    print(f"    Writing 'Delivered' → M{row['sheet_row']}")
                elif status == "Delivered":
                    print(f"    M{row['sheet_row']} already 'Delivered' — not overwriting")

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

                if already_sent(sent, key, status):
                    print(f"    Already alerted for '{status}' — skipping")
                else:
                    send_ftl_email(row["efj"], row["load_num"], status, tab_name, account_lookup)
                    mark_sent(sent, key, status)

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

    clear_incorrect_pickup_dates(creds, gc, account_tabs)
    backfill_planned_times(creds, gc, account_tabs)

    while True:
        run_once(account_lookup)
        print(f"\n  Sleeping {POLL_INTERVAL // 60} minutes...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
