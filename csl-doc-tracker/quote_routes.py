"""
Quote Builder API routes.
"""
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, date, timedelta

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse

import database as db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quotes", tags=["quotes"])

UPLOAD_DIR = "/root/csl-bot/csl-doc-tracker/uploads/quotes"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _next_quote_number():
    year = datetime.now().year
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT quote_number FROM quotes WHERE quote_number LIKE %s ORDER BY id DESC LIMIT 1",
            (f"CSL-{year}-%",)
        )
        row = cur.fetchone()
    if row:
        seq = int(row["quote_number"].split("-")[-1]) + 1
    else:
        seq = 1
    return f"CSL-{year}-{seq:04d}"


# ── Settings ──

@router.get("/settings")
async def get_settings():
    with db.get_cursor() as cur:
        cur.execute("SELECT * FROM quote_settings WHERE id = 1")
        row = cur.fetchone()
    if not row:
        return {"default_margin_pct": 15, "default_terms": [], "default_accessorials": []}
    return {
        "default_margin_pct": float(row["default_margin_pct"]),
        "default_terms": row["default_terms"] if isinstance(row["default_terms"], list) else json.loads(row["default_terms"]),
        "default_accessorials": row["default_accessorials"] if isinstance(row["default_accessorials"], list) else json.loads(row["default_accessorials"]),
    }


@router.put("/settings")
async def update_settings(
    default_margin_pct: float = Form(None),
    default_terms: str = Form(None),
    default_accessorials: str = Form(None),
):
    updates = []
    params = []
    if default_margin_pct is not None:
        updates.append("default_margin_pct = %s")
        params.append(default_margin_pct)
    if default_terms is not None:
        updates.append("default_terms = %s")
        params.append(default_terms)
    if default_accessorials is not None:
        updates.append("default_accessorials = %s")
        params.append(default_accessorials)
    if not updates:
        raise HTTPException(400, "No fields to update")
    params.append(1)
    with db.get_cursor() as cur:
        cur.execute(f"UPDATE quote_settings SET {', '.join(updates)} WHERE id = %s", params)
    return {"ok": True}


# ── Extract ──

@router.post("/extract")
async def extract_quote(
    file: UploadFile = File(None),
    text: str = Form(None),
):
    if not file and not text:
        raise HTTPException(400, "Provide a file or text to extract from")

    try:
        from quote_extractor import extract_from_image, extract_from_pdf, extract_from_text, extract_from_email
    except ImportError as e:
        raise HTTPException(500, f"Extractor not available: {e}")

    if text:
        result = extract_from_text(text)
        return JSONResponse(result)

    # Save uploaded file temporarily
    suffix = os.path.splitext(file.filename or "upload")[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=UPLOAD_DIR) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        if suffix == ".pdf":
            result = extract_from_pdf(tmp_path)
        elif suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            result = extract_from_image(tmp_path)
        elif suffix in (".msg", ".eml"):
            result = extract_from_email(tmp_path)
        else:
            raise HTTPException(400, f"Unsupported file type: {suffix}")

        result["source_filename"] = file.filename
        return JSONResponse(result)
    except Exception as e:
        log.exception("Extraction failed")
        raise HTTPException(500, f"Extraction failed: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass



# ── Distance / Mileage Calculator ──

@router.get("/distance")
async def get_distance(origin: str = "", destination: str = ""):
    """Return driving distance and transit time between origin and destination."""
    import httpx, os
    if not origin or not destination:
        return JSONResponse({"error": "origin and destination required"}, status_code=400)
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "Google Maps API key not configured"}, status_code=500)
    try:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": origin,
            "destinations": destination,
            "units": "imperial",
            "key": api_key,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
        if data.get("status") != "OK":
            return JSONResponse({"error": f"API error: {data.get('status')}"}, status_code=502)
        element = data["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            return JSONResponse({"error": f"Route error: {element.get('status')}"}, status_code=404)
        meters = element["distance"]["value"]
        one_way = round(meters / 1609.344)
        seconds = element["duration"]["value"]
        hours = seconds / 3600
        if one_way <= 250:
            transit = "1 day"
        elif one_way <= 600:
            transit = "1-2 days"
        elif one_way <= 1200:
            transit = "2-3 days"
        elif one_way <= 2000:
            transit = "3-4 days"
        else:
            transit = "4-5 days"
        return {
            "one_way_miles": one_way,
            "round_trip_miles": one_way * 2,
            "transit_time": transit,
            "duration_hours": round(hours, 1),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── CRUD ──

@router.post("")
async def create_quote(
    quote_data: str = Form(...),
):
    data = json.loads(quote_data)
    qn = _next_quote_number()
    valid_until = data.get("valid_until")
    if not valid_until:
        valid_until = (date.today() + timedelta(days=7)).isoformat()

    with db.get_cursor() as cur:
        cur.execute("""
            INSERT INTO quotes (
                quote_number, created_by, status,
                pod, final_delivery, final_zip,
                round_trip_miles, one_way_miles, transit_time, shipment_type,
                carrier_name, carrier_total,
                margin_pct, sell_subtotal, accessorial_total, estimated_total,
                customer_name, customer_email, valid_until,
                linehaul_json, accessorials_json, terms_json, route_json,
                source_type, source_filename
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s
            )
            RETURNING id, quote_number, created_at
        """, (
            qn, data.get("created_by", ""), data.get("status", "draft"),
            data.get("pod", ""), data.get("final_delivery", ""), data.get("final_zip", ""),
            data.get("round_trip_miles", ""), data.get("one_way_miles", ""), data.get("transit_time", ""), data.get("shipment_type", ""),
            data.get("carrier_name", ""), data.get("carrier_total", 0),
            data.get("margin_pct", 15), data.get("sell_subtotal", 0), data.get("accessorial_total", 0), data.get("estimated_total", 0),
            data.get("customer_name", ""), data.get("customer_email", ""), valid_until,
            json.dumps(data.get("linehaul_items", [])), json.dumps(data.get("accessorials", [])),
            json.dumps(data.get("terms", [])), json.dumps(data.get("route", [])),
            data.get("source_type", ""), data.get("source_filename", ""),
        ))
        row = cur.fetchone()

    return {"id": row["id"], "quote_number": row["quote_number"], "created_at": str(row["created_at"])}


@router.get("")
async def list_quotes(
    status: str = Query(None),
    search: str = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
):
    where = []
    params = []
    if status:
        where.append("status = %s")
        params.append(status)
    if search:
        where.append("(quote_number ILIKE %s OR customer_name ILIKE %s OR pod ILIKE %s OR final_delivery ILIKE %s)")
        s = f"%{search}%"
        params.extend([s, s, s, s])

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    with db.get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) as total FROM quotes{where_sql}", params or None)
        total = cur.fetchone()["total"]

        params.extend([limit, offset])
        cur.execute(f"""
            SELECT id, quote_number, created_at, updated_at, created_by, status,
                   pod, final_delivery, shipment_type, carrier_name,
                   margin_pct, estimated_total, customer_name, source_type
            FROM quotes{where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params)
        rows = cur.fetchall()

    return {"total": total, "quotes": [dict(r) for r in rows]}


@router.get("/{quote_id}")
async def get_quote(quote_id: int):
    with db.get_cursor() as cur:
        cur.execute("SELECT * FROM quotes WHERE id = %s", (quote_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Quote not found")
    result = dict(row)
    # Ensure JSON fields are parsed
    for field in ("linehaul_json", "accessorials_json", "terms_json", "route_json"):
        if isinstance(result.get(field), str):
            result[field] = json.loads(result[field])
    return result


@router.put("/{quote_id}")
async def update_quote(quote_id: int, quote_data: str = Form(...)):
    data = json.loads(quote_data)

    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM quotes WHERE id = %s", (quote_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Quote not found")

        cur.execute("""
            UPDATE quotes SET
                updated_at = NOW(), status = %s,
                pod = %s, final_delivery = %s, final_zip = %s,
                round_trip_miles = %s, one_way_miles = %s, transit_time = %s, shipment_type = %s,
                carrier_name = %s, carrier_total = %s,
                margin_pct = %s, sell_subtotal = %s, accessorial_total = %s, estimated_total = %s,
                customer_name = %s, customer_email = %s, valid_until = %s,
                linehaul_json = %s, accessorials_json = %s, terms_json = %s, route_json = %s,
                source_type = %s, source_filename = %s
            WHERE id = %s
        """, (
            data.get("status", "draft"),
            data.get("pod", ""), data.get("final_delivery", ""), data.get("final_zip", ""),
            data.get("round_trip_miles", ""), data.get("one_way_miles", ""), data.get("transit_time", ""), data.get("shipment_type", ""),
            data.get("carrier_name", ""), data.get("carrier_total", 0),
            data.get("margin_pct", 15), data.get("sell_subtotal", 0), data.get("accessorial_total", 0), data.get("estimated_total", 0),
            data.get("customer_name", ""), data.get("customer_email", ""), data.get("valid_until"),
            json.dumps(data.get("linehaul_items", [])), json.dumps(data.get("accessorials", [])),
            json.dumps(data.get("terms", [])), json.dumps(data.get("route", [])),
            data.get("source_type", ""), data.get("source_filename", ""),
            quote_id,
        ))
    return {"ok": True}


@router.delete("/{quote_id}")
async def delete_quote(quote_id: int):
    with db.get_cursor() as cur:
        cur.execute("DELETE FROM quotes WHERE id = %s RETURNING id", (quote_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Quote not found")
    return {"ok": True}
