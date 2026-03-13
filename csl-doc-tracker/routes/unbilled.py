import logging
import os
import sys
from datetime import datetime, date
from io import BytesIO

import xlrd
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import database as db
from shared import log

router = APIRouter()
_completed_cache = {"ts": 0, "data": []}


def _parse_unbilled_excel(file_bytes: bytes, filename: str) -> list:
    """Parse .xls or .xlsx unbilled orders file. Returns list of dicts."""
    rows = []
    if filename.lower().endswith(".xls"):
        wb = xlrd.open_workbook(file_contents=file_bytes)
        ws = wb.sheet_by_index(0)
        # Find header row: look for row containing "Order#"
        header_row = 0
        for r in range(min(5, ws.nrows)):
            vals = [str(ws.cell_value(r, c)).strip().lower() for c in range(ws.ncols)]
            if any("order#" in v for v in vals):
                header_row = r
                break
        headers = [str(ws.cell_value(header_row, c)).strip() for c in range(ws.ncols)]
        for r in range(header_row + 1, ws.nrows):
            row = {}
            for c, h in enumerate(headers):
                val = ws.cell_value(r, c)
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
        # Find header row (look for "Order")
        header_idx = 0
        for idx, r in enumerate(all_rows[:5]):
            if any("order#" in str(v).lower() for v in r if v):
                header_idx = idx
                break
        headers = [str(h).strip() if h else f"col{i}" for i, h in enumerate(all_rows[header_idx])]
        for vals in all_rows[header_idx + 1:]:
            row = {}
            for h, v in zip(headers, vals):
                if hasattr(v, "strftime"):
                    v = v.strftime("%Y-%m-%d")
                row[h] = v
            rows.append(row)
        wb.close()
    return rows


def _map_unbilled_row(row: dict) -> dict:
    """Map Excel columns to DB columns. Exact header matching with fallbacks."""
    def find(keys):
        for k in keys:
            # Try exact match first
            if k in row:
                return row[k]
            # Then case-insensitive exact
            for h in row:
                if h.lower().strip() == k.lower():
                    return row[h]
            # Then substring
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


def _archive_shipment_on_close(efj: str):
    """Archive a shipment in PG + Google Sheet when its unbilled order is closed."""
    import sys as _sys
    _csl_bot_dir = "/root/csl-bot"
    if _csl_bot_dir not in _sys.path:
        _sys.path.insert(0, _csl_bot_dir)
    # PG archive
    try:
        from csl_pg_writer import pg_archive_shipment
        pg_archive_shipment(efj)
        log.info("Unbilled close → PG archived %s", efj)
    except Exception as e:
        log.warning("Unbilled close → PG archive failed for %s: %s", efj, e)
    # Sheet archive (fire-and-forget)
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT account, rep FROM shipments WHERE efj = %s", (efj,))
            ship = cur.fetchone()
        if ship and ship.get("account"):
            from csl_sheet_writer import sheet_archive_row
            sheet_archive_row(efj, ship["account"], ship.get("rep"))
    except Exception as e:
        log.warning("Unbilled close → sheet archive failed for %s: %s", efj, e)
    # Invalidate completed cache
    _completed_cache["ts"] = 0


@router.post("/api/unbilled/upload")
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

    # Cross-reference: how many active unbilled orders have delivered shipments?
    delivered_count = 0
    try:
        with db.get_cursor() as _xref_cur:
            _xref_cur.execute("""
                SELECT COUNT(*) as cnt
                FROM unbilled_orders u
                JOIN shipments s ON REPLACE(u.order_num, ' ', '') = s.efj
                WHERE u.dismissed = FALSE
                  AND LOWER(s.status) IN ('delivered','completed','empty returned','billed_closed','returned to port')
            """)
            delivered_count = _xref_cur.fetchone()["cnt"]
    except Exception:
        pass

    log.info("Unbilled upload: %d inserted, %d updated, %d reconciled, %d delivered (batch=%s)",
             inserted, updated, reconciled, delivered_count, batch_id)
    return JSONResponse({
        "ok": True, "imported": inserted + updated,
        "inserted": inserted, "updated": updated, "reconciled": reconciled,
        "delivered_count": delivered_count,
        "batch": batch_id
    })


@router.get("/api/unbilled")
def api_unbilled_list():
    """List all non-dismissed unbilled orders, enriched with shipment status."""
    with db.get_cursor() as cur:
        cur.execute(
        """SELECT u.id, u.order_num, u.container, u.bill_to, u.tractor,
                  u.entered::text, u.appt_date::text, u.dliv_dt::text, u.act_dt::text,
                  u.age_days, u.upload_batch, u.created_at::text,
                  COALESCE(u.billing_status, 'ready_to_bill') as billing_status,
                  s.status as shipment_status,
                  s.account as shipment_account,
                  s.delivery_date::text as shipment_delivery,
                  s.archived as shipment_archived,
                  CASE WHEN LOWER(COALESCE(s.status,'')) IN
                       ('delivered','completed','empty returned','billed_closed','returned to port')
                       THEN TRUE ELSE FALSE END as shipment_delivered
           FROM unbilled_orders u
           LEFT JOIN shipments s ON REPLACE(u.order_num, ' ', '') = s.efj
           WHERE u.dismissed = FALSE
           ORDER BY u.age_days DESC"""
        )
        rows = cur.fetchall()
    return JSONResponse({"orders": [dict(r) for r in rows]})


@router.get("/api/unbilled/stats")
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
    # Count unbilled orders with delivered shipments
    delivered_count = 0
    try:
        with db.get_cursor() as _dc:
            _dc.execute("""
                SELECT COUNT(*) as cnt
                FROM unbilled_orders u
                JOIN shipments s ON REPLACE(u.order_num, ' ', '') = s.efj
                WHERE u.dismissed = FALSE
                  AND LOWER(s.status) IN ('delivered','completed','empty returned','billed_closed','returned to port')
            """)
            delivered_count = _dc.fetchone()["cnt"]
    except Exception:
        pass
    return JSONResponse({"count": count, "avg_age": avg_age, "by_customer": by_customer, "delivered_count": delivered_count})


@router.post("/api/unbilled/{order_id}/dismiss")
def api_unbilled_dismiss(order_id: int):
    """Dismiss (hide) an unbilled order."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE unbilled_orders SET dismissed = TRUE, dismissed_at = NOW(), dismissed_reason = 'manual' WHERE id = %s",
                (order_id,)
            )
    return JSONResponse({"ok": True})


@router.post("/api/unbilled/{order_id}/status")
async def api_unbilled_update_status(order_id: int, request: Request):
    """Update billing status of an unbilled order. Auto-archives shipment on 'closed'."""
    body = await request.json()
    new_status = body.get("billing_status", "").strip()
    if not new_status:
        raise HTTPException(400, "Missing billing_status")
    valid = ("ready_to_bill", "billed_cx", "driver_paid", "closed")
    if new_status not in valid:
        raise HTTPException(400, f"Invalid billing_status: {new_status}")

    # Update billing status + get order_num for cross-reference
    order_num = None
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE unbilled_orders SET billing_status = %s WHERE id = %s AND dismissed = FALSE RETURNING order_num",
                (new_status, order_id)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, f"Order {order_id} not found or dismissed")
            order_num = row["order_num"]

    # Auto-dismiss + archive on closed
    if new_status == "closed" and order_num:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute(
                    "UPDATE unbilled_orders SET dismissed = TRUE, dismissed_at = NOW(), dismissed_reason = 'closed' WHERE id = %s",
                    (order_id,)
                )
        # Archive matching shipment
        efj = order_num.replace(" ", "").strip()
        if efj:
            _archive_shipment_on_close(efj)

    return JSONResponse({"ok": True, "billing_status": new_status})


@router.post("/api/unbilled/bulk-close-delivered")
async def api_unbilled_bulk_close_delivered():
    """Close all unbilled orders whose matching shipment is delivered/completed."""
    closed_efjs = []
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                UPDATE unbilled_orders u
                SET billing_status = 'closed',
                    dismissed = TRUE,
                    dismissed_at = NOW(),
                    dismissed_reason = 'auto_delivered'
                FROM shipments s
                WHERE REPLACE(u.order_num, ' ', '') = s.efj
                  AND u.dismissed = FALSE
                  AND LOWER(s.status) IN ('delivered','completed','empty returned','billed_closed','returned to port')
                RETURNING s.efj
            """)
            closed_efjs = [r["efj"] for r in cur.fetchall()]

    # Archive each in PG + sheet (best-effort)
    for efj in closed_efjs:
        _archive_shipment_on_close(efj)

    log.info("Bulk close delivered: %d orders closed + archived", len(closed_efjs))
    return JSONResponse({"ok": True, "closed_count": len(closed_efjs)})
