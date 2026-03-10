"""
csl_sheet_writer.py — Shared Google Sheet write-back module for dual-write mode.

All writes are fire-and-forget: errors are logged but never raised.
This ensures PG remains the primary write path and sheet writes are best-effort.

Usage:
    from csl_sheet_writer import sheet_update_import, sheet_update_ftl, sheet_update_export

Deploy to: /root/csl-bot/csl_sheet_writer.py
"""

import os
import logging
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger("sheet_writer")

MASTER_SHEET_ID = "19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0"
CREDS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "/root/csl-credentials.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Master Tracker column letters (A-P)
COL_EFJ       = "A"
COL_CONTAINER = "C"
COL_ETA       = "I"
COL_PICKUP    = "K"
COL_DELIVERY  = "L"
COL_STATUS    = "M"
COL_DRIVER    = "N"
COL_BOTNOTES  = "O"
COL_RETURN    = "P"

# Tabs with non-standard column layout (16-col: Agent Alert at N, Return at O)
# These tabs are missing the extra Notes column that standard 17-col tabs have
TAB_COL_OVERRIDES = {
    "GW-World": {"COL_BOTNOTES": "N", "COL_RETURN": "O"},
    "Mamata":   {"COL_BOTNOTES": "N", "COL_RETURN": "O"},
}

def _tab_cols(account):
    """Return (COL_BOTNOTES, COL_RETURN) for a given account tab."""
    ov = TAB_COL_OVERRIDES.get(account, {})
    return (
        ov.get("COL_BOTNOTES", COL_BOTNOTES),
        ov.get("COL_RETURN",   COL_RETURN),
    )

def _fmt_eta(val):
    """Convert ISO date/datetime string to MM/DD for sheet display.
    e.g. '2026-03-10 06:00' → '03/10'  |  '2026-03-10' → '03/10'
    Returns original string if it can't be parsed (manual entries preserved).
    """
    if not val:
        return val
    try:
        # Works for '2026-03-10', '2026-03-10 06:00', '2026-03-10 06:00:00'
        dt = datetime.strptime(val.strip()[:10], "%Y-%m-%d")
        return dt.strftime("%m/%d")
    except Exception:
        return val  # leave manual entries (03/10, 26-Mar, etc.) untouched

# Module-level cache for gspread client (reused across calls within same process)
_gc = None

def _get_gc():
    """Lazy-init gspread client."""
    global _gc
    if _gc is None:
        try:
            creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
            _gc = gspread.authorize(creds)
        except Exception as e:
            log.error("Sheet auth failed: %s", e)
            return None
    return _gc


def _find_row_by_efj(ws, efj):
    """Find the row number for a given EFJ# in column A. Returns None if not found."""
    try:
        col_a = ws.col_values(1)  # Column A
        for i, val in enumerate(col_a):
            if val.strip() == efj.strip():
                return i + 1  # 1-indexed
    except Exception as e:
        log.error("Error searching for %s: %s", efj, e)
    return None


def sheet_update_import(efj, account, eta=None, pickup=None, return_date=None, status=None):
    """
    Write Dray Import tracking results back to the Master Sheet.
    Mirrors the old write_tracking_results() logic.
    """
    try:
        gc = _get_gc()
        if not gc:
            return
        sh = gc.open_by_key(MASTER_SHEET_ID)
        ws = sh.worksheet(account)
        row = _find_row_by_efj(ws, efj)
        if not row:
            log.warning("Sheet dual-write: %s not found in tab '%s'", efj, account)
            return

        timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
        _botnotes_col, _return_col = _tab_cols(account)

        # Batch update: ETA, Pickup, Return, Timestamp as RAW
        raw_updates = []
        if eta:
            raw_updates.append({"range": f"{COL_ETA}{row}", "values": [[_fmt_eta(eta)]]})
        if pickup:
            raw_updates.append({"range": f"{COL_PICKUP}{row}", "values": [[pickup]]})
        if return_date:
            raw_updates.append({"range": f"{_return_col}{row}", "values": [[return_date]]})
        raw_updates.append({"range": f"{_botnotes_col}{row}", "values": [[f"{timestamp} — {status}" if status else timestamp]]})

        if raw_updates:
            ws.batch_update(raw_updates, value_input_option="RAW")

        # Status as USER_ENTERED (so dropdown validates)
        if status:
            ws.batch_update(
                [{"range": f"{COL_STATUS}{row}", "values": [[status]]}],
                value_input_option="USER_ENTERED",
            )
            if status == "Returned to Port":
                ws.format(f"{COL_STATUS}{row}", {
                    "backgroundColor": {"red": 144/255, "green": 238/255, "blue": 144/255}
                })

        log.info("Sheet dual-write OK: %s [%s] eta=%s pickup=%s return=%s status=%s",
                 efj, account, eta, pickup, return_date, status)

    except Exception as e:
        log.error("Sheet dual-write FAILED for %s [%s]: %s", efj, account, e)


def sheet_update_export(efj, account, container=None, status=None, bot_notes=None):
    """
    Write Dray Export updates back to the Master Sheet.
    Primarily used for container discovery and status changes.
    """
    try:
        gc = _get_gc()
        if not gc:
            return
        sh = gc.open_by_key(MASTER_SHEET_ID)
        ws = sh.worksheet(account)
        row = _find_row_by_efj(ws, efj)
        if not row:
            log.warning("Sheet dual-write: %s not found in tab '%s'", efj, account)
            return

        _botnotes_col, _return_col = _tab_cols(account)
        updates = []
        if container:
            updates.append({"range": f"{COL_CONTAINER}{row}", "values": [[container]]})
        if bot_notes:
            updates.append({"range": f"{_botnotes_col}{row}", "values": [[bot_notes]]})

        if updates:
            ws.batch_update(updates, value_input_option="RAW")

        if status:
            ws.batch_update(
                [{"range": f"{COL_STATUS}{row}", "values": [[status]]}],
                value_input_option="USER_ENTERED",
            )

        log.info("Sheet dual-write OK: %s [%s] container=%s status=%s",
                 efj, account, container, status)

    except Exception as e:
        log.error("Sheet dual-write FAILED for %s [%s]: %s", efj, account, e)


def sheet_update_ftl(efj, account, pickup=None, delivery=None, status=None, driver=None):
    """
    Write FTL updates back to the Master Sheet.
    FTL loads are in the same Master Sheet under their account tab.
    """
    try:
        gc = _get_gc()
        if not gc:
            return
        sh = gc.open_by_key(MASTER_SHEET_ID)
        ws = sh.worksheet(account)
        row = _find_row_by_efj(ws, efj)
        if not row:
            log.warning("Sheet dual-write: %s not found in tab '%s'", efj, account)
            return

        timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
        _botnotes_col, _return_col = _tab_cols(account)

        raw_updates = []
        if pickup:
            raw_updates.append({"range": f"{COL_PICKUP}{row}", "values": [[pickup]]})
        if delivery:
            raw_updates.append({"range": f"{COL_DELIVERY}{row}", "values": [[delivery]]})
        if driver:
            raw_updates.append({"range": f"{COL_DRIVER}{row}", "values": [[driver]]})
        raw_updates.append({"range": f"{_botnotes_col}{row}", "values": [[f"{timestamp} — {status}" if status else timestamp]]})

        if raw_updates:
            ws.batch_update(raw_updates, value_input_option="RAW")

        if status:
            ws.batch_update(
                [{"range": f"{COL_STATUS}{row}", "values": [[status]]}],
                value_input_option="USER_ENTERED",
            )

        log.info("Sheet dual-write OK: %s [%s] pickup=%s delivery=%s status=%s",
                 efj, account, pickup, delivery, status)

    except Exception as e:
        log.error("Sheet dual-write FAILED for %s [%s]: %s", efj, account, e)


def sheet_archive_row(efj, account, rep=None):
    """
    Move a row from its account tab to the rep's Completed tab.
    Best-effort — if it fails, the row stays in the active tab.
    """
    try:
        gc = _get_gc()
        if not gc:
            return
        sh = gc.open_by_key(MASTER_SHEET_ID)
        ws = sh.worksheet(account)
        row = _find_row_by_efj(ws, efj)
        if not row:
            return

        row_data = ws.row_values(row)

        # Determine destination tab
        dest_tab = f"Completed {rep}" if rep else "Completed Eli"
        try:
            dest_ws = sh.worksheet(dest_tab)
        except gspread.WorksheetNotFound:
            log.warning("Sheet archive: tab '%s' not found, skipping", dest_tab)
            return

        dest_ws.append_row(row_data, value_input_option="RAW")
        ws.delete_rows(row)
        log.info("Sheet archive OK: %s moved from '%s' to '%s'", efj, account, dest_tab)

    except Exception as e:
        log.error("Sheet archive FAILED for %s [%s]: %s", efj, account, e)


# ═══ Generic Field Write-Back (Dashboard → Master Sheet) ═════════════════

# Map PG field names → Master Sheet column letters
PG_TO_SHEET_COL = {
    "move_type":     "B",
    "container":     "C",   # COL_CONTAINER
    "bol":           "D",   # BOL/Booking
    "vessel":        "E",   # SSL/Vessel
    "carrier":       "F",   # Carrier
    "origin":        "G",   # Origin
    "destination":   "H",   # Destination
    "eta":           "I",   # COL_ETA
    "lfd":           "J",   # LFD/Cutoff
    "pickup_date":   "K",   # COL_PICKUP
    "delivery_date": "L",   # COL_DELIVERY
    "status":        "M",   # COL_STATUS
    "driver":        "N",   # COL_DRIVER
    "bot_notes":     "O",   # COL_BOTNOTES
    "return_date":   "P",   # COL_RETURN
}


def sheet_update_field(efj, account, updates):
    """
    Generic field write-back to Master Sheet.

    Args:
        efj: The EFJ number (e.g., "EFJ107416")
        account: The account tab name (e.g., "Allround", "DHL")
        updates: Dict of PG field names to values,
                 e.g. {"carrier": "ABC Trucking", "eta": "2026-03-15"}

    Fire-and-forget: logs errors but never raises.
    """
    try:
        gc = _get_gc()
        if not gc:
            return
        sh = gc.open_by_key(MASTER_SHEET_ID)
        try:
            ws = sh.worksheet(account)
        except Exception:
            log.warning("Sheet write-back: tab '%s' not found in Master Sheet", account)
            return
        row = _find_row_by_efj(ws, efj)
        if not row:
            log.warning("Sheet write-back: %s not found in tab '%s'", efj, account)
            return

        # Separate status (USER_ENTERED) from other fields (RAW)
        raw_updates = []
        status_updates = []

        for field, value in updates.items():
            col = PG_TO_SHEET_COL.get(field)
            if not col:
                continue  # Field not mapped to a sheet column
            entry = {"range": f"{col}{row}", "values": [[value or ""]]}
            if field == "status":
                status_updates.append(entry)
            else:
                raw_updates.append(entry)

        if raw_updates:
            ws.batch_update(raw_updates, value_input_option="RAW")
        if status_updates:
            ws.batch_update(status_updates, value_input_option="USER_ENTERED")

        fields_written = [f for f in updates if f in PG_TO_SHEET_COL]
        log.info("Sheet write-back OK: %s [%s] fields=%s", efj, account, fields_written)

    except Exception as e:
        log.error("Sheet write-back FAILED for %s [%s]: %s", efj, account, e)


def sheet_add_row(efj, account, data):
    """
    Append a new load row to the Master Sheet account tab.

    Args:
        efj: The EFJ number
        account: The account tab name
        data: Dict with PG field names and values

    Fire-and-forget: logs errors but never raises.
    """
    try:
        gc = _get_gc()
        if not gc:
            return
        sh = gc.open_by_key(MASTER_SHEET_ID)
        try:
            ws = sh.worksheet(account)
        except Exception:
            log.warning("Sheet add-row: tab '%s' not found in Master Sheet", account)
            return

        # Check if EFJ already exists in sheet to avoid duplicates
        existing = _find_row_by_efj(ws, efj)
        if existing:
            log.info("Sheet add-row: %s already exists in '%s' row %d, skipping", efj, account, existing)
            return

        # Build row A-P (16 columns)
        row = [""] * 16
        col_map = {
            0: "efj", 1: "move_type", 2: "container", 3: "bol",
            4: "vessel", 5: "carrier", 6: "origin", 7: "destination",
            8: "eta", 9: "lfd", 10: "pickup_date", 11: "delivery_date",
            12: "status", 13: "driver", 14: "bot_notes", 15: "return_date",
        }
        for idx, field in col_map.items():
            if field == "efj":
                row[idx] = efj
            else:
                row[idx] = data.get(field, "") or ""

        ws.append_row(row, value_input_option="USER_ENTERED")
        log.info("Sheet add-row OK: %s → '%s'", efj, account)

    except Exception as e:
        log.error("Sheet add-row FAILED for %s [%s]: %s", efj, account, e)
