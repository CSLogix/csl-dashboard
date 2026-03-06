#!/usr/bin/env python3
"""
Postgres Migration — Phase 1: Create shipments table + import all Google Sheet data.

Run on server:
    python3 /tmp/patch_postgres_migration.py

Creates the `shipments` table in PostgreSQL and imports all rows from:
  - Master Tracker (all account tabs)
  - Boviet (all project tabs)
  - Tolead (ORD, JFK, LAX, DFW)
"""

import json
import logging
import os
import re
import sys
import time

# Add project to path
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
os.chdir("/root/csl-bot/csl-doc-tracker")

from dotenv import load_dotenv
load_dotenv("/root/csl-bot/.env")

import gspread
from google.oauth2.service_account import Credentials

import config
import database as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pg_migration")

# ---------------------------------------------------------------------------
# Sheet IDs (same as app.py)
# ---------------------------------------------------------------------------
SHEET_ID = "19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0"
BOVIET_SHEET_ID = "1OP-ZDaMCOsPxcxezHSPfN5ftUXlUcOjFgsfCQgDp3wI"
CREDS_FILE = "/root/csl-credentials.json"

SKIP_TABS = {
    "Sheet 4", "DTCELNJW", "Account Rep", "SSL Links",
    "Completed Eli", "Completed Radka", "Completed John F", "Boviet",
}

COL = {
    "efj": 0, "move_type": 1, "container": 2, "bol": 3,
    "ssl": 4, "carrier": 5, "origin": 6, "destination": 7,
    "eta": 8, "lfd": 9, "pickup": 10, "delivery": 11,
    "status": 12, "notes": 13, "bot_alert": 14, "return_port": 15,
}

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
BOVIET_DONE_STATUSES = {"delivered", "completed", "canceled", "cancelled", "ready to close"}

TOLEAD_HUB_CONFIGS = {
    "ORD": {
        "sheet_id": "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac",
        "tab": "Schedule",
        "cols": {"efj": 15, "load_id": 1, "status": 9, "origin": 6, "destination": 7,
                 "pickup_date": 4, "pickup_time": 5, "delivery": 3, "driver": 16, "phone": 17, "appt_id": 2},
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
                 "pickup_date": 5, "pickup_time": 6, "delivery": 2, "driver": 12, "phone": 13,
                 "appt_id": 1, "equipment": 8},
        "default_origin": "Irving, TX", "start_row": 172,
    },
}

TOLEAD_SKIP_STATUSES = {"delivered", "canceled", "cancelled"}


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


# ---------------------------------------------------------------------------
# Step 1: Create the shipments table
# ---------------------------------------------------------------------------
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS shipments (
    efj             TEXT PRIMARY KEY,
    move_type       TEXT,
    container       TEXT,
    bol             TEXT,
    vessel          TEXT,
    carrier         TEXT,
    origin          TEXT,
    destination     TEXT,
    eta             TEXT,
    lfd             TEXT,
    pickup_date     TEXT,
    delivery_date   TEXT,
    status          TEXT,
    notes           TEXT,
    bot_notes       TEXT,
    return_date     TEXT,
    driver          TEXT,
    driver_phone    TEXT,
    account         TEXT NOT NULL,
    hub             TEXT,
    rep             TEXT,
    source          TEXT DEFAULT 'sheet',
    customer_ref    TEXT,
    equipment_type  TEXT,
    container_url   TEXT,
    sheet_row_index INT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    archived        BOOLEAN DEFAULT FALSE,
    archived_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_shipments_account ON shipments(account);
CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status);
CREATE INDEX IF NOT EXISTS idx_shipments_rep ON shipments(rep);
CREATE INDEX IF NOT EXISTS idx_shipments_hub ON shipments(hub);
CREATE INDEX IF NOT EXISTS idx_shipments_archived ON shipments(archived);
"""


def create_table():
    log.info("Creating shipments table...")
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(CREATE_TABLE_SQL)
    log.info("shipments table ready")


# ---------------------------------------------------------------------------
# Step 2: Import data from Google Sheets
# ---------------------------------------------------------------------------
def import_from_sheets():
    creds = Credentials.from_service_account_file(
        CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)

    all_rows = []

    # ── Master Tracker ──
    log.info("Reading Master Tracker...")
    sh = gc.open_by_key(SHEET_ID)

    # Load rep map
    rep_map = {}
    try:
        rep_rows = sh.worksheet("Account Rep").get_all_values()
        for r in rep_rows[2:]:
            if r[0].strip() and len(r) > 1 and r[1].strip():
                rep_map[r[0].strip()] = r[1].strip()
    except Exception as e:
        log.warning("Could not load rep map: %s", e)

    tabs = [ws.title for ws in sh.worksheets() if ws.title not in SKIP_TABS]
    ranges = [f"'{t}'!A:P" for t in tabs]
    batch_result = sh.values_batch_get(ranges)
    value_ranges = batch_result.get("valueRanges", [])

    master_count = 0
    for vr, tab_name in zip(value_ranges, tabs):
        rows = vr.get("values", [])
        if len(rows) < 2:
            continue
        # Detect header row
        hdr_idx = 0
        if len(rows) > 1:
            r0 = sum(1 for c in rows[0] if c.strip())
            r1 = sum(1 for c in rows[1] if c.strip())
            if r1 > r0:
                hdr_idx = 1
        for ri, row in enumerate(rows[hdr_idx + 1:], start=hdr_idx + 2):
            efj = row[COL["efj"]].strip() if len(row) > COL["efj"] else ""
            ctr = row[COL["container"]].strip() if len(row) > COL["container"] else ""
            if not efj and not ctr:
                continue

            def cell(key, r=row):
                idx = COL[key]
                return r[idx].strip() if len(r) > idx else ""

            all_rows.append({
                "efj": efj,
                "move_type": cell("move_type"),
                "container": ctr,
                "bol": cell("bol"),
                "vessel": cell("ssl"),
                "carrier": cell("carrier"),
                "origin": cell("origin"),
                "destination": cell("destination"),
                "eta": cell("eta"),
                "lfd": cell("lfd"),
                "pickup_date": cell("pickup"),
                "delivery_date": cell("delivery"),
                "status": cell("status"),
                "notes": cell("notes"),       # Col N (13) = Notes
                "bot_notes": cell("bot_alert"),  # Col O (14) = Agent Alert
                "return_date": cell("return_port"),  # Col P (15) = Return to Port
                "driver": "",
                "account": tab_name,
                "hub": None,
                "rep": rep_map.get(tab_name, "Unassigned"),
                "source": "sheet",
                "container_url": "",
                "driver_phone": "",
                "sheet_row_index": ri,
            })
            master_count += 1

    log.info("Master Tracker: %d rows from %d tabs", master_count, len(tabs))
    time.sleep(2)

    # ── Boviet ──
    log.info("Reading Boviet...")
    boviet_count = 0
    try:
        bov_sh = gc.open_by_key(BOVIET_SHEET_ID)
        bov_tabs = [ws.title for ws in bov_sh.worksheets()
                    if ws.title not in BOVIET_SKIP_TABS and ws.title in BOVIET_TAB_CONFIGS]
        bov_ranges = [f"'{t}'!A:Z" for t in bov_tabs]
        bov_batch = bov_sh.values_batch_get(bov_ranges)
        bov_value_ranges = bov_batch.get("valueRanges", [])

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

                all_rows.append({
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
                })
                boviet_count += 1
            time.sleep(1)
    except Exception as e:
        log.error("Boviet import failed: %s", e)

    log.info("Boviet: %d rows", boviet_count)
    time.sleep(2)

    # ── Tolead (all hubs) ──
    log.info("Reading Tolead hubs...")
    tolead_count = 0
    for hub_name, hub_cfg in TOLEAD_HUB_CONFIGS.items():
        try:
            time.sleep(1)
            hub_sh = gc.open_by_key(hub_cfg["sheet_id"])
            hub_ws = hub_sh.worksheet(hub_cfg["tab"])
            hub_rows = hub_ws.get_all_values()
            cols = hub_cfg["cols"]
            hub_start = hub_cfg.get("start_row", 1)

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

                origin = _shorten_address(_cell(cols["origin"]) or hub_cfg["default_origin"])
                pickup_date = _cell(cols["pickup_date"])
                pickup_time = _cell(cols["pickup_time"])
                pickup = f"{pickup_date} {pickup_time}".strip() if pickup_date else ""
                delivery = _cell(cols["delivery"])
                driver_trailer = _cell(cols.get("driver")) if cols.get("driver") is not None else ""
                driver_phone = _cell(cols.get("phone")) if cols.get("phone") is not None else ""

                all_rows.append({
                    "efj": efj or load_id,
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
                })
                tolead_count += 1
            log.info("Tolead %s: %d rows", hub_name, tolead_count)
        except Exception as e:
            log.error("Tolead %s import failed: %s", hub_name, e)

    log.info("Tolead total: %d rows", tolead_count)

    # ── Insert into Postgres ──
    log.info("Inserting %d rows into shipments table...", len(all_rows))

    # Deduplicate by EFJ (keep last occurrence, which is most recent)
    seen = {}
    for row in all_rows:
        efj = row["efj"]
        if efj:
            seen[efj] = row
    deduped = list(seen.values())
    log.info("After dedup: %d unique EFJs", len(deduped))

    inserted = 0
    skipped = 0
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            for row in deduped:
                try:
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
                            move_type = EXCLUDED.move_type,
                            container = EXCLUDED.container,
                            bol = EXCLUDED.bol,
                            vessel = EXCLUDED.vessel,
                            carrier = EXCLUDED.carrier,
                            origin = EXCLUDED.origin,
                            destination = EXCLUDED.destination,
                            eta = EXCLUDED.eta,
                            lfd = EXCLUDED.lfd,
                            pickup_date = EXCLUDED.pickup_date,
                            delivery_date = EXCLUDED.delivery_date,
                            status = EXCLUDED.status,
                            notes = EXCLUDED.notes,
                            driver = EXCLUDED.driver,
                            bot_notes = EXCLUDED.bot_notes,
                            return_date = EXCLUDED.return_date,
                            account = EXCLUDED.account,
                            hub = EXCLUDED.hub,
                            rep = EXCLUDED.rep,
                            container_url = EXCLUDED.container_url,
                            driver_phone = EXCLUDED.driver_phone,
                            sheet_row_index = EXCLUDED.sheet_row_index,
                            updated_at = NOW()
                    """, row)
                    inserted += 1
                except Exception as e:
                    log.warning("Insert failed for EFJ %s: %s", row.get("efj"), e)
                    skipped += 1

    log.info("=" * 60)
    log.info("MIGRATION COMPLETE")
    log.info("  Imported: %d rows", inserted)
    log.info("  Skipped:  %d rows", skipped)
    log.info("  Sources:  Master=%d  Boviet=%d  Tolead=%d", master_count, boviet_count, tolead_count)
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("Initializing database pool...")
    db.init_pool()

    # Verify DB connection
    with db.get_cursor() as cur:
        cur.execute("SELECT 1")
        log.info("Database connection OK")

    create_table()
    import_from_sheets()

    log.info("Done. Verify with: SELECT account, count(*) FROM shipments GROUP BY account ORDER BY count DESC;")
