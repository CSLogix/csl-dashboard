#!/usr/bin/env python3
"""
Patch: Add unbilled orders API endpoints to app.py
- Creates unbilled_orders table in PostgreSQL
- Adds 4 endpoints: GET /api/unbilled, GET /api/unbilled/stats,
  POST /api/unbilled/upload, POST /api/unbilled/{id}/dismiss
- Installs xlrd for .xls file support
"""

import subprocess, sys, textwrap

APP = "/root/csl-bot/csl-doc-tracker/app.py"

# ── Step 0: Install xlrd for .xls parsing ──────────────────────────────────
print("[1/4] Installing xlrd...")
subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "xlrd"], check=True)

# ── Step 1: Create DB table ────────────────────────────────────────────────
print("[2/4] Creating unbilled_orders table...")

import psycopg2
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS unbilled_orders (
    id          SERIAL PRIMARY KEY,
    order_num   TEXT NOT NULL,
    container   TEXT,
    bill_to     TEXT,
    tractor     TEXT,
    entered     DATE,
    appt_date   DATE,
    dliv_dt     DATE,
    act_dt      DATE,
    age_days    INTEGER DEFAULT 0,
    dismissed   BOOLEAN DEFAULT FALSE,
    dismissed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    upload_batch TEXT
);
CREATE INDEX IF NOT EXISTS idx_unbilled_dismissed ON unbilled_orders(dismissed);
CREATE INDEX IF NOT EXISTS idx_unbilled_order ON unbilled_orders(order_num);
""")
conn.commit()
cur.close()
conn.close()
print("   Table created (or already exists).")

# ── Step 2: Add unbilled endpoints to app.py ───────────────────────────────
print("[3/4] Patching app.py with unbilled endpoints...")

UNBILLED_CODE = '''

# ═══════════════════════════════════════════════════════════════
# UNBILLED ORDERS API
# ═══════════════════════════════════════════════════════════════
import xlrd
from io import BytesIO

def _parse_unbilled_excel(file_bytes: bytes, filename: str) -> list:
    """Parse .xls or .xlsx unbilled orders file. Returns list of dicts."""
    rows = []
    if filename.lower().endswith(".xls"):
        wb = xlrd.open_workbook(file_contents=file_bytes)
        ws = wb.sheet_by_index(0)
        headers = [str(ws.cell_value(0, c)).strip() for c in range(ws.ncols)]
        for r in range(1, ws.nrows):
            row = {}
            for c, h in enumerate(headers):
                val = ws.cell_value(r, c)
                # xlrd returns dates as floats
                if ws.cell_type(r, c) == xlrd.XL_CELL_DATE:
                    try:
                        dt = xlrd.xldate_as_datetime(val, wb.datemode)
                        val = dt.strftime("%Y-%m-%d")
                    except Exception:
                        val = str(val)
                row[h] = val
            rows.append(row)
    else:
        import openpyxl
        wb = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            return []
        headers = [str(h).strip() if h else f"col{i}" for i, h in enumerate(all_rows[0])]
        for vals in all_rows[1:]:
            row = {}
            for h, v in zip(headers, vals):
                if hasattr(v, "strftime"):
                    v = v.strftime("%Y-%m-%d")
                row[h] = v
            rows.append(row)
        wb.close()
    return rows


def _map_unbilled_row(row: dict) -> dict:
    """Map Excel columns to DB columns. Flexible header matching."""
    def find(keys):
        for k in keys:
            for h in row:
                if k.lower() in h.lower():
                    return row[h]
        return None

    def safe_date(val):
        if not val:
            return None
        s = str(val).strip()
        if not s or s == "None":
            return None
        # Already YYYY-MM-DD from parser
        if len(s) == 10 and s[4] == "-":
            return s
        # Try MM/DD/YYYY
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                from datetime import datetime
                return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    return {
        "order_num": str(find(["Order"]) or "").strip(),
        "container": str(find(["Container"]) or "").strip(),
        "bill_to": str(find(["Bill"]) or "").strip(),
        "tractor": str(find(["Tractor"]) or "").strip(),
        "entered": safe_date(find(["Entered"])),
        "appt_date": safe_date(find(["Appt"])),
        "dliv_dt": safe_date(find(["DLIV"])),
        "act_dt": safe_date(find(["ACT"])),
    }


def _calc_age(entered_str):
    """Days since entered date."""
    if not entered_str:
        return 0
    try:
        from datetime import datetime, date
        d = datetime.strptime(str(entered_str), "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return 0


@app.post("/api/unbilled/upload")
async def api_unbilled_upload(request: Request):
    """Upload .xls/.xlsx file of unbilled orders. Replaces non-dismissed orders."""
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"error": "No file"}, status_code=400)

    filename = file.filename or "upload.xls"
    contents = await file.read()
    try:
        rows = _parse_unbilled_excel(contents, filename)
    except Exception as e:
        return JSONResponse({"error": f"Parse error: {e}"}, status_code=400)

    if not rows:
        return JSONResponse({"error": "No data rows found"}, status_code=400)

    mapped = [_map_unbilled_row(r) for r in rows]
    mapped = [m for m in mapped if m["order_num"]]  # skip empty rows

    from datetime import datetime
    batch_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            # Clear old non-dismissed orders
            cur.execute("DELETE FROM unbilled_orders WHERE dismissed = FALSE")
            # Insert new batch
            for m in mapped:
                age = _calc_age(m["entered"])
                cur.execute(
                    """INSERT INTO unbilled_orders
                       (order_num, container, bill_to, tractor, entered, appt_date, dliv_dt, act_dt, age_days, upload_batch)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (m["order_num"], m["container"], m["bill_to"], m["tractor"],
                     m["entered"], m["appt_date"], m["dliv_dt"], m["act_dt"], age, batch_id)
                )

    return JSONResponse({"ok": True, "imported": len(mapped), "batch": batch_id})


@app.get("/api/unbilled")
def api_unbilled_list():
    """List all non-dismissed unbilled orders."""
    with db.get_cursor() as cur:
        cur.execute(
            """SELECT id, order_num, container, bill_to, tractor,
                      entered::text, appt_date::text, dliv_dt::text, act_dt::text,
                      age_days, upload_batch, created_at::text
               FROM unbilled_orders
               WHERE dismissed = FALSE
               ORDER BY age_days DESC"""
        )
        rows = cur.fetchall()
    return JSONResponse({"orders": [dict(r) for r in rows]})


@app.get("/api/unbilled/stats")
def api_unbilled_stats():
    """Unbilled orders summary stats."""
    with db.get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM unbilled_orders WHERE dismissed = FALSE")
        count = cur.fetchone()["count"]
        cur.execute(
            """SELECT bill_to, COUNT(*) as cnt, MAX(age_days) as max_age
               FROM unbilled_orders WHERE dismissed = FALSE
               GROUP BY bill_to ORDER BY cnt DESC"""
        )
        by_customer = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT COALESCE(SUM(age_days), 0) as total_age FROM unbilled_orders WHERE dismissed = FALSE"
        )
        total_age = cur.fetchone()["total_age"]
        avg_age = round(total_age / count, 1) if count > 0 else 0
    return JSONResponse({"count": count, "avg_age": avg_age, "by_customer": by_customer})


@app.post("/api/unbilled/{order_id}/dismiss")
def api_unbilled_dismiss(order_id: int):
    """Dismiss (hide) an unbilled order."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE unbilled_orders SET dismissed = TRUE, dismissed_at = NOW() WHERE id = %s",
                (order_id,)
            )
    return JSONResponse({"ok": True})
'''

# Read current app.py
with open(APP, "r") as f:
    code = f.read()

# Check if already patched
if "/api/unbilled/upload" in code:
    print("   Already patched! Skipping.")
else:
    # Insert before the last react SPA route (which should be the catch-all)
    # Find the react_root function and insert before it
    marker = '@app.get("/app")'
    if marker in code:
        code = code.replace(marker, UNBILLED_CODE + "\n\n" + marker)
        with open(APP, "w") as f:
            f.write(code)
        print("   Patched successfully.")
    else:
        # Fallback: append before EOF
        code += UNBILLED_CODE
        with open(APP, "w") as f:
            f.write(code)
        print("   Appended to end of file.")

# ── Step 3: Add /api/unbilled paths to public paths ───────────────────────
print("[4/4] Adding unbilled paths to auth bypass...")

with open(APP, "r") as f:
    code = f.read()

# The PUBLIC_PATHS or the auth middleware checks path.startswith("/api/")
# which already covers /api/unbilled. Verify:
if 'path.startswith("/api/")' in code:
    print("   /api/ paths already bypassed in auth middleware. No change needed.")
else:
    print("   WARNING: May need to add /api/unbilled to auth bypass manually.")

print("\n✅ Done! Restart with: systemctl restart csl-dashboard")
