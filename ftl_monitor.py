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
import time
from csl_logging import get_logger
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

import psycopg2
import psycopg2.extras
from csl_pg_writer import pg_update_shipment, pg_archive_shipment
from csl_sheet_writer import sheet_update_ftl, sheet_archive_row
from csl_ftl_alerts import (
    ACCOUNT_REPS_PG, STATUS_TO_DROPDOWN,
    _send_pod_reminder_ftl,
)


log = get_logger("ftl_monitor")


# ── Config ──────────────────────────────────────────────────────────────────────
TRACKING_CACHE_FILE = "/root/csl-bot/ftl_tracking_cache.json"
POLL_INTERVAL       = 30 * 60  # seconds

# ── SMTP / email ─────────────────────────────────────────────────────────────────


# ── Postgres ─────────────────────────────────────────────────────────────────────
from dotenv import load_dotenv as _pg_load_dotenv

# ── Status hierarchy: higher number = further along in lifecycle ──
_STATUS_RANK = {
    "Tracking Started": 1,
    "Tracking Waiting for Update": 2,
    "Driver Phone Unresponsive": 2,
    "Driver Arrived at Pickup": 3,
    "At Pickup": 3,
    "Departed Pickup - En Route": 4,
    "In Transit": 4,
    "Running Late": 4,
    "Tracking Behind Schedule": 4,
    "Arrived at Delivery": 5,
    "At Delivery": 5,
    "Departed Delivery": 6,
    "Delivered": 7,
    "Tracking Completed Successfully": 8,
}

_TERMINAL_STATUSES = {"Delivered", "Tracking Completed Successfully", "Billed/Closed", "billed_closed"}

def _status_is_regression(old_status, new_status):
    """Return True if new_status is a regression from old_status."""
    old_rank = _STATUS_RANK.get(old_status, 0)
    new_rank = _STATUS_RANK.get(new_status, 0)
    return new_rank > 0 and old_rank > 0 and new_rank < old_rank

_pg_load_dotenv("/root/csl-bot/csl-doc-tracker/.env")

def _pg_connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "csl_dispatch"),
        user=os.getenv("DB_USER", "csl_user"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def _find_cache_entry(cache, efj):
    """Find a tracking cache entry matching the given EFJ."""
    efj_clean = efj.replace("EFJ", "").strip()
    if efj in cache:
        return efj, cache[efj]
    if efj_clean in cache:
        return efj_clean, cache[efj_clean]
    for key, entry in cache.items():
        entry_efj = entry.get("efj", "")
        if (entry_efj == efj or entry_efj == efj_clean or
                entry.get("mp_load_id") == efj or entry.get("mp_load_id") == efj_clean):
            return key, entry
    return None, None


def _build_note(existing_notes: str, new_part: str) -> str:
    today    = datetime.now(ZoneInfo("America/New_York")).strftime("%m-%d")
    base     = re.sub(r"\s*—\s*updated\s*\d{2}-\d{2}\s*$", "", existing_notes).strip()
    combined = f"{base}, {new_part}".lstrip(", ") if base else new_part
    return f"{combined} — updated {today}"


# ── Alert dedup ──────────────────────────────────────────────────────────────────




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






# ── Archive (Postgres only) ────────────────────────────────────────────────────
def archive_ftl_row_pg(efj, load_num, dest, tab_name, pickup_val, delivery_val,
                       account_lookup, mp_load_id=None, stop_times=None):
    """Archive FTL row — Postgres only (no sheet writes)."""
    rep_info = account_lookup.get(tab_name, {})
    rep_name = rep_info.get("rep", "")
    try:
        pg_archive_shipment(efj)
        sheet_archive_row(efj, tab_name, rep=rep_name)
        log.info("Archived load (Delivered)", extra={"efj": efj})

        # Send POD reminder
        _send_pod_reminder_ftl(efj, load_num, dest, tab_name, account_lookup, mp_load_id=mp_load_id)
        return True
    except Exception as e:
        log.warning("Archive failed", extra={"efj": efj, "error": str(e)})
        return False



def run_once():
    """FTL poll cycle — reads from Postgres, checks webhook-updated tracking cache."""
    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    log.info("FTL poll cycle (Postgres mode)")

    # ── Read active FTL loads from Postgres ────────────────────────────────
    conn = None
    try:
        conn = _pg_connect()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT efj, container, bol, vessel, carrier, origin, destination,
                       CAST(eta AS TEXT) AS eta, CAST(lfd AS TEXT) AS lfd,
                       CAST(pickup_date AS TEXT) AS pickup_date,
                       CAST(delivery_date AS TEXT) AS delivery_date,
                       status, bot_notes, account, rep
                FROM shipments
                WHERE move_type = 'FTL' AND archived = FALSE
                ORDER BY account, efj
            """)
            all_loads = cur.fetchall()
    except Exception as exc:
        log.error("Could not read from Postgres", extra={"error": str(exc)})
        return
    finally:
        if conn is not None:
            conn.close()

    # Group by account
    from collections import defaultdict
    by_account = defaultdict(list)
    for row in all_loads:
        acct = row["account"] or "Unknown"
        by_account[acct].append(row)

    account_tabs = sorted(by_account.keys())
    log.info("Loaded active FTL loads", extra={"load_count": len(all_loads), "account_count": len(account_tabs)})
    if not account_tabs:
        log.info("No active FTL loads found")
        return

    tracking_cache = load_tracking_cache()

    for tab_name in account_tabs:
        loads = by_account[tab_name]
        log.info("Checking account", extra={"tab": tab_name, "row_count": len(loads)})

        for row in loads:
            efj = (row["efj"] or "").strip()
            container = (row["container"] or "").strip()
            load_num = container or efj  # FTL uses container/load# as identifier
            dest = (row["destination"] or "").strip()
            existing_pickup = (row["pickup_date"] or "").strip()
            existing_delivery = (row["delivery_date"] or "").strip()
            existing_status = (row["status"] or "").strip()
            existing_notes = (row["bot_notes"] or "").strip()

            if not efj:
                continue

            key = f"{efj}|{load_num}"

            # ── Find or initialize cache entry ────────────────────────────
            cache_key, cached = _find_cache_entry(tracking_cache, efj)
            if cached is None:
                # Initialize so webhook can update it later
                cache_key = efj.replace("EFJ", "").strip()
                tracking_cache[cache_key] = {
                    "efj": efj,
                    "load_num": load_num,
                    "status": existing_status,
                    "mp_load_id": efj,
                    "cant_make_it": None,
                    "stop_times": {},
                    "macropoint_url": "",
                    "last_scraped": "",
                    "driver_phone": "",
                }
                cached = tracking_cache[cache_key]
                log.info("Initialized cache entry", extra={"efj": efj, "load_num": load_num})

            cached_status = cached.get("status", "")
            stop_times = cached.get("stop_times", {})
            mp_load_id = cached.get("mp_load_id", "")
            cant_make_it = cached.get("cant_make_it")
            driver_phone = cached.get("driver_phone", "")

            log.info("Processing load", extra={"efj": efj, "load_num": load_num, "cached_status": cached_status, "pg_status": existing_status})

            if not cached_status:
                continue  # No webhook data yet

            # ── Map webhook status to dropdown ────────────────────────────
            dropdown_val = STATUS_TO_DROPDOWN.get(cached_status)

            note_parts = []
            final_pickup = existing_pickup
            final_delivery = existing_delivery
            final_notes = existing_notes

            # Extract dates from stop_times (webhook provides these)
            stop1_date = stop_times.get("stop1_arrived")
            stop2_date = stop_times.get("stop2_departed") or stop_times.get("stop2_arrived")

            # Update pickup from cache if PG has no value
            if stop1_date and not existing_pickup:
                final_pickup = stop1_date
                note_parts.append(f"Pickup {stop1_date}")

            # Update delivery from cache if PG has no value
            if stop2_date and not existing_delivery:
                final_delivery = stop2_date
                note_parts.append(f"Delivery {stop2_date}")

            # Check if status changed
            # ── Block status regression ──
            if dropdown_val and _status_is_regression(existing_status, cached_status):
                log.info("Blocked status regression", extra={"efj": efj, "from_status": existing_status, "to_status": dropdown_val})
                dropdown_val = None
            if dropdown_val and existing_status != dropdown_val:
                note_parts.append(dropdown_val)
                log.info("Status change", extra={"efj": efj, "load_num": load_num, "from_status": existing_status, "to_status": dropdown_val})

            # ── Write to PG if anything changed ──────────────────────────
            if note_parts:
                note = _build_note(existing_notes, ", ".join(note_parts))
                final_notes = note
                pg_update_shipment(
                    efj,
                    pickup_date=final_pickup or None,
                    delivery_date=final_delivery or None,
                    status=dropdown_val or None,
                    bot_notes=final_notes or None,
                    account=tab_name,
                    move_type="FTL",
                )
                # Dual-write: update Master Sheet (best-effort)
                sheet_update_ftl(
                    efj, tab_name,
                    pickup=final_pickup or None,
                    delivery=final_delivery or None,
                    status=dropdown_val or None,
                )
                log.info("PG updated", extra={"efj": efj, "load_num": load_num})

            # ── Archive if Delivered ──────────────────────────────────────
            if "delivered" in cached_status.lower():
                # Guard: don't archive if truck is still > 15 miles from destination.
                # Macropoint sometimes fires D1 events prematurely (wrong driver,
                # auto-close, or re-tracked shipment). Verify proximity first.
                dist_raw = cached.get("distance_to_stop")
                dist_miles = None
                try:
                    dist_miles = float(dist_raw) if dist_raw is not None else None
                except (TypeError, ValueError):
                    pass
                if dist_miles is not None and dist_miles > 15:
                    log.warning("Archive blocked — truck too far from destination, likely false positive", extra={"efj": efj, "load_num": load_num, "distance_miles": dist_miles})
                else:
                    archive_ftl_row_pg(efj, load_num, dest, tab_name,
                                        final_pickup, final_delivery, ACCOUNT_REPS_PG,
                                        mp_load_id=mp_load_id, stop_times=stop_times)

    save_tracking_cache(tracking_cache)
    log.info("FTL poll complete")


def main():
    log.info("FTL Monitor v3 (Postgres mode) started")
    while True:
        run_once()
        log.info("Sleeping", extra={"minutes": POLL_INTERVAL // 60})
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        log.info("FTL Monitor v3 — single run (Postgres)")
        run_once()
        log.info("Run complete")
    else:
        main()


# ── scrape_macropoint re-export ───────────────────────────────────────────────
# boviet_monitor and tolead_monitor import scrape_macropoint from this module.
# The implementation lives in daily_summary.py. Re-export it here.
try:
    from daily_summary import scrape_macropoint  # noqa: F401
except ImportError:
    def scrape_macropoint(browser, url, mp_cookies=None):
        raise NotImplementedError("scrape_macropoint not available")
