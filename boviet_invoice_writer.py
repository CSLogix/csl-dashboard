#!/usr/bin/env python3
"""
boviet_invoice_writer.py — Fills Piedra Invoice tab from Macropoint tracking data.

For each row in "Piedra Invoice" that has an EFJ/MP URL in col AA but is missing
stop-time data, this script:
  1. Scrapes Macropoint for stop1/stop2 Arrived+Departed timestamps
  2. Writes times to the sheet (HH:MM, 24-hr):
       G  = Arrival at warehouse     (stop1_arrived)
       I  = Unloading End at whse    (stop1_departed)
       L  = Arrival at site          (stop2_arrived)
       N  = Unloading End at site    (stop2_departed)
  3. Calculates detention (hours after 3 free):
       J  = max(0, round((col_I_hrs - col_F_hrs) - 3.0, 2))  whse waiting
       O  = max(0, round((col_N_hrs - col_K_hrs) - 3.0, 2))  site waiting

Only writes to cells that are currently empty — never overwrites existing data.
Rate: $50/hr.  Detention hours rounded to 2 decimal places.

Run modes:
  python3 boviet_invoice_writer.py --once        # single pass
  python3 boviet_invoice_writer.py               # daemon (every 2 hrs, 6AM-8PM)
  python3 boviet_invoice_writer.py --dry-run     # log what would be written, no writes
"""

import json
import os
import re
import sys
import time
import requests
import gspread
from datetime import datetime
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Import MP scraper from daily_summary (import-safe — all code under __main__ guard)
sys.path.insert(0, "/root/csl-bot")
from daily_summary import scrape_macropoint

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────
CREDENTIALS_FILE  = os.environ.get("GOOGLE_CREDENTIALS_FILE", "/root/csl-credentials.json")
BOVIET_SHEET_ID   = "1OP-ZDaMCOsPxcxezHSPfN5ftUXlUcOjFgsfCQgDp3wI"
INVOICE_TAB       = "Piedra Invoice"
DATA_START_ROW    = 4   # 0-indexed; rows 0-3 are title/header rows
POLL_INTERVAL_SEC = 2 * 60 * 60  # 2 hours
MP_COOKIES_FILE   = "/root/csl-bot/mp_cookies.json"

# Column indices (0-based)
COL_APPT_WHSE   = 5   # F — Appt Time at Warehouse
COL_ARRIVE_WHSE = 6   # G — Arrival at warehouse       ← bot writes
COL_LEAVE_WHSE  = 8   # I — Unloading End at whse      ← bot writes
COL_WAIT_WHSE   = 9   # J — whse Waiting hours         ← bot calculates
COL_APPT_SITE   = 10  # K — Appt Time at Site
COL_ARRIVE_SITE = 11  # L — Arrival at site            ← bot writes
COL_LEAVE_SITE  = 13  # N — Unloading End at Site      ← bot writes
COL_WAIT_SITE   = 14  # O — Site Waiting hours         ← bot calculates
COL_EFJ_MPURL   = 26  # AA — EFJ# (text) + MP URL (hyperlink)

FREE_HOURS = 3.0

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ── Time helpers ─────────────────────────────────────────────────────────────

def _mp_ts_to_hhmm(ts: str) -> str | None:
    """
    Convert Macropoint timestamp to HH:MM (24-hr) for sheet entry.
    Handles:  "03/11 10:27 CT"  →  "10:27"
              "3/11 8:05 ET"    →  "8:05"
    """
    if not ts:
        return None
    # Pattern: MM/DD HH:MM TZ
    m = re.search(r"\d{1,2}/\d{1,2}\s+(\d{1,2}:\d{2})", ts)
    if m:
        return m.group(1)
    # Fallback: bare HH:MM
    m2 = re.search(r"\b(\d{1,2}:\d{2})\b", ts)
    return m2.group(1) if m2 else None


def _time_to_hours(s: str) -> float | None:
    """
    Convert sheet time string to decimal hours.
    Handles: "7:30", "8:36", "8:30 AM", "2:00 PM", "14:00", "1:00 PM"
    Heuristic: bare "H:MM" with hour 1-6 is treated as PM (trucking appt times
    are virtually never 1-6 AM; avoids 12-hr misparse on sheet data without AM/PM).
    """
    if not s:
        return None
    s = s.strip()
    # 12-hour with AM/PM
    m12 = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", s, re.I)
    if m12:
        h, mi, meridiem = int(m12.group(1)), int(m12.group(2)), m12.group(3).upper()
        if meridiem == "PM" and h != 12:
            h += 12
        elif meridiem == "AM" and h == 12:
            h = 0
        return h + mi / 60.0
    # 24-hour HH:MM (or ambiguous bare "H:MM")
    m24 = re.match(r"(\d{1,2}):(\d{2})$", s)
    if m24:
        h, mi = int(m24.group(1)), int(m24.group(2))
        # Trucking heuristic: bare 1-6 → PM (1:00=13:00, 2:00=14:00, etc.)
        if 1 <= h <= 6:
            h += 12
        return h + mi / 60.0
    return None


def _detention_hours(departure_str: str, appt_str: str) -> float | None:
    """
    Calculate billable detention hours: max(0, (departure - appt) - FREE_HOURS).
    Returns None if either time cannot be parsed.
    """
    dep = _time_to_hours(departure_str)
    apt = _time_to_hours(appt_str)
    if dep is None or apt is None:
        return None
    dwell = dep - apt
    billable = max(0.0, round(dwell - FREE_HOURS, 2))
    return billable


def _a1(row_1based: int, col_0based: int) -> str:
    """Convert 1-based row + 0-based col to A1 notation."""
    col = col_0based + 1
    letters = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row_1based}"


# ── Sheet helpers ─────────────────────────────────────────────────────────────

def _load_mp_cookies() -> list | None:
    """Load Macropoint session cookies from file."""
    try:
        with open(MP_COOKIES_FILE) as f:
            cookies = json.load(f)
        for c in cookies:
            exp = c.get("expires", -1)
            if isinstance(exp, (int, float)) and exp > 1e12:
                c["expires"] = int(exp / 1e6)
            elif exp == 0 or exp is None:
                c["expires"] = -1
        return cookies
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _load_credentials():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds


def _get_hyperlinks(creds, tab: str) -> list[dict]:
    """
    Fetch hyperlinks from all cells in the tab.
    Returns list of dicts per row: {col_idx: hyperlink_url, ...}
    """
    encoded = requests.utils.quote(tab)
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{BOVIET_SHEET_ID}"
        f"?ranges={encoded}"
        f"&fields=sheets.data.rowData.values.hyperlink"
        f"&includeGridData=true"
    )
    resp = requests.get(
        url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=30
    )
    resp.raise_for_status()
    raw_rows = resp.json().get("sheets", [{}])[0].get("data", [{}])[0].get("rowData", [])
    result = []
    for row in raw_rows:
        vals = row.get("values", [])
        row_links = {}
        for ci, cell in enumerate(vals):
            link = cell.get("hyperlink", "")
            if link:
                row_links[ci] = link
        result.append(row_links)
    return result


def _cell(row: list, idx: int) -> str:
    return row[idx].strip() if len(row) > idx else ""


# ── Core logic ────────────────────────────────────────────────────────────────

def run_once(dry_run: bool = False):
    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    print(f"\n{'='*60}\nBoviet Invoice Writer — {now_str}")

    creds = _load_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(BOVIET_SHEET_ID)
    ws = sh.worksheet(INVOICE_TAB)

    rows = ws.get_all_values()
    hyperlinks = _get_hyperlinks(creds, INVOICE_TAB)

    # Identify rows that need the bot
    to_process = []
    for ri, row in enumerate(rows):
        if ri < DATA_START_ROW:
            continue

        efj = _cell(row, COL_EFJ_MPURL)
        if not efj or not efj.startswith("EFJ"):
            continue

        # Get MP URL from hyperlink on col AA
        mp_url = hyperlinks[ri].get(COL_EFJ_MPURL, "") if ri < len(hyperlinks) else ""
        if not mp_url or "macropoint" not in mp_url.lower():
            continue

        # Check what's missing
        g = _cell(row, COL_ARRIVE_WHSE)
        i_col = _cell(row, COL_LEAVE_WHSE)
        l_col = _cell(row, COL_ARRIVE_SITE)
        n_col = _cell(row, COL_LEAVE_SITE)

        if g and i_col and l_col and n_col:
            continue  # All times present — nothing to do

        to_process.append({
            "ri": ri,
            "efj": efj,
            "mp_url": mp_url,
            "row": row,
            "g": g, "i": i_col, "l": l_col, "n": n_col,
        })

    print(f"  Rows with EFJ+MP URL: {len(rows) - DATA_START_ROW} total, {len(to_process)} need bot")

    if not to_process:
        print("  Nothing to do.")
        return

    mp_cookies = _load_mp_cookies()
    updates = []  # (row_1based, col_0based, value)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for item in to_process:
                ri = item["ri"]
                efj = item["efj"]
                row = item["row"]
                mp_url = item["mp_url"]
                sheet_row = ri + 1  # 1-based for gspread

                print(f"\n  [{sheet_row}] {efj}")
                print(f"    URL: {mp_url[:70]}...")

                result = scrape_macropoint(browser, mp_url, mp_cookies)
                stop_times = result[-1] if isinstance(result[-1], dict) else {}

                s1_arr = stop_times.get("stop1_arrived")
                s1_dep = stop_times.get("stop1_departed")
                s2_arr = stop_times.get("stop2_arrived")
                s2_dep = stop_times.get("stop2_departed")

                print(f"    stop1: arrived={s1_arr}  departed={s1_dep}")
                print(f"    stop2: arrived={s2_arr}  departed={s2_dep}")

                row_updates = []

                # G — arrival at warehouse
                if not item["g"] and s1_arr:
                    t = _mp_ts_to_hhmm(s1_arr)
                    if t:
                        row_updates.append((sheet_row, COL_ARRIVE_WHSE, t))
                        print(f"    → G={t} (whse arrival)")

                # I — departure from warehouse
                if not item["i"] and s1_dep:
                    t = _mp_ts_to_hhmm(s1_dep)
                    if t:
                        row_updates.append((sheet_row, COL_LEAVE_WHSE, t))
                        print(f"    → I={t} (whse departure)")

                # J — warehouse detention (needs F appt + I departure)
                appt_whse = _cell(row, COL_APPT_WHSE)
                i_for_calc = _mp_ts_to_hhmm(s1_dep) if s1_dep else _cell(row, COL_LEAVE_WHSE)
                if not _cell(row, COL_WAIT_WHSE) and appt_whse and i_for_calc:
                    det = _detention_hours(i_for_calc, appt_whse)
                    if det is not None:
                        row_updates.append((sheet_row, COL_WAIT_WHSE, det))
                        print(f"    → J={det} (whse detention hrs)")

                # L — arrival at site
                if not item["l"] and s2_arr:
                    t = _mp_ts_to_hhmm(s2_arr)
                    if t:
                        row_updates.append((sheet_row, COL_ARRIVE_SITE, t))
                        print(f"    → L={t} (site arrival)")

                # N — departure from site
                if not item["n"] and s2_dep:
                    t = _mp_ts_to_hhmm(s2_dep)
                    if t:
                        row_updates.append((sheet_row, COL_LEAVE_SITE, t))
                        print(f"    → N={t} (site departure)")

                # O — site detention (needs K appt + N departure)
                appt_site = _cell(row, COL_APPT_SITE)
                n_for_calc = _mp_ts_to_hhmm(s2_dep) if s2_dep else _cell(row, COL_LEAVE_SITE)
                if not _cell(row, COL_WAIT_SITE) and appt_site and n_for_calc:
                    det = _detention_hours(n_for_calc, appt_site)
                    if det is not None:
                        row_updates.append((sheet_row, COL_WAIT_SITE, det))
                        print(f"    → O={det} (site detention hrs)")

                if not row_updates:
                    print("    No new data from MP")
                else:
                    updates.extend(row_updates)

        finally:
            browser.close()

    if not updates:
        print("\n  No updates to write.")
        return

    print(f"\n  Writing {len(updates)} cell(s) to sheet...")
    if dry_run:
        for r, c, v in updates:
            print(f"    DRY-RUN: {_a1(r, c)} = {v}")
    else:
        payload = [{"range": _a1(r, c), "values": [[v]]} for r, c, v in updates]
        ws.batch_update(payload)
        print(f"  Done — {len(updates)} cell(s) written.")


def main():
    print("Boviet Invoice Writer started — every 2 hrs, 6AM-8PM ET, Mon-Fri")
    while True:
        now_et = datetime.now(ZoneInfo("America/New_York"))
        hour = now_et.hour
        weekday = now_et.weekday()

        if weekday >= 5 or hour < 6 or hour >= 20:
            import math
            wake = now_et.replace(hour=6, minute=0, second=0, microsecond=0)
            if hour >= 20 or weekday >= 5:
                from datetime import timedelta
                wake += timedelta(days=1)
            while wake.weekday() >= 5:
                from datetime import timedelta
                wake += timedelta(days=1)
            sleep_secs = (wake - now_et).total_seconds()
            print(f"  Outside hours. Sleeping until {wake.strftime('%a 6 AM')}...")
            time.sleep(max(sleep_secs, 60))
            continue

        try:
            run_once()
        except Exception as exc:
            print(f"  ERROR: {exc}")

        print(f"  Sleeping {POLL_INTERVAL_SEC // 3600} hr(s)...")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        run_once(dry_run=True)
    elif "--once" in sys.argv:
        run_once()
    else:
        main()
