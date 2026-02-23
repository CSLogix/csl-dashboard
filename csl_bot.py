import json
import os
import re
import smtplib
import requests
import gspread
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SHEET_ID         = "19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0"
CREDENTIALS_FILE = "/root/csl-credentials.json"
STATUS_FILTER    = "Tracking Waiting for Update"
LAST_CHECK_FILE  = "/root/csl-bot/last_check.json"

# ── SMTP / email ────────────────────────────────────────────────────────────────
SMTP_HOST      = "smtp.office365.com"
SMTP_PORT      = 587
SMTP_USER      = "efj-operations@evansdelivery.com"
SMTP_PASSWORD  = "9rWWcm-9kEbs"
EMAIL_CC       = "efj-operations@evansdelivery.com"
EMAIL_FALLBACK = "efj-operations@evansdelivery.com"

# ── Tab config ──────────────────────────────────────────────────────────────────
ACCOUNT_LOOKUP_TAB = "Account Rep"
SKIP_TABS = {
    "Sheet 4", "DTCELNJW", "Account Rep", "Completed Eli", "Completed Radka",
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Column numbers (1-indexed, for gspread)
COL_MOVE_TYPE = 2   # B — determines workflow
COL_TRACKING  = 3   # C — hyperlink URL
COL_BOL       = 4   # D — BOL / booking number
COL_ETA       = 9   # I
COL_PICKUP    = 11  # K
COL_RETURN    = 16  # P — Return to Port date
COL_STATUS    = 13  # M — dropdown status
COL_TIMESTAMP = 15  # O

# ShipmentLink status keyword → sheet dropdown value mapping
SHIPMENTLINK_STATUS_MAP = {
    "vessel eta":                  "Vessel",
    "estimated arrival":           "Vessel",
    "expected arrival":            "Vessel",
    "expected":                    "Vessel",
    "eta":                         "Vessel",
    "rail":                        "Rail",
    "on rail":                     "Rail",
    "ramp arrival":                "Rail",
    "intermodal":                  "Rail",
    "ramp":                        "Rail",
    "vessel arrived":              "Vessel Arrived",
    "ata":                         "Vessel Arrived",
    "actual arrival":              "Vessel Arrived",
    "arrival":                     "Vessel Arrived",
    "discharged":                  "Discharged",
    "pick-up by merchant haulage": "Released",
    "merchant haulage":            "Released",
    "gate out":                    "Released",
    "full out":                    "Released",
    "out gate":                    "Released",
    "full gate out":               "Released",
    "empty container returned":    "Returned to Port",
    "empty return":                "Returned to Port",
    "empty in":                    "Returned to Port",
    "gate in empty":               "Returned to Port",
    "returned":                    "Returned to Port",
}


# ─────────────────────────────────────────────
# Google Sheets helpers
# ─────────────────────────────────────────────

def get_sheet_hyperlinks(creds, sheet_id, tab_name):
    """
    Call Sheets API v4 directly to fetch the hyperlink property for every cell.
    Returns a 2-D list [row][col] of URL strings or None.
    """
    creds.refresh(GoogleRequest())
    api_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        f"?ranges={requests.utils.quote(tab_name)}"
        f"&fields=sheets.data.rowData.values.hyperlink"
        f"&includeGridData=true"
    )
    resp = requests.get(api_url, headers={"Authorization": f"Bearer {creds.token}"})
    resp.raise_for_status()
    data = resp.json()

    result = []
    for row_data in data["sheets"][0]["data"][0].get("rowData", []):
        result.append([cell.get("hyperlink") for cell in row_data.get("values", [])])
    return result


def col_letter(n):
    """Convert 1-indexed column number to A1 letter(s).  9 → 'I', 15 → 'O'."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_tracking_results(ws, sheet_row, eta, pickup, return_date, status=None):
    """
    Write ETA (I), Pickup (K), Return (P), and Timestamp (O) as RAW values.
    Status (M) is written USER_ENTERED so Sheets validates the dropdown.
    """
    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")

    ws.batch_update(
        [
            {"range": f"{col_letter(COL_ETA)}{sheet_row}",       "values": [[eta or ""]]},
            {"range": f"{col_letter(COL_PICKUP)}{sheet_row}",    "values": [[pickup or ""]]},
            {"range": f"{col_letter(COL_RETURN)}{sheet_row}",    "values": [[return_date or ""]]},
            {"range": f"{col_letter(COL_TIMESTAMP)}{sheet_row}", "values": [[timestamp]]},
        ],
        value_input_option="RAW",
    )

    if status:
        ws.batch_update(
            [{"range": f"{col_letter(COL_STATUS)}{sheet_row}", "values": [[status]]}],
            value_input_option="USER_ENTERED",
        )

    if status == "Returned to Port":
        ws.format(
            f"{col_letter(COL_STATUS)}{sheet_row}",
            {"backgroundColor": {"red": 144 / 255, "green": 238 / 255, "blue": 144 / 255}},
        )

    print(f"  Written → ETA={eta!r}  Pickup={pickup!r}  Return={return_date!r}  "
          f"Status={status!r}  [{timestamp}]")


# ─────────────────────────────────────────────
# Playwright — generic browser helpers
# ─────────────────────────────────────────────

INPUT_SELECTORS = [
    "input[placeholder*='BOL' i]",
    "input[placeholder*='B/L' i]",
    "input[placeholder*='bill of lading' i]",
    "input[placeholder*='booking' i]",
    "input[placeholder*='tracking' i]",
    "input[placeholder*='container' i]",
    "input[placeholder*='search' i]",
    "input[placeholder*='reference' i]",
    "input[name*='bol' i]",
    "input[name*='bl' i]",
    "input[name*='booking' i]",
    "input[name*='tracking' i]",
    "input[name*='search' i]",
    "input[name*='query' i]",
    "input[id*='bol' i]",
    "input[id*='bl' i]",
    "input[id*='booking' i]",
    "input[id*='tracking' i]",
    "input[id*='search' i]",
    "input[type='search']",
    "input[type='text']",
    "textarea",
]

SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Track')",
    "button:has-text('Search')",
    "button:has-text('Submit')",
    "button:has-text('Go')",
    "[role='button']:has-text('Track')",
    "[role='button']:has-text('Search')",
]

DISMISS_SELECTORS = [
    "button:has-text('Accept all')",
    "button:has-text('Accept')",
    "button:has-text('Agree')",
    "button:has-text('Close')",
    "button:has-text('Got it')",
]

DATE_RE = re.compile(
    r"\b("
    r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"
    r"|\d{4}[/\-]\d{2}[/\-]\d{2}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{2,4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*-\d{1,2}-\d{4}"
    r")\b",
    re.IGNORECASE,
)

ETA_KEYWORDS    = ["eta", "estimated arrival", "est. arrival", "vessel arrival",
                   "arrival date", "arrives", "port arrival", "ata", "atd"]
PICKUP_KEYWORDS = ["pickup", "pick up", "pick-up", "available", "lfd",
                   "last free day", "free time", "available for pickup", "avail",
                   "gate out", "out gate", "out-gate", "full out"]
RETURN_KEYWORDS = ["return", "empty return", "empty due", "return date",
                   "empty out", "empty in", "gate in empty"]


def _find_date_near_keyword(text, keywords):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        if any(kw in line.lower() for kw in keywords):
            context = " ".join(lines[i: i + 3])
            m = DATE_RE.search(context)
            if m:
                return m.group(0)
    return None


def _find_input(page):
    for selector in INPUT_SELECTORS:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=500) and loc.is_enabled(timeout=500):
                return loc
        except Exception:
            continue
    return None


def _dismiss_dialogs(page):
    for sel in DISMISS_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=800):
                btn.click()
                page.wait_for_timeout(500)
        except Exception:
            pass


def _submit(page, input_loc, value):
    input_loc.click()
    input_loc.fill(value)
    input_loc.press("Enter")

    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        pass

    for sel in SUBMIT_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=500):
                btn.click()
                page.wait_for_load_state("networkidle", timeout=15_000)
                break
        except Exception:
            continue


def _scrape_dates(page):
    try:
        text = page.inner_text("body")
    except Exception:
        return None, None, None

    return (
        _find_date_near_keyword(text, ETA_KEYWORDS),
        _find_date_near_keyword(text, PICKUP_KEYWORDS),
        _find_date_near_keyword(text, RETURN_KEYWORDS),
    )


def run_dray_import(browser, url, bol):
    page = browser.new_page()
    try:
        print(f"    Loading {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        _dismiss_dialogs(page)

        input_loc = _find_input(page)
        if input_loc is None:
            print(f"    WARNING: no search input found on page")
            return None, None, None, None

        _submit(page, input_loc, bol)
        page.wait_for_timeout(2_000)

        eta, pickup, ret = _scrape_dates(page)

        if ret:
            status = "Returned to Port"
        elif pickup:
            status = "Released"
        elif eta:
            status = "Vessel"
        else:
            status = None

        return eta, pickup, ret, status

    except PlaywrightTimeout as exc:
        print(f"    TIMEOUT: {exc}")
        return None, None, None, None
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return None, None, None, None
    finally:
        page.close()


# ─────────────────────────────────────────────
# Shipmentlink-specific scraper
# ─────────────────────────────────────────────

SHIPMENTLINK_ETA_STATUSES = [
    "vessel eta", "estimated arrival", "expected arrival", "expected", "eta",
    "vessel arrived", "ata", "actual arrival", "arrival", "discharged",
]
SHIPMENTLINK_PRE_ARRIVAL_STATUSES = {
    "vessel eta", "estimated arrival", "expected arrival", "expected", "eta",
}
SHIPMENTLINK_RAIL_STATUSES = [
    "rail", "on rail", "ramp arrival", "intermodal", "ramp", "train",
]
SHIPMENTLINK_PICKUP_STATUSES = [
    "pick-up by merchant haulage", "merchant haulage",
    "gate out", "full out", "out gate", "full gate out",
]
SHIPMENTLINK_RETURN_STATUSES = [
    "empty container returned", "empty return", "empty in", "gate in empty",
]

_CONTAINER_ID_RE = re.compile(r'\b[A-Z]{4}\d{7}\b', re.IGNORECASE)


_SHIPMENTLINK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)


def run_shipmentlink(browser, url, bol, container):
    """
    Shipmentlink (ct.shipmentlink.com) scraper.
    Uses a real-browser User-Agent and retries once on timeout.
    """
    for attempt in range(1, 3):
        context = browser.new_context(user_agent=_SHIPMENTLINK_UA)
        page = context.new_page()
        try:
            label = " (retry)" if attempt == 2 else ""
            print(f"    Loading {url}{label}")
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)

            try:
                if page.locator("#btn_cookie_accept_all").is_visible(timeout=2_000):
                    page.locator("#btn_cookie_accept_all").click()
                    page.wait_for_timeout(800)
            except Exception:
                pass

            page.locator("#s_bl").check()
            inp = page.locator("input#NO")
            inp.fill(bol)
            inp.press("Enter")
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except PlaywrightTimeout:
                pass
            page.wait_for_timeout(3_000)

            if bol not in page.inner_text("body"):
                print(f"    WARNING: B/L {bol} not found in results page")
                return None, None, None, None

            try:
                page.evaluate("getDispInfo('PickupRefTitle','PickupRefInfo')")
                page.wait_for_function(
                    "document.getElementById('PickupRefInfo') && "
                    "document.getElementById('PickupRefInfo').innerText.trim().length > 0",
                    timeout=8_000,
                )
            except Exception:
                pass
            page.wait_for_timeout(1_500)

            try:
                page.evaluate("getDispInfo('RlsStatusTitle','RlsStatusInfo')")
                page.wait_for_function(
                    "document.getElementById('RlsStatusInfo') && "
                    "document.getElementById('RlsStatusInfo').innerText.trim().length > 0",
                    timeout=5_000,
                )
            except Exception:
                pass
            page.wait_for_timeout(1_000)

            body_text = page.inner_text("body")
            lines = [l.strip() for l in body_text.split("\n") if l.strip()]
            container_upper = container.upper()

            # ── ETA ──────────────────────────────────────────────────────────────
            eta = None
            eta_status_kw = None
            for line in lines:
                if container_upper in line.upper():
                    ll = line.lower()
                    for kw in SHIPMENTLINK_ETA_STATUSES:
                        if kw in ll:
                            m = DATE_RE.search(line)
                            if m:
                                eta = m.group(0)
                                eta_status_kw = kw
                                break
                if eta:
                    break

            # ── Pickup Date — popup scrape ────────────────────────────────────────
            pickup = None
            pickup_status_kw = None
            popup_eta = None
            popup_eta_kw = None
            try:
                cont_link = page.locator(f"a:has-text('{container_upper}')").first
                if cont_link.is_visible(timeout=3_000):
                    with page.expect_popup(timeout=15_000) as popup_info:
                        cont_link.click()
                    popup = popup_info.value
                    try:
                        popup.wait_for_load_state("domcontentloaded", timeout=15_000)
                        popup.wait_for_timeout(2_000)
                        popup_lines = [
                            l.strip()
                            for l in popup.inner_text("body").split("\n")
                            if l.strip()
                        ]
                        popup_matches = []
                        for line in popup_lines:
                            ll = line.lower()
                            for kw in SHIPMENTLINK_PICKUP_STATUSES:
                                if kw in ll:
                                    m = DATE_RE.search(line)
                                    if m:
                                        popup_matches.append((m.group(0), kw))
                                    break
                        if popup_matches:
                            pickup, pickup_status_kw = popup_matches[-1]
                        print(f"    Popup pickup: {pickup!r}  (kw={pickup_status_kw!r})")

                        popup_eta_matches = []
                        for line in popup_lines:
                            ll = line.lower()
                            for kw in SHIPMENTLINK_ETA_STATUSES:
                                if kw in ll:
                                    m = DATE_RE.search(line)
                                    if m:
                                        popup_eta_matches.append((m.group(0), kw))
                                    break
                        if popup_eta_matches:
                            popup_eta, popup_eta_kw = popup_eta_matches[-1]
                        print(f"    Popup ETA:    {popup_eta!r}  (kw={popup_eta_kw!r})")
                    finally:
                        popup.close()
                else:
                    print(f"    WARNING: container link not visible for {container_upper}")
            except Exception as exc:
                print(f"    WARNING: pickup popup scrape failed: {exc}")

            if eta is None and popup_eta is not None:
                eta = popup_eta
                eta_status_kw = popup_eta_kw

            # ── Return Date ───────────────────────────────────────────────────────
            return_date = None
            return_status_kw = None
            for line in lines:
                if container_upper in line.upper():
                    ll = line.lower()
                    for kw in SHIPMENTLINK_RETURN_STATUSES:
                        if kw in ll:
                            m = DATE_RE.search(line)
                            if m:
                                return_date = m.group(0)
                                return_status_kw = kw
                                break
                if return_date:
                    break

            # ── Rail transit detection ────────────────────────────────────────────
            rail_detected = False
            for line in lines:
                if container_upper in line.upper():
                    ll = line.lower()
                    if any(kw in ll for kw in SHIPMENTLINK_RAIL_STATUSES):
                        rail_detected = True
                        break

            # ── Status dropdown value ─────────────────────────────────────────────
            if return_status_kw:
                status = SHIPMENTLINK_STATUS_MAP.get(return_status_kw, "Returned to Port")
            elif pickup_status_kw:
                status = SHIPMENTLINK_STATUS_MAP.get(pickup_status_kw, "Released")
            elif rail_detected:
                status = "Rail"
            elif eta_status_kw:
                if eta_status_kw in SHIPMENTLINK_PRE_ARRIVAL_STATUSES:
                    status = "Vessel"
                else:
                    status = SHIPMENTLINK_STATUS_MAP.get(eta_status_kw, "Vessel Arrived")
            else:
                status = None

            return eta, pickup, return_date, status

        except PlaywrightTimeout as exc:
            print(f"    TIMEOUT: {exc}")
            if attempt < 2:
                print(f"    Retrying once more...")
            else:
                return None, None, None, None
        except Exception as exc:
            print(f"    ERROR: {exc}")
            return None, None, None, None
        finally:
            page.close()
            context.close()

    return None, None, None, None


# ─────────────────────────────────────────────
# Hapag-Lloyd scraper
# ─────────────────────────────────────────────

def run_hapag_lloyd(browser, url, bol, container):
    """
    Hapag-Lloyd (hapag-lloyd.com) scraper.
    The site is Next.js/React — waits for hydration before looking for the input.
    """
    context = browser.new_context(user_agent=_SHIPMENTLINK_UA)
    page = context.new_page()
    try:
        print(f"    Loading {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        # Wait for React to render the tracking input
        try:
            page.wait_for_selector(
                "input[placeholder*='B/L' i], input[placeholder*='Container' i], input.hal-input",
                timeout=20_000,
            )
        except PlaywrightTimeout:
            print(f"    WARNING: Hapag-Lloyd form did not render in time")
            return None, None, None, None
        _dismiss_dialogs(page)
        input_loc = page.locator(
            "input[placeholder*='B/L' i], input[placeholder*='Container' i], input.hal-input"
        ).first
        _submit(page, input_loc, bol)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(2_000)
        eta, pickup, ret = _scrape_dates(page)
        status = "Returned to Port" if ret else "Released" if pickup else "Vessel" if eta else None
        return eta, pickup, ret, status
    except PlaywrightTimeout as exc:
        print(f"    TIMEOUT: {exc}")
        return None, None, None, None
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return None, None, None, None
    finally:
        page.close()
        context.close()


# ─────────────────────────────────────────────
# ONE Line scraper
# ─────────────────────────────────────────────

def run_one_line(browser, url, bol, container):
    """
    ONE Line (one-line.com) scraper.
    The site is Next.js/React with a tabbed search form — clicks the BL/Booking
    tab before filling the input.
    """
    context = browser.new_context(user_agent=_SHIPMENTLINK_UA)
    page = context.new_page()
    try:
        print(f"    Loading {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        # Wait for React to hydrate the search form
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(3_000)
        _dismiss_dialogs(page)
        # Click the BL / Booking No. search tab
        try:
            bl_tab = page.locator(
                "button:has-text('BL'), [role='tab']:has-text('BL'), "
                "button:has-text('B/L'), button:has-text('Booking')"
            ).first
            if bl_tab.is_visible(timeout=5_000):
                bl_tab.click()
                page.wait_for_timeout(1_000)
        except Exception:
            pass
        # Wait for the text input to appear and submit
        try:
            page.wait_for_selector("input[type='text'], input[type='search']", timeout=10_000)
        except PlaywrightTimeout:
            print(f"    WARNING: ONE Line form did not render in time")
            return None, None, None, None
        input_loc = page.locator("input[type='text'], input[type='search']").first
        _submit(page, input_loc, bol)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(3_000)
        eta, pickup, ret = _scrape_dates(page)
        status = "Returned to Port" if ret else "Released" if pickup else "Vessel" if eta else None
        return eta, pickup, ret, status
    except PlaywrightTimeout as exc:
        print(f"    TIMEOUT: {exc}")
        return None, None, None, None
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return None, None, None, None
    finally:
        page.close()
        context.close()


# ─────────────────────────────────────────────
# Workflow dispatcher
# ─────────────────────────────────────────────

def dray_import_workflow(browser, ws, sheet_row, url, bol, container):
    print(f"\n  [Dray Import] row {sheet_row} — Container: {container}  BOL: {bol}")
    url_lower = url.lower() if url else ""
    if "shipmentlink.com" in url_lower:
        eta, pickup, ret, status = run_shipmentlink(browser, url, bol, container)
    elif "hapag-lloyd.com" in url_lower:
        eta, pickup, ret, status = run_hapag_lloyd(browser, url, bol, container)
    elif "one-line.com" in url_lower:
        eta, pickup, ret, status = run_one_line(browser, url, bol, container)
    else:
        eta, pickup, ret, status = run_dray_import(browser, url, bol)
    print(f"    ETA={eta!r}  Pickup={pickup!r}  Return={ret!r}  Status={status!r}")
    write_tracking_results(ws, sheet_row, eta, pickup, ret, status)
    return eta, pickup, ret, status


# ─────────────────────────────────────────────
# State persistence
# ─────────────────────────────────────────────

def load_last_check():
    """Return the previously saved state dict, keyed by tab:container."""
    if os.path.exists(LAST_CHECK_FILE):
        try:
            with open(LAST_CHECK_FILE) as f:
                return json.load(f)
        except Exception as exc:
            print(f"  WARNING: Could not read {LAST_CHECK_FILE}: {exc}")
    return {}


def save_last_check(data):
    """Persist the current state dict to disk."""
    try:
        with open(LAST_CHECK_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        print(f"  WARNING: Could not save {LAST_CHECK_FILE}: {exc}")


# ─────────────────────────────────────────────
# Account lookup + tab discovery
# ─────────────────────────────────────────────

def load_account_lookup(sheet):
    """Read 'Account Rep' tab → dict mapping account_name → {rep, email}."""
    try:
        ws   = sheet.worksheet(ACCOUNT_LOOKUP_TAB)
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


def get_account_tabs(sheet, account_lookup):
    """Return tab titles that are in account_lookup and not in SKIP_TABS."""
    all_tabs = [ws.title for ws in sheet.worksheets()]
    tabs = [t for t in all_tabs if t not in SKIP_TABS and t in account_lookup]
    print(f"  Account tabs to process: {tabs}")
    return tabs


# ─────────────────────────────────────────────
# Email notification
# ─────────────────────────────────────────────

def _send_email(to_email, cc_email, subject, body):
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
        print(f"  Email sent → {to_email}  (cc: {cc_email or 'none'})")
    except Exception as exc:
        print(f"  WARNING: Email failed: {exc}")


def send_account_notification(account_name, account_lookup, changes):
    """Route a change-alert email to the rep assigned to this account tab."""
    if not changes:
        return

    info      = account_lookup.get(account_name, {})
    rep_email = info.get("email", "")
    rep_name  = info.get("rep",   "")

    if rep_email:
        to_email = rep_email
        cc_email = EMAIL_CC
    else:
        to_email = EMAIL_FALLBACK
        cc_email = None

    now     = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    subject = f"CSL Container Update — {account_name} — {now}"

    lines = [f"CSL Container Update — {account_name}", f"Generated: {now}"]
    if rep_name:
        lines.append(f"Rep: {rep_name}")
    lines.append("")

    for c in changes:
        field_str = ", ".join(c.get("changed_fields", []))
        lines.append(f"Container: {c.get('container') or 'N/A'}")
        lines.append(f"  ETA:    {c.get('eta') or '—'}")
        lines.append(f"  LFD:    {c.get('lfd') or '—'}")
        lines.append(f"  Status: {c.get('status') or '—'}")
        if c.get("return_date"):
            lines.append(f"  Return: {c['return_date']}")
        lines.append(f"  Changed: {field_str}")
        lines.append("")

    body = "\n".join(lines).strip()
    _send_email(to_email, cc_email, subject, body)


# ─────────────────────────────────────────────
# Archive helpers
# ─────────────────────────────────────────────

def _completed_tab_for(account_name, account_lookup):
    """Return 'Completed Eli', 'Completed Radka', or None based on rep name."""
    rep_name = account_lookup.get(account_name, {}).get("rep", "")
    rl = rep_name.lower()
    if "eli" in rl:
        return "Completed Eli"
    if "radka" in rl:
        return "Completed Radka"
    return None


def archive_completed_row(sheet, tab_name, sheet_row, row_data, url, eta, pickup,
                          return_date, status, account_lookup):
    """
    Copy the row to the rep's Completed tab, then delete it from the account tab.
    Performs a duplicate EFJ# check before appending.
    Sends an archive email to the rep, or writes a note to Col O if no email found.
    Returns True on full success, False on any failure or skip.
    """
    rep_info  = account_lookup.get(tab_name, {})
    rep_name  = rep_info.get("rep", "unknown")
    rep_email = rep_info.get("email", "")
    dest_tab  = _completed_tab_for(tab_name, account_lookup)
    efj_num   = (row_data[0].strip() if row_data else "") or ""
    container = (row_data[2].strip() if len(row_data) > 2 else "") or ""

    # ── No completed tab — write note to Col O on source tab, bail ───────────
    if not dest_tab:
        note = f"No completed tab for rep '{rep_name}' — manual archive needed"
        print(f"  WARNING: {note} (account '{tab_name}', row {sheet_row})")
        try:
            src_ws = sheet.worksheet(tab_name)
            src_ws.update_cell(sheet_row, COL_TIMESTAMP, note)
        except Exception as exc:
            print(f"  WARNING: Could not write fallback note to Col O: {exc}")
        return False

    try:
        dest_ws = sheet.worksheet(dest_tab)
    except Exception as exc:
        print(f"  WARNING: Could not open '{dest_tab}': {exc}")
        return False

    # ── Duplicate check — skip if EFJ# already in completed tab ──────────────
    if efj_num:
        try:
            existing_efjs = dest_ws.col_values(1)  # Col A
            if efj_num in existing_efjs:
                dup_note = (f"WARNING: EFJ# {efj_num} already in '{dest_tab}' "
                            f"— archive skipped")
                print(f"  {dup_note}")
                try:
                    src_ws = sheet.worksheet(tab_name)
                    src_ws.update_cell(sheet_row, COL_TIMESTAMP, dup_note)
                except Exception:
                    pass
                return False
        except Exception as exc:
            print(f"  WARNING: Duplicate EFJ# check failed: {exc}")

    # ── Build archive row — patch tracking columns with current values ────────
    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    row = list(row_data)
    max_col = max(COL_ETA, COL_PICKUP, COL_RETURN, COL_STATUS, COL_TIMESTAMP)
    while len(row) < max_col:
        row.append("")
    row[COL_ETA - 1]    = eta         or ""
    row[COL_PICKUP - 1] = pickup      or ""
    row[COL_RETURN - 1] = return_date or ""
    row[COL_STATUS - 1] = status      or ""
    # Col O: timestamp if we have an email to send, fallback note otherwise
    if rep_email:
        row[COL_TIMESTAMP - 1] = timestamp
    else:
        row[COL_TIMESTAMP - 1] = "No rep email found — alert not sent"

    # Reconstruct Col C as =HYPERLINK formula so the link is preserved
    if url and len(row) > 2:
        display      = row[2] or ""
        safe_url     = url.replace('"', '%22')
        safe_display = display.replace('"', "'")
        row[2] = f'=HYPERLINK("{safe_url}","{safe_display}")'

    # ── Append to completed tab ───────────────────────────────────────────────
    try:
        dest_ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"  Archived row {sheet_row} → '{dest_tab}'")
    except Exception as exc:
        print(f"  WARNING: Archive append failed for row {sheet_row}: {exc}")
        return False

    # ── Send archive email ────────────────────────────────────────────────────
    if rep_email:
        subject = f"CSL Archived | {efj_num} | {container} | Returned to Port"
        body = (
            f"Container {container} (EFJ# {efj_num}) has been archived.\n\n"
            f"Account:  {tab_name}\n"
            f"Rep:      {rep_name}\n\n"
            f"ETA:      {eta or '—'}\n"
            f"Pickup:   {pickup or '—'}\n"
            f"Returned: {return_date or '—'}\n"
            f"Status:   {status}\n"
            f"Archived: {timestamp}\n"
        )
        _send_email(rep_email, EMAIL_CC, subject, body)

    # ── Delete from source tab ────────────────────────────────────────────────
    try:
        src_ws = sheet.worksheet(tab_name)
        src_ws.delete_rows(sheet_row)
        print(f"  Deleted row {sheet_row} from '{tab_name}'")
    except Exception as exc:
        print(f"  WARNING: Delete failed for row {sheet_row} in '{tab_name}': {exc}")
        return False

    return True


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    sheet = gc.open_by_key(SHEET_ID)

    account_lookup = load_account_lookup(sheet)
    account_tabs   = get_account_tabs(sheet, account_lookup)

    if not account_tabs:
        print("No account tabs found to process.")
        return

    last_check = load_last_check()
    new_check  = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            proxy={
                "server":   "http://pr.oxylabs.io:7777",
                "username": "customer-CSLogix_raNhv-cc-US",
                "password": "MFDoom113+12",
            },
        )

        for tab_name in account_tabs:
            print(f"\n{'='*60}")
            print(f"Tab: {tab_name}")

            ws           = sheet.worksheet(tab_name)
            display_rows = ws.get_all_values()
            hyperlinks   = get_sheet_hyperlinks(creds, SHEET_ID, tab_name)

            if len(display_rows) < 2:
                print(f"  Empty or missing header — skipped.")
                continue

            # Headers on row 2 (index 1), data from row 3 (index 2)
            headers = display_rows[1]
            try:
                status_col = next(
                    i for i, h in enumerate(headers) if h.strip().lower() == "status"
                )
            except StopIteration:
                print(f"  ERROR: 'Status' column not found — skipped.")
                continue

            def _find_col(keyword, _h=headers):
                for i, h in enumerate(_h):
                    if keyword in h.strip().lower():
                        return i
                return None

            account_col = _find_col("account")
            rep_col     = _find_col("rep")
            print(f"  Columns — Account: {account_col}  Rep: {rep_col}  Status: {status_col}")
            print(f"  Data rows: {len(display_rows) - 2}")

            dray_jobs = []
            for row_idx, row in enumerate(display_rows[2:], start=2):
                if len(row) <= 1 or row[1].strip().lower() != "dray import":
                    continue
                sheet_row = row_idx + 1
                link_row  = hyperlinks[row_idx] if row_idx < len(hyperlinks) else []
                dray_jobs.append({
                    "sheet_row": sheet_row,
                    "container": row[2] if len(row) > 2 else "",
                    "url":       link_row[2] if len(link_row) > 2 else None,
                    "bol":       row[3] if len(row) > 3 else "",
                    "account":   row[account_col] if account_col is not None and len(row) > account_col else "",
                    "rep":       row[rep_col]     if rep_col     is not None and len(row) > rep_col     else "",
                    "row_data":  row,   # full row snapshot for archiving
                })

            print(f"  Dray Import rows: {len(dray_jobs)}")

            tab_changes  = []
            archive_jobs = []   # rows to copy→delete after all scraping is done
            for job in dray_jobs:
                if not job["url"]:
                    print(f"  Row {job['sheet_row']}: no URL — skipped.")
                    continue
                if not job["bol"]:
                    print(f"  Row {job['sheet_row']}: no BOL — skipped.")
                    continue

                eta, pickup, ret, status = dray_import_workflow(
                    browser, ws, job["sheet_row"], job["url"], job["bol"], job["container"]
                )

                container_id  = job["container"].strip() or f"row_{job['sheet_row']}"
                container_key = f"{tab_name}:{container_id}"

                current = {
                    "eta":         eta    or "",
                    "lfd":         pickup or "",
                    "return_date": ret    or "",
                    "status":      status or "",
                }
                new_check[container_key] = current

                prev           = last_check.get(container_key, {})
                changed_fields = [
                    field.replace("_", " ").title()
                    for field in ("eta", "lfd", "return_date", "status")
                    if current[field] != prev.get(field, "")
                ]

                if changed_fields:
                    tab_changes.append({
                        "container":      container_id,
                        "eta":            current["eta"],
                        "lfd":            current["lfd"],
                        "return_date":    current["return_date"],
                        "status":         current["status"],
                        "changed_fields": changed_fields,
                    })

                # Queue for archiving if container has been returned to port
                if status == "Returned to Port":
                    archive_jobs.append({
                        "sheet_row":   job["sheet_row"],
                        "row_data":    job["row_data"],
                        "url":         job["url"],
                        "eta":         eta,
                        "pickup":      pickup,
                        "return_date": ret,
                        "status":      status,
                        "container":   container_id,
                    })

            # ── Archive completed rows (bottom-to-top to keep row numbers valid) ──
            if archive_jobs:
                print(f"\n  Archiving {len(archive_jobs)} completed row(s)...")
                # Sort highest row number first so deletions don't shift lower rows
                for aj in sorted(archive_jobs, key=lambda j: j["sheet_row"], reverse=True):
                    ok = archive_completed_row(
                        sheet, tab_name, aj["sheet_row"], aj["row_data"],
                        aj["url"], aj["eta"], aj["pickup"], aj["return_date"],
                        aj["status"], account_lookup,
                    )
                    if ok:
                        # Remove from new_check — row no longer exists in the tab
                        archived_key = f"{tab_name}:{aj['container']}"
                        new_check.pop(archived_key, None)

            if tab_changes:
                print(f"\n  {len(tab_changes)} change(s) detected — sending email...")
                send_account_notification(tab_name, account_lookup, tab_changes)
            else:
                print(f"\n  No changes in '{tab_name}'.")

        browser.close()

    save_last_check(new_check)
    print("\nRun complete.")


if __name__ == "__main__":
    main()
