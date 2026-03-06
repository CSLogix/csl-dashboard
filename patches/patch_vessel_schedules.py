#!/usr/bin/env python3
"""
Patch: SeaRates Vessel Schedules + Add Load v2
- Creates port_locode_map + vessel_schedules tables in PostgreSQL
- Seeds port_locode_map with common ports
- Adds POST /api/searates/lookup endpoint (auto-fetch vessel schedule)
- Adds GET /api/port-codes endpoint
- Adds POST /api/accounts/add + GET /api/reps endpoints
- Modifies POST /api/load/add to accept new fields (bol, customerRef, equipmentType, rep)
"""

import sys, os, json, psycopg2

APP = "/root/csl-bot/csl-doc-tracker/app.py"

# -- Step 1: Schema migration ------------------------------------------------
print("[1/4] Creating database tables...")
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS port_locode_map (
    id SERIAL PRIMARY KEY,
    city_name TEXT NOT NULL,
    locode TEXT NOT NULL,
    port_name TEXT,
    country TEXT,
    region TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(city_name)
);
""")

cur.execute("""
CREATE INDEX IF NOT EXISTS idx_port_locode_city ON port_locode_map(city_name);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS vessel_schedules (
    id SERIAL PRIMARY KEY,
    efj TEXT NOT NULL,
    container_or_booking TEXT,
    move_type TEXT,
    carrier_name TEXT,
    carrier_scac TEXT,
    origin_port TEXT,
    origin_locode TEXT,
    origin_terminal TEXT,
    destination_port TEXT,
    destination_locode TEXT,
    destination_terminal TEXT,
    departure_date DATE,
    arrival_date DATE,
    eta DATE,
    lfd DATE,
    cutoff DATE,
    erd DATE,
    transit_days INTEGER,
    is_direct BOOLEAN DEFAULT TRUE,
    vessel_name TEXT,
    vessel_imo INTEGER,
    voyage_number TEXT,
    transshipment_ports TEXT[],
    tracking_status TEXT,
    legs_json JSONB,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(efj)
);
""")

cur.execute("CREATE INDEX IF NOT EXISTS idx_vessel_schedules_efj ON vessel_schedules(efj);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_vessel_schedules_carrier ON vessel_schedules(carrier_scac);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_vessel_schedules_origin ON vessel_schedules(origin_locode);")

conn.commit()
cur.close()
conn.close()
print("   Tables ready.")

# -- Step 2: Seed port codes ------------------------------------------------
print("[2/4] Seeding port_locode_map...")

PORT_SEEDS = {
    # US East Coast
    "newark": ("USNYC", "Port Newark", "US", "US East"),
    "new york": ("USNYC", "New York/New Jersey", "US", "US East"),
    "port elizabeth": ("USNYC", "Port Elizabeth", "US", "US East"),
    "elizabeth": ("USNYC", "Port Elizabeth", "US", "US East"),
    "ny": ("USNYC", "New York", "US", "US East"),
    "savannah": ("USSAV", "Port of Savannah", "US", "US East"),
    "garden city": ("USSAV", "Garden City/Savannah", "US", "US East"),
    "charleston": ("USCHS", "Port of Charleston", "US", "US East"),
    "norfolk": ("USORF", "Port of Norfolk", "US", "US East"),
    "portsmouth": ("USORF", "Portsmouth/Norfolk", "US", "US East"),
    "baltimore": ("USBAL", "Port of Baltimore", "US", "US East"),
    "philadelphia": ("USPHL", "Port of Philadelphia", "US", "US East"),
    "boston": ("USBOS", "Port of Boston", "US", "US East"),
    "jacksonville": ("USJAX", "Port of Jacksonville", "US", "US East"),
    "miami": ("USMIA", "Port of Miami", "US", "US East"),
    "port everglades": ("USPEF", "Port Everglades", "US", "US East"),
    "wilmington nc": ("USILM", "Port of Wilmington NC", "US", "US East"),
    "wilmington de": ("USWIL", "Port of Wilmington DE", "US", "US East"),
    # US West Coast
    "los angeles": ("USLAX", "Port of Los Angeles", "US", "US West"),
    "la": ("USLAX", "Port of Los Angeles", "US", "US West"),
    "long beach": ("USLGB", "Port of Long Beach", "US", "US West"),
    "oakland": ("USOAK", "Port of Oakland", "US", "US West"),
    "seattle": ("USSEA", "Port of Seattle", "US", "US West"),
    "tacoma": ("USTIW", "Port of Tacoma", "US", "US West"),
    # US Gulf
    "houston": ("USHOU", "Port of Houston", "US", "US Gulf"),
    "new orleans": ("USMSY", "Port of New Orleans", "US", "US Gulf"),
    "mobile": ("USMOB", "Port of Mobile", "US", "US Gulf"),
    # Asia - China
    "shanghai": ("CNSHA", "Port of Shanghai", "CN", "Asia"),
    "ningbo": ("CNNGB", "Port of Ningbo", "CN", "Asia"),
    "shenzhen": ("CNSZX", "Port of Shenzhen", "CN", "Asia"),
    "yantian": ("CNYTN", "Yantian", "CN", "Asia"),
    "qingdao": ("CNTAO", "Port of Qingdao", "CN", "Asia"),
    "xiamen": ("CNXMN", "Port of Xiamen", "CN", "Asia"),
    "guangzhou": ("CNGZG", "Port of Guangzhou", "CN", "Asia"),
    "tianjin": ("CNTSN", "Port of Tianjin", "CN", "Asia"),
    "dalian": ("CNDLC", "Port of Dalian", "CN", "Asia"),
    # Asia - Other
    "hong kong": ("HKHKG", "Port of Hong Kong", "HK", "Asia"),
    "busan": ("KRPUS", "Port of Busan", "KR", "Asia"),
    "pusan": ("KRPUS", "Port of Busan", "KR", "Asia"),
    "tokyo": ("JPTYO", "Port of Tokyo", "JP", "Asia"),
    "yokohama": ("JPYOK", "Port of Yokohama", "JP", "Asia"),
    "kaohsiung": ("TWKHH", "Port of Kaohsiung", "TW", "Asia"),
    "ho chi minh": ("VNSGN", "Ho Chi Minh City", "VN", "Asia"),
    "cat lai": ("VNCLI", "Cat Lai", "VN", "Asia"),
    "haiphong": ("VNHPH", "Port of Haiphong", "VN", "Asia"),
    "singapore": ("SGSIN", "Port of Singapore", "SG", "Asia"),
    "port klang": ("MYPKG", "Port Klang", "MY", "Asia"),
    "tanjung pelepas": ("MYTPP", "Tanjung Pelepas", "MY", "Asia"),
    "bangkok": ("THBKK", "Port of Bangkok", "TH", "Asia"),
    "laem chabang": ("THLCH", "Laem Chabang", "TH", "Asia"),
    "jakarta": ("IDJKT", "Port of Jakarta", "ID", "Asia"),
    # Europe
    "rotterdam": ("NLRTM", "Port of Rotterdam", "NL", "Europe"),
    "antwerp": ("BEANR", "Port of Antwerp", "BE", "Europe"),
    "hamburg": ("DEHAM", "Port of Hamburg", "DE", "Europe"),
    "bremerhaven": ("DEBRV", "Bremerhaven", "DE", "Europe"),
    "felixstowe": ("GBFXT", "Port of Felixstowe", "GB", "Europe"),
    "southampton": ("GBSOU", "Port of Southampton", "GB", "Europe"),
    "genoa": ("ITGOA", "Port of Genoa", "IT", "Europe"),
    "valencia": ("ESVLC", "Port of Valencia", "ES", "Europe"),
    "barcelona": ("ESBCN", "Port of Barcelona", "ES", "Europe"),
    "piraeus": ("GRPIR", "Port of Piraeus", "GR", "Europe"),
    "le havre": ("FRLEH", "Port of Le Havre", "FR", "Europe"),
    # Indian Subcontinent
    "mumbai": ("INBOM", "Port of Mumbai", "IN", "South Asia"),
    "nhava sheva": ("INNSA", "Nhava Sheva", "IN", "South Asia"),
    "chennai": ("INMAA", "Port of Chennai", "IN", "South Asia"),
    "colombo": ("LKCMB", "Port of Colombo", "LK", "South Asia"),
    "karachi": ("PKKHI", "Port of Karachi", "PK", "South Asia"),
    # Middle East
    "jebel ali": ("AEJEA", "Jebel Ali", "AE", "Middle East"),
    "dubai": ("AEDXB", "Port of Dubai", "AE", "Middle East"),
    "jeddah": ("SAJED", "Port of Jeddah", "SA", "Middle East"),
    # Americas
    "santos": ("BRSSZ", "Port of Santos", "BR", "Americas"),
    "manzanillo": ("MXZLO", "Port of Manzanillo", "MX", "Americas"),
    "kingston": ("JMKIN", "Port of Kingston", "JM", "Americas"),
    "freeport": ("BSFPO", "Port of Freeport", "BS", "Americas"),
    "colon": ("PAONX", "Port of Colon", "PA", "Americas"),
}

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()

for city, (locode, port_name, country, region) in PORT_SEEDS.items():
    cur.execute("""
        INSERT INTO port_locode_map (city_name, locode, port_name, country, region)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (city_name) DO UPDATE SET
            locode = EXCLUDED.locode,
            port_name = EXCLUDED.port_name,
            country = EXCLUDED.country,
            region = EXCLUDED.region
    """, (city.lower(), locode, port_name, country, region))

conn.commit()
cur.close()
conn.close()
print(f"   Seeded {len(PORT_SEEDS)} port codes.")

# -- Step 3: Add new endpoints to app.py ------------------------------------
print("[3/4] Patching app.py with new endpoints...")

with open(APP, "r") as f:
    code = f.read()

if "/api/searates/lookup" in code:
    print("   SeaRates lookup already patched -- skipping endpoints.")
else:
    # Insert before the Add Load endpoint
    ANCHOR = '# ── Add New Load ──'

    NEW_ENDPOINTS = '''# ── SeaRates Vessel Schedules + Port Codes ──

import requests as _requests
from datetime import timedelta as _timedelta

_CARRIER_SCAC_MAP = {
    "maersk": "MAEU", "msc": "MSCU", "cosco": "COSU",
    "evergreen": "EGLV", "yang ming": "YMLU", "hmm": "HDMU",
    "hyundai": "HDMU", "oocl": "OOLU", "one": "ONEY",
    "ocean network": "ONEY", "cma": "CMDU", "cma cgm": "CMDU",
    "hapag": "HLCU", "hapag-lloyd": "HLCU", "zim": "ZIMU",
    "wan hai": "WHLC", "apl": "CMDU",
}

def _resolve_locode(city_name):
    """Resolve a city name to a UN/LOCODE via DB lookup."""
    if not city_name:
        return None
    clean = city_name.strip().lower()
    # Strip state/country suffixes like ", NJ" or ", OH"
    for sep in [",", " - "]:
        if sep in clean:
            clean = clean.split(sep)[0].strip()
    # Remove common prefixes
    for prefix in ["port ", "port of "]:
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("SELECT locode FROM port_locode_map WHERE city_name = %s", (clean,))
                row = cur.fetchone()
                if row:
                    return row[0] if isinstance(row, tuple) else row.get("locode")
    except Exception:
        pass
    return None

def _resolve_scac(ssl_field):
    """Extract SCAC code from carrier/vessel name."""
    if not ssl_field:
        return None
    lower = ssl_field.lower()
    for key, scac in _CARRIER_SCAC_MAP.items():
        if key in lower:
            return scac
    return None

def _searates_schedule_lookup(origin_locode, dest_locode, carrier_scac=None, from_date=None):
    """Query SeaRates Ship Schedules API for sailing schedules."""
    api_key = os.environ.get("SEARATES_SCHEDULES_API_KEY") or os.environ.get("SEARATES_API_KEY")
    if not api_key:
        return []
    if not from_date:
        from_date = datetime.now().strftime("%Y-%m-%d")
    params = {
        "cargo_type": "GC",
        "origin": origin_locode,
        "destination": dest_locode,
        "from_date": from_date,
        "weeks": 4,
        "sort": "DEP",
    }
    if carrier_scac:
        params["carriers"] = carrier_scac
    try:
        resp = _requests.get(
            "https://schedules.searates.com/api/v2/schedules/by-points",
            params=params,
            headers={"X-API-KEY": api_key},
            timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", {}).get("schedules", [])
    except Exception as e:
        log.warning("SeaRates schedules lookup failed: %s", e)
    return []

def _searates_container_lookup(number):
    """Query SeaRates Container Tracking API."""
    api_key = os.environ.get("SEARATES_API_KEY")
    if not api_key:
        return {}
    try:
        resp = _requests.get(
            "https://tracking.searates.com/tracking",
            params={"api_key": api_key, "number": number, "sealine": "auto"},
            timeout=30
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        log.warning("SeaRates container lookup failed: %s", e)
    return {}

def _extract_tracking_data(raw):
    """Extract ETA, vessel, carrier, LFD from SeaRates tracking response."""
    result = {"eta": None, "vessel": None, "carrier": None, "lfd": None, "status": None}
    if not raw or not raw.get("data"):
        return result
    data = raw.get("data", {})
    # Carrier info
    metadata = data.get("metadata", {})
    if metadata.get("sealine_name"):
        result["carrier"] = metadata["sealine_name"]
    # Parse route/events for ETA
    route = data.get("route", {})
    pod = route.get("pod", {})
    if pod.get("date"):
        result["eta"] = pod["date"][:10] if len(pod.get("date", "")) >= 10 else None
    # Vessel from route
    prepol = route.get("prepol", {})
    if prepol.get("name") and "vessel" in prepol.get("transport_type", "").lower():
        result["vessel"] = prepol.get("name")
    # Parse containers for status
    containers = data.get("containers", [])
    if containers:
        events = containers[0].get("events", [])
        if events:
            last = events[-1]
            result["status"] = last.get("description", "")
            # Look for LFD in event descriptions
            for ev in events:
                desc = (ev.get("description") or "").lower()
                if "last free" in desc or "lfd" in desc:
                    result["lfd"] = ev.get("date", "")[:10] if ev.get("date") else None
    return result


@app.post("/api/searates/lookup")
async def api_searates_lookup(request: Request):
    """Auto-fetch vessel schedule data from SeaRates APIs."""
    body = await request.json()
    move_type = body.get("moveType", "")
    number = body.get("number", "").strip()
    origin = body.get("origin", "")
    destination = body.get("destination", "")

    result = {
        "eta": None, "lfd": None, "cutoff": None, "erd": None,
        "vessel": None, "carrier": None, "terminal": None,
        "voyage": None, "transitDays": None
    }

    # Step 1: Container/booking tracking
    if number:
        raw = _searates_container_lookup(number)
        tracking = _extract_tracking_data(raw)
        result["eta"] = tracking.get("eta")
        result["lfd"] = tracking.get("lfd")
        result["vessel"] = tracking.get("vessel")
        result["carrier"] = tracking.get("carrier")

    # Step 2: Ship Schedules (if ports resolve)
    origin_locode = _resolve_locode(origin)
    dest_locode = _resolve_locode(destination)
    carrier_scac = _resolve_scac(result.get("carrier") or "")

    if origin_locode and dest_locode:
        schedules = _searates_schedule_lookup(origin_locode, dest_locode, carrier_scac)
        if schedules:
            best = schedules[0]  # Already sorted by departure
            is_export = "Export" in move_type
            if is_export:
                dep = best.get("origin", {}).get("estimated_date", "")
                result["erd"] = dep[:10] if dep else None
                # Cut-off from legs or schedule data
                legs = best.get("legs", [])
                if legs:
                    cut = legs[0].get("departure", {}).get("estimated_date", "")
                    result["cutoff"] = cut[:10] if cut else result["erd"]
                result["terminal"] = best.get("origin", {}).get("terminal_name")
            else:
                arr = best.get("destination", {}).get("estimated_date", "")
                if not result["eta"] and arr:
                    result["eta"] = arr[:10]
                result["terminal"] = best.get("destination", {}).get("terminal_name")

            result["vessel"] = result["vessel"] or (best.get("legs", [{}])[0].get("vessel_name") if best.get("legs") else None)
            result["voyage"] = (best.get("legs", [{}])[0].get("voyages", [{}])[0].get("voyage") if best.get("legs") and best["legs"][0].get("voyages") else None)
            result["transitDays"] = best.get("transit_time")
            result["carrier"] = result["carrier"] or best.get("carrier_name")

    return JSONResponse(result)


@app.get("/api/port-codes")
async def api_port_codes():
    """Return all known port code mappings."""
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("SELECT city_name, locode, port_name, country, region FROM port_locode_map ORDER BY city_name")
                rows = cur.fetchall()
        ports = []
        for r in rows:
            if isinstance(r, dict):
                ports.append(r)
            else:
                ports.append({"city_name": r[0], "locode": r[1], "port_name": r[2], "country": r[3], "region": r[4]})
        return {"ports": ports, "count": len(ports)}
    except Exception as e:
        log.error("Failed to fetch port codes: %s", e)
        raise HTTPException(500, str(e))


@app.get("/api/reps")
async def api_reps():
    """Return list of account reps."""
    return {"reps": ["Eli", "Radka", "John F", "Janice"]}


@app.post("/api/accounts/add")
async def api_add_account(request: Request):
    """Add a new account tab to the Master Tracker."""
    body = await request.json()
    name = body.get("name", "").strip()
    rep = body.get("rep", "").strip()
    if not name:
        raise HTTPException(400, "Account name is required")
    # For now, just return success — actual sheet tab creation would need gspread
    log.info("New account requested: %s (rep: %s)", name, rep)
    return {"ok": True, "account": name, "rep": rep}


''' + ANCHOR

    if ANCHOR not in code:
        print(f"   ERROR: anchor '{ANCHOR}' not found in app.py")
        sys.exit(1)

    code = code.replace(ANCHOR, NEW_ENDPOINTS, 1)

    with open(APP, "w") as f:
        f.write(code)
    print("   Endpoints added.")

# -- Step 4: Update /api/load/add to accept new fields ----------------------
print("[4/4] Updating /api/load/add for new fields...")

with open(APP, "r") as f:
    code = f.read()

# Add new field extraction after existing field parsing
OLD_FIELDS = '''    notes = body.get("notes", "")
    driver_phone = body.get("driverPhone", "")'''

NEW_FIELDS = '''    notes = body.get("notes", "")
    bol = body.get("bol", "").strip()
    customer_ref = body.get("customerRef", "").strip()
    equipment_type = body.get("equipmentType", "").strip()
    rep = body.get("rep", "").strip()
    driver_phone = body.get("driverPhone", "")'''

if OLD_FIELDS in code and "customer_ref = body.get" not in code:
    code = code.replace(OLD_FIELDS, NEW_FIELDS, 1)

    # Update Master Tracker row to include BOL in column D
    OLD_ROW = '''            row[COL["carrier"]] = carrier'''
    NEW_ROW = '''            row[COL["carrier"]] = carrier
            if bol:
                row[3] = bol  # Column D: BOL/Booking'''
    if OLD_ROW in code:
        code = code.replace(OLD_ROW, NEW_ROW, 1)

    # Store schedule data in vessel_schedules after successful sheet write
    OLD_CACHE = '''        # Invalidate cache so next fetch picks up the new row
        sheet_cache.last_refresh = 0'''
    NEW_CACHE = '''        # Invalidate cache so next fetch picks up the new row
        sheet_cache.last_refresh = 0

        # Store schedule data in vessel_schedules if provided
        schedule_data = body.get("scheduleData")
        if schedule_data and isinstance(schedule_data, dict):
            try:
                with db.get_conn() as sconn:
                    with db.get_cursor(sconn) as scur:
                        scur.execute("""
                            INSERT INTO vessel_schedules (efj, container_or_booking, move_type, carrier_name,
                                origin_port, origin_locode, destination_port, destination_locode,
                                eta, lfd, cutoff, erd, vessel_name, voyage_number, transit_days)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (efj) DO UPDATE SET
                                container_or_booking = EXCLUDED.container_or_booking,
                                carrier_name = EXCLUDED.carrier_name,
                                eta = EXCLUDED.eta, lfd = EXCLUDED.lfd,
                                cutoff = EXCLUDED.cutoff, erd = EXCLUDED.erd,
                                vessel_name = EXCLUDED.vessel_name,
                                voyage_number = EXCLUDED.voyage_number,
                                transit_days = EXCLUDED.transit_days,
                                updated_at = NOW()
                        """, (
                            efj, container or bol, move_type,
                            schedule_data.get("carrier"),
                            origin, schedule_data.get("originLocode"),
                            destination, schedule_data.get("destLocode"),
                            schedule_data.get("eta"), schedule_data.get("lfd"),
                            schedule_data.get("cutoff"), schedule_data.get("erd"),
                            schedule_data.get("vessel"), schedule_data.get("voyage"),
                            schedule_data.get("transitDays"),
                        ))
            except Exception as sched_err:
                log.warning("Schedule data save failed for %s: %s", efj, sched_err)'''

    if OLD_CACHE in code:
        code = code.replace(OLD_CACHE, NEW_CACHE, 1)

    with open(APP, "w") as f:
        f.write(code)
    print("   /api/load/add updated with new fields.")
else:
    print("   Already patched or anchor not found -- skipping.")

print("\nDone! Restart csl-dashboard to apply changes.")
print("  systemctl restart csl-dashboard")
