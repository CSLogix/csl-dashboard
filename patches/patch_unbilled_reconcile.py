#!/usr/bin/env python3
"""
Patch: Smart unbilled upload reconciliation + billing_status support
- Adds billing_status and dismissed_reason columns to unbilled_orders
- Adds partial unique index on order_num WHERE dismissed = FALSE
- Rewrites upload endpoint to UPSERT (preserves billing status across uploads)
- Adds POST /api/unbilled/{id}/status endpoint
- Updates list endpoint to include billing_status
"""

import sys, psycopg2

APP = "/root/csl-bot/csl-doc-tracker/app.py"

# ── Step 1: Schema migration ──────────────────────────────────────────────
print("[1/3] Migrating unbilled_orders schema...")
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()

# Add billing_status column if missing
cur.execute("""
    DO $$ BEGIN
        ALTER TABLE unbilled_orders ADD COLUMN billing_status TEXT DEFAULT 'ready_to_bill';
    EXCEPTION WHEN duplicate_column THEN NULL;
    END $$;
""")

# Add dismissed_reason column if missing
cur.execute("""
    DO $$ BEGIN
        ALTER TABLE unbilled_orders ADD COLUMN dismissed_reason TEXT;
    EXCEPTION WHEN duplicate_column THEN NULL;
    END $$;
""")

# Create partial unique index for UPSERT (only on non-dismissed orders)
# Drop old non-unique index first if it conflicts
cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_unbilled_order_active
    ON unbilled_orders(order_num) WHERE dismissed = FALSE;
""")

conn.commit()
cur.close()
conn.close()
print("   Schema migrated (billing_status, dismissed_reason, unique index).")

# ── Step 2: Rewrite upload endpoint ───────────────────────────────────────
print("[2/3] Patching upload endpoint with UPSERT reconciliation...")

with open(APP, "r") as f:
    code = f.read()

# Check if already patched
if "ON CONFLICT (order_num) WHERE dismissed = FALSE" in code:
    print("   Upload already patched — skipping.")
else:
    OLD_UPLOAD = '''@app.post("/api/unbilled/upload")
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

    return JSONResponse({"ok": True, "imported": len(mapped), "batch": batch_id})'''

    NEW_UPLOAD = '''@app.post("/api/unbilled/upload")
async def api_unbilled_upload(request: Request):
    """Upload .xls/.xlsx file of unbilled orders. Smart UPSERT reconciliation."""
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

    inserted = 0
    updated = 0
    reconciled = 0

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            # UPSERT each row — preserves billing_status for existing orders
            for m in mapped:
                age = _calc_age(m["entered"])
                cur.execute(
                    """INSERT INTO unbilled_orders
                       (order_num, container, bill_to, tractor, entered, appt_date, dliv_dt, act_dt, age_days, upload_batch)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (order_num) WHERE dismissed = FALSE
                       DO UPDATE SET
                           container = EXCLUDED.container,
                           bill_to = EXCLUDED.bill_to,
                           tractor = EXCLUDED.tractor,
                           entered = EXCLUDED.entered,
                           appt_date = EXCLUDED.appt_date,
                           dliv_dt = EXCLUDED.dliv_dt,
                           act_dt = EXCLUDED.act_dt,
                           age_days = EXCLUDED.age_days,
                           upload_batch = EXCLUDED.upload_batch""",
                    (m["order_num"], m["container"], m["bill_to"], m["tractor"],
                     m["entered"], m["appt_date"], m["dliv_dt"], m["act_dt"], age, batch_id)
                )
                if cur.statusmessage.startswith("INSERT"):
                    inserted += 1
                else:
                    updated += 1

            # Auto-dismiss orders NOT in this upload (they dropped off the report)
            cur.execute(
                """UPDATE unbilled_orders
                   SET dismissed = TRUE, dismissed_at = NOW(), dismissed_reason = 'reconciled'
                   WHERE dismissed = FALSE AND upload_batch != %s""",
                (batch_id,)
            )
            reconciled = cur.rowcount

    log.info("Unbilled upload: %d inserted, %d updated, %d reconciled (batch=%s)",
             inserted, updated, reconciled, batch_id)
    return JSONResponse({
        "ok": True, "imported": inserted + updated,
        "inserted": inserted, "updated": updated, "reconciled": reconciled,
        "batch": batch_id
    })'''

    if OLD_UPLOAD not in code:
        print("   ERROR: Could not find old upload endpoint")
        sys.exit(1)

    code = code.replace(OLD_UPLOAD, NEW_UPLOAD)

# ── Step 3: Update list endpoint + add billing status endpoint ────────────
print("[3/3] Updating list endpoint and adding billing status endpoint...")

# Update the list query to include billing_status
OLD_LIST = '''@app.get("/api/unbilled")
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
    return JSONResponse({"orders": [dict(r) for r in rows]})'''

NEW_LIST = '''@app.get("/api/unbilled")
def api_unbilled_list():
    """List all non-dismissed unbilled orders."""
    with db.get_cursor() as cur:
        cur.execute(
            """SELECT id, order_num, container, bill_to, tractor,
                      entered::text, appt_date::text, dliv_dt::text, act_dt::text,
                      age_days, billing_status, upload_batch, created_at::text
               FROM unbilled_orders
               WHERE dismissed = FALSE
               ORDER BY age_days DESC"""
        )
        rows = cur.fetchall()
    return JSONResponse({"orders": [dict(r) for r in rows]})'''

if OLD_LIST in code:
    code = code.replace(OLD_LIST, NEW_LIST)
else:
    print("   WARNING: Could not find old list endpoint — may already be updated")

# Add billing status update endpoint after the dismiss endpoint
OLD_DISMISS = '''@app.post("/api/unbilled/{order_id}/dismiss")
def api_unbilled_dismiss(order_id: int):
    """Dismiss (hide) an unbilled order."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE unbilled_orders SET dismissed = TRUE, dismissed_at = NOW() WHERE id = %s",
                (order_id,)
            )
    return JSONResponse({"ok": True})'''

NEW_DISMISS_PLUS_STATUS = '''@app.post("/api/unbilled/{order_id}/dismiss")
def api_unbilled_dismiss(order_id: int):
    """Dismiss (hide) an unbilled order."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE unbilled_orders SET dismissed = TRUE, dismissed_at = NOW(), dismissed_reason = 'manual' WHERE id = %s",
                (order_id,)
            )
    return JSONResponse({"ok": True})


@app.post("/api/unbilled/{order_id}/status")
async def api_unbilled_update_status(order_id: int, request: Request):
    """Update billing status of an unbilled order."""
    body = await request.json()
    new_status = body.get("billing_status", "").strip()
    if not new_status:
        raise HTTPException(400, "Missing billing_status")
    valid = ("ready_to_bill", "billed_cx", "driver_paid", "closed")
    if new_status not in valid:
        raise HTTPException(400, f"Invalid billing_status: {new_status}")
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE unbilled_orders SET billing_status = %s WHERE id = %s AND dismissed = FALSE",
                (new_status, order_id)
            )
            if cur.rowcount == 0:
                raise HTTPException(404, f"Order {order_id} not found or dismissed")
    # Auto-dismiss when closed
    if new_status == "closed":
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute(
                    "UPDATE unbilled_orders SET dismissed = TRUE, dismissed_at = NOW(), dismissed_reason = 'closed' WHERE id = %s",
                    (order_id,)
                )
    return JSONResponse({"ok": True, "billing_status": new_status})'''

if OLD_DISMISS in code:
    code = code.replace(OLD_DISMISS, NEW_DISMISS_PLUS_STATUS)
else:
    print("   WARNING: Could not find dismiss endpoint — may already be updated")

with open(APP, "w") as f:
    f.write(code)

print("   Done! Unbilled reconciliation patch applied.")
print("   Restart: systemctl restart csl-dashboard")
