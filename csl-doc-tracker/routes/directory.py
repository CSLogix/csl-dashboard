import logging
import os
from decimal import Decimal
from fastapi import APIRouter, Query, Request, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
import database as db

log = logging.getLogger(__name__)
router = APIRouter()


def _serialize_row(row):
    """Convert a DB row dict to JSON-safe dict."""
    d = dict(row)
    for k in ("created_at", "updated_at", "effective_date", "quote_date", "indexed_at", "date_quoted"):
        if d.get(k) and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    # Decimal -> float
    for k, v in d.items():
        if hasattr(v, "as_tuple"):
            d[k] = float(v)
    return d


@router.get("/api/carriers")
async def api_list_carriers(
    search: str = Query(default=None),
    region: str = Query(default=None),
    market: str = Query(default=None),
    capability: str = Query(default=None),
    exclude_dnu: bool = Query(default=False),
    include_lanes: bool = Query(default=False),
):
    with db.get_cursor() as cur:
        clauses, params = [], []
        if search:
            clauses.append("(carrier_name ILIKE %s OR mc_number ILIKE %s OR contact_email ILIKE %s)")
            s = f"%{search}%"
            params.extend([s, s, s])
        if region:
            clauses.append("regions ILIKE %s")
            params.append(f"%{region}%")
        if market:
            clauses.append("%s = ANY(markets)")
            params.append(market)
        if exclude_dnu:
            clauses.append("(dnu IS NOT TRUE)")
        if capability:
            caps = [c.strip().lower() for c in capability.split(",") if c.strip()]
            cap_map = {
                "hazmat": "can_hazmat", "dray": "can_dray", "overweight": "can_overweight",
                "transload": "can_transload", "reefer": "can_reefer", "bonded": "can_bonded",
                "oog": "can_oog", "warehousing": "can_warehousing",
            }
            for cap in caps:
                col = cap_map.get(cap)
                if col:
                    clauses.append(f"{col} IS TRUE")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(f"SELECT * FROM carriers {where} ORDER BY tier_rank ASC NULLS LAST, carrier_name ASC", params)
        rows = [_serialize_row(r) for r in cur.fetchall()]

        # Optionally nest lane_rates per carrier
        if include_lanes and rows:
            carrier_names = list({r.get("carrier_name") for r in rows if r.get("carrier_name")})
            if carrier_names:
                placeholders = ",".join(["%s"] * len(carrier_names))
                cur.execute(
                    f"SELECT * FROM lane_rates WHERE carrier_name IN ({placeholders}) ORDER BY port, destination, total ASC NULLS LAST",
                    carrier_names,
                )
                lane_rows = [_serialize_row(r) for r in cur.fetchall()]
                lanes_by_carrier = {}
                for lr in lane_rows:
                    cn = lr.get("carrier_name", "")
                    lanes_by_carrier.setdefault(cn, []).append(lr)
                for row in rows:
                    row["lane_rates"] = lanes_by_carrier.get(row.get("carrier_name", ""), [])

    return JSONResponse({"carriers": rows, "total": len(rows)})


@router.post("/api/carriers")
async def api_create_carrier(request: Request):
    body = await request.json()
    fields = ["carrier_name", "mc_number", "dot_number", "contact_email", "contact_phone",
              "contact_name", "regions", "ports", "rail_ramps", "equipment_types", "notes", "source",
              "pickup_area", "destination_area", "date_quoted", "v_code",
              "can_dray", "can_hazmat", "can_overweight", "can_transload",
              "can_reefer", "can_bonded", "can_oog", "can_warehousing",
              "tier_rank", "dnu", "trucks",
              "service_feedback", "service_notes", "service_record", "comments", "insurance_info",
              "markets", "haz_classes"]
    bool_fields = {"can_dray", "can_hazmat", "can_overweight", "can_transload",
                   "can_reefer", "can_bonded", "can_oog", "can_warehousing", "dnu"}
    int_fields = {"tier_rank", "trucks"}
    array_fields = {"markets", "haz_classes"}
    vals = []
    for f in fields:
        if f in bool_fields:
            vals.append(bool(body.get(f, False)))
        elif f in int_fields:
            v = body.get(f)
            vals.append(int(v) if v is not None else None)
        elif f in array_fields:
            v = body.get(f)
            if isinstance(v, list):
                vals.append(v)
            elif isinstance(v, str) and v:
                vals.append([x.strip() for x in v.split(",") if x.strip()])
            else:
                vals.append(None)
        elif f == "carrier_name":
            vals.append(body.get(f, ""))
        else:
            vals.append(body.get(f, None))
    if not vals[0]:
        vals[0] = "Unknown Carrier"
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(f"""
                INSERT INTO carriers ({', '.join(fields)})
                VALUES ({', '.join(['%s'] * len(fields))}) RETURNING *
            """, vals)
            row = _serialize_row(cur.fetchone())
    return JSONResponse(row)


@router.put("/api/carriers/{carrier_id}")
async def api_update_carrier(carrier_id: int, request: Request):
    body = await request.json()
    allowed = {"carrier_name", "mc_number", "dot_number", "contact_email", "contact_phone",
               "contact_name", "regions", "ports", "rail_ramps", "equipment_types", "notes",
               "pickup_area", "destination_area", "date_quoted", "v_code",
               "can_dray", "can_hazmat", "can_overweight", "can_transload",
               "can_reefer", "can_bonded", "can_oog", "can_warehousing",
               "tier_rank", "dnu", "trucks",
               "service_feedback", "service_notes", "service_record", "comments", "insurance_info",
               "markets", "haz_classes"}
    bool_fields = {"can_dray", "can_hazmat", "can_overweight", "can_transload",
                   "can_reefer", "can_bonded", "can_oog", "can_warehousing", "dnu"}
    int_fields = {"tier_rank", "trucks"}
    array_fields = {"markets", "haz_classes"}
    sets, params = [], []
    for k, v in body.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            if k in bool_fields:
                params.append(bool(v))
            elif k in int_fields:
                params.append(int(v) if v is not None else None)
            elif k in array_fields:
                if isinstance(v, list):
                    params.append(v)
                elif isinstance(v, str) and v:
                    params.append([x.strip() for x in v.split(",") if x.strip()])
                else:
                    params.append(None)
            else:
                params.append(v)
    if not sets:
        raise HTTPException(400, "No valid fields")
    sets.append("updated_at = NOW()")
    params.append(carrier_id)
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(f"UPDATE carriers SET {', '.join(sets)} WHERE id = %s RETURNING *", params)
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Carrier not found")
    return JSONResponse(_serialize_row(row))


@router.delete("/api/carriers/{carrier_id}")
async def api_delete_carrier(carrier_id: int):
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("DELETE FROM carriers WHERE id = %s", (carrier_id,))
    return JSONResponse({"ok": True})


_CARRIER_EXTRACT_PROMPT = """Extract carrier directory information from this document (rate sheet, carrier packet, or screenshot).
Return ONLY valid JSON (no markdown, no explanation) with these fields:
{
  "carrier_name": "string",
  "mc_number": "MC number digits only, or null",
  "dot_number": "DOT/USDOT number digits only, or null",
  "contact_email": "string or null",
  "contact_phone": "string or null",
  "contact_name": "string or null",
  "regions": "comma-separated service regions or null",
  "ports": "comma-separated ports served or null",
  "equipment_types": "comma-separated equipment types (Dry Van, Flatbed, Reefer, etc.) or null",
  "rates": [{"lane": "origin to destination", "rate": "dollar amount", "equipment": "type"}]
}
Extract ALL lanes/rates if this is a rate sheet. Omit null fields."""


@router.post("/api/carriers/extract")
async def api_carrier_extract(request: Request):
    """Extract carrier info from uploaded file via Claude Vision."""
    import config
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(422, "ANTHROPIC_API_KEY not configured")
    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(400, "No file provided")
    file_bytes = await file.read()
    filename = getattr(file, "filename", "") or ""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    import base64
    if ext in ("png", "jpg", "jpeg", "gif", "webp"):
        media_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "gif": "image/gif", "webp": "image/webp"}
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_map.get(ext, "image/png"),
                                         "data": base64.b64encode(file_bytes).decode()}},
            {"type": "text", "text": _CARRIER_EXTRACT_PROMPT},
        ]
    elif ext == "pdf":
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.b64encode(file_bytes).decode()}},
            {"type": "text", "text": _CARRIER_EXTRACT_PROMPT},
        ]
    elif ext in ("txt", "csv", "eml"):
        text_content = file_bytes.decode("utf-8", errors="replace")
        content = [{"type": "text", "text": _CARRIER_EXTRACT_PROMPT + "\n\n" + text_content}]
    else:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    try:
        from shared import _extract_with_claude
        result = _extract_with_claude(content)
        return JSONResponse(result)
    except Exception as e:
        log.error("Carrier extraction failed: %s", e)
        raise HTTPException(500, f"AI extraction failed: {e}")


# ═══════════════════════════════════════════════════════════
# WAREHOUSE DIRECTORY API
# ═══════════════════════════════════════════════════════════

@router.get("/api/warehouses")
async def api_list_warehouses(search: str = Query(default=None), region: str = Query(default=None),
                              state: str = Query(default=None)):
    with db.get_cursor() as cur:
        clauses, params = [], []
        if search:
            clauses.append("(name ILIKE %s OR mc_number ILIKE %s OR contact_email ILIKE %s)")
            s = f"%{search}%"
            params.extend([s, s, s])
        if region:
            clauses.append("region ILIKE %s")
            params.append(f"%{region}%")
        if state:
            clauses.append("state = %s")
            params.append(state.upper())
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(f"SELECT * FROM warehouses {where} ORDER BY name ASC", params)
        warehouses = [_serialize_row(r) for r in cur.fetchall()]
        # Attach rate summaries
        wh_ids = [w["id"] for w in warehouses]
        if wh_ids:
            cur.execute("""SELECT warehouse_id, rate_type, rate_amount, unit, description
                           FROM warehouse_rates WHERE warehouse_id = ANY(%s) ORDER BY warehouse_id, rate_type""",
                        (wh_ids,))
            rates_map = {}
            for r in cur.fetchall():
                rates_map.setdefault(r["warehouse_id"], []).append(_serialize_row(r))
            for w in warehouses:
                w["rates"] = rates_map.get(w["id"], [])
    return JSONResponse({"warehouses": warehouses})


@router.post("/api/warehouses")
async def api_create_warehouse(request: Request):
    body = await request.json()
    fields = ["name", "mc_number", "region", "address", "city", "state", "zip_code",
              "contact_name", "contact_email", "contact_phone", "services", "notes", "source"]
    vals = [body.get(f, "" if f == "name" else None) for f in fields]
    if not vals[0]:
        vals[0] = "Unknown Warehouse"
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(f"""INSERT INTO warehouses ({', '.join(fields)})
                VALUES ({', '.join(['%s'] * len(fields))}) RETURNING *""", vals)
            row = _serialize_row(cur.fetchone())
    return JSONResponse(row)


@router.put("/api/warehouses/{wh_id}")
async def api_update_warehouse(wh_id: int, request: Request):
    body = await request.json()
    allowed = {"name", "mc_number", "region", "address", "city", "state", "zip_code",
               "contact_name", "contact_email", "contact_phone", "services", "notes"}
    sets, params = [], []
    for k, v in body.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            params.append(v)
    if not sets:
        raise HTTPException(400, "No valid fields")
    sets.append("updated_at = NOW()")
    params.append(wh_id)
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(f"UPDATE warehouses SET {', '.join(sets)} WHERE id = %s RETURNING *", params)
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Warehouse not found")
    return JSONResponse(_serialize_row(row))


@router.delete("/api/warehouses/{wh_id}")
async def api_delete_warehouse(wh_id: int):
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("DELETE FROM warehouses WHERE id = %s", (wh_id,))
    return JSONResponse({"ok": True})


@router.get("/api/warehouses/{wh_id}/rates")
async def api_warehouse_rates(wh_id: int):
    with db.get_cursor() as cur:
        cur.execute("SELECT * FROM warehouse_rates WHERE warehouse_id = %s ORDER BY rate_type", (wh_id,))
        rows = [_serialize_row(r) for r in cur.fetchall()]
    return JSONResponse({"rates": rows})


@router.post("/api/warehouses/{wh_id}/rates")
async def api_add_warehouse_rate(wh_id: int, request: Request):
    body = await request.json()
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""INSERT INTO warehouse_rates (warehouse_id, rate_type, rate_amount, unit, description, notes)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                (wh_id, body.get("rate_type", "flat"), body.get("rate_amount"),
                 body.get("unit"), body.get("description"), body.get("notes")))
            row = _serialize_row(cur.fetchone())
    return JSONResponse(row)


@router.delete("/api/warehouses/{wh_id}/rates/{rate_id}")
async def api_delete_warehouse_rate(wh_id: int, rate_id: int):
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("DELETE FROM warehouse_rates WHERE id = %s AND warehouse_id = %s", (rate_id, wh_id))
    return JSONResponse({"ok": True})


_WAREHOUSE_EXTRACT_PROMPT = """Extract warehouse/transloading facility information from this rate card or document.
Return ONLY valid JSON (no markdown, no explanation) with these fields:
{
  "name": "facility name",
  "mc_number": "MC number digits or null",
  "address": "full address or null",
  "city": "string or null",
  "state": "2-letter state code or null",
  "contact_name": "string or null",
  "contact_email": "string or null",
  "contact_phone": "string or null",
  "services": "comma-separated services (Transload, Cross-dock, Storage, etc.) or null",
  "rates": [
    {"rate_type": "per_pallet|per_day|per_container|monthly_min|per_hour|flat|per_case|per_label",
     "rate_amount": numeric, "unit": "string", "description": "what this covers"}
  ]
}
Extract ALL rate line items. Look for per-pallet, per-day storage, container handling, labeling, monthly minimums. Omit null fields."""


@router.post("/api/warehouses/extract")
async def api_warehouse_extract(request: Request):
    """Extract warehouse info from uploaded file via Claude Vision."""
    import config
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(422, "ANTHROPIC_API_KEY not configured")
    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(400, "No file provided")
    file_bytes = await file.read()
    filename = getattr(file, "filename", "") or ""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    import base64
    if ext in ("png", "jpg", "jpeg", "gif", "webp"):
        media_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "gif": "image/gif", "webp": "image/webp"}
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_map.get(ext, "image/png"),
                                         "data": base64.b64encode(file_bytes).decode()}},
            {"type": "text", "text": _WAREHOUSE_EXTRACT_PROMPT},
        ]
    elif ext == "pdf":
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.b64encode(file_bytes).decode()}},
            {"type": "text", "text": _WAREHOUSE_EXTRACT_PROMPT},
        ]
    elif ext in ("txt", "csv", "eml"):
        text_content = file_bytes.decode("utf-8", errors="replace")
        content = [{"type": "text", "text": _WAREHOUSE_EXTRACT_PROMPT + "\n\n" + text_content}]
    else:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    try:
        from shared import _extract_with_claude
        result = _extract_with_claude(content)
        return JSONResponse(result)
    except Exception as e:
        log.error("Warehouse extraction failed: %s", e)
        raise HTTPException(500, f"AI extraction failed: {e}")


# ═══════════════════════════════════════════════════════════
# LANE RATES API
# ═══════════════════════════════════════════════════════════

@router.get("/api/lane-rates")
async def api_list_lane_rates(port: str = Query(default=None), carrier: str = Query(default=None),
                              destination: str = Query(default=None)):
    with db.get_cursor() as cur:
        clauses, params = [], []
        if port:
            clauses.append("port ILIKE %s")
            params.append(f"%{port}%")
        if carrier:
            clauses.append("carrier_name ILIKE %s")
            params.append(f"%{carrier}%")
        if destination:
            clauses.append("destination ILIKE %s")
            params.append(f"%{destination}%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(f"SELECT * FROM lane_rates {where} ORDER BY port, destination, total ASC NULLS LAST LIMIT 1000", params)
        rows = [_serialize_row(r) for r in cur.fetchall()]
    return JSONResponse({"lane_rates": rows, "total": len(rows)})

@router.put("/api/lane-rates/{rate_id}")
async def api_update_lane_rate(rate_id: int, request: Request):
    body = await request.json()
    allowed = {"port", "destination", "carrier_name", "dray_rate", "fsc", "total",
               "chassis_per_day", "prepull", "storage_per_day", "detention",
               "chassis_split", "overweight", "tolls", "reefer", "hazmat",
               "triaxle", "bond_fee", "residential", "all_in_total",
               "rank", "equipment_type", "move_type", "notes"}
    decimal_fields = {"dray_rate", "total", "chassis_per_day", "prepull", "storage_per_day",
                      "chassis_split", "overweight", "tolls", "reefer", "hazmat",
                      "triaxle", "bond_fee", "residential", "all_in_total"}
    int_fields = {"rank"}
    sets, params = [], []
    for k, v in body.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            if k in decimal_fields:
                from decimal import InvalidOperation
                try:
                    params.append(Decimal(str(v)) if v is not None and str(v).strip() != "" else None)
                except (InvalidOperation, ValueError):
                    params.append(None)
            elif k in int_fields:
                params.append(int(v) if v is not None else None)
            else:
                params.append(str(v).strip() if v is not None else None)
    if not sets:
        raise HTTPException(400, "No valid fields")
    # Auto-recalculate total if dray_rate or fsc changed but total not explicitly sent
    if ("dray_rate" in body or "fsc" in body) and "total" not in body:
        sets.append("total = COALESCE(dray_rate, 0) + CASE WHEN fsc ~ '^[0-9.]+$' THEN fsc::numeric ELSE 0 END")
    params.append(rate_id)
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(f"UPDATE lane_rates SET {', '.join(sets)} WHERE id = %s RETURNING *", params)
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Lane rate not found")
    return JSONResponse(_serialize_row(row))



# ═══════════════════════════════════════════════════════════
# EXCEL BULK IMPORT
# ═══════════════════════════════════════════════════════════

_CITY_TABS = {
    "Atlanta", "Baltimore", "Birmingham", "Buffalo", "Boston", "Charleston", "Charlotte",
    "Chicago", "Cincinnati", "Cleveland", "Columbus", "Dallas", "Denver", "Detroit",
    "El Paso, TX", "Houston", "Indianapolis", "Jacksonville", "Kansas City", "Louisville",
    "Los Angeles", "Memphis", "Miami", "Mobile", "Nashville", "New York", "NOLA",
    "Norfolk", "Oakland", "Omaha", "Phildadelphia", "Pittsburgh", "Portland",
    "Salt Lake City", "Seattle", "Savannah", "St Louis", "Wilmington", "Tacoma", "Tampa",
    "Toronto",
}

_SKIP_TABS = {
    "Sheet1", "Sheet2", "Sheet3", "Sheet4", "Rate Quote Sheet-John (1)",
    "Priority 1", "PostMaster", "Oversize", "Timberlab",
}


def _safe_float(val):
    """Try to convert a value to float, return None on failure."""
    if val is None:
        return None
    try:
        s = str(val).replace(",", "").replace("$", "").strip()
        if not s:
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_city_tab(ws, tab_name):
    """Parse a city tab from the Excel workbook. Returns (carriers, lane_rates)."""
    carriers = []
    lane_rates = []
    max_row = ws.max_row or 1

    # Detect the rate grid header row (cols E-R) and carrier directory section
    rate_grid_header_row = None
    carrier_section_row = None

    for row_idx in range(1, min(max_row + 1, 5)):
        cell_e = ws.cell(row=row_idx, column=5).value  # Col E
        cell_f = ws.cell(row=row_idx, column=6).value  # Col F
        if cell_e and cell_f:
            e_str = str(cell_e).lower().strip()
            f_str = str(cell_f).lower().strip()
            if any(kw in e_str for kw in ("destination", "lane", "carrier")) or any(kw in f_str for kw in ("carrier", "dray", "lane")):
                rate_grid_header_row = row_idx
                break

    # Find carrier directory section (look for "Carrier" header in col B)
    for row_idx in range(1, max_row + 1):
        cell_b = ws.cell(row=row_idx, column=2).value
        if cell_b and str(cell_b).strip().lower() == "carrier":
            cell_c = ws.cell(row=row_idx, column=3).value
            if cell_c and "email" in str(cell_c).lower():
                carrier_section_row = row_idx
                break

    # Parse rate grid (rows after header, cols E-R)
    if rate_grid_header_row:
        # Determine column mapping from header
        hdr = {}
        for col in range(5, 25):
            v = ws.cell(row=rate_grid_header_row, column=col).value
            if v:
                hdr[str(v).strip().lower()] = col

        dest_col = hdr.get("destination", hdr.get("lane", 5))
        carrier_col = hdr.get("carrier", 6)

        for row_idx in range(rate_grid_header_row + 1, max_row + 1):
            carrier_val = ws.cell(row=row_idx, column=carrier_col).value
            dest_val = ws.cell(row=row_idx, column=dest_col).value
            if not carrier_val and not dest_val:
                # Check if we've hit the quote template or carrier section
                cell_b = ws.cell(row=row_idx, column=2).value
                if cell_b and str(cell_b).strip().lower() in ("pod", "carrier", "warehousing"):
                    break
                continue
            if not carrier_val:
                continue

            lr = {
                "port": tab_name,
                "destination": str(dest_val).strip() if dest_val else None,
                "carrier_name": str(carrier_val).strip(),
                "dray_rate": _safe_float(ws.cell(row=row_idx, column=hdr.get("dray", hdr.get("rate", 7))).value),
                "fsc": str(ws.cell(row=row_idx, column=hdr.get("fsc", 8)).value or "").strip() or None,
                "total": _safe_float(ws.cell(row=row_idx, column=hdr.get("total", 9)).value),
                "chassis_per_day": _safe_float(ws.cell(row=row_idx, column=hdr.get("chassis", 10)).value),
                "prepull": _safe_float(ws.cell(row=row_idx, column=hdr.get("prepull", hdr.get("drop", 11))).value),
                "storage_per_day": _safe_float(ws.cell(row=row_idx, column=hdr.get("storage", hdr.get("reefer", 12))).value),
                "detention": str(ws.cell(row=row_idx, column=hdr.get("detention", 14)).value or "").strip() or None,
                "overweight": _safe_float(ws.cell(row=row_idx, column=hdr.get("ow", 15)).value),
                "tolls": _safe_float(ws.cell(row=row_idx, column=hdr.get("tolls", hdr.get("toll", 16))).value),
                "all_in_total": _safe_float(ws.cell(row=row_idx, column=hdr.get("total", 17)).value),
                "rank": int(_safe_float(ws.cell(row=row_idx, column=hdr.get("rank", 18)).value) or 0) or None,
                "move_type": "dray",
                "source": "excel_import",
            }
            # Use the last "total" column for all_in
            for k2 in sorted(hdr.keys()):
                if k2 == "total" and hdr[k2] > 9:
                    lr["all_in_total"] = _safe_float(ws.cell(row=row_idx, column=hdr[k2]).value)
            if lr["dray_rate"] or lr["total"]:
                lane_rates.append(lr)

    # Parse carrier directory (rows after "Carrier | Email | MC" header)
    if carrier_section_row:
        for row_idx in range(carrier_section_row + 1, max_row + 1):
            cell_b = ws.cell(row=row_idx, column=2).value
            cell_c = ws.cell(row=row_idx, column=3).value
            if not cell_b and not cell_c:
                # Check for end of carrier section
                continue
            name = str(cell_b).strip() if cell_b else None
            email = str(cell_c).strip() if cell_c else None
            if not name or name == "\xa0":
                continue
            if name.lower() in ("warehousing", "warehouse charges", ""):
                break
            mc = ws.cell(row=row_idx, column=4).value
            notes_val = ws.cell(row=row_idx, column=5).value
            carriers.append({
                "carrier_name": name,
                "contact_email": email if email and "@" in str(email) else None,
                "mc_number": str(mc).strip() if mc else None,
                "regions": tab_name,
                "notes": str(notes_val).strip() if notes_val else None,
                "source": "excel_import",
            })

    return carriers, lane_rates


@router.post("/api/directory/import-excel")
async def api_import_excel(file: UploadFile = File(...)):
    """Bulk import carriers, lane rates, and warehouses from the rate quote Excel."""
    import tempfile
    file_bytes = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        import openpyxl
        wb = openpyxl.load_workbook(tmp_path, data_only=True, read_only=True)
    except Exception as e:
        os.unlink(tmp_path)
        raise HTTPException(400, f"Failed to read Excel file: {e}")

    all_carriers = []
    all_lane_rates = []
    all_warehouses = []
    summary = {"sheets_processed": [], "carriers": 0, "lane_rates": 0, "warehouses": 0}

    for name in wb.sheetnames:
        if name in _SKIP_TABS:
            continue
        ws = wb[name]

        if name in _CITY_TABS:
            carriers, lane_rates = _parse_city_tab(ws, name)
            all_carriers.extend(carriers)
            all_lane_rates.extend(lane_rates)
            if carriers or lane_rates:
                summary["sheets_processed"].append(name)
            continue

        # Specialty tabs
        if name == "Tolead Rates ORD":
            for row_idx in range(2, (ws.max_row or 1) + 1):
                city = ws.cell(row=row_idx, column=1).value
                rate = _safe_float(ws.cell(row=row_idx, column=3).value)
                if city and rate:
                    all_lane_rates.append({
                        "port": "Chicago (ORD)", "destination": str(city).strip(),
                        "carrier_name": "Tolead", "total": rate, "move_type": "ftl",
                        "source": "excel_import",
                    })
            summary["sheets_processed"].append(name)

        elif name == "LTL":
            for row_idx in range(2, (ws.max_row or 1) + 1):
                pallets = ws.cell(row=row_idx, column=1).value
                dest = ws.cell(row=row_idx, column=2).value
                rate = _safe_float(ws.cell(row=row_idx, column=4).value)
                if rate:
                    all_lane_rates.append({
                        "port": "LTL", "destination": str(dest or "").strip() or None,
                        "carrier_name": f"LTL ({pallets} pallet{'s' if str(pallets) != '1' else ''})",
                        "total": rate, "move_type": "ltl", "source": "excel_import",
                        "notes": f"{ws.cell(row=row_idx, column=3).value} transit days" if ws.cell(row=row_idx, column=3).value else None,
                    })
            summary["sheets_processed"].append(name)

        elif name == "Step Deck":
            for row_idx in range(2, (ws.max_row or 1) + 1):
                pickup = ws.cell(row=row_idx, column=1).value
                lane = ws.cell(row=row_idx, column=2).value
                rate = _safe_float(ws.cell(row=row_idx, column=3).value)
                if lane and rate:
                    all_lane_rates.append({
                        "port": str(pickup or "").strip() or "Step Deck",
                        "destination": str(lane).strip(),
                        "carrier_name": "Step Deck",
                        "total": rate, "move_type": "step_deck", "equipment_type": "Step Deck",
                        "source": "excel_import",
                    })
            summary["sheets_processed"].append(name)

        elif name == "Sutton WH - Inventory (Meiborg)":
            wh = {"name": "Sutton Warehouse (Meiborg)", "source": "excel_import", "services": "Storage, Labeling, Palletizing"}
            rates = []
            for row_idx in range(2, (ws.max_row or 1) + 1):
                desc = ws.cell(row=row_idx, column=1).value
                rate = _safe_float(ws.cell(row=row_idx, column=3).value)
                if desc and rate:
                    desc_str = str(desc).strip()
                    if "total" in desc_str.lower():
                        continue
                    rates.append({"rate_type": "flat", "rate_amount": rate, "unit": "each", "description": desc_str})
            if rates:
                all_warehouses.append({"warehouse": wh, "rates": rates})
            summary["sheets_processed"].append(name)

        elif name == "Tolead Box Rates":
            # Similar to Tolead Rates ORD but for box rates
            for row_idx in range(2, (ws.max_row or 1) + 1):
                city = ws.cell(row=row_idx, column=1).value
                rate = _safe_float(ws.cell(row=row_idx, column=3).value)
                if city and rate:
                    all_lane_rates.append({
                        "port": "Tolead Box", "destination": str(city).strip(),
                        "carrier_name": "Tolead", "total": rate, "move_type": "ftl",
                        "source": "excel_import",
                    })
            summary["sheets_processed"].append(name)

        elif name == "Heavy Haul":
            # Heavy haul has truck assignments with rates
            for row_idx in range(2, (ws.max_row or 1) + 1):
                truck = ws.cell(row=row_idx, column=13).value  # M
                rate = _safe_float(ws.cell(row=row_idx, column=14).value)  # N
                equip = ws.cell(row=row_idx, column=16).value  # P
                if rate:
                    all_lane_rates.append({
                        "port": "Heavy Haul", "destination": "Project Site",
                        "carrier_name": f"Truck {truck}" if truck else "Heavy Haul",
                        "total": rate, "move_type": "heavy_haul",
                        "equipment_type": str(equip).strip() if equip else None,
                        "source": "excel_import",
                    })
            summary["sheets_processed"].append(name)

    wb.close()
    os.unlink(tmp_path)

    # Bulk insert into database
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            # Insert carriers (deduplicate by name+email within import)
            seen_carriers = set()
            for c in all_carriers:
                key = (c["carrier_name"].lower(), (c.get("contact_email") or "").lower())
                if key in seen_carriers:
                    # Append region to existing
                    continue
                seen_carriers.add(key)
                cur.execute("""
                    INSERT INTO carriers (carrier_name, mc_number, contact_email, regions, notes, source)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (c["carrier_name"], c.get("mc_number"), c.get("contact_email"),
                      c.get("regions"), c.get("notes"), "excel_import"))
                summary["carriers"] += 1

            # Insert lane rates
            for lr in all_lane_rates:
                cur.execute("""
                    INSERT INTO lane_rates (port, destination, carrier_name, dray_rate, fsc, total,
                        chassis_per_day, prepull, storage_per_day, detention, chassis_split,
                        overweight, tolls, reefer, hazmat, all_in_total, rank,
                        equipment_type, move_type, notes, source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (lr.get("port"), lr.get("destination"), lr.get("carrier_name"),
                      lr.get("dray_rate"), lr.get("fsc"), lr.get("total"),
                      lr.get("chassis_per_day"), lr.get("prepull"), lr.get("storage_per_day"),
                      lr.get("detention"), lr.get("chassis_split"), lr.get("overweight"),
                      lr.get("tolls"), lr.get("reefer"), lr.get("hazmat"),
                      lr.get("all_in_total"), lr.get("rank"),
                      lr.get("equipment_type"), lr.get("move_type", "dray"),
                      lr.get("notes"), lr.get("source", "excel_import")))
                summary["lane_rates"] += 1

            # Insert warehouses + rates
            for wh_data in all_warehouses:
                wh = wh_data["warehouse"]
                cur.execute("""INSERT INTO warehouses (name, services, source)
                    VALUES (%s, %s, %s) RETURNING id""",
                    (wh["name"], wh.get("services"), "excel_import"))
                wh_id = cur.fetchone()["id"]
                for rate in wh_data["rates"]:
                    cur.execute("""INSERT INTO warehouse_rates (warehouse_id, rate_type, rate_amount, unit, description)
                        VALUES (%s, %s, %s, %s, %s)""",
                        (wh_id, rate["rate_type"], rate["rate_amount"], rate["unit"], rate.get("description")))
                summary["warehouses"] += 1

    return JSONResponse(summary)
