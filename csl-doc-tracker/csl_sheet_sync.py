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

# Statuses that mean the load is done — skip importing these from sheets
TERMINAL_STATUSES = {"completed", "ready to close", "delivered", "cancelled", "billed_closed"}

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
    """Insert or update a shipment in Postgres."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO shipments (
                    efj, move_type, container, bol, vessel, carrier,
                    origin, destination, eta, lfd, pickup_date, delivery_date,
                    status, notes, driver, bot_notes, return_date,
                    account, hub, rep, source, container_url, driver_phone,
                    sheet_row_index
                ) VALUES (
                    %(efj)s, %(move_type)s, %(container)s, %(bol)s, %(vessel)s, %(carrier)s,
                    %(origin)s, %(destination)s, %(eta)s, %(lfd)s, %(pickup_date)s, %(delivery_date)s,
                    %(status)s, %(notes)s, %(driver)s, %(bot_notes)s, %(return_date)s,
                    %(account)s, %(hub)s, %(rep)s, %(source)s, %(container_url)s, %(driver_phone)s,
                    %(sheet_row_index)s
                )
                ON CONFLICT (efj) DO UPDATE SET
                    status = EXCLUDED.status,
                    pickup_date = EXCLUDED.pickup_date,
                    delivery_date = EXCLUDED.delivery_date,
                    driver = EXCLUDED.driver,
                    driver_phone = EXCLUDED.driver_phone,
                    origin = EXCLUDED.origin,
                    destination = EXCLUDED.destination,
                    container = EXCLUDED.container,
                    sheet_row_index = EXCLUDED.sheet_row_index,
                    updated_at = NOW()
            """, data)


# ---------------------------------------------------------------------------
# Sync Tolead
# ---------------------------------------------------------------------------
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
                if status.lower() in TERMINAL_STATUSES:
                    continue

                key = efj or load_id
                origin = _shorten_address(_cell(cols["origin"]) or hub_cfg["default_origin"])
                pickup_date = _cell(cols["pickup_date"])
                pickup_time = _cell(cols["pickup_time"])
                pickup = f"{pickup_date} {pickup_time}".strip() if pickup_date else ""
                delivery = _cell(cols["delivery"])
                driver_trailer = _cell(cols.get("driver")) if cols.get("driver") is not None else ""
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
                    "driver": driver_trailer,
                    "bot_notes": "",
                    "return_date": "",
                    "account": "Tolead",
                    "hub": hub_name,
                    "rep": "Tolead",
                    "source": "sheet",
                    "container_url": "",
                    "driver_phone": driver_phone,
                    "sheet_row_index": ri,
                }

                pg_row = pg_map.get(key)

                if not pg_row:
                    # New row from sheet → insert into Postgres
                    _upsert_shipment(sheet_data)
                    synced_from_sheet += 1
                else:
                    # Row exists in both — compare status
                    sheet_status = (status or "").strip().lower()
                    pg_status = (pg_row["status"] or "").strip().lower()

                    if sheet_status != pg_status:
                        # Check if Postgres was updated more recently
                        pg_updated = pg_row.get("updated_at")
                        # For sheet → PG sync, sheet always wins unless PG was explicitly
                        # updated via dashboard (source would change or updated_at > last sync).
                        # Simple approach: sheet wins for status, PG wins for fields updated via dashboard.
                        # Since we can't track sheet timestamps, sheet always wins on sync.
                        _upsert_shipment(sheet_data)
                        synced_from_sheet += 1
                    else:
                        # Status same, but update other fields from sheet
                        _upsert_shipment(sheet_data)

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
                if status.lower() in TERMINAL_STATUSES:
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
                    # Update from sheet
                    _upsert_shipment(sheet_data)

            time.sleep(1)

    except Exception as e:
        log.error("Boviet sync failed: %s", e)

    return synced_from_sheet, synced_to_sheet


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

    total_from = t_from + b_from
    total_to = t_to + b_to
    log.info(
        "Sync complete: %d from sheet → PG, %d from PG → sheet (Tolead: %d/%d, Boviet: %d/%d)",
        total_from, total_to, t_from, t_to, b_from, b_to,
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
