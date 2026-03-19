import json
import logging
import os
import re

from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import JSONResponse

import config
import database as db

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/quotes/settings")
async def api_quote_settings():
    """Return default quote builder settings."""
    return JSONResponse({
        "default_margin_pct": 15,
        "default_terms": [
            "Rates valid for 7 days from quote date",
            "Subject to carrier availability at time of booking",
            "Accessorial charges may vary based on actual services required",
            "Payment terms: Net 30 days from invoice date",
        ],
        "default_accessorials": [
            {"charge": "Storage", "rate": "45.00", "frequency": "per day", "checked": False, "amount": "45.00"},
            {"charge": "Pre-Pull", "rate": "150.00", "frequency": "flat", "checked": False, "amount": "150.00"},
            {"charge": "Chassis (2 days)", "rate": "45.00", "frequency": "per day", "checked": False, "amount": "45.00"},
            {"charge": "Overweight", "rate": "150.00", "frequency": "flat", "checked": False, "amount": "150.00"},
            {"charge": "Detention", "rate": "85.00", "frequency": "per hour", "checked": False, "amount": "85.00"},
        ],
    })


# ── Distance lookup (Google Maps Distance Matrix API) ──

@router.get("/api/quotes/distance")
async def api_quote_distance(origin: str = Query(...), destination: str = Query(...)):
    """Calculate mileage and transit time between origin and destination via Google Maps."""
    import requests as _req

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "Google Maps API key not configured"}, status_code=500)

    try:
        r = _req.get(
            "https://maps.googleapis.com/maps/api/distancematrix/json",
            params={
                "origins": origin,
                "destinations": destination,
                "units": "imperial",
                "key": api_key,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        if data.get("status") != "OK":
            return JSONResponse({"error": f"API error: {data.get('status')}"}, status_code=502)

        element = data["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            return JSONResponse({"error": f"Route error: {element.get('status')}"}, status_code=404)

        meters = element["distance"]["value"]
        one_way_miles = round(meters / 1609.344)
        seconds = element["duration"]["value"]
        duration_hours = round(seconds / 3600, 1)

        # Transit time string
        if one_way_miles <= 250:
            transit_time = "1 day"
        elif one_way_miles <= 600:
            transit_time = "1-2 days"
        elif one_way_miles <= 1200:
            transit_time = "2-3 days"
        elif one_way_miles <= 2000:
            transit_time = "3-4 days"
        else:
            transit_time = "4-5 days"

        return JSONResponse({
            "one_way_miles": one_way_miles,
            "round_trip_miles": one_way_miles * 2,
            "duration_hours": duration_hours,
            "transit_time": transit_time,
        })

    except _req.exceptions.Timeout:
        return JSONResponse({"error": "Google Maps API timeout"}, status_code=504)
    except Exception as e:
        log.warning("Distance lookup failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Extract rates from file or text ──

def _parse_rate_text(text: str) -> dict:
    """Parse carrier rate info from plain text (email body, rate confirmation).
    Returns structured fields that the frontend can populate."""
    import re as _re
    result = {}

    # Try to find carrier name (first line or "Carrier: X" pattern)
    carrier_m = _re.search(r'(?:carrier|trucking|transport|logistics|freight)\s*[:\-]?\s*(.+)', text, _re.IGNORECASE)
    if carrier_m:
        result["carrier_name"] = carrier_m.group(1).strip()[:120]

    # MC number — usually in email signature (MC#123456, MC-123456, MC 123456, MC:123456)
    mc_m = _re.search(r'MC\s*[#:\-]?\s*(\d{4,7})', text, _re.IGNORECASE)
    if mc_m:
        result["carrier_mc"] = mc_m.group(1)

    # DOT number — often near MC#
    dot_m = _re.search(r'(?:DOT|USDOT)\s*[#:\-]?\s*(\d{4,8})', text, _re.IGNORECASE)
    if dot_m:
        result["carrier_dot"] = dot_m.group(1)

    # Origin / destination patterns
    orig_m = _re.search(r'(?:origin|pick\s*up|from|shipper)\s*[:\-]\s*(.+)', text, _re.IGNORECASE)
    if orig_m:
        result["origin"] = orig_m.group(1).strip().split("\n")[0][:200]
    dest_m = _re.search(r'(?:destination|deliver(?:y)?|to|consignee)\s*[:\-]\s*(.+)', text, _re.IGNORECASE)
    if dest_m:
        result["destination"] = dest_m.group(1).strip().split("\n")[0][:200]

    # Shipment type
    text_lower = text.lower()
    if "dray" in text_lower or "container" in text_lower or "chassis" in text_lower:
        result["shipment_type"] = "Dray"
    elif "ftl" in text_lower or "full truckload" in text_lower or "53" in text_lower:
        result["shipment_type"] = "FTL"
    elif "ltl" in text_lower:
        result["shipment_type"] = "LTL"
    elif "transload" in text_lower:
        result["shipment_type"] = "Transload"

    # Mileage
    miles_m = _re.search(r'(\d[\d,]*)\s*(?:miles|mi\b)', text, _re.IGNORECASE)
    if miles_m:
        result["one_way_miles"] = miles_m.group(1).replace(",", "")

    # Dollar amounts — collect all as potential linehaul items
    dollar_matches = _re.findall(
        r'(.{0,60}?)\$\s*([\d,]+(?:\.\d{2})?)', text
    )
    linehaul_items = []
    for context, amount in dollar_matches:
        # Clean up context to use as description
        desc = context.strip().rstrip(":-\u2013\u2014").strip()
        # Remove leading junk
        desc = _re.sub(r'^.*?(?:rate|charge|fee|cost|price|total)\s*[:\-]?\s*', '', desc, flags=_re.IGNORECASE).strip()
        if not desc:
            # Try to label from nearby keywords
            ctx_lower = context.lower()
            if "line" in ctx_lower or "haul" in ctx_lower:
                desc = "Linehaul"
            elif "fuel" in ctx_lower or "fsc" in ctx_lower:
                desc = "Fuel Surcharge"
            elif "stop" in ctx_lower:
                desc = "Stop Charge"
            else:
                desc = "Linehaul"
        linehaul_items.append({
            "description": desc[:80],
            "rate": amount.replace(",", ""),
        })

    if linehaul_items:
        result["linehaul_items"] = linehaul_items

    # Accessorials — look for common terms
    acc_patterns = [
        (r'storage\s*[:\-$]*\s*\$?([\d,.]+)', "Storage"),
        (r'pre[\-\s]?pull\s*[:\-$]*\s*\$?([\d,.]+)', "Pre-Pull"),
        (r'chassis\s*[:\-$]*\s*\$?([\d,.]+)', "Chassis (2 days)"),
        (r'over\s*weight\s*[:\-$]*\s*\$?([\d,.]+)', "Overweight"),
        (r'detention\s*[:\-$]*\s*\$?([\d,.]+)', "Detention"),
        (r'demurrage\s*[:\-$]*\s*\$?([\d,.]+)', "Demurrage"),
        (r'layover\s*[:\-$]*\s*\$?([\d,.]+)', "Layover"),
    ]
    accessorials = []
    for pat, name in acc_patterns:
        m = _re.search(pat, text, _re.IGNORECASE)
        if m:
            accessorials.append({
                "charge": name,
                "rate": m.group(1).replace(",", ""),
                "frequency": "flat",
                "amount": m.group(1).replace(",", ""),
            })
    if accessorials:
        result["accessorials"] = accessorials

    return result


_EXTRACT_PROMPT = """Extract rate/quote information from this carrier rate confirmation or email.
Look carefully for the carrier's MC# and DOT# — these are often in the email signature block at the bottom.
Return ONLY valid JSON (no markdown, no explanation) with these fields:
{
  "carrier_name": "string or null",
  "carrier_mc": "MC number (digits only) or null — look in email signature for MC#, MC:, MC-, etc",
  "carrier_dot": "DOT/USDOT number (digits only) or null — look in email signature",
  "origin": "city, state or full address or null",
  "destination": "city, state or full address or null",
  "shipment_type": "Dray|FTL|LTL|Transload|OTR or null",
  "round_trip_miles": "string or null",
  "one_way_miles": "string or null",
  "transit_time": "string or null",
  "linehaul_items": [{"description": "string", "rate": "numeric string", "section": "Charges|OTR|Dray/Transload|Transload|LTL"}],
  "accessorials": [{"charge": "name", "rate": "numeric string", "frequency": "flat|per day|per hour", "amount": "numeric string"}]
}
Only include fields you can confidently extract. For linehaul_items, list each charge line separately (linehaul, fuel surcharge, stop charges, etc). Omit null fields."""


def _extract_with_claude(content: list) -> dict:
    """
    Send content blocks to the Claude model and return the parsed rate/quote data as a dictionary.
    
    Parameters:
        content (list): A list of content blocks to send to Claude. Each block may be plain text or an image payload formatted per the Anthropic client expectations.
    
    Returns:
        dict: Parsed JSON object containing extracted rate/quote fields.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )
    # Parse the JSON from Claude's response
    response_text = message.content[0].text.strip()
    # Strip markdown code fences if present
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(response_text)


@router.post("/api/quotes/extract")
async def api_quote_extract(request: Request):
    """Extract rate info from uploaded file (image/PDF) or pasted text.
    Uses Claude Vision when ANTHROPIC_API_KEY is configured, falls back to regex."""
    content_type = request.headers.get("content-type", "")
    has_claude = bool(config.ANTHROPIC_API_KEY)

    if "multipart/form-data" not in content_type:
        raise HTTPException(400, "No file or text provided")

    form = await request.form()
    text = form.get("text")
    file = form.get("file")

    # ── Text extraction ──
    if text:
        text_str = str(text)
        if has_claude:
            try:
                content = [{"type": "text", "text": _EXTRACT_PROMPT + "\n\n" + text_str}]
                result = _extract_with_claude(content)
                return JSONResponse(result)
            except Exception as e:
                log.warning("Claude text extraction failed, falling back to regex: %s", e)
        result = _parse_rate_text(text_str)
        if not result:
            raise HTTPException(400, "Could not extract any rate information from the text")
        return JSONResponse(result)

    # ── File extraction ──
    if file:
        file_bytes = await file.read()
        filename = getattr(file, "filename", "") or ""
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

        # Text-based files
        if ext in ("txt", "csv", "eml"):
            try:
                text_content = file_bytes.decode("utf-8", errors="replace")
            except Exception:
                text_content = file_bytes.decode("latin-1", errors="replace")
            if has_claude:
                try:
                    content = [{"type": "text", "text": _EXTRACT_PROMPT + "\n\n" + text_content}]
                    result = _extract_with_claude(content)
                    return JSONResponse(result)
                except Exception as e:
                    log.warning("Claude text extraction failed, falling back to regex: %s", e)
            result = _parse_rate_text(text_content)
            if not result:
                raise HTTPException(400, "Could not extract rate info from file")
            return JSONResponse(result)

        # Images — send to Claude Vision
        if ext in ("png", "jpg", "jpeg", "gif", "webp"):
            if not has_claude:
                raise HTTPException(422, "Image extraction requires ANTHROPIC_API_KEY to be configured")
            import base64
            media_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                         "gif": "image/gif", "webp": "image/webp"}
            media_type = media_map.get(ext, "image/png")
            try:
                content = [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(file_bytes).decode(),
                    }},
                    {"type": "text", "text": _EXTRACT_PROMPT},
                ]
                result = _extract_with_claude(content)
                return JSONResponse(result)
            except Exception as e:
                log.error("Claude Vision extraction failed: %s", e)
                raise HTTPException(500, f"AI extraction failed: {e}")

        # PDFs — send to Claude as document
        if ext == "pdf":
            if not has_claude:
                raise HTTPException(422, "PDF extraction requires ANTHROPIC_API_KEY to be configured")
            import base64
            try:
                content = [
                    {"type": "document", "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.b64encode(file_bytes).decode(),
                    }},
                    {"type": "text", "text": _EXTRACT_PROMPT},
                ]
                result = _extract_with_claude(content)
                return JSONResponse(result)
            except Exception as e:
                log.error("Claude PDF extraction failed: %s", e)
                raise HTTPException(500, f"AI extraction failed: {e}")

        # .msg (Outlook) - use extract-msg for proper parsing
        elif ext in ('msg',):
            try:
                import extract_msg, io as _io
                msg = extract_msg.openMsg(_io.BytesIO(file_bytes))
                parts = []
                if msg.subject:
                    parts.append('Subject: ' + str(msg.subject))
                if msg.sender:
                    parts.append('From: ' + str(msg.sender))
                if msg.date:
                    parts.append('Date: ' + str(msg.date))
                if msg.body:
                    parts.append(msg.body)
                text_content = chr(10).join(parts)
                # Extract image attachments for Claude Vision
                attachment_images = []
                for att in (msg.attachments or []):
                    att_name = (att.longFilename or att.shortFilename or '').lower()
                    if att_name.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                        att_data = att.data
                        if att_data:
                            import base64 as _b64
                            ext2 = att_name.rsplit('.', 1)[-1]
                            mt = dict(png='image/png', jpg='image/jpeg', jpeg='image/jpeg', gif='image/gif', webp='image/webp').get(ext2, 'image/png')
                            attachment_images.append(dict(type='image', source=dict(type='base64', media_type=mt, data=_b64.b64encode(att_data).decode())))
                    elif att_name.endswith('.pdf') and att.data:
                        try:
                            import fitz
                            pdf_doc = fitz.open(stream=att.data, filetype='pdf')
                            pdf_text = chr(10).join(page.get_text() for page in pdf_doc)
                            if pdf_text.strip():
                                text_content += chr(10)*2 + '--- Attached PDF: ' + att_name + ' ---' + chr(10) + pdf_text[:4000]
                        except Exception:
                            pass
                if not text_content.strip():
                    raise HTTPException(400, 'Could not extract readable text from .msg file')
                if has_claude:
                    try:
                        content_msg = [dict(type='text', text=_EXTRACT_PROMPT + chr(10)*2 + text_content[:8000])]
                        content_msg = attachment_images + content_msg
                        result = _extract_with_claude(content_msg)
                        return JSONResponse(result)
                    except Exception as e:
                        log.warning('Claude .msg extraction failed: %s', e)
                result = _parse_rate_text(text_content)
                if not result:
                    raise HTTPException(400, 'Could not extract rate info from .msg file')
                return JSONResponse(result)
            except HTTPException:
                raise
            except Exception as e:
                log.error('.msg extraction failed: %s', e)
                # Fallback: brute-force ASCII extraction
                try:
                    raw = file_bytes.decode('latin-1', errors='replace')
                    blocks = re.findall(r'[ -~]{20,}', raw)
                    fallback_text = chr(10).join(blocks)
                    if fallback_text.strip() and has_claude:
                        content_msg = [dict(type='text', text=_EXTRACT_PROMPT + chr(10)*2 + fallback_text[:8000])]
                        result = _extract_with_claude(content_msg)
                        return JSONResponse(result)
                except Exception:
                    pass
                raise HTTPException(500, f'Failed to process .msg file: {e}')

        # .htm/.html files
        elif ext in ('htm', 'html'):
            try:
                raw = file_bytes.decode('utf-8', errors='replace')
                text_content = re.sub(r'<[^>]+>', ' ', raw)
                text_content = re.sub(chr(92) + 's+', ' ', text_content).strip()
                if not text_content:
                    raise HTTPException(400, 'Could not extract text from HTML file')
                if has_claude:
                    try:
                        content_msg = [dict(type='text', text=_EXTRACT_PROMPT + chr(10)*2 + text_content[:8000])]
                        result = _extract_with_claude(content_msg)
                        return JSONResponse(result)
                    except Exception as e:
                        log.warning('Claude HTML extraction failed: %s', e)
                result = _parse_rate_text(text_content)
                if not result:
                    raise HTTPException(400, 'Could not extract rate info from HTML')
                return JSONResponse(result)
            except HTTPException:
                raise
            except Exception as e:
                log.error('HTML extraction failed: %s', e)
                raise HTTPException(500, f'Failed to process HTML file: {e}')

        else:
            raise HTTPException(400, f"Unsupported file type: .{ext}")

    raise HTTPException(400, "No file or text provided")


# ── CRUD (list, create, get, update) — register AFTER /settings and /distance ──

def _index_quote_to_rate_iq(row: dict, quote_id: int = None):
    """
    Write carrier cost from a saved quote into rate_quotes for Rate IQ lane intelligence.
    Only indexes dray-type quotes with a valid carrier_total and origin+dest.
    """
    DRAY_TYPES = {"Dray", "Dray+Transload", "OTR", "Transload"}
    shipment_type = (row.get("shipment_type") or "").strip()
    if shipment_type not in DRAY_TYPES:
        return
    origin = (row.get("pod") or "").strip()
    destination = (row.get("final_delivery") or "").strip()
    carrier_name = (row.get("carrier_name") or "").strip()
    try:
        carrier_total = float(row.get("carrier_total") or 0)
    except (TypeError, ValueError):
        carrier_total = None
    if not origin or not destination or not carrier_total:
        return
    lane = f"{origin} → {destination}"
    quote_date = row.get("created_at") or row.get("updated_at")
    qid = quote_id or row.get("id")
    try:
        with db.get_cursor() as cur:
            if qid:
                # Update existing rate_quotes entry for this quote
                cur.execute(
                    "UPDATE rate_quotes SET origin=%s, destination=%s, lane=%s, "
                    "carrier_name=%s, rate_amount=%s, move_type=%s, quote_date=%s, status='quoted' "
                    "WHERE source_quote_id=%s",
                    (origin, destination, lane, carrier_name, carrier_total,
                     shipment_type.lower(), quote_date, qid)
                )
                if cur.rowcount == 0:
                    # No existing row — insert
                    cur.execute(
                        "INSERT INTO rate_quotes "
                        "(origin, destination, lane, carrier_name, rate_amount, rate_unit, "
                        " move_type, quote_date, status, source_quote_id) "
                        "VALUES (%s,%s,%s,%s,%s,'flat',%s,%s,'quoted',%s) "
                        "ON CONFLICT DO NOTHING",
                        (origin, destination, lane, carrier_name, carrier_total,
                         shipment_type.lower(), quote_date, qid)
                    )
            else:
                cur.execute(
                    "INSERT INTO rate_quotes "
                    "(origin, destination, lane, carrier_name, rate_amount, rate_unit, "
                    " move_type, quote_date, status) "
                    "VALUES (%s,%s,%s,%s,%s,'flat',%s,%s,'quoted') "
                    "ON CONFLICT DO NOTHING",
                    (origin, destination, lane, carrier_name, carrier_total,
                     shipment_type.lower(), quote_date)
                )
    except Exception as e:
        import logging
        logging.getLogger("csl-dashboard").warning("rate_quotes index failed: %s", e)


def _sanitize_row(row: dict) -> dict:
    """Convert Decimal->float, datetime->str for JSON serialization."""
    from decimal import Decimal as _Dec
    out = {}
    for k, v in row.items():
        if isinstance(v, _Dec):
            out[k] = float(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


@router.get("/api/quotes")
async def api_list_quotes(
    status: str = Query(default=None),
    search: str = Query(default=None),
    move_types: str = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
):
    """List quotes with optional filters. move_types is comma-separated shipment types."""
    mt_list = [t.strip() for t in move_types.split(",")] if move_types else None
    rows = db.list_quotes(status=status, search=search, move_types=mt_list, limit=limit, offset=offset)
    rows = [_sanitize_row(r) for r in rows]
    return JSONResponse({"quotes": rows})


@router.post("/api/quotes")
async def api_create_quote(request: Request):
    """Create a new quote."""
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        raw = form.get("quote_data")
        if not raw:
            raise HTTPException(400, "Missing quote_data")
        data = json.loads(raw)
    else:
        data = await request.json()

    row = db.insert_quote(data)
    # Index carrier cost to rate_quotes for Rate IQ lane intelligence
    _index_quote_to_rate_iq(row)
    return JSONResponse(_sanitize_row(row), status_code=201)


@router.get("/api/quotes/{quote_id}")
async def api_get_quote(quote_id: int):
    """Get a single quote by ID."""
    row = db.get_quote(quote_id)
    if not row:
        raise HTTPException(404, "Quote not found")
    return JSONResponse(_sanitize_row(row))


@router.patch("/api/quotes/{quote_id}/status")
async def update_quote_status(quote_id: int, request: Request):
    """Quick status update for a quote (won/lost/expired/sent)"""
    body = await request.json()
    new_status = body.get("status")
    if new_status not in ("draft", "sent", "accepted", "lost", "expired"):
        return JSONResponse({"error": "Invalid status"}, status_code=400)
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE quotes SET status=%s, updated_at=NOW() WHERE id=%s RETURNING id, quote_number, status",
            (new_status, quote_id)
        )
        row = cur.fetchone()
        conn.commit()
        if not row:
            return JSONResponse({"error": "Quote not found"}, status_code=404)
        return {"id": row[0], "quote_number": row[1], "status": row[2]}
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.put_conn(conn)


@router.put("/api/quotes/{quote_id}")
async def api_update_quote(quote_id: int, request: Request):
    """Update an existing quote."""
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        raw = form.get("quote_data")
        if not raw:
            raise HTTPException(400, "Missing quote_data")
        data = json.loads(raw)
    else:
        data = await request.json()

    row = db.update_quote(quote_id, data)
    if not row:
        raise HTTPException(404, "Quote not found")
    # Re-index carrier cost to rate_quotes for Rate IQ
    _index_quote_to_rate_iq(row, quote_id=quote_id)
    return JSONResponse(_sanitize_row(row))
