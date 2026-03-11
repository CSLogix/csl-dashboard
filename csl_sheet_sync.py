#!/usr/bin/env python3
"""
Two-way sync for shared Google Sheet accounts (Tolead + Boviet).

Reads from Google Sheets → updates Postgres if sheet is newer.
Reads from Postgres → writes back to sheet if Postgres is newer.

Usage:
    python3 csl_sheet_sync.py          # continuous (every 10 min)
    python3 csl_sheet_sync.py --once   # single run

Designed to run as cron or systemd service.
"""

import argparse
import json
import logging
from date_normalizer import clean_date
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
os.chdir("/root/csl-bot/csl-doc-tracker")

from dotenv import load_dotenv
load_dotenv("/root/csl-bot/.env")

import gspread
from google.oauth2.service_account import Credentials

import config
import database as db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [sheet_sync] %(message)s",
)
log = logging.getLogger("sheet_sync")

CREDS_FILE = "/root/csl-credentials.json"
BOVIET_SHEET_ID = "1OP-ZDaMCOsPxcxezHSPfN5ftUXlUcOjFgsfCQgDp3wI"

SYNC_INTERVAL = 600  # 10 minutes

# ---------------------------------------------------------------------------
# Same configs as app.py
# ---------------------------------------------------------------------------
BOVIET_SKIP_TABS = {"POCs", "Boviet Master"}
BOVIET_TAB_CONFIGS = {
    "DTE Fresh/Stock":  {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Sundance":         {"efj_col": 0, "load_id_col": 1, "status_col": 6},
    "Renewable Energy": {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Radiance Solar":   {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Piedra":           {"efj_col": 0, "load_id_col": 2, "status_col": 8,
                         "pickup_col": 6, "delivery_col": 7,
                         "phone_col": 11, "trailer_col": 12,
                         "default_origin": "Greenville, NC", "default_dest": "Mexia, TX",
                         "start_row": 45},
    "Hanson":           {"efj_col": 0, "load_id_col": 1, "status_col": 6,
                         "pickup_col": 4, "delivery_col": 5,
                         "phone_col": 8, "trailer_col": 10},
}

TOLEAD_HUB_CONFIGS = {
    "ORD": {
        "sheet_id": "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac",
        "tab": "Schedule",
        "cols": {"efj": 15, "load_id": 1, "status": 9, "origin": 6, "destination": 7,
                 "pickup_date": 4, "pickup_time": 5, "delivery": 3, "driver": 16, "phone": 17},
        "default_origin": "ORD", "start_row": 790,
    },
    "JFK": {
        "sheet_id": "1mfhEsK2zg6GWTqMDTo5VwCgY-QC1tkNPknurHMxtBhs",
        "tab": "Schedule",
        "cols": {"efj": 14, "load_id": 0, "status": 9, "origin": 6, "destination": 7,
                 "pickup_date": 3, "pickup_time": 4, "delivery": 5, "driver": 15, "phone": 16},
        "default_origin": "Garden City, NY", "start_row": 184,
    },
    "LAX": {
        "sheet_id": "1YLB6z5LdL0kFYTcfq_H5e6acU8-VLf8nN0XfZrJ-bXo",
        "tab": "LAX",
        "cols": {"efj": 0, "load_id": 3, "status": 9, "origin": 6, "destination": 7,
                 "pickup_date": 4, "pickup_time": 5, "delivery": 8, "driver": 11, "phone": 12},
        "default_origin": "Vernon, CA", "start_row": 755,
    },
    "DFW": {
        "sheet_id": "1RfGcq25x4qshlBDWDJD-xBJDlJm6fvDM_w2RTHhn9oI",
        "tab": "DFW",
        "cols": {"efj": 10, "load_id": 4, "status": 11, "origin": None, "destination": 3,
                 "pickup_date": 5, "pickup_time": 6, "delivery": 2, "driver": 12, "phone": 13},
        "default_origin": "Irving, TX", "start_row": 172,
    },
}


def _shorten_address(addr):
    if not addr:
        return addr


def _get_sheet_hyperlinks(creds, sheet_id, tab_name):
    """Fetch hyperlink URLs from a sheet tab via Sheets API v4."""
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

    addr = re.sub(r'^\(\w+\)\s*', '', addr).strip()
    addr = re.sub(r'\s*\([^)]*\)\s*$', '', addr).strip()
    m = re.search(r'([A-Za-z][A-Za-z .]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$', addr)
    if m:
        return f"{m.group(1).strip()}, {m.group(2)} {m.group(3)}"
    m = re.search(r'([A-Za-z][A-Za-z .]+),\s*([A-Z]{2})\s*$', addr)
    if m:
        return f"{m.group(1).strip()}, {m.group(2)}"
    return addr


def _get_pg_shipments(account: str, hub: str = None) -> dict:
    """Get all Postgres shipments for an account, keyed by EFJ."""
    with db.get_cursor() as cur:
        if hub:
            cur.execute(
                "SELECT * FROM shipments WHERE account = %s AND hub = %s",
                (account, hub),
            )
        else:
            cur.execute(
                "SELECT * FROM shipments WHERE account = %s",
                (account,),
            )
        rows = cur.fetchall()
    return {r["efj"]: dict(r) for r in rows}


def _upsert_shipment(data: dict):
    """Insert or update a Tolead/Boviet shipment in Postgres."""

    # Normalize date fields to MM-DD / MM-DD HH:MM
    for _df in ("eta", "lfd", "pickup_date", "delivery_date", "return_date"):
        if data.get(_df):
            data[_df] = clean_date(data[_df]) or data[_df]

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO shipments (
                    efj, move_type, container, bol, vessel, carrier,
                    origin, destination, eta, lfd, pickup_date, delivery_date,
                    status, notes, driver, bot_notes, return_date,
                    account, hub, rep, source, container_url, driver_phone,
                    sheet_row_index, sheet_synced_at
                ) VALUES (
                    %(efj)s, %(move_type)s, %(container)s, %(bol)s, %(vessel)s, %(carrier)s,
                    %(origin)s, %(destination)s, %(eta)s, %(lfd)s, %(pickup_date)s, %(delivery_date)s,
                    %(status)s, %(notes)s, %(driver)s, %(bot_notes)s, %(return_date)s,
                    %(account)s, %(hub)s, %(rep)s, %(source)s, %(container_url)s, %(driver_phone)s,
                    %(sheet_row_index)s, NOW()
                )
                ON CONFLICT (efj) DO UPDATE SET
                    status = COALESCE(NULLIF(EXCLUDED.status, ''), shipments.status),
                    pickup_date = COALESCE(NULLIF(EXCLUDED.pickup_date, ''), shipments.pickup_date),
                    delivery_date = COALESCE(NULLIF(EXCLUDED.delivery_date, ''), shipments.delivery_date),
                    driver = COALESCE(NULLIF(EXCLUDED.driver, ''), shipments.driver),
                    driver_phone = COALESCE(NULLIF(EXCLUDED.driver_phone, ''), shipments.driver_phone),
                    carrier = COALESCE(NULLIF(EXCLUDED.carrier, ''), shipments.carrier),
                    origin = COALESCE(NULLIF(EXCLUDED.origin, ''), shipments.origin),
                    destination = COALESCE(NULLIF(EXCLUDED.destination, ''), shipments.destination),
                    container = EXCLUDED.container,
                    container_url = COALESCE(NULLIF(EXCLUDED.container_url, ''), shipments.container_url),
                    sheet_row_index = EXCLUDED.sheet_row_index,
                    sheet_synced_at = NOW(),
                    updated_at = NOW()
            """, data)


def _a1(row_1based, col_0based):
    """Convert 1-based row + 0-based col to A1 notation (e.g. row=5, col=9 -> 'J5')."""
    col = col_0based + 1
    letters = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row_1based}"


def _batch_writeback(ws, updates):
    """
    Write cells back to a gspread worksheet.
    updates: list of (row_1based, col_0based, value)
    """
    if not updates:
        return
    payload = [{"range": _a1(r, c), "values": [[v]]} for r, c, v in updates]
    ws.batch_update(payload)


# ---------------------------------------------------------------------------
# Sync Tolead
# ---------------------------------------------------------------------------
def _write_driver_contact(efj, trailer="", phone=""):
    """Write trailer/phone to driver_contacts table (upsert)."""
    if not efj or (not trailer and not phone):
        return
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    INSERT INTO driver_contacts (efj, trailer_number, driver_phone)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (efj) DO UPDATE SET
                        trailer_number = COALESCE(NULLIF(EXCLUDED.trailer_number, ''), driver_contacts.trailer_number),
                        driver_phone = COALESCE(NULLIF(EXCLUDED.driver_phone, ''), driver_contacts.driver_phone),
                        updated_at = NOW()
                """, (efj, trailer or None, phone or None))
    except Exception as e:
        log.debug("driver_contact write for %s: %s", efj, e)


def sync_tolead(gc, creds):
    synced_from_sheet = 0
    synced_to_sheet = 0

    for hub_name, hub_cfg in TOLEAD_HUB_CONFIGS.items():
        try:
            time.sleep(1)
            hub_sh = gc.open_by_key(hub_cfg["sheet_id"])
            hub_ws = hub_sh.worksheet(hub_cfg["tab"])
            hub_rows = hub_ws.get_all_values()
            cols = hub_cfg["cols"]
            hub_start = hub_cfg.get("start_row", 1)
            lax_writebacks = []  # (row_1based, col_0based, value) — LAX only

            # Fetch hyperlinks for MP URLs from the EFJ column
            hub_links = _get_sheet_hyperlinks(creds, hub_cfg["sheet_id"], hub_cfg["tab"])

            # Get current Postgres state for this hub
            pg_map = _get_pg_shipments("Tolead", hub_name)

            for ri, row in enumerate(hub_rows[1:], start=2):
                if ri < hub_start:
                    continue

                def _cell(idx, r=row):
                    if idx is None:
                        return ""
                    return r[idx].strip() if len(r) > idx else ""

                efj = _cell(cols["efj"])
                load_id = _cell(cols["load_id"])
                status = _cell(cols["status"])

                if not load_id:
                    continue

                key = efj or load_id

                # If EFJ was assigned, clean up old load_id-keyed row to prevent duplicates
                if efj and load_id and efj != load_id:
                    try:
                        with db.get_conn() as _conn:
                            with db.get_cursor(_conn) as _cur:
                                # Migrate tracking_events from ghost to real EFJ
                                _cur.execute("UPDATE tracking_events SET efj = %s WHERE efj = %s", (efj, load_id))
                                migrated = _cur.rowcount
                                # Copy container_url from ghost if real record is empty
                                _cur.execute("""
                                    UPDATE shipments SET container_url = sub.container_url
                                    FROM (SELECT container_url FROM shipments WHERE efj = %s AND container_url != '') sub
                                    WHERE shipments.efj = %s AND (shipments.container_url IS NULL OR shipments.container_url = '')
                                """, (load_id, efj))
                                # Delete the ghost record
                                _cur.execute("DELETE FROM shipments WHERE efj = %s", (load_id,))
                                if _cur.rowcount > 0:
                                    log.info("Tolead %s: cleaned up ghost %s -> %s (migrated %d events)", hub_name, load_id, efj, migrated)
                    except Exception as de:
                        log.warning("Tolead %s: failed to clean up old row %s: %s", hub_name, load_id, de)

                # Extract Macropoint URL from hyperlink in the EFJ column
                mp_url = ""
                efj_col = cols["efj"]
                # hub_rows is 0-indexed but ri is 1-indexed (header at index 0)
                link_row_idx = ri - 1  # Convert sheet row to 0-indexed for hub_links
                if hub_links and link_row_idx < len(hub_links):
                    link_row = hub_links[link_row_idx]
                    if efj_col < len(link_row) and link_row[efj_col]:
                        mp_url = link_row[efj_col]

                origin = _shorten_address(_cell(cols["origin"]) or hub_cfg["default_origin"])
                pickup_date = _cell(cols["pickup_date"])
                pickup_time = _cell(cols["pickup_time"])
                pickup = f"{pickup_date} {pickup_time}".strip() if pickup_date else ""
                delivery = _cell(cols["delivery"])
                # cols["driver"] actually contains TRAILER data (per sheet layout)
                trailer_val = _cell(cols.get("driver")) if cols.get("driver") is not None else ""
                driver_phone = _cell(cols.get("phone")) if cols.get("phone") is not None else ""

                sheet_data = {
                    "efj": key,
                    "move_type": "FTL",
                    "container": load_id,
                    "bol": "",
                    "vessel": "",
                    "carrier": "",
                    "origin": origin,
                    "destination": _shorten_address(_cell(cols["destination"])),
                    "eta": pickup_date,
                    "lfd": "",
                    "pickup_date": pickup,
                    "delivery_date": delivery,
                    "status": status,
                    "notes": "",
                    "driver": "",
                    "bot_notes": "",
                    "return_date": "",
                    "account": "Tolead",
                    "hub": hub_name,
                    "rep": "Tolead",
                    "source": "sheet",
                    "container_url": mp_url,
                    "driver_phone": driver_phone,
                    "sheet_row_index": ri,
                }

                pg_row = pg_map.get(key)

                if not pg_row:
                    _upsert_shipment(sheet_data)
                    synced_from_sheet += 1
                else:
                    _merge_master_shipment(pg_row, sheet_data,
                                           syncable_fields=TOLEAD_BOVIET_SYNCABLE_FIELDS)
                    # LAX is internal-only — write PG dashboard edits back to sheet
                    if hub_name == "LAX":
                        _pg_updated = pg_row.get("updated_at")
                        _pg_synced = pg_row.get("sheet_synced_at")
                        if _pg_updated and _pg_synced and _pg_updated > _pg_synced:
                            if pg_row.get("status") and pg_row["status"] != status:
                                lax_writebacks.append((ri, cols["status"], pg_row["status"]))
                            _pg_pu = (pg_row.get("pickup_date") or "").strip()
                            _sh_pu = f"{pickup_date} {pickup_time}".strip() if pickup_date else ""
                            if _pg_pu and _pg_pu != _sh_pu:
                                lax_writebacks.append((ri, cols["pickup_date"], _pg_pu))
                            _pg_del = (pg_row.get("delivery_date") or "").strip()
                            _sh_del = delivery
                            if _pg_del and _pg_del != _sh_del:
                                lax_writebacks.append((ri, cols["delivery"], _pg_del))

                # Write trailer to driver_contacts (separate from shipments.driver)
                if trailer_val or driver_phone:
                    _write_driver_contact(key, trailer=trailer_val, phone=driver_phone)

            # Flush LAX write-backs (one batch API call per hub cycle)
            if hub_name == "LAX" and lax_writebacks:
                try:
                    _batch_writeback(hub_ws, lax_writebacks)
                    log.info("Tolead LAX: wrote back %d cell(s) to sheet", len(lax_writebacks))
                except Exception as _wb_err:
                    log.warning("Tolead LAX write-back failed: %s", _wb_err)

            log.info("Tolead %s: synced", hub_name)

        except Exception as e:
            log.error("Tolead %s sync failed: %s", hub_name, e)

    return synced_from_sheet, synced_to_sheet




# ---------------------------------------------------------------------------
# Sync Boviet
# ---------------------------------------------------------------------------
def sync_boviet(gc, creds):
    synced_from_sheet = 0
    synced_to_sheet = 0

    try:
        bov_sh = gc.open_by_key(BOVIET_SHEET_ID)
        bov_tabs = [ws.title for ws in bov_sh.worksheets()
                    if ws.title not in BOVIET_SKIP_TABS and ws.title in BOVIET_TAB_CONFIGS]
        bov_ranges = [f"'{t}'!A:Z" for t in bov_tabs]
        bov_batch = bov_sh.values_batch_get(bov_ranges)
        bov_value_ranges = bov_batch.get("valueRanges", [])

        pg_map = _get_pg_shipments("Boviet")
        boviet_writebacks = {t: [] for t in bov_tabs}  # per-tab write-back queue

        for vr, tab_name in zip(bov_value_ranges, bov_tabs):
            cfg = BOVIET_TAB_CONFIGS[tab_name]
            rows = vr.get("values", [])
            bov_start = cfg.get("start_row", 1)

            for ri, row in enumerate(rows[1:], start=2):
                if ri < bov_start:
                    continue
                efj = row[cfg["efj_col"]].strip() if len(row) > cfg["efj_col"] else ""
                load_id = row[cfg["load_id_col"]].strip() if len(row) > cfg["load_id_col"] else ""
                status = row[cfg["status_col"]].strip() if len(row) > cfg["status_col"] else ""
                if not efj:
                    continue

                bov_pickup = ""
                bov_delivery = ""
                bov_phone = ""
                bov_trailer = ""
                if "pickup_col" in cfg:
                    bov_pickup = row[cfg["pickup_col"]].strip() if len(row) > cfg["pickup_col"] else ""
                if "delivery_col" in cfg:
                    bov_delivery = row[cfg["delivery_col"]].strip() if len(row) > cfg["delivery_col"] else ""
                if "phone_col" in cfg:
                    bov_phone = row[cfg["phone_col"]].strip() if len(row) > cfg["phone_col"] else ""
                if "trailer_col" in cfg:
                    bov_trailer = row[cfg["trailer_col"]].strip() if len(row) > cfg["trailer_col"] else ""

                sheet_data = {
                    "efj": efj,
                    "move_type": "FTL",
                    "container": load_id,
                    "bol": "",
                    "vessel": "",
                    "carrier": "",
                    "origin": cfg.get("default_origin", ""),
                    "destination": cfg.get("default_dest", ""),
                    "eta": "",
                    "lfd": "",
                    "pickup_date": bov_pickup,
                    "delivery_date": bov_delivery,
                    "status": status,
                    "notes": "",
                    "driver": bov_trailer,
                    "bot_notes": "",
                    "return_date": "",
                    "account": "Boviet",
                    "hub": tab_name,
                    "rep": "Boviet",
                    "source": "sheet",
                    "container_url": "",
                    "driver_phone": bov_phone,
                    "sheet_row_index": ri,
                }

                pg_row = pg_map.get(efj)
                if not pg_row:
                    _upsert_shipment(sheet_data)
                    synced_from_sheet += 1
                else:
                    _merge_master_shipment(pg_row, sheet_data,
                                           syncable_fields=TOLEAD_BOVIET_SYNCABLE_FIELDS)
                    # All Boviet tabs are internal — write PG dashboard edits back
                    _pg_updated = pg_row.get("updated_at")
                    _pg_synced = pg_row.get("sheet_synced_at")
                    if _pg_updated and _pg_synced and _pg_updated > _pg_synced:
                        if pg_row.get("status") and pg_row["status"] != status:
                            boviet_writebacks[tab_name].append(
                                (ri, cfg["status_col"], pg_row["status"]))
                        if "pickup_col" in cfg:
                            _pg_pu = (pg_row.get("pickup_date") or "").strip()
                            _sh_pu = bov_pickup
                            if _pg_pu and _pg_pu != _sh_pu:
                                boviet_writebacks[tab_name].append(
                                    (ri, cfg["pickup_col"], _pg_pu))
                        if "delivery_col" in cfg:
                            _pg_del = (pg_row.get("delivery_date") or "").strip()
                            _sh_del = bov_delivery
                            if _pg_del and _pg_del != _sh_del:
                                boviet_writebacks[tab_name].append(
                                    (ri, cfg["delivery_col"], _pg_del))

            time.sleep(1)

        # Flush write-backs for this tab
        if boviet_writebacks.get(tab_name):
            try:
                ws_write = bov_sh.worksheet(tab_name)
                _batch_writeback(ws_write, boviet_writebacks[tab_name])
                log.info("Boviet %s: wrote back %d cell(s) to sheet",
                         tab_name, len(boviet_writebacks[tab_name]))
                time.sleep(0.5)
            except Exception as _wb_err:
                log.warning("Boviet %s write-back failed: %s", tab_name, _wb_err)

    except Exception as e:
        log.error("Boviet sync failed: %s", e)

    return synced_from_sheet, synced_to_sheet




# ---------------------------------------------------------------------------
# Master Sheet → PG Sync
# ---------------------------------------------------------------------------
MASTER_SHEET_ID = "19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0"

# Tabs to skip (non-account tabs)
MASTER_SKIP_TABS = {
    "Sheet14",
    "Completed Eli", "Completed Radka", "Completed John F",
    "Account Rep", "SSL Links", "Boviet",
}

# Master Sheet columns A-P (0-indexed) → PG field names
MASTER_COL_MAP = {
    0:  "efj",
    1:  "move_type",
    2:  "container",
    3:  "bol",
    4:  "vessel",
    5:  "carrier",
    6:  "origin",
    7:  "destination",
    8:  "eta",
    9:  "lfd",
    10: "pickup_date",
    11: "delivery_date",
    12: "status",
    13: "driver",
    14: "bot_notes",
    15: "return_date",
}

# Fields the sync is allowed to update (excludes metadata-only fields)
MASTER_SYNCABLE_FIELDS = [
    "move_type", "container", "bol", "vessel", "carrier",
    "origin", "destination", "eta", "lfd", "pickup_date",
    "delivery_date", "status", "driver", "bot_notes", "return_date",
]

# Fields the Tolead/Boviet sync is allowed to overwrite (no financial/ops fields)
TOLEAD_BOVIET_SYNCABLE_FIELDS = [
    "move_type", "container", "carrier", "origin", "destination",
    "pickup_date", "delivery_date", "status", "driver_phone", "container_url",
]


def _get_pg_master_shipments() -> dict:
    """Get all non-Tolead, non-Boviet PG shipments, keyed by EFJ."""
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT * FROM shipments WHERE account NOT IN ('Tolead', 'Boviet')"
        )
        rows = cur.fetchall()
    return {r["efj"]: dict(r) for r in rows}


def _get_rep_map(sh):
    """Read the Account Rep tab to get account→rep mapping."""
    rep_map = {}
    try:
        ws = sh.worksheet("Account Rep")
        rows = ws.get_all_values()
        for r in rows[2:]:
            if r and r[0].strip() and len(r) > 1 and r[1].strip():
                rep_map[r[0].strip()] = r[1].strip()
    except Exception as e:
        log.warning("Could not read Account Rep tab: %s", e)
    return rep_map


def _upsert_master_shipment(data: dict):
    """Insert a new shipment from Master Sheet into Postgres."""

    # Normalize date fields to MM-DD / MM-DD HH:MM
    for _df in ("eta", "lfd", "pickup_date", "delivery_date", "return_date"):
        if data.get(_df):
            data[_df] = clean_date(data[_df]) or data[_df]

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO shipments (
                    efj, move_type, container, bol, vessel, carrier,
                    origin, destination, eta, lfd, pickup_date, delivery_date,
                    status, notes, driver, bot_notes, return_date,
                    account, hub, rep, source, sheet_row_index, sheet_synced_at
                ) VALUES (
                    %(efj)s, %(move_type)s, %(container)s, %(bol)s, %(vessel)s, %(carrier)s,
                    %(origin)s, %(destination)s, %(eta)s, %(lfd)s, %(pickup_date)s, %(delivery_date)s,
                    %(status)s, '', %(driver)s, %(bot_notes)s, %(return_date)s,
                    %(account)s, '', %(rep)s, 'sheet', %(sheet_row_index)s, NOW()
                )
                ON CONFLICT (efj) DO NOTHING
            """, data)
            return cur.rowcount


def _merge_master_shipment(pg_row: dict, sheet_data: dict, syncable_fields=None):
    """
    Merge a sheet row with an existing PG row using timestamp-based conflict resolution.

    Rules:
    1. If PG was updated since last sync (updated_at > sheet_synced_at),
       PG wins — don't overwrite dashboard edits. But fill empty PG fields from sheet.
    2. If PG was NOT updated since last sync, sheet wins for non-empty fields.
    3. sheet_synced_at is always updated to NOW().
    """
    pg_updated = pg_row.get("updated_at")
    pg_synced = pg_row.get("sheet_synced_at")

    # Determine if PG was edited via dashboard/bot since last sync
    pg_is_newer = False
    if pg_updated and pg_synced and pg_updated > pg_synced:
        pg_is_newer = True

    # Pre-normalize sheet dates before merge comparison
    for _df in ("eta", "lfd", "pickup_date", "delivery_date", "return_date"):
        if sheet_data.get(_df):
            sheet_data[_df] = clean_date(sheet_data[_df]) or sheet_data[_df]

    updates = {}
    if syncable_fields is None:
        syncable_fields = MASTER_SYNCABLE_FIELDS
    for field in syncable_fields:
        sheet_val = (sheet_data.get(field) or "").strip()
        pg_val = (pg_row.get(field) or "").strip()

        if pg_is_newer:
            # PG was edited recently — only fill empty PG fields from sheet
            if not pg_val and sheet_val:
                updates[field] = sheet_val
        else:
            # Sheet is authoritative — non-empty sheet values overwrite PG
            if sheet_val and sheet_val != pg_val:
                updates[field] = sheet_val

    # Always sync metadata
    if sheet_data.get("account") and sheet_data["account"] != (pg_row.get("account") or ""):
        updates["account"] = sheet_data["account"]
    if sheet_data.get("rep") and sheet_data["rep"] != (pg_row.get("rep") or ""):
        updates["rep"] = sheet_data["rep"]
    if sheet_data.get("sheet_row_index"):
        updates["sheet_row_index"] = sheet_data["sheet_row_index"]

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            if updates:
                set_parts = [f"{k} = %({k})s" for k in updates]
                set_parts.append("sheet_synced_at = NOW()")
                updates["efj"] = sheet_data["efj"]
                cur.execute(
                    f"UPDATE shipments SET {', '.join(set_parts)} WHERE efj = %(efj)s",
                    updates,
                )
            else:
                # Just bump sync timestamp
                cur.execute(
                    "UPDATE shipments SET sheet_synced_at = NOW() WHERE efj = %s",
                    (sheet_data["efj"],),
                )


def sync_master(gc, creds):
    """Sync Master Track/Trace account tabs into Postgres."""
    synced_new = 0
    synced_updated = 0

    try:
        sh = gc.open_by_key(MASTER_SHEET_ID)

        # Get account→rep mapping
        rep_map = _get_rep_map(sh)

        # Get all tab names (skip non-account tabs)
        tabs = [ws.title for ws in sh.worksheets() if ws.title not in MASTER_SKIP_TABS]
        ranges = [f"'{t}'!A:P" for t in tabs]

        # Batch read all tabs
        batch_result = sh.values_batch_get(ranges)
        value_ranges = batch_result.get("valueRanges", [])

        # Get current PG state
        pg_map = _get_pg_master_shipments()

        for vr, tab_name in zip(value_ranges, tabs):
            rows = vr.get("values", [])
            if len(rows) < 2:
                continue

            # Detect header row (skip title rows with fewer filled cells)
            hdr_idx = 0
            if len(rows) > 1:
                r0_filled = sum(1 for c in rows[0] if c.strip()) if rows[0] else 0
                r1_filled = sum(1 for c in rows[1] if c.strip()) if rows[1] else 0
                if r1_filled > r0_filled:
                    hdr_idx = 1

            for ri, row in enumerate(rows[hdr_idx + 1:], start=hdr_idx + 2):
                def _cell(idx, r=row):
                    return r[idx].strip() if len(r) > idx else ""

                efj = _cell(0)
                if not efj:
                    continue
                # Skip rows that don't look like EFJ numbers
                if not efj.startswith("EFJ") and not efj.replace("-", "").isdigit():
                    continue

                sheet_data = {
                    "efj": efj,
                    "move_type": _cell(1),
                    "container": _cell(2),
                    "bol": _cell(3),
                    "vessel": _cell(4),
                    "carrier": _cell(5),
                    "origin": _cell(6),
                    "destination": _cell(7),
                    "eta": _cell(8),
                    "lfd": _cell(9),
                    "pickup_date": _cell(10),
                    "delivery_date": _cell(11),
                    "status": _cell(12),
                    "driver": _cell(13),
                    "bot_notes": _cell(14),
                    "return_date": _cell(15),
                    "account": tab_name,
                    "rep": rep_map.get(tab_name, "Unassigned"),
                    "sheet_row_index": ri,
                }

                pg_row = pg_map.get(efj)
                if not pg_row:
                    # New row from sheet → insert into PG
                    inserted = _upsert_master_shipment(sheet_data)
                    if inserted:
                        synced_new += 1
                else:
                    # Existing row — merge with conflict resolution
                    _merge_master_shipment(pg_row, sheet_data)
                    synced_updated += 1

        log.info("Master sync: %d new, %d checked/merged", synced_new, synced_updated)

    except Exception as e:
        log.error("Master Sheet sync failed: %s", e)

    return synced_new, 0

# ---------------------------------------------------------------------------
# Main sync loop
# ---------------------------------------------------------------------------
def run_sync():
    log.info("Starting sheet sync...")
    creds = Credentials.from_service_account_file(
        CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)

    t_from, t_to = sync_tolead(gc, creds)
    time.sleep(2)
    b_from, b_to = sync_boviet(gc, creds)
    time.sleep(2)
    m_from, m_to = sync_master(gc, creds)

    total_from = t_from + b_from + m_from
    total_to = t_to + b_to + m_to
    log.info(
        "Sync complete: %d from sheet → PG, %d from PG → sheet "
        "(Tolead: %d/%d, Boviet: %d/%d, Master: %d/%d)",
        total_from, total_to, t_from, t_to, b_from, b_to, m_from, m_to,
    )


def main():
    parser = argparse.ArgumentParser(description="CSL Sheet ↔ Postgres Sync")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    db.init_pool()
    log.info("Database pool initialized")

    if args.once:
        run_sync()
        return

    log.info("Running in continuous mode (every %ds)...", SYNC_INTERVAL)
    while True:
        try:
            run_sync()
        except Exception as e:
            log.error("Sync cycle failed: %s", e)
        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    main()
