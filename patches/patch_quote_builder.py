#!/usr/bin/env python3
"""
Patch: Quote Builder — DB tables + Claude extraction module + FastAPI router

Creates:
  1. PostgreSQL tables: quotes, quote_settings
  2. /root/csl-bot/csl-doc-tracker/quote_extractor.py  (Claude API vision extraction)
  3. /root/csl-bot/csl-doc-tracker/quote_routes.py      (FastAPI APIRouter)
  4. Patches app.py to import and include the quote router

Run on server:
    python3 /tmp/patch_quote_builder.py
"""

import os
import sys
import shutil

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"
BASE_DIR = "/root/csl-bot/csl-doc-tracker"

# ═══════════════════════════════════════════════════════════════
# Step 1: Create PostgreSQL tables
# ═══════════════════════════════════════════════════════════════
print("[1/4] Creating quotes + quote_settings tables...")

import psycopg2
sys.path.insert(0, BASE_DIR)
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS quotes (
    id SERIAL PRIMARY KEY,
    quote_number VARCHAR(20) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT '',
    status VARCHAR(20) DEFAULT 'draft',

    -- Route info
    pod VARCHAR(200) DEFAULT '',
    final_delivery VARCHAR(200) DEFAULT '',
    final_zip VARCHAR(20) DEFAULT '',
    round_trip_miles VARCHAR(20) DEFAULT '',
    one_way_miles VARCHAR(20) DEFAULT '',
    transit_time VARCHAR(50) DEFAULT '',
    shipment_type VARCHAR(50) DEFAULT '',

    -- Carrier costs (internal only)
    carrier_name VARCHAR(200) DEFAULT '',
    carrier_total NUMERIC(12,2) DEFAULT 0,

    -- Margin/Pricing
    margin_pct NUMERIC(5,2) DEFAULT 15,
    sell_subtotal NUMERIC(12,2) DEFAULT 0,
    accessorial_total NUMERIC(12,2) DEFAULT 0,
    estimated_total NUMERIC(12,2) DEFAULT 0,

    -- Customer info
    customer_name VARCHAR(200) DEFAULT '',
    customer_email VARCHAR(200) DEFAULT '',
    valid_until DATE,

    -- JSON data
    linehaul_json JSONB DEFAULT '[]',
    accessorials_json JSONB DEFAULT '[]',
    terms_json JSONB DEFAULT '[]',
    route_json JSONB DEFAULT '[]',

    -- Source tracking
    source_type VARCHAR(50) DEFAULT '',
    source_filename VARCHAR(500) DEFAULT ''
);

CREATE TABLE IF NOT EXISTS quote_settings (
    id SERIAL PRIMARY KEY,
    default_margin_pct NUMERIC(5,2) DEFAULT 15,
    default_terms JSONB DEFAULT '["Rates valid for 7 days from quote date","Subject to carrier availability at time of booking","Accessorial charges may vary based on actual services required","Payment terms: Net 30 days from invoice date"]',
    default_accessorials JSONB DEFAULT '[{"charge":"Storage","rate":"","frequency":"per day","checked":false,"amount":""},{"charge":"Port Tolls","rate":"","frequency":"flat","checked":false,"amount":""},{"charge":"Pre-Pull","rate":"","frequency":"flat","checked":false,"amount":""},{"charge":"Chassis","rate":"","frequency":"per day","checked":false,"amount":""},{"charge":"Overweight","rate":"","frequency":"flat","checked":false,"amount":""},{"charge":"Detention","rate":"","frequency":"per hour","checked":false,"amount":""}]'
);

INSERT INTO quote_settings (id, default_margin_pct) VALUES (1, 15) ON CONFLICT (id) DO NOTHING;
""")
conn.commit()
cur.close()
conn.close()
print("   Tables created (or already exist).")

# ═══════════════════════════════════════════════════════════════
# Step 2: Write quote_extractor.py
# ═══════════════════════════════════════════════════════════════
print("[2/4] Writing quote_extractor.py...")

EXTRACTOR_PATH = os.path.join(BASE_DIR, "quote_extractor.py")

EXTRACTOR_CODE = r'''"""
Quote Extractor — Uses Claude API to extract carrier rate data from images, PDFs, and emails.
"""
import base64
import json
import logging
import re
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-5-20241022"
EXTRACTION_PROMPT = """You are a logistics rate extraction assistant. Extract carrier rate information from this document.

Return ONLY valid JSON with this exact structure:
{
  "carrier_name": "string",
  "origin": "string",
  "destination": "string",
  "shipment_type": "Dray|FTL|OTR|Transload|Dray+Transload|LTL",
  "round_trip_miles": "string or empty",
  "one_way_miles": "string or empty",
  "transit_time": "string or empty",
  "linehaul_items": [
    {"description": "string", "rate": "number as string e.g. 1250.00"}
  ],
  "accessorials": [
    {"charge": "string", "rate": "string", "frequency": "per day|per hour|flat|per mile", "amount": "string"}
  ],
  "notes": "any extra info"
}

Rules:
- Extract ALL line items with their rates
- Separate linehaul charges from accessorial charges
- Linehaul = main transportation charges (dray, OTR, transload handling, fuel surcharge if bundled)
- Accessorials = extra charges (storage, tolls, pre-pull, chassis, detention, overweight)
- Use empty string for unknown fields, never null
- Rates should be numeric strings without $ sign
"""


def _get_api_key():
    import os
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    return key


def _call_claude(messages, max_tokens=2000):
    api_key = _get_api_key()
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "messages": messages,
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]


def _parse_json_response(text):
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting JSON from markdown code block
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Try finding first { to last }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from Claude response: {text[:200]}")


def extract_from_image(file_path: str) -> dict:
    path = Path(file_path)
    suffix = path.suffix.lower()
    media_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }
    media_type = media_map.get(suffix, "image/png")

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    messages = [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]
    }]

    raw = _call_claude(messages)
    return _parse_json_response(raw)


def extract_from_pdf(file_path: str) -> dict:
    path = Path(file_path)
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    messages = [{
        "role": "user",
        "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]
    }]

    raw = _call_claude(messages)
    return _parse_json_response(raw)


def extract_from_text(text: str) -> dict:
    messages = [{
        "role": "user",
        "content": f"{EXTRACTION_PROMPT}\n\nHere is the text to extract from:\n\n{text}"
    }]
    raw = _call_claude(messages)
    return _parse_json_response(raw)
'''

with open(EXTRACTOR_PATH, "w") as f:
    f.write(EXTRACTOR_CODE)
print(f"   Written: {EXTRACTOR_PATH}")

# ═══════════════════════════════════════════════════════════════
# Step 3: Write quote_routes.py
# ═══════════════════════════════════════════════════════════════
print("[3/4] Writing quote_routes.py...")

ROUTES_PATH = os.path.join(BASE_DIR, "quote_routes.py")

ROUTES_CODE = r'''"""
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
        from quote_extractor import extract_from_image, extract_from_pdf, extract_from_text
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
'''

with open(ROUTES_PATH, "w") as f:
    f.write(ROUTES_CODE)
print(f"   Written: {ROUTES_PATH}")

# ═══════════════════════════════════════════════════════════════
# Step 4: Patch app.py — import + include_router
# ═══════════════════════════════════════════════════════════════
print("[4/4] Patching app.py...")

# Create uploads/quotes directory
os.makedirs(os.path.join(BASE_DIR, "uploads", "quotes"), exist_ok=True)
print("   Created uploads/quotes directory.")

# Backup
shutil.copy(APP_PY, APP_PY + ".bak_quotes")
print("   Backup saved to app.py.bak_quotes")

with open(APP_PY, "r") as f:
    code = f.read()

already_patched = False

# Check if already patched
if "quote_routes" in code:
    print("   app.py already has quote_routes — skipping patch.")
    already_patched = True

if not already_patched:
    # ── Add import after 'import database as db' ──
    import_marker = "import database as db"
    import_line = "from quote_routes import router as quote_router"

    if import_marker in code:
        code = code.replace(
            import_marker,
            import_marker + "\n" + import_line,
        )
        print(f"   Added import: {import_line}")
    else:
        # Fallback: add at top of file after last import block
        print("   WARNING: Could not find 'import database as db' — inserting import at top.")
        code = import_line + "\n" + code

    # ── Add app.include_router(quote_router) after app is created ──
    # Look for common patterns of app creation
    include_line = "app.include_router(quote_router)"

    # Strategy: find 'app = FastAPI(' and insert after the closing paren of that block
    # We search for 'app = FastAPI' then find the end of that statement
    app_create_idx = code.find("app = FastAPI(")
    if app_create_idx == -1:
        app_create_idx = code.find("app = FastAPI (")

    if app_create_idx != -1:
        # Find the end of the FastAPI() call — could be multi-line
        # Walk forward from app_create_idx to find the matching closing paren
        paren_depth = 0
        found_open = False
        insert_idx = app_create_idx
        for i in range(app_create_idx, len(code)):
            if code[i] == '(':
                paren_depth += 1
                found_open = True
            elif code[i] == ')':
                paren_depth -= 1
                if found_open and paren_depth == 0:
                    insert_idx = i + 1
                    break

        # Find the end of the line after the closing paren
        newline_idx = code.find('\n', insert_idx)
        if newline_idx == -1:
            newline_idx = len(code)

        code = code[:newline_idx] + "\n" + include_line + code[newline_idx:]
        print(f"   Added: {include_line} (after app = FastAPI(...))")
    else:
        # Fallback: look for first @app. decorator and insert before it
        first_route_idx = code.find("@app.")
        if first_route_idx != -1:
            # Find the line start
            line_start = code.rfind("\n", 0, first_route_idx)
            if line_start == -1:
                line_start = 0
            code = code[:line_start] + "\n" + include_line + "\n" + code[line_start:]
            print(f"   Added: {include_line} (before first @app route)")
        else:
            # Last resort: append
            code += "\n" + include_line + "\n"
            print(f"   Added: {include_line} (appended to end)")

    with open(APP_PY, "w") as f:
        f.write(code)
    print("   app.py patched successfully.")

# ── Summary ──
print()
print("Done! Quote Builder backend ready.")
print()
print("Files created:")
print(f"  {EXTRACTOR_PATH}")
print(f"  {ROUTES_PATH}")
print()
print("Tables created:")
print("  quotes")
print("  quote_settings")
print()
print("API endpoints (via /api/quotes router):")
print("  GET    /api/quotes/settings       — default margin/terms/accessorials")
print("  PUT    /api/quotes/settings       — update defaults")
print("  POST   /api/quotes/extract        — Claude vision extraction from file/text")
print("  POST   /api/quotes               — create quote")
print("  GET    /api/quotes               — list quotes (?status=&search=&limit=&offset=)")
print("  GET    /api/quotes/{id}          — get single quote")
print("  PUT    /api/quotes/{id}          — update quote")
print("  DELETE /api/quotes/{id}          — delete quote")
print()
print("NOTE: Set ANTHROPIC_API_KEY in /root/csl-bot/.env for extraction to work.")
print("      pip install httpx --break-system-packages  (if not already installed)")
print()
print("Restart with: systemctl restart csl-dashboard")
