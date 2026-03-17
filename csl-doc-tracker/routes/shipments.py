import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse

import database as db
import config
from crypto import encrypt_data
from shared import (
    sheet_cache, log,
    _get_bot_status_detailed, _generate_alerts,
    _read_tracking_cache, _classify_mp_display_status,
    ALLOWED_EXTENSIONS, MAX_UPLOAD_SIZE, _sanitize_filename,
)

router = APIRouter()


@router.get("/api/stats")
def api_stats():
    sheet_cache.refresh_if_needed()
    return sheet_cache.stats


@router.get("/api/bot-status")
def api_bot_status():
    return _get_bot_status_detailed()


@router.get("/api/load/{efj}")
def api_load_detail(efj: str):
    """Get full load details from sheet cache + document status from DB."""
    sheet_cache.refresh_if_needed()
    shipment = None
    for s in sheet_cache.shipments:
        if s["efj"] == efj:
            shipment = s
            break
    if not shipment:
        raise HTTPException(status_code=404, detail=f"Load {efj} not found")

    # Get documents from database
    documents = []
    try:
        load_row = db.find_load_id_by_reference(efj)
        if load_row:
            docs = db.get_documents_for_load(load_row)
            for d in docs:
                documents.append({
                    "doc_type": d.get("doc_type", d.get("document_type", "")),
                    "filename": d.get("filename", d.get("original_filename", "")),
                    "file_path": d.get("file_path", d.get("stored_path", "")),
                    "received_at": str(d.get("created_at", d.get("received_at", ""))) if d.get("created_at") or d.get("received_at") else "",
                })
    except Exception as e:
        log.warning("Error fetching documents for %s: %s", efj, e)

    return {
        "efj": shipment["efj"],
        "account": shipment["account"],
        "move_type": shipment["move_type"],
        "container": shipment["container"],
        "bol": shipment["bol"],
        "ssl": shipment["ssl"],
        "carrier": shipment["carrier"],
        "origin": shipment["origin"],
        "destination": shipment["destination"],
        "eta": shipment["eta"],
        "lfd": shipment["lfd"],
        "pickup": shipment["pickup"],
        "delivery": shipment["delivery"],
        "status": shipment["status"],
        "notes": shipment["notes"],
        "bot_alert": shipment["bot_alert"],
        "return_port": shipment["return_port"],
        "rep": shipment["rep"],
        "container_url": shipment.get("container_url", ""),
        "documents": documents,
    }


@router.post("/api/load/{efj}/upload")
async def api_load_upload(efj: str, file: UploadFile = File(...), doc_type: str = Form(...)):
    """Upload a document for a load — validates, encrypts, and stores securely."""
    if doc_type not in ("BOL", "POD", "Invoice", "Other"):
        raise HTTPException(status_code=400, detail="Invalid document type")

    # Validate file extension
    original_name = file.filename or "unknown"
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Read file with size check
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024*1024)} MB"
        )

    # Sanitize filename
    safe_name = _sanitize_filename(original_name)

    # Create storage directory with restricted permissions
    store_dir = config.DOCUMENT_STORAGE_PATH / efj / doc_type
    os.makedirs(store_dir, mode=0o700, exist_ok=True)

    # Handle duplicates
    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix
    dest = store_dir / safe_name
    counter = 1
    while dest.exists():
        dest = store_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    final_name = dest.name

    # Encrypt and save
    encrypted_data = encrypt_data(contents)
    dest.write_bytes(encrypted_data)
    os.chmod(str(dest), 0o600)

    # Insert into database (with correct parameter order)
    rel_path = f"{efj}/{doc_type}/{final_name}"
    try:
        load_id = db.find_load_id_by_reference(efj)
        if load_id is None:
            log.warning("No load found for reference %s, skipping DB insert", efj)
        else:
            db.insert_document(load_id, doc_type, rel_path, original_name)
    except Exception as e:
        log.warning("DB insert for doc %s/%s failed: %s", efj, doc_type, e)

    return {"status": "ok", "filename": original_name, "path": rel_path}


@router.post("/api/load/{efj}/invoiced")
async def api_set_invoiced(efj: str, request: Request):
    """Toggle invoiced status for a load."""
    body = await request.json()
    invoiced = bool(body.get("invoiced", False))
    db.set_load_invoiced(efj, invoiced)
    return {"status": "ok", "invoiced": invoiced}


@router.post("/api/load/{efj}/ready-to-invoice")
async def api_ready_to_invoice(efj: str):
    """Mark a load as ready to invoice after POD is uploaded."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE loads SET status = 'ready_to_invoice', updated_at = NOW() WHERE load_number = %s",
                (efj,)
            )
    return {"status": "ok"}


@router.post("/api/load/{efj}/dismiss")
async def api_dismiss_load(efj: str):
    """Dismiss a load from the ready-to-invoice list (mark as invoiced/complete)."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE loads SET status = 'invoiced', invoiced = TRUE, updated_at = NOW() WHERE load_number = %s",
                (efj,)
            )
    return {"status": "ok"}


# ── React Dashboard: Shipments API ──
@router.get("/api/shipments")
async def api_shipments(request: Request, account: str = None, status: str = None):
    """Return all shipments as JSON, optionally filtered by account and/or status."""
    sheet_cache.refresh_if_needed()
    data = sheet_cache.shipments
    if account:
        data = [s for s in data if s.get("account", "").lower() == account.lower()]
    if status:
        data = [s for s in data if s.get("status", "").lower() == status.lower()]
    return {"shipments": data, "total": len(data)}


# ── React Dashboard: Alerts API ──
@router.get("/api/alerts")
async def api_alerts(request: Request):
    """Return current alerts for the dashboard."""
    sheet_cache.refresh_if_needed()
    alerts = _generate_alerts(sheet_cache.shipments)
    return {"alerts": alerts, "total": len(alerts)}


# ── React Dashboard: Accounts API ──
@router.get("/api/accounts")
async def api_accounts(request: Request):
    """Return account summaries for the dashboard."""
    sheet_cache.refresh_if_needed()
    return {"accounts": sheet_cache.accounts}


# ── React Dashboard: Team API ──
@router.get("/api/team")
async def api_team(request: Request):
    """Return team member summaries for the dashboard."""
    sheet_cache.refresh_if_needed()
    return {"team": sheet_cache.team}


# ═══════════════════════════════════════════════════════════════
# BATCH TABLE DATA ENDPOINTS (tracking + documents)
# ═══════════════════════════════════════════════════════════════

@router.get("/api/shipments/tracking-summary")
async def api_tracking_summary():
    """Return tracking status summary with stop timestamps for all FTL loads."""
    cache = _read_tracking_cache()

    # Bulk-load driver_contacts from PG to enrich tracking with phone/trailer
    _dc_map = {}  # efj_num -> {driver_phone, trailer_number}
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT efj, driver_phone, trailer_number, carrier_email FROM driver_contacts")
            for row in cur.fetchall():
                efj_key = (row["efj"] or "").replace("EFJ", "").strip()
                _dc_map[efj_key] = {
                    "phone": (row["driver_phone"] or "").strip(),
                    "trailer": (row["trailer_number"] or "").strip(),
                    "carrierEmail": (row["carrier_email"] or "").strip(),
                }
    except Exception as e:
        log.debug("driver_contacts bulk load failed, using cache-only: %s", e)

    result = {}
    for efj, entry in cache.items():
        stop_times = entry.get("stop_times") or {}
        behind = False
        for k in ("stop1_eta", "stop2_eta"):
            val = stop_times.get(k) or ""
            if "BEHIND" in val.upper():
                behind = True
        # Also check schedule_alert text from native MP protocol
        _sa_text = (entry.get("schedule_alert") or "").upper()
        if "BEHIND" in _sa_text or "PAST APPOINTMENT" in _sa_text:
            behind = True
        _ts_disp, _ts_detail = _classify_mp_display_status(entry)
        result[efj] = {
            "behindSchedule": behind,
            "cantMakeIt": bool(entry.get("cant_make_it")),
            "status": entry.get("status", ""),
            "lastScraped": entry.get("last_scraped", ""),
            # Stop timestamps for slide view display
            "stop1Arrived": stop_times.get("stop1_arrived"),
            "stop1Departed": stop_times.get("stop1_departed"),
            "stop2Arrived": stop_times.get("stop2_arrived"),
            "stop2Departed": stop_times.get("stop2_departed"),
            "stop1Eta": stop_times.get("stop1_eta"),
            "stop2Eta": stop_times.get("stop2_eta"),
            "mpDisplayStatus": _ts_disp,
            "mpDisplayDetail": _ts_detail,
            # Driver/trailer/email: prefer cache (real-time), fall back to PG driver_contacts
            "driverPhone": entry.get("driver_phone", "") or _dc_map.get(efj, {}).get("phone", ""),
            "trailer": entry.get("trailer", "") or _dc_map.get(efj, {}).get("trailer", ""),
            "carrierEmail": _dc_map.get(efj, {}).get("carrierEmail", ""),
        }
    return {"tracking": result}


@router.get("/api/shipments/document-summary")
async def api_document_summary():
    """Return document type counts + latest doc id per load for table icons and alerts."""
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT efj, doc_type, COUNT(*) as cnt, MAX(id) as latest_id
            FROM load_documents
            GROUP BY efj, doc_type
            ORDER BY efj
        """)
        rows = cur.fetchall()
    result = {}
    doc_ids = {}
    for r in rows:
        efj_val = r["efj"] if isinstance(r, dict) else r[0]
        doc_type = r["doc_type"] if isinstance(r, dict) else r[1]
        cnt = r["cnt"] if isinstance(r, dict) else r[2]
        latest_id = r["latest_id"] if isinstance(r, dict) else r[3]
        # Normalize EFJ key to bare number (strip "EFJ" prefix with or without space)
        efj_key = re.sub(r'^EFJ\s*', '', str(efj_val), flags=re.IGNORECASE).strip()
        if not efj_key:
            efj_key = efj_val  # fallback to original if normalization yields empty
        if efj_key not in result:
            result[efj_key] = {}
            doc_ids[efj_key] = {}
        result[efj_key][doc_type] = cnt
        doc_ids[efj_key][doc_type] = latest_id
    return {"documents": result, "doc_ids": doc_ids}


# ═══════════════════════════════════════════════════════════════
# UNCLASSIFIED DOCUMENTS + RATE IQ
# ═══════════════════════════════════════════════════════════════

@router.get("/api/unclassified-documents")
async def api_unclassified_documents():
    """Return documents with unclassified doc_type for manual review."""
    with db.get_cursor() as cur:
        cur.execute("""
        SELECT ld.id, ld.efj, ld.doc_type, ld.original_name,
               ld.uploaded_at, ld.uploaded_by
        FROM load_documents ld
        WHERE ld.doc_type = 'unclassified'
        ORDER BY ld.uploaded_at DESC
        LIMIT 50
        """)
        rows = cur.fetchall()
    docs = []
    for r in rows:
        docs.append({
            "id": r["id"],
            "efj": r["efj"],
            "doc_type": r["doc_type"],
            "original_name": r["original_name"],
            "uploaded_at": r["uploaded_at"].isoformat() if r["uploaded_at"] else None,
            "uploaded_by": r["uploaded_by"],
        })
    return {"documents": docs, "count": len(docs)}
