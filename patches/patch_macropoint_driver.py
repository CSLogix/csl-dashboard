#!/usr/bin/env python3
"""
patch_macropoint_driver.py
Patches app.py to add:
  1. driver_contacts PostgreSQL table
  2. GET/POST /api/load/{efj}/driver — manage driver phone, email, name
  3. Enhanced /api/macropoint/{efj} — includes driver info + stop timeline from tracking cache

Run: python3 /tmp/patch_macropoint_driver.py
"""
import re

FILE = "/root/csl-bot/csl-doc-tracker/app.py"

with open(FILE) as f:
    code = f.read()

# ══════════════════════════════════════════════════════════════════════════
# 1) Add TRACKING_CACHE_FILE constant near other Macropoint constants
# ══════════════════════════════════════════════════════════════════════════
if "TRACKING_CACHE_FILE" in code:
    print("TRACKING_CACHE_FILE already defined — skipping")
else:
    anchor = 'DISPATCH_EMAIL = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")'
    if anchor not in code:
        print("ERROR: Cannot find DISPATCH_EMAIL constant")
        exit(1)
    code = code.replace(
        anchor,
        anchor + '\nTRACKING_CACHE_FILE = "/root/csl-bot/ftl_tracking_cache.json"',
    )
    print("Added TRACKING_CACHE_FILE constant")

# ══════════════════════════════════════════════════════════════════════════
# 2) Add driver_contacts table creation in the startup/init section
# ══════════════════════════════════════════════════════════════════════════
if "driver_contacts" in code:
    print("driver_contacts references already exist — skipping table creation")
else:
    # Find db.init_pool() call and add table creation after it
    anchor = "db.init_pool()"
    if anchor not in code:
        print("ERROR: Cannot find db.init_pool()")
        exit(1)
    idx = code.index(anchor) + len(anchor)
    # Find the next newline
    next_nl = code.index("\n", idx)

    table_create = '''
    # Create driver_contacts table if not exists
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS driver_contacts (
                        efj VARCHAR(32) PRIMARY KEY,
                        driver_name VARCHAR(120),
                        driver_phone VARCHAR(30),
                        driver_email VARCHAR(120),
                        notes TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
        log.info("driver_contacts table ready")
    except Exception as e:
        log.warning("Could not create driver_contacts table: %s", e)
'''
    code = code[:next_nl + 1] + table_create + code[next_nl + 1:]
    print("Added driver_contacts table creation")

# ══════════════════════════════════════════════════════════════════════════
# 3) Add helper to read tracking cache
# ══════════════════════════════════════════════════════════════════════════
if "def _read_tracking_cache" in code:
    print("_read_tracking_cache already defined — skipping")
else:
    # Insert before the _build_macropoint_progress function
    anchor = "def _build_macropoint_progress(status_str: str):"
    if anchor not in code:
        print("ERROR: Cannot find _build_macropoint_progress")
        exit(1)
    idx = code.index(anchor)

    helper = '''def _read_tracking_cache() -> dict:
    """Read the FTL tracking cache written by ftl_monitor.py."""
    try:
        with open(TRACKING_CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _get_driver_contact(efj: str) -> dict:
    """Get driver contact info from PostgreSQL."""
    try:
        with db.get_cursor() as cur:
            cur.execute(
                "SELECT driver_name, driver_phone, driver_email, notes "
                "FROM driver_contacts WHERE efj = %s",
                (efj,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
    except Exception as e:
        log.warning("Failed to read driver contact for %s: %s", efj, e)
    return {}


def _upsert_driver_contact(efj: str, name: str = None, phone: str = None,
                           email: str = None, notes: str = None):
    """Insert or update driver contact info."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO driver_contacts (efj, driver_name, driver_phone, driver_email, notes)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (efj) DO UPDATE SET
                    driver_name  = COALESCE(EXCLUDED.driver_name,  driver_contacts.driver_name),
                    driver_phone = COALESCE(EXCLUDED.driver_phone, driver_contacts.driver_phone),
                    driver_email = COALESCE(EXCLUDED.driver_email, driver_contacts.driver_email),
                    notes        = COALESCE(EXCLUDED.notes,        driver_contacts.notes),
                    updated_at   = NOW()
            """, (efj, name or None, phone or None, email or None, notes or None))


'''
    code = code[:idx] + helper + code[idx:]
    print("Added _read_tracking_cache, _get_driver_contact, _upsert_driver_contact helpers")

# ══════════════════════════════════════════════════════════════════════════
# 4) Add GET /api/load/{efj}/driver and POST /api/load/{efj}/driver
# ══════════════════════════════════════════════════════════════════════════
if "/api/load/{efj}/driver" in code:
    print("Driver endpoints already exist — skipping")
else:
    # Insert before the macropoint screenshot endpoint
    anchor = '@app.get("/api/macropoint/{efj}/screenshot")'
    if anchor not in code:
        print("ERROR: Cannot find macropoint screenshot endpoint")
        exit(1)
    idx = code.index(anchor)

    driver_endpoints = '''
# ── Driver contact endpoints ──────────────────────────────────────────────

@app.get("/api/load/{efj}/driver")
async def api_get_driver(efj: str):
    """Return driver contact info for a load."""
    contact = _get_driver_contact(efj)
    # Also check Column N (driver/truck) from sheet cache as fallback for name
    sheet_driver = ""
    for s in sheet_cache.shipments:
        if s["efj"] == efj:
            sheet_driver = s.get("notes", "")  # COL index 13 = Column N = Driver/Truck
            break
    return {
        "efj": efj,
        "driverName": contact.get("driver_name") or sheet_driver or "",
        "driverPhone": contact.get("driver_phone") or "",
        "driverEmail": contact.get("driver_email") or "",
        "notes": contact.get("notes") or "",
    }


@app.post("/api/load/{efj}/driver")
async def api_update_driver(efj: str, request: Request):
    """Create or update driver contact info."""
    body = await request.json()
    _upsert_driver_contact(
        efj,
        name=body.get("driverName"),
        phone=body.get("driverPhone"),
        email=body.get("driverEmail"),
        notes=body.get("notes"),
    )
    log.info("Driver contact updated for %s", efj)
    return {"status": "ok", "efj": efj}


'''
    code = code[:idx] + driver_endpoints + code[idx:]
    print("Added GET/POST /api/load/{efj}/driver endpoints")

# ══════════════════════════════════════════════════════════════════════════
# 5) Enhance /api/macropoint/{efj} to include driver info + stop timeline
# ══════════════════════════════════════════════════════════════════════════

# Replace the entire macropoint endpoint return block
old_return = '''    return {
        "loadId": shipment.get("container", "") or shipment.get("efj", ""),
        "carrier": "Evans Delivery Company, Inc.",
        "driver": "",
        "phone": phone_fmt,
        "email": DISPATCH_EMAIL,
        "trackingStatus": status or "Unknown",
        "macropointUrl": shipment.get("container_url", ""),
        "progress": progress,
        "origin": shipment.get("origin", ""),
        "destination": shipment.get("destination", ""),
        "pickup": shipment.get("pickup", ""),
        "delivery": shipment.get("delivery", ""),
        "eta": shipment.get("eta", ""),
        "account": shipment.get("account", ""),
        "moveType": shipment.get("move_type", ""),
    }'''

if old_return in code:
    new_return = '''    # ── Driver contact info (from DB) ──
    contact = _get_driver_contact(efj)
    driver_name = contact.get("driver_name") or ""
    driver_phone = contact.get("driver_phone") or ""
    driver_email = contact.get("driver_email") or ""

    # ── Tracking cache (stop timeline from ftl_monitor) ──
    tracking_cache = _read_tracking_cache()
    cached = tracking_cache.get(efj, {})
    stop_times = cached.get("stop_times", {})
    cant_make_it = cached.get("cant_make_it")
    last_scraped = cached.get("last_scraped")
    mp_load_id_cached = cached.get("mp_load_id")

    # Build stop timeline array for frontend
    timeline = []
    if stop_times.get("stop1_arrived"):
        timeline.append({"event": "Arrived at Pickup", "time": stop_times["stop1_arrived"], "type": "arrived"})
    elif stop_times.get("stop1_eta"):
        timeline.append({"event": "Pickup ETA", "time": stop_times["stop1_eta"], "type": "eta"})
    if stop_times.get("stop1_departed"):
        timeline.append({"event": "Departed Pickup", "time": stop_times["stop1_departed"], "type": "departed"})
    if stop_times.get("stop2_arrived"):
        timeline.append({"event": "Arrived at Delivery", "time": stop_times["stop2_arrived"], "type": "arrived"})
    elif stop_times.get("stop2_eta"):
        timeline.append({"event": "Delivery ETA", "time": stop_times["stop2_eta"], "type": "eta"})
    if stop_times.get("stop2_departed"):
        timeline.append({"event": "Departed Delivery", "time": stop_times["stop2_departed"], "type": "departed"})

    # Detect behind schedule from ETA strings
    behind_schedule = False
    for k in ("stop1_eta", "stop2_eta"):
        if stop_times.get(k) and "BEHIND" in stop_times[k].upper():
            behind_schedule = True

    return {
        "loadId": shipment.get("container", "") or shipment.get("efj", ""),
        "carrier": "Evans Delivery Company, Inc.",
        "driver": driver_name,
        "phone": phone_fmt,
        "email": DISPATCH_EMAIL,
        "trackingStatus": status or "Unknown",
        "macropointUrl": shipment.get("container_url", ""),
        "progress": progress,
        "origin": shipment.get("origin", ""),
        "destination": shipment.get("destination", ""),
        "pickup": shipment.get("pickup", ""),
        "delivery": shipment.get("delivery", ""),
        "eta": shipment.get("eta", ""),
        "account": shipment.get("account", ""),
        "moveType": shipment.get("move_type", ""),
        # ── New fields ──
        "driverName": driver_name,
        "driverPhone": driver_phone,
        "driverEmail": driver_email,
        "mpLoadId": mp_load_id_cached,
        "timeline": timeline,
        "behindSchedule": behind_schedule,
        "cantMakeIt": cant_make_it,
        "lastScraped": last_scraped,
    }'''
    code = code.replace(old_return, new_return)
    print("Enhanced /api/macropoint/{efj} response with driver info + timeline")
else:
    print("WARNING: Could not find exact macropoint return block — may already be patched")

# ══════════════════════════════════════════════════════════════════════════
# 6) Add /api/load/{efj}/driver to PUBLIC_PATHS bypass
# ══════════════════════════════════════════════════════════════════════════
if '"/api/"' in code and "PUBLIC_PATHS" in code:
    # The /api/ prefix is already public — driver endpoints will work
    print("API paths already public — driver endpoints accessible")
else:
    print("WARNING: Check that /api/ paths bypass auth")


with open(FILE, "w") as f:
    f.write(code)

print("\n✅ app.py patched with driver contacts + enhanced Macropoint API")
print("   Restart service: systemctl restart csl-dashboard")
