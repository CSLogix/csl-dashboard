import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import gspread
import requests as _requests
from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from google.oauth2.service_account import Credentials

from psycopg2 import sql as psql
import database as db
from shared import (
    sheet_cache, log,
    _read_tracking_cache, _find_tracking_entry,
    _get_driver_contact, _upsert_driver_contact,
    _build_macropoint_progress, _classify_mp_display_status,
    send_delivery_email,
    SHEET_ID, CREDS_FILE, COL,
    TRACKING_PHONE, DISPATCH_EMAIL,
    BOVIET_SHEET_ID, BOVIET_TAB_CONFIGS,
    TOLEAD_SHEET_ID, TOLEAD_TAB, TOLEAD_COL_EFJ, TOLEAD_COL_STATUS,
    TOLEAD_HUB_CONFIGS,
)

router = APIRouter()


# ── Constants ─────────────────────────────────────────────────────────────

_CARRIER_SCAC_MAP = {
    "maersk": "MAEU", "msc": "MSCU", "cosco": "COSU",
    "evergreen": "EGLV", "yang ming": "YMLU", "hmm": "HDMU",
    "hyundai": "HDMU", "oocl": "OOLU", "one": "ONEY",
    "ocean network": "ONEY", "cma": "CMDU", "cma cgm": "CMDU",
    "hapag": "HLCU", "hapag-lloyd": "HLCU", "zim": "ZIMU",
    "wan hai": "WHLC", "apl": "CMDU",
}

# Master Tracker account tabs (anything NOT in SKIP_TABS, Tolead, or Boviet)
_TOLEAD_ACCOUNTS = {"Tolead", "Tolead ORD", "Tolead JFK", "Tolead LAX", "Tolead DFW"}
_BOVIET_ACCOUNTS = set(BOVIET_TAB_CONFIGS.keys()) | {"Boviet"}

_SHARED_SHEET_ACCOUNTS = {"Tolead", "Boviet"}


# ── Helper Functions ──────────────────────────────────────────────────────

def _build_timeline_from_pg(efj: str) -> list:
    """Build a chronological timeline from tracking_events PG table.

    Uses stop_name + shipment origin/destination to determine pickup vs delivery
    instead of counting X1 occurrences (which fails when pickup events are missing).
    """
    try:
        with db.get_cursor() as cur:
            cur.execute("""
                SELECT event_code, status_mapped, stop_name, stop_type,
                       event_time, city, state
                FROM tracking_events
                WHERE efj = %s AND event_code IN ('AF', 'X1', 'X2', 'X4', 'X6', 'D1')
                ORDER BY event_time ASC
            """, (efj,))
            rows = cur.fetchall()
    except Exception:
        return []

    if not rows:
        return []

    # Get shipment origin/destination for stop matching
    origin = ""
    destination = ""
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT origin, destination FROM shipments WHERE efj = %s", (efj,))
            ship = cur.fetchone()
            if ship:
                origin = (ship["origin"] or "").upper()
                destination = (ship["destination"] or "").upper()
    except Exception:
        pass

    def _is_pickup_stop(stop_name, stop_type, city, state):
        """Determine if an event is at the pickup stop."""
        sn = (stop_name or "").upper()
        st = (stop_type or "").upper()
        c = (city or "").upper()
        s = (state or "").upper()
        # Explicit stop type from Macropoint
        if st in ("PICKUP", "ORIGIN"):
            return True
        if st in ("DROPOFF", "DELIVERY", "DESTINATION"):
            return False
        # Match against shipment origin/destination
        if origin and (origin in sn or c in origin or sn in origin):
            return True
        if destination and (destination in sn or c in destination or sn in destination):
            return False
        # Fallback: if city matches destination, it's delivery
        if destination and c and c in destination:
            return False
        if origin and c and c in origin:
            return True
        return None  # Unknown

    timeline = []
    for row in rows:
        code = row["event_code"]
        stop = row["stop_name"] or ""
        stop_type = row["stop_type"] or ""
        city = row["city"] or ""
        state = row["state"] or ""
        location = f"{city}, {state}".strip(", ") if city or state else stop
        event_time = row["event_time"].isoformat() if row["event_time"] else ""

        if code == "AF":
            timeline.append({
                "event": "Tracking Started",
                "time": event_time,
                "type": "info",
                "location": location,
            })
        elif code == "X1":
            is_pickup = _is_pickup_stop(stop, stop_type, city, state)
            if is_pickup:
                timeline.append({
                    "event": "Arrived at Pickup",
                    "time": event_time,
                    "type": "arrived",
                    "location": location,
                })
            else:
                timeline.append({
                    "event": "Arrived at Delivery",
                    "time": event_time,
                    "type": "arrived",
                    "location": location,
                })
        elif code == "X2":
            is_pickup = _is_pickup_stop(stop, stop_type, city, state)
            if is_pickup:
                timeline.append({
                    "event": "Departed Pickup",
                    "time": event_time,
                    "type": "departed",
                    "location": location,
                })
            else:
                timeline.append({
                    "event": "Departed Delivery",
                    "time": event_time,
                    "type": "departed",
                    "location": location,
                })
        elif code == "X4":
            timeline.append({
                "event": "Departed Pickup - En Route",
                "time": event_time,
                "type": "departed",
                "location": location,
            })
        elif code in ("X6", "D1"):
            timeline.append({
                "event": "Delivered",
                "time": event_time,
                "type": "delivered",
                "location": location,
            })

    return timeline


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


def _write_fields_to_master_sheet(efj: str, account: str, fields: dict):
    """Background task: write dashboard field edits back to Master Sheet."""
    try:
        from csl_sheet_writer import sheet_update_field
        sheet_update_field(efj, account, fields)
    except Exception as e:
        log.warning("Sheet write-back failed for %s [%s]: %s (PG update succeeded)", efj, account, e)


def _shipment_row_to_dict(row: dict) -> dict:
    """Convert a Postgres shipments row to the same JSON shape as sheet_cache."""
    return {
        "efj": row["efj"] or "",
        "move_type": row["move_type"] or "",
        "container": row["container"] or "",
        "bol": row["bol"] or "",
        "ssl": row["vessel"] or "",
        "carrier": row["carrier"] or "",
        "origin": row["origin"] or "",
        "destination": row["destination"] or "",
        "eta": row["eta"] or "",
        "lfd": row["lfd"] or "",
        "pickup": row["pickup_date"] or "",
        "delivery": row["delivery_date"] or "",
        "status": row["status"] or "",
        "notes": row["notes"] or "",
        "bot_alert": row["bot_notes"] or "",
        "return_port": row["return_date"] or "",
        "container_url": row["container_url"] or "",
        "rep": row["rep"] or "Unassigned",
        "account": row["account"] or "",
        "hub": row["hub"] or "",
        "driver": row["driver"] or "",
        "driver_phone": row["driver_phone"] or "",
        "carrier_email": row.get("carrier_email") or "",
        "trailer": row.get("trailer") or row.get("driver") or "",
        "driver_name": row.get("driver_name") or "",
        "source": row["source"] or "sheet",
        "archived": row.get("archived", False),
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
        "customer_rate": float(row["customer_rate"]) if row.get("customer_rate") else None,
        "carrier_pay": float(row["carrier_pay"]) if row.get("carrier_pay") else None,
    }


# ── Document CRUD ─────────────────────────────────────────────────────────

@router.get("/api/load/{efj}/documents")
async def get_load_documents(efj: str):
    """List all documents for a load."""
    with db.get_cursor() as cur:
        cur.execute(
        "SELECT id, doc_type, original_name, size_bytes, uploaded_at "
        "FROM load_documents WHERE efj = %s ORDER BY uploaded_at DESC",
        (efj,)
        )
        rows = cur.fetchall()
    docs = [
        {
            "id": r["id"],
            "doc_type": r["doc_type"],
            "original_name": r["original_name"],
            "size_bytes": r["size_bytes"],
            "uploaded_at": r["uploaded_at"].isoformat() if r["uploaded_at"] else None,
        }
        for r in rows
    ]
    return JSONResponse({"documents": docs})


@router.post("/api/load/{efj}/documents")
async def upload_load_document(efj: str, file: UploadFile = File(...), doc_type: str = Form("other")):
    """Upload a document for a load."""
    import uuid
    upload_dir = f"/root/csl-bot/csl-doc-tracker/uploads/{efj}"
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_name)
    contents = await file.read()
    import hashlib as _hl
    file_hash = _hl.sha256(contents).hexdigest()
    # Check for duplicate
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("SELECT 1 FROM load_documents WHERE efj=%s AND file_hash=%s", (efj, file_hash))
            if cur.fetchone():
                return JSONResponse({"error": "Document already exists for this load"}, status_code=409)
    with open(file_path, "wb") as f:
        f.write(contents)
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO load_documents (efj, doc_type, filename, original_name, size_bytes, file_hash) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (efj, doc_type, safe_name, file.filename, len(contents), file_hash)
            )
            doc_id = cur.fetchone()["id"]

    # Auto-advance status when POD is uploaded and load is awaiting POD
    auto_status = None
    if doc_type == "pod":
        try:
            with db.get_cursor() as cur:
                cur.execute("SELECT status, move_type FROM shipments WHERE efj = %s", (efj,))
                ship = cur.fetchone()
            if ship:
                cur_status = (ship["status"] or "").lower().replace(" ", "_")
                if cur_status in ("delivered", "need_pod"):
                    with db.get_conn() as conn:
                        with db.get_cursor(conn) as cur:
                            cur.execute(
                                "UPDATE shipments SET status = 'pod_received', updated_at = NOW() WHERE efj = %s",
                                (efj,),
                            )
                    auto_status = "pod_received"
                    log.info("Auto-advanced %s → pod_received on POD upload", efj)
        except Exception as e:
            log.warning("POD auto-status failed for %s: %s", efj, e)

    resp = {"ok": True, "id": doc_id, "original_name": file.filename}
    if auto_status:
        resp["auto_status"] = auto_status
    return JSONResponse(resp)


@router.delete("/api/load/{efj}/documents/{doc_id}")
async def delete_load_document(efj: str, doc_id: int):
    """Delete a document for a load."""
    with db.get_cursor() as cur:
        cur.execute("SELECT filename FROM load_documents WHERE id = %s AND efj = %s", (doc_id, efj))
        row = cur.fetchone()
    if row:
        file_path = f"/root/csl-bot/csl-doc-tracker/uploads/{efj}/{row['filename']}"
        if os.path.exists(file_path):
            os.remove(file_path)
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("DELETE FROM load_documents WHERE id = %s AND efj = %s", (doc_id, efj))
    return JSONResponse({"ok": True})


@router.get("/api/load/{efj}/documents/{doc_id}/download")
async def download_load_document(efj: str, doc_id: int, inline: bool = False):
    """Download or inline-preview a specific document."""
    with db.get_cursor() as cur:
        cur.execute(
        "SELECT filename, original_name FROM load_documents WHERE id = %s AND efj = %s",
        (doc_id, efj)
        )
        row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "not found"})
    file_path = f"/root/csl-bot/csl-doc-tracker/uploads/{efj}/{row['filename']}"
    if not os.path.exists(file_path):
        return JSONResponse(status_code=404, content={"error": "file missing"})
    if inline:
        import mimetypes
        media_type = mimetypes.guess_type(row["original_name"])[0] or "application/octet-stream"
        return FileResponse(
            file_path,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{row["original_name"]}"'}
        )
    return FileResponse(file_path, filename=row["original_name"])


@router.patch("/api/load/{efj}/documents/{doc_id}")
async def update_load_document(efj: str, doc_id: int, request: Request):
    """
    Reclassify a load document by updating its `doc_type`.
    
    Validates the provided `doc_type` against the allowed set and updates the matching `load_documents` record for the given `efj` and `doc_id`.
    
    Returns:
        JSONResponse: On success, `{"ok": True, "doc_type": <new_type>}`.
        If `doc_type` is invalid, returns status 400 with `{"error": "Invalid doc_type. Must be one of: <allowed_types>"}`.
        If no matching document is found, returns status 404 with `{"error": "not found"}`.
    """
    body = await request.json()
    new_type = body.get("doc_type", "").strip()
    valid_types = [
        "customer_rate", "carrier_rate", "rate", "unclassified",
        "pod", "bol", "carrier_invoice", "packing_list", "msds",
        "screenshot", "email", "other",
    ]
    if new_type not in valid_types:
        return JSONResponse(status_code=400, content={"error": f"Invalid doc_type. Must be one of: {valid_types}"})
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE load_documents SET doc_type = %s WHERE id = %s AND efj = %s RETURNING id",
                (new_type, doc_id, efj)
            )
            row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return JSONResponse({"ok": True, "doc_type": new_type})


# ── Driver Contact ────────────────────────────────────────────────────────

@router.get("/api/load/{efj}/driver")
async def api_get_driver(efj: str):
    """Return driver contact info for a load."""
    contact = _get_driver_contact(efj)

    # Fall back to shipments table for driver/phone/container_url
    # (Tolead sync + PG-native loads populate these but not driver_contacts)
    pg_driver = ""
    pg_phone = ""
    pg_mp_url = ""
    try:
        with db.get_cursor() as cur:
            cur.execute(
                "SELECT driver, driver_phone, container_url FROM shipments WHERE efj = %s",
                (efj,),
            )
            pg_row = cur.fetchone()
            if pg_row:
                pg_driver = (pg_row["driver"] or "").strip()
                pg_phone = (pg_row["driver_phone"] or "").strip()
                pg_mp_url = (pg_row["container_url"] or "").strip()
    except Exception:
        pass

    # Also check Column N (driver/truck) from sheet cache as fallback for name
    sheet_driver = ""
    for s in sheet_cache.shipments:
        if s["efj"] == efj:
            sheet_driver = s.get("notes", "")  # COL index 13 = Column N = Driver/Truck
            break

    # Fall back to tracking cache for driver_phone (scraped from MP portal)
    cached_phone = ""
    cached_mp_url = ""
    tracking_cache = _read_tracking_cache()
    cached = _find_tracking_entry(tracking_cache, efj)
    if cached.get("driver_phone"):
        cached_phone = cached["driver_phone"]
        # Auto-save scraped phone to DB if DB doesn't have one yet
        if not contact.get("driver_phone"):
            try:
                _upsert_driver_contact(efj, phone=cached_phone)
            except Exception:
                pass
    if cached.get("macropoint_url"):
        cached_mp_url = cached["macropoint_url"]

    # Priority: driver_contacts > shipments table > sheet cache > tracking cache
    final_name = contact.get("driver_name") or pg_driver or sheet_driver or ""
    final_phone = contact.get("driver_phone") or pg_phone or cached_phone or ""
    final_mp_url = contact.get("macropoint_url") or pg_mp_url or cached_mp_url or ""
    phone_source = "db" if contact.get("driver_phone") else ("pg" if pg_phone else ("macropoint" if cached_phone else ""))

    return {
        "efj": efj,
        "driverName": final_name,
        "driverPhone": final_phone,
        "driverEmail": contact.get("driver_email") or "",
        "carrierEmail": contact.get("carrier_email") or "",
        "trailerNumber": contact.get("trailer_number") or "",
        "macropointUrl": final_mp_url,
        "notes": contact.get("notes") or "",
        "phoneSource": phone_source,
    }


@router.post("/api/load/{efj}/driver")
async def api_update_driver(efj: str, request: Request):
    """Create or update driver contact info."""
    body = await request.json()
    _upsert_driver_contact(
        efj,
        name=body.get("driverName"),
        phone=body.get("driverPhone"),
        email=body.get("driverEmail"),
        notes=body.get("notes"),
        carrier_email=body.get("carrierEmail"),
        trailer_number=body.get("trailerNumber"),
        macropoint_url=body.get("macropointUrl"),
    )
    log.info("Driver contact updated for %s", efj)
    return {"status": "ok", "efj": efj}


# ── Timestamped Notes Log ─────────────────────────────────────────────────

@router.get("/api/load/{efj}/notes")
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


@router.post("/api/load/{efj}/notes")
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
    return JSONResponse({"ok": True, "note": dict(row)})


# ── Macropoint Screenshot ─────────────────────────────────────────────────

@router.get("/api/macropoint/{efj}/screenshot")
async def get_macropoint_screenshot(efj: str):
    """Serve a cached Macropoint tracking screenshot."""
    screenshot_path = f"/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.png"
    if not os.path.exists(screenshot_path):
        return JSONResponse(status_code=404, content={"error": "no screenshot"})
    import json as _json
    meta_path = f"/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.json"
    headers = {"Cache-Control": "max-age=300"}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = _json.load(f)
        headers["X-Captured-At"] = meta.get("captured_at", "")
    return FileResponse(screenshot_path, media_type="image/png", headers=headers)


# ── Macropoint Tracking ───────────────────────────────────────────────────

@router.get("/api/macropoint/{efj}")
async def api_macropoint(efj: str):
    """Return Macropoint tracking data for an FTL load."""
    sheet_cache.refresh_if_needed()
    # Find the shipment — check sheet cache first, then Postgres
    shipment = None
    for s in sheet_cache.shipments:
        if s["efj"] == efj:
            shipment = s
            break
    if not shipment:
        # Fall back to Postgres (PG-migrated loads aren't in sheet cache)
        try:
            with db.get_cursor() as cur:
                cur.execute(
                    "SELECT efj, container, status, origin, destination, pickup_date, "
                    "delivery_date, eta, account, move_type, container_url, carrier "
                    "FROM shipments WHERE efj = %s",
                    (efj,),
                )
                pg_row = cur.fetchone()
                if pg_row:
                    shipment = {
                        "efj": pg_row["efj"],
                        "container": pg_row["container"] or "",
                        "status": pg_row["status"] or "",
                        "origin": pg_row["origin"] or "",
                        "destination": pg_row["destination"] or "",
                        "pickup": pg_row["pickup_date"] or "",
                        "delivery": pg_row["delivery_date"] or "",
                        "eta": pg_row["eta"] or "",
                        "account": pg_row["account"] or "",
                        "move_type": pg_row["move_type"] or "",
                        "container_url": pg_row["container_url"] or "",
                        "carrier": pg_row["carrier"] or "",
                    }
        except Exception:
            pass
    if not shipment:
        raise HTTPException(404, f"Load {efj} not found")
    # Also check tracking cache
    _tracking_cache = _read_tracking_cache()
    _cached_entry = _find_tracking_entry(_tracking_cache, efj)
    _cached_url = _cached_entry.get("macropoint_url", "")

    status = shipment.get("status", "")
    progress = _build_macropoint_progress(status)

    # Format phone
    phone_raw = TRACKING_PHONE
    if len(phone_raw) == 10:
        phone_fmt = f"({phone_raw[:3]}) {phone_raw[3:6]}-{phone_raw[6:]}"
    else:
        phone_fmt = phone_raw

    # ── Tracking cache (stop timeline from ftl_monitor) ──
    tracking_cache = _read_tracking_cache()
    cached = _find_tracking_entry(tracking_cache, efj)

    # ── Driver contact info (from DB, with cache fallback) ──
    contact = _get_driver_contact(efj)
    driver_name = contact.get("driver_name") or ""
    driver_phone = contact.get("driver_phone") or cached.get("driver_phone") or ""
    driver_email = contact.get("driver_email") or ""
    stop_times = cached.get("stop_times", {})
    cant_make_it = cached.get("cant_make_it")
    last_scraped = cached.get("last_scraped")
    mp_load_id_cached = cached.get("mp_load_id")

    # Build stop timeline from PG tracking_events (durable) + cache supplement
    timeline = _build_timeline_from_pg(efj)

    # Supplement: merge cache stop_times for any events missing from PG.
    # PG might only have Tracking Started (AF) while cache has arrival/departure
    # from GPS inference that failed to persist (e.g. "ET" timestamp bug).
    _pg_events = {e.get("event", "") for e in timeline}
    _cache_supplements = []
    if stop_times.get("stop1_arrived") and "Arrived at Pickup" not in _pg_events:
        _cache_supplements.append({"event": "Arrived at Pickup", "time": stop_times["stop1_arrived"], "type": "arrived"})
    if stop_times.get("stop1_departed") and "Departed Pickup" not in _pg_events:
        _cache_supplements.append({"event": "Departed Pickup", "time": stop_times["stop1_departed"], "type": "departed"})
    if stop_times.get("stop2_arrived") and "Arrived at Delivery" not in _pg_events:
        _cache_supplements.append({"event": "Arrived at Delivery", "time": stop_times["stop2_arrived"], "type": "arrived"})
    if stop_times.get("stop2_departed") and "Departed Delivery" not in _pg_events:
        _cache_supplements.append({"event": "Departed Delivery", "time": stop_times["stop2_departed"], "type": "departed"})
    if not timeline and not _cache_supplements:
        # Pure fallback for ETA-only loads
        if stop_times.get("stop1_eta"):
            _cache_supplements.append({"event": "Pickup ETA", "time": stop_times["stop1_eta"], "type": "eta"})
        if stop_times.get("stop2_eta"):
            _cache_supplements.append({"event": "Delivery ETA", "time": stop_times["stop2_eta"], "type": "eta"})
    timeline.extend(_cache_supplements)

    # Detect behind schedule from ETA strings
    behind_schedule = False
    for k in ("stop1_eta", "stop2_eta"):
        if stop_times.get(k) and "BEHIND" in stop_times[k].upper():
            behind_schedule = True

    return {
        "loadId": shipment.get("container", "") or shipment.get("efj", ""),
        "carrier": "Evans Delivery Company, Inc.",
        "driver": driver_name,
        "phone": phone_fmt,
        "email": DISPATCH_EMAIL,
        "trackingStatus": status or "Unknown",
        "macropointUrl": shipment.get("container_url", "") or cached.get("macropoint_url", ""),
        "progress": progress,
        "origin": shipment.get("origin", ""),
        "destination": shipment.get("destination", ""),
        "pickup": shipment.get("pickup", ""),
        "delivery": shipment.get("delivery", ""),
        "eta": shipment.get("eta", ""),
        "account": shipment.get("account", ""),
        "moveType": shipment.get("move_type", ""),
        # ── New fields ──
        "driverName": driver_name,
        "driverPhone": driver_phone,
        "driverEmail": driver_email,
        "mpLoadId": mp_load_id_cached,
        "timeline": timeline,
        "behindSchedule": behind_schedule,
        "cantMakeIt": cant_make_it,
        "lastScraped": last_scraped,
        "mpLastUpdated": cached.get("last_event_at") or cached.get("last_ping_at") or last_scraped or None,
        "lastLocation": cached.get("last_location") or None,
        "mpDisplayStatus": _classify_mp_display_status(cached, shipment)[0] if cached else "",
        "mpDisplayDetail": _classify_mp_display_status(cached, shipment)[1] if cached else "",
        "scheduleAlert": cached.get("schedule_alert", "") if cached else "",
        "distanceToStop": cached.get("distance_to_stop", "") if cached else "",
    }


# ── Status Update ─────────────────────────────────────────────────────────

@router.post("/api/load/{efj}/status")
async def api_update_status(efj: str, request: Request):
    """Update a load's status in Google Sheet."""
    body = await request.json()
    new_status = body.get("status", "").strip()
    if not new_status:
        raise HTTPException(400, "Missing status")

    # Find the shipment in cache to get its tab and row
    shipment = None
    for s in sheet_cache.shipments:
        if s["efj"] == efj:
            shipment = s
            break
    if not shipment:
        raise HTTPException(404, f"Load {efj} not found")

    tab = shipment.get("account", "")
    if not tab:
        raise HTTPException(400, "Cannot determine sheet tab for this load")

    # Write to Google Sheet
    try:
        creds = Credentials.from_service_account_file(
            CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)

        if tab == "Tolead":
            sh = gc.open_by_key(TOLEAD_SHEET_ID)
            ws = sh.worksheet(TOLEAD_TAB)
            rows = ws.get_all_values()
            target_row = None
            for i, row in enumerate(rows):
                if len(row) > TOLEAD_COL_EFJ and row[TOLEAD_COL_EFJ].strip() == efj:
                    target_row = i + 1
                    break
            if not target_row:
                raise HTTPException(404, f"Row for {efj} not found in Tolead")
            ws.update_cell(target_row, TOLEAD_COL_STATUS + 1, new_status)

        elif tab == "Boviet":
            # Search all Boviet tabs for the EFJ
            sh = gc.open_by_key(BOVIET_SHEET_ID)
            found = False
            for bov_tab, cfg in BOVIET_TAB_CONFIGS.items():
                try:
                    ws = sh.worksheet(bov_tab)
                    rows = ws.get_all_values()
                    for i, row in enumerate(rows):
                        if len(row) > cfg["efj_col"] and row[cfg["efj_col"]].strip() == efj:
                            ws.update_cell(i + 1, cfg["status_col"] + 1, new_status)
                            found = True
                            log.info("Status updated: %s → %s (Boviet/%s, row=%d)", efj, new_status, bov_tab, i + 1)
                            break
                    if found:
                        break
                except Exception:
                    continue
            if not found:
                raise HTTPException(404, f"Row for {efj} not found in Boviet tabs")

        else:
            # Master sheet — tab name is the account name
            sh = gc.open_by_key(SHEET_ID)
            ws = sh.worksheet(tab)
            rows = ws.get_all_values()
            target_row = None
            efj_col = COL.get("efj", 0)
            status_col = COL.get("status", 12)
            for i, row in enumerate(rows):
                if len(row) > efj_col and row[efj_col].strip() == efj:
                    target_row = i + 1
                    break
            if not target_row:
                raise HTTPException(404, f"Row for {efj} not found in {tab}")
            ws.update_cell(target_row, status_col + 1, new_status)

            # NOTE: billed_closed no longer auto-archives here.
            # Archiving now ONLY fires via the billing close path:
            # POST /api/unbilled/{id}/status → billing_status=closed → _archive_shipment_on_close()
            # This prevents loads from disappearing before the finance cycle completes.

        # Update cache
        shipment["status"] = new_status
        log.info("Status updated: %s → %s (tab=%s)", efj, new_status, tab)

        # Send delivery email for Master loads
        _normalized = new_status.strip().lower()
        if _normalized == "delivered" and tab not in ("Tolead", "Boviet"):
            send_delivery_email(shipment)

        return {"status": "ok", "efj": efj, "new_status": new_status}

    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to update status for %s: %s", efj, e)
        raise HTTPException(500, f"Failed to update status: {e}")


# ── SeaRates Vessel Schedules + Port Codes ────────────────────────────────

@router.post("/api/searates/lookup")
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


@router.get("/api/port-codes")
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


# ── Reps & Accounts ──────────────────────────────────────────────────────

@router.get("/api/reps")
async def api_reps():
    """Return list of account reps."""
    return {"reps": ["Eli", "Radka", "John F", "Janice"]}


@router.post("/api/accounts/add")
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


# ── Add New Load ──────────────────────────────────────────────────────────

@router.post("/api/load/add")
async def api_add_load(request: Request):
    """Add a new load to the appropriate Google Sheet tab."""
    body = await request.json()
    efj = body.get("efj", "").strip()
    account = body.get("account", "").strip()
    if not efj:
        raise HTTPException(400, "EFJ Pro # is required")
    if not account:
        raise HTTPException(400, "Account is required")

    move_type = body.get("moveType", "Dray Import")
    container = body.get("container", "").strip()
    carrier = body.get("carrier", "").strip()
    origin = body.get("origin", "").strip()
    destination = body.get("destination", "").strip()
    eta = body.get("eta", "")
    lfd = body.get("lfd", "")
    pickup = body.get("pickupDate", "")
    delivery = body.get("deliveryDate", "")
    status = body.get("status", "")
    notes = body.get("notes", "")
    bol = body.get("bol", "").strip()
    customer_ref = body.get("customerRef", "").strip()
    equipment_type = body.get("equipmentType", "").strip()
    rep = body.get("rep", "").strip()
    driver_phone = body.get("driverPhone", "")
    trailer = body.get("trailerNumber", "")
    carrier_email = body.get("carrierEmail", "")
    mp_url = body.get("macropointUrl", "")

    try:
        creds = Credentials.from_service_account_file(
            CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)

        # --- Determine which sheet to write to ---
        target_sheet = "master"
        hub_key = None
        boviet_tab = None

        # Check if Tolead hub
        if account in _TOLEAD_ACCOUNTS:
            hub_key = account.replace("Tolead ", "").upper() if account != "Tolead" else "ORD"
            if hub_key not in TOLEAD_HUB_CONFIGS:
                raise HTTPException(400, f"Unknown Tolead hub: {hub_key}")
            target_sheet = "tolead"

        # Check if Boviet tab
        elif account in _BOVIET_ACCOUNTS:
            boviet_tab = account if account != "Boviet" else "Piedra"
            if boviet_tab not in BOVIET_TAB_CONFIGS:
                raise HTTPException(400, f"Unknown Boviet tab: {boviet_tab}")
            target_sheet = "boviet"

        if target_sheet == "master":
            # --- Master Tracker: columns A-P ---
            sh = gc.open_by_key(SHEET_ID)
            try:
                ws = sh.worksheet(account)
            except gspread.WorksheetNotFound:
                raise HTTPException(400, f"Account tab '{account}' not found in Master Tracker")
            status_display = status.replace("_", " ").title() if status else ""
            row = [""] * 16
            row[COL["efj"]] = efj
            row[COL["move_type"]] = move_type
            row[COL["container"]] = container
            row[COL["carrier"]] = carrier
            if bol:
                row[3] = bol  # Column D: BOL/Booking
            row[COL["origin"]] = origin
            row[COL["destination"]] = destination
            row[COL["eta"]] = eta
            row[COL["lfd"]] = lfd
            row[COL["pickup"]] = pickup
            row[COL["delivery"]] = delivery
            row[COL["status"]] = status_display
            row[COL["notes"]] = notes
            ws.append_row(row, value_input_option="USER_ENTERED")
            log.info("Added load %s to Master/%s", efj, account)
            result_tab = account

        elif target_sheet == "tolead":
            # --- Tolead hub sheet ---
            hub_cfg = TOLEAD_HUB_CONFIGS[hub_key]
            sh = gc.open_by_key(hub_cfg["sheet_id"])
            ws = sh.worksheet(hub_cfg["tab"])
            cols = hub_cfg["cols"]
            max_col = max(v for v in cols.values() if v is not None) + 1
            row = [""] * max_col
            if cols.get("efj") is not None:
                row[cols["efj"]] = efj
            if cols.get("load_id") is not None:
                row[cols["load_id"]] = container or efj
            if cols.get("status") is not None:
                row[cols["status"]] = status.replace("_", " ").title() if status else ""
            if cols.get("origin") is not None:
                row[cols["origin"]] = origin or hub_cfg.get("default_origin", "")
            if cols.get("destination") is not None:
                row[cols["destination"]] = destination
            if cols.get("pickup_date") is not None:
                row[cols["pickup_date"]] = pickup
            if cols.get("delivery") is not None:
                row[cols["delivery"]] = delivery
            if cols.get("driver") is not None:
                row[cols["driver"]] = trailer
            if cols.get("phone") is not None:
                row[cols["phone"]] = driver_phone
            ws.append_row(row, value_input_option="USER_ENTERED")
            log.info("Added load %s to Tolead/%s", efj, hub_key)
            result_tab = f"Tolead {hub_key}"

        elif target_sheet == "boviet":
            # --- Boviet tab ---
            cfg = BOVIET_TAB_CONFIGS[boviet_tab]
            sh = gc.open_by_key(BOVIET_SHEET_ID)
            ws = sh.worksheet(boviet_tab)
            max_col = max(v for v in cfg.values() if isinstance(v, int)) + 1
            row = [""] * max_col
            row[cfg["efj_col"]] = efj
            row[cfg["load_id_col"]] = container or efj
            row[cfg["status_col"]] = status.replace("_", " ").title() if status else ""
            if cfg.get("pickup_col") is not None:
                row[cfg["pickup_col"]] = pickup
            if cfg.get("delivery_col") is not None:
                row[cfg["delivery_col"]] = delivery
            if cfg.get("phone_col") is not None:
                row[cfg["phone_col"]] = driver_phone
            if cfg.get("trailer_col") is not None:
                row[cfg["trailer_col"]] = trailer
            ws.append_row(row, value_input_option="USER_ENTERED")
            log.info("Added load %s to Boviet/%s", efj, boviet_tab)
            result_tab = f"Boviet {boviet_tab}"

        # Invalidate cache so next fetch picks up the new row
        sheet_cache._last = 0

        # Store FTL driver info in DB if provided
        if move_type == "FTL" and (driver_phone or carrier_email):
            try:
                # Build notes with trailer/MP URL info
                extra_notes = []
                if trailer:
                    extra_notes.append(f"Trailer: {trailer}")
                if mp_url:
                    extra_notes.append(f"MP: {mp_url}")
                notes_str = " | ".join(extra_notes) or None
                with db.get_conn() as conn:
                    with db.get_cursor(conn) as cur:
                        cur.execute(
                            """INSERT INTO driver_contacts (efj, driver_phone, driver_email, notes, updated_at)
                               VALUES (%s, %s, %s, %s, NOW())
                               ON CONFLICT (efj) DO UPDATE SET
                                 driver_phone = COALESCE(EXCLUDED.driver_phone, driver_contacts.driver_phone),
                                 driver_email = COALESCE(EXCLUDED.driver_email, driver_contacts.driver_email),
                                 notes        = COALESCE(EXCLUDED.notes, driver_contacts.notes),
                                 updated_at = NOW()""",
                            (efj, driver_phone or None, carrier_email or None, notes_str),
                        )
            except Exception as db_err:
                log.warning("Driver contact save failed for %s: %s", efj, db_err)

        return {"ok": True, "efj": efj, "tab": result_tab, "sheet": target_sheet}

    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to add load %s: %s", efj, e)
        raise HTTPException(500, f"Failed to add load: {e}")


# ── Rate Quotes ───────────────────────────────────────────────────────────

@router.get("/api/load/{efj}/rate-quotes")
async def get_load_rate_quotes(efj: str, request: Request):
    """Return pending/accepted rate quotes for a specific load."""
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT id, carrier_name, carrier_email, rate_amount, rate_unit,
                   move_type, origin, destination, miles, status, quote_date
            FROM rate_quotes
            WHERE efj = %s AND status IN ('pending', 'accepted')
            ORDER BY
                CASE WHEN status = 'accepted' THEN 0 ELSE 1 END,
                quote_date DESC
        """, (efj,))
        rows = cur.fetchall()
    quotes = []
    for r in rows:
        q = dict(r)
        if q.get("rate_amount") is not None:
            q["rate_amount"] = float(q["rate_amount"])
        if q.get("quote_date"):
            q["quote_date"] = q["quote_date"].isoformat()
        quotes.append(q)
    return {"quotes": quotes}


@router.post("/api/load/{efj}/apply-rate")
async def apply_rate_to_shipment(efj: str, request: Request):
    """Apply a rate quote amount to the shipment's carrier_pay or customer_rate field."""
    from fastapi import BackgroundTasks
    body = await request.json()
    quote_id = body.get("quote_id")
    field = body.get("field", "carrier_pay")
    if field not in ("carrier_pay", "customer_rate"):
        return JSONResponse(status_code=400, content={"error": "field must be carrier_pay or customer_rate"})
    if not quote_id:
        return JSONResponse(status_code=400, content={"error": "quote_id required"})

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            # Look up the quote
            cur.execute("SELECT id, rate_amount, efj FROM rate_quotes WHERE id = %s", (quote_id,))
            quote = cur.fetchone()
            if not quote or not quote["rate_amount"]:
                return JSONResponse(status_code=400, content={"error": "Quote has no rate amount"})

            # Write to shipments
            cur.execute(
                psql.SQL("UPDATE shipments SET {} = %s, updated_at = NOW() WHERE efj = %s RETURNING *").format(
                    psql.Identifier(field)),
                (quote["rate_amount"], efj),
            )
            row = cur.fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": f"Shipment {efj} not found"})

            # Mark this quote accepted, reject competing
            cur.execute("UPDATE rate_quotes SET status = 'accepted' WHERE id = %s AND status != 'accepted'", (quote_id,))
            cur.execute(
                "UPDATE rate_quotes SET status = 'rejected' WHERE efj = %s AND id != %s AND status = 'pending'",
                (efj, quote_id),
            )

    # Sheet write-back for non-shared accounts
    account = row.get("account")
    if account and account not in _SHARED_SHEET_ACCOUNTS:
        # Fire-and-forget background write-back
        import threading
        threading.Thread(
            target=_write_fields_to_master_sheet,
            args=(efj, account, {field: str(quote["rate_amount"])}),
            daemon=True,
        ).start()

    log.info("Applied rate quote %d ($%s) → %s.%s", quote_id, quote["rate_amount"], efj, field)
    return {"ok": True, "applied": float(quote["rate_amount"]), "field": field,
            "shipment": _shipment_row_to_dict(row)}
