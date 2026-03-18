#!/usr/bin/env python3
"""
CSL Vessel Schedules Monitor
Periodically refreshes vessel schedule data from SeaRates APIs for active dray shipments.

Designed to run via cron:
  0 6 * * 1-5  cd /root/csl-bot && python3 csl_vessel_schedules.py --once >> /var/log/csl-vessel-schedules.log 2>&1
  0 12 * * 1-5 cd /root/csl-bot && python3 csl_vessel_schedules.py --once >> /var/log/csl-vessel-schedules.log 2>&1
"""

import argparse
import json
import os
import sys
import time
import requests
import psycopg2
import psycopg2.extras
from datetime import datetime, date
from zoneinfo import ZoneInfo

# ── Setup ─────────────────────────────────────────────────────────────────────
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

from csl_logging import get_logger

ET = ZoneInfo("America/New_York")
log = get_logger("vessel-schedules")

# SeaRates API keys
SEARATES_API_KEY = os.environ.get("SEARATES_API_KEY", "")
SEARATES_SCHEDULES_API_KEY = os.environ.get("SEARATES_SCHEDULES_API_KEY", "")

# Skip these statuses — shipment is done
SKIP_STATUSES = {
    "delivered", "billed_closed", "billed/closed", "cancelled",
    "returned to port", "completed", "archived",
}

# Carrier SCAC mapping
CARRIER_SCAC_MAP = {
    "maersk": "MAEU", "msc": "MSCU", "cosco": "COSU",
    "evergreen": "EGLV", "yang ming": "YMLU", "hmm": "HDMU",
    "oocl": "OOLU", "one": "ONEY", "cma": "CMDU", "cma cgm": "CMDU",
    "hapag": "HLCU", "hapag-lloyd": "HLCU", "zim": "ZIMU",
    "wan hai": "WHLC", "pil": "PCIU", "sm line": "SMLU",
}


# ── Database ──────────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def get_active_schedules(conn):
    """Get all vessel_schedules rows for active (non-delivered) shipments."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM vessel_schedules
            WHERE LOWER(COALESCE(tracking_status, '')) NOT IN %s
              AND container_or_booking IS NOT NULL
              AND container_or_booking != ''
        """, (tuple(SKIP_STATUSES),))
        return cur.fetchall()


def get_port_locodes(conn):
    """Load port LOCODE cache from DB."""
    with conn.cursor() as cur:
        cur.execute("SELECT city_name, locode FROM port_locode_map")
        rows = cur.fetchall()
    return {r["city_name"].lower(): r["locode"] for r in rows}


def upsert_schedule(conn, data):
    """Update vessel_schedules row for a given EFJ."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE vessel_schedules SET
                carrier_name = COALESCE(%(carrier_name)s, carrier_name),
                carrier_scac = COALESCE(%(carrier_scac)s, carrier_scac),
                origin_terminal = COALESCE(%(origin_terminal)s, origin_terminal),
                destination_terminal = COALESCE(%(destination_terminal)s, destination_terminal),
                departure_date = COALESCE(%(departure_date)s, departure_date),
                arrival_date = COALESCE(%(arrival_date)s, arrival_date),
                eta = COALESCE(%(eta)s, eta),
                lfd = COALESCE(%(lfd)s, lfd),
                cutoff = COALESCE(%(cutoff)s, cutoff),
                erd = COALESCE(%(erd)s, erd),
                transit_days = COALESCE(%(transit_days)s, transit_days),
                vessel_name = COALESCE(%(vessel_name)s, vessel_name),
                vessel_imo = COALESCE(%(vessel_imo)s, vessel_imo),
                voyage_number = COALESCE(%(voyage_number)s, voyage_number),
                tracking_status = COALESCE(%(tracking_status)s, tracking_status),
                legs_json = COALESCE(%(legs_json)s, legs_json),
                updated_at = NOW()
            WHERE efj = %(efj)s
        """, data)
        conn.commit()
        return cur.rowcount


# ── SeaRates API Calls ────────────────────────────────────────────────────────
def resolve_scac(carrier_name):
    """Resolve carrier name to SCAC code."""
    if not carrier_name:
        return None
    name = carrier_name.lower().strip()
    for key, scac in CARRIER_SCAC_MAP.items():
        if key in name:
            return scac
    return None


def resolve_locode(city_name, port_cache):
    """Resolve city/port name to LOCODE using DB cache."""
    if not city_name:
        return None
    key = city_name.lower().strip()
    # Direct match
    if key in port_cache:
        return port_cache[key]
    # Partial match
    for name, code in port_cache.items():
        if key in name or name in key:
            return code
    return None


def container_track(container_num):
    """Call SeaRates Container Tracking API."""
    if not SEARATES_API_KEY or not container_num:
        return None
    try:
        resp = requests.get(
            "https://tracking.searates.com/tracking",
            params={"api_key": SEARATES_API_KEY, "number": container_num, "sealine": "auto"},
            timeout=25,
        )
        data = resp.json()
        if data.get("status") != "success":
            log.debug("Container track failed for %s: %s", container_num, data.get("message"))
            return None
        return extract_tracking_data(data)
    except Exception as e:
        log.warning("Container track error for %s: %s", container_num, e)
        return None


def extract_tracking_data(data):
    """Extract useful fields from SeaRates container tracking response."""
    result = {}
    metadata = data.get("data", {}).get("metadata", {})
    route = data.get("data", {}).get("route", {})

    # ETA from various paths
    eta_str = (
        route.get("pod", {}).get("date")
        or metadata.get("eta")
        or metadata.get("arrival_date")
    )
    if eta_str:
        result["eta"] = parse_date(eta_str)

    # Vessel info
    result["vessel_name"] = metadata.get("vessel_name") or metadata.get("vessel")
    result["vessel_imo"] = metadata.get("imo") or metadata.get("vessel_imo")

    # Carrier
    result["carrier_name"] = metadata.get("sealine_name") or metadata.get("carrier")
    result["carrier_scac"] = resolve_scac(result.get("carrier_name"))

    # Status
    result["tracking_status"] = metadata.get("status")

    # Departure
    dep_str = route.get("pol", {}).get("date") or metadata.get("departure_date")
    if dep_str:
        result["departure_date"] = parse_date(dep_str)

    # Terminal
    result["destination_terminal"] = (
        route.get("pod", {}).get("name")
        or metadata.get("destination_terminal")
    )
    result["origin_terminal"] = (
        route.get("pol", {}).get("name")
        or metadata.get("origin_terminal")
    )

    # Legs
    containers = data.get("data", {}).get("containers", [])
    if containers:
        legs = containers[0].get("events", [])
        if legs:
            result["legs_json"] = json.dumps(legs[:20])  # Keep first 20 events

    return result


def schedule_lookup(origin_locode, dest_locode, carrier_scac=None):
    """Call SeaRates Ship Schedules API v2 — by points."""
    api_key = SEARATES_SCHEDULES_API_KEY or SEARATES_API_KEY
    if not api_key or not origin_locode or not dest_locode:
        return None
    try:
        params = {
            "departure": origin_locode,
            "arrival": dest_locode,
            "type": "P2P",
        }
        if carrier_scac:
            params["scac"] = carrier_scac

        resp = requests.get(
            "https://schedules.searates.com/api/v2/schedules/by-points",
            params=params,
            headers={"X-API-KEY": api_key},
            timeout=30,
        )
        if resp.status_code != 200:
            log.debug("Schedules API %d for %s→%s", resp.status_code, origin_locode, dest_locode)
            return None

        data = resp.json()
        schedules = data if isinstance(data, list) else data.get("data", data.get("schedules", []))
        if not schedules:
            return None
        return schedules
    except Exception as e:
        log.warning("Schedules API error %s→%s: %s", origin_locode, dest_locode, e)
        return None


def match_best_schedule(schedules, target_eta=None):
    """Pick the best schedule from a list, preferring one that matches target ETA."""
    if not schedules:
        return None
    if target_eta and isinstance(target_eta, (date, datetime)):
        # Find schedule with arrival closest to known ETA
        best = None
        best_delta = None
        for s in schedules:
            arr = parse_date(s.get("arrivalDate") or s.get("arrival_date") or "")
            if arr:
                delta = abs((arr - target_eta).days)
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    best = s
        if best:
            return best
    # Default: first schedule (typically soonest departure)
    return schedules[0] if schedules else None


def parse_date(s):
    """Parse date string to date object."""
    if not s:
        return None
    if isinstance(s, (date, datetime)):
        return s if isinstance(s, date) else s.date()
    s = str(s).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ── Main Logic ────────────────────────────────────────────────────────────────
def has_changes(existing, new_data):
    """Check if any field actually changed."""
    fields_to_check = [
        "eta", "lfd", "cutoff", "erd", "vessel_name", "carrier_name",
        "tracking_status", "departure_date", "arrival_date",
        "destination_terminal", "origin_terminal", "transit_days",
    ]
    for f in fields_to_check:
        old_val = existing.get(f)
        new_val = new_data.get(f)
        if new_val is not None and str(new_val) != str(old_val or ""):
            return True
    return False


def process_shipment(row, port_cache, lane_cache):
    """Process a single shipment — track container + fetch schedules."""
    efj = row["efj"]
    container = row.get("container_or_booking", "")
    move_type = (row.get("move_type") or "").lower()
    is_export = "export" in move_type

    result = {"efj": efj}

    # Step 1: Container tracking (imports + transload)
    if container and not is_export:
        tracking = container_track(container)
        if tracking:
            result.update({k: v for k, v in tracking.items() if v is not None})
        time.sleep(1)  # Rate limit

    # Step 2: Ship Schedules (if we have port codes)
    origin = row.get("origin_locode") or resolve_locode(row.get("origin_port", ""), port_cache)
    dest = row.get("destination_locode") or resolve_locode(row.get("destination_port", ""), port_cache)
    scac = row.get("carrier_scac") or result.get("carrier_scac") or resolve_scac(row.get("carrier_name", ""))

    lane_key = f"{origin}:{dest}:{scac or ''}"

    if origin and dest:
        # Dedup by lane — same origin+dest+carrier = one API call
        if lane_key not in lane_cache:
            schedules = schedule_lookup(origin, dest, scac)
            lane_cache[lane_key] = schedules
            time.sleep(1)  # Rate limit
        else:
            schedules = lane_cache[lane_key]

        if schedules:
            target_eta = result.get("eta") or parse_date(str(row.get("eta") or ""))
            best = match_best_schedule(schedules, target_eta)
            if best:
                if is_export:
                    dep = parse_date(best.get("departureDate") or best.get("departure_date"))
                    if dep:
                        result["erd"] = dep
                    cutoff = parse_date(best.get("cutOffDate") or best.get("cut_off_date"))
                    if cutoff:
                        result["cutoff"] = cutoff
                    result.setdefault("origin_terminal", best.get("originTerminal") or best.get("origin_terminal"))
                else:
                    arr = parse_date(best.get("arrivalDate") or best.get("arrival_date"))
                    if arr:
                        result.setdefault("eta", arr)
                    result.setdefault("destination_terminal", best.get("destinationTerminal") or best.get("destination_terminal"))

                result.setdefault("vessel_name", best.get("vesselName") or best.get("vessel_name"))
                result.setdefault("voyage_number", best.get("voyageNumber") or best.get("voyage_number"))

                transit = best.get("transitTime") or best.get("transit_time")
                if transit:
                    result["transit_days"] = int(transit) if str(transit).isdigit() else None

    return result


def run_once():
    """Single pass: refresh all active shipment schedules."""
    now = datetime.now(ET)
    log.info("=== Vessel Schedules Monitor — %s ===", now.strftime("%Y-%m-%d %H:%M ET"))

    if not SEARATES_API_KEY and not SEARATES_SCHEDULES_API_KEY:
        log.warning("No SEARATES API keys configured — skipping")
        return

    conn = get_conn()
    try:
        rows = get_active_schedules(conn)
        log.info("Found %d active shipments with container/booking #", len(rows))

        if not rows:
            log.info("Nothing to update")
            return

        port_cache = get_port_locodes(conn)
        lane_cache = {}  # Dedup schedules API calls by lane
        updated = 0
        skipped = 0
        errors = 0

        for row in rows:
            efj = row["efj"]
            try:
                new_data = process_shipment(row, port_cache, lane_cache)

                if has_changes(row, new_data):
                    # Prepare upsert data with None for unchanged fields
                    upsert_data = {
                        "efj": efj,
                        "carrier_name": new_data.get("carrier_name"),
                        "carrier_scac": new_data.get("carrier_scac"),
                        "origin_terminal": new_data.get("origin_terminal"),
                        "destination_terminal": new_data.get("destination_terminal"),
                        "departure_date": new_data.get("departure_date"),
                        "arrival_date": new_data.get("arrival_date"),
                        "eta": new_data.get("eta"),
                        "lfd": new_data.get("lfd"),
                        "cutoff": new_data.get("cutoff"),
                        "erd": new_data.get("erd"),
                        "transit_days": new_data.get("transit_days"),
                        "vessel_name": new_data.get("vessel_name"),
                        "vessel_imo": new_data.get("vessel_imo"),
                        "voyage_number": new_data.get("voyage_number"),
                        "tracking_status": new_data.get("tracking_status"),
                        "legs_json": new_data.get("legs_json"),
                    }
                    upsert_schedule(conn, upsert_data)
                    updated += 1
                    log.info("  %s — updated", efj)
                else:
                    skipped += 1
                    log.debug("  %s — no change", efj)

            except Exception as e:
                errors += 1
                log.error("  %s — error: %s", efj, e)

        log.info("Done: %d updated, %d skipped, %d errors (of %d total)",
                 updated, skipped, errors, len(rows))

    finally:
        conn.close()


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CSL Vessel Schedules Monitor")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        # Loop mode (not typically used — cron preferred)
        while True:
            try:
                run_once()
            except Exception as e:
                log.error("Run failed: %s", e)
            log.info("Sleeping 6 hours...")
            time.sleep(6 * 3600)
