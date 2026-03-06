#!/usr/bin/env python3
"""
Patch: Timestamped Notes Log
- Creates load_notes table in PostgreSQL
- Adds GET /api/load/{efj}/notes endpoint (returns all notes, newest first)
- Adds POST /api/load/{efj}/notes endpoint (adds a timestamped note)
"""

import sys, psycopg2

APP = "/root/csl-bot/csl-doc-tracker/app.py"

# -- Step 1: Schema migration ------------------------------------------------
print("[1/2] Creating load_notes table...")
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS load_notes (
    id SERIAL PRIMARY KEY,
    efj TEXT NOT NULL,
    note_text TEXT NOT NULL,
    created_by TEXT DEFAULT 'dashboard',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
""")

cur.execute("""
CREATE INDEX IF NOT EXISTS idx_load_notes_efj ON load_notes(efj);
""")

conn.commit()
cur.close()
conn.close()
print("   Table ready.")

# -- Step 2: Add endpoints to app.py -----------------------------------------
print("[2/2] Patching app.py with notes endpoints...")

with open(APP, "r") as f:
    code = f.read()

if "/api/load/{efj}/notes" in code:
    print("   Already patched -- skipping.")
    sys.exit(0)

# Insert after the driver POST endpoint
ANCHOR = '''@app.post("/api/load/{efj}/driver")
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
    return {"status": "ok", "efj": efj}'''

NOTES_ENDPOINTS = '''


# -- Timestamped Notes Log ---------------------------------------------------

@app.get("/api/load/{efj}/notes")
def api_load_notes_list(efj: str):
    """List all timestamped notes for a load, newest first."""
    with db.get_cursor() as cur:
        cur.execute(
            """SELECT id, efj, note_text, created_by, created_at::text
               FROM load_notes
               WHERE efj = %s
               ORDER BY created_at DESC""",
            (efj,)
        )
        rows = cur.fetchall()
    return JSONResponse({"notes": [dict(r) for r in rows]})


@app.post("/api/load/{efj}/notes")
async def api_load_notes_add(efj: str, request: Request):
    """Add a timestamped note to a load."""
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Missing note text")
    created_by = (body.get("created_by") or "dashboard").strip()
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO load_notes (efj, note_text, created_by)
                   VALUES (%s, %s, %s)
                   RETURNING id, efj, note_text, created_by, created_at::text""",
                (efj, text, created_by)
            )
            row = cur.fetchone()
    log.info("Note added for %s by %s", efj, created_by)
    return JSONResponse({"ok": True, "note": dict(row)})'''

if ANCHOR not in code:
    print("   ERROR: Could not find driver POST endpoint anchor")
    sys.exit(1)

code = code.replace(ANCHOR, ANCHOR + NOTES_ENDPOINTS)

with open(APP, "w") as f:
    f.write(code)

print("   Done! Notes log patch applied.")
print("   Restart: systemctl restart csl-dashboard")
