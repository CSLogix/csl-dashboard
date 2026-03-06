#!/usr/bin/env python3
"""
Patch: Add load_metadata table + PATCH /api/load/{efj}/metadata endpoint
       + merge metadata into /api/shipments response

Creates:
1. load_metadata table in PostgreSQL (efj, notes, truck_type, customer_rate)
2. PATCH /api/load/{efj}/metadata — upsert a single metadata field
3. GET   /api/load/{efj}/metadata — read metadata for a load
4. Merges metadata into /api/shipments response
"""

import sys, os, shutil, re

APP = "/root/csl-bot/csl-doc-tracker/app.py"

# ── Step 1: Create DB table ─────────────────────────────────────────────────
print("[1/3] Creating load_metadata table...")

import psycopg2
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS load_metadata (
    id              SERIAL PRIMARY KEY,
    efj             TEXT NOT NULL UNIQUE,
    notes           TEXT DEFAULT '',
    truck_type      TEXT DEFAULT '',
    customer_rate   TEXT DEFAULT '',
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_load_metadata_efj ON load_metadata(efj);
""")
conn.commit()
cur.close()
conn.close()
print("   Table created (or already exists).")

# ── Step 2: Read app.py ─────────────────────────────────────────────────────
print("[2/3] Reading app.py...")
with open(APP, "r") as f:
    code = f.read()

shutil.copy(APP, APP + ".bak_metadata")
print("   Backup saved to app.py.bak_metadata")

# ── Step 3: Inject endpoints + shipments merge ──────────────────────────────
print("[3/3] Patching app.py...")

METADATA_ENDPOINTS = '''

# ===================================================================
# LOAD METADATA API (notes, truck_type, customer_rate)
# Added by patch_dispatch_metadata.py
# ===================================================================

@app.get("/api/load/{efj}/metadata")
async def api_get_metadata(efj: str):
    """Get load metadata (notes, truck_type, customer_rate)."""
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT notes, truck_type, customer_rate FROM load_metadata WHERE efj = %s",
            (efj,)
        )
        row = cur.fetchone()
    if row:
        return {"notes": row["notes"] or "", "truck_type": row["truck_type"] or "", "customer_rate": row["customer_rate"] or ""}
    return {"notes": "", "truck_type": "", "customer_rate": ""}


@app.patch("/api/load/{efj}/metadata")
async def api_update_metadata(efj: str, request: Request):
    """Update a single metadata field for a load. Body: { field, value }"""
    body = await request.json()
    field = body.get("field", "").strip()
    value = body.get("value", "")
    if isinstance(value, str):
        value = value.strip()

    allowed = ("notes", "truck_type", "customer_rate")
    if field not in allowed:
        raise HTTPException(400, f"Invalid metadata field: {field}. Allowed: {allowed}")

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                f"""INSERT INTO load_metadata (efj, {field}, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (efj) DO UPDATE SET {field} = %s, updated_at = NOW()""",
                (efj, value, value)
            )
    return {"status": "ok", "efj": efj, "field": field, "value": value}

'''

if "api_get_metadata" in code:
    print("   Metadata endpoints already present — skipping endpoint injection.")
else:
    # Insert before the health endpoint or at end
    match = re.search(r'(@app\.(get|post)\("/health")', code)
    if match:
        code = code[:match.start()] + METADATA_ENDPOINTS + "\n" + code[match.start():]
    else:
        # Insert before if __name__
        match2 = re.search(r'if __name__\s*==', code)
        if match2:
            code = code[:match2.start()] + METADATA_ENDPOINTS + "\n" + code[match2.start():]
        else:
            code += METADATA_ENDPOINTS
    print("   Added GET/PATCH /api/load/{efj}/metadata endpoints")

# Now merge metadata into the /api/shipments response
MERGE_CODE = '''
    # ── Merge load_metadata (notes, truck_type, customer_rate) ──
    try:
        with db.get_cursor() as _mc:
            _mc.execute("SELECT efj, notes, truck_type, customer_rate FROM load_metadata")
            _meta_map = {r["efj"]: r for r in _mc.fetchall()}
        for _s in data:
            _m = _meta_map.get(_s.get("efj", ""), {})
            _s["notes"] = _m.get("notes", "") or _s.get("notes", "")
            _s["truck_type"] = _m.get("truck_type", "")
            _s["customer_rate"] = _m.get("customer_rate", "")
    except Exception:
        pass
'''

if "load_metadata" in code and "_meta_map" in code:
    print("   Metadata merge already present — skipping.")
else:
    # Find the shipments endpoint return line
    # Pattern: return {"shipments": data, ...}
    match = re.search(r'(    return \{"shipments": data)', code)
    if match:
        code = code[:match.start()] + MERGE_CODE + "\n" + code[match.start():]
        print("   Added metadata merge to /api/shipments")
    else:
        print("   WARNING: Could not find /api/shipments return statement — manual merge needed")

# Write patched file
with open(APP, "w") as f:
    f.write(code)
print("\nDone! Restart with: systemctl restart csl-dashboard")
