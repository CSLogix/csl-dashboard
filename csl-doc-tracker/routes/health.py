import json
import logging
import os
import re
import subprocess
import sys
import threading
import time as _time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import gspread
from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from google.oauth2.service_account import Credentials

import database as db

log = logging.getLogger(__name__)
router = APIRouter()

# These are imported from app at module level; callers must ensure app.py
# has been loaded first (which it will be, since app.py includes this router).
from shared import (
    sheet_cache, SHEET_ID, CREDS_FILE, COL, SKIP_TABS,
    CACHE_TTL, BOT_SERVICES, _find_tracking_entry, _classify_mp_display_status,
    _read_tracking_cache,
)
import config


# ---------------------------------------------------------------------------
# BOL Generator Proxy Endpoints
# ---------------------------------------------------------------------------

_BOL_ACCOUNTS = {
    "accounts": [
        {
            "key": "boviet",
            "label": "Boviet / Piedra Solar",
            "name": "Boviet",
            "columns": ["EFJ Pro #", "BV #", "Boviet  Load#",
                        "Pickup Appt Date", "PU Appt Time",
                        "Delivery Apt Date", "Delivery Appt Time"],
            "required_columns": ["EFJ Pro #", "BV #", "Boviet  Load#",
                                 "Pickup Appt Date", "PU Appt Time",
                                 "Delivery Apt Date", "Delivery Appt Time"],
            "combined_columns": [],
            "hint": "Matches Piedra Solar pickup & delivery plan format. "
                    "Drop the Excel export directly — no reformatting needed.",
        },
    ]
}

BOL_WEBAPP_URL = "http://localhost:5002"
BOL_WEBAPP_PASSWORD = os.getenv("BOL_PASSWORD", "evans2026")


@router.get("/api/bol/accounts")
async def api_bol_accounts():
    """Return static BOL account configuration."""
    return JSONResponse(_BOL_ACCOUNTS)


@router.post("/api/bol/generate")
async def api_bol_generate(request: Request):
    """Proxy file upload to BOL webapp on localhost:5002.
    Authenticates with the BOL webapp, forwards the uploaded file,
    and streams back the generated ZIP."""
    import requests as _bol_req

    form = await request.form()
    file = form.get("file") or form.get("datafile")
    if not file:
        raise HTTPException(400, "No file uploaded")

    file_bytes = await file.read()
    filename = getattr(file, "filename", "data.xlsx") or "data.xlsx"

    try:
        sess = _bol_req.Session()
        # Authenticate with the BOL webapp
        sess.post(
            f"{BOL_WEBAPP_URL}/login",
            data={"password": BOL_WEBAPP_PASSWORD},
            allow_redirects=False,
            timeout=10,
        )
        # Forward the file to /generate
        resp = sess.post(
            f"{BOL_WEBAPP_URL}/generate",
            files={"datafile": (filename, file_bytes)},
            allow_redirects=False,
            timeout=300,
        )
    except _bol_req.ConnectionError:
        raise HTTPException(503, "BOL webapp is unreachable (port 5002)")
    except _bol_req.Timeout:
        raise HTTPException(504, "BOL webapp timed out")
    except Exception as e:
        log.error("BOL proxy error: %s", e)
        raise HTTPException(502, f"BOL proxy error: {e}")

    # If the BOL webapp redirected (flash error), extract the error
    if resp.status_code in (301, 302, 303):
        raise HTTPException(422, "BOL generation failed — check file format and columns")

    content_type = resp.headers.get("content-type", "application/zip")
    content_disp = resp.headers.get("content-disposition", "attachment; filename=BOLs.zip")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={
            "Content-Type": content_type,
            "Content-Disposition": content_disp,
        },
    )


_BOL_EXTRACT_PROMPT = """You are a logistics data extraction assistant. Extract BOL (Bill of Lading) data from this image/document.

Return a JSON object with this structure:
{
  "rows": [
    {
      "po_number": "string or null",
      "quantity": "string or null",
      "weight": "string or null",
      "description": "string or null",
      "consignee": "string or null",
      "ship_from": "string or null",
      "ship_to": "string or null"
    }
  ],
  "shipper": "string or null",
  "consignee": "string or null",
  "carrier": "string or null",
  "bol_number": "string or null",
  "date": "string or null",
  "notes": "string or null"
}

Extract as many line-item rows as you can find. Include addresses, PO numbers, weights, quantities, and descriptions.
If a field is not present, use null. Return ONLY valid JSON, no markdown fences."""


@router.post("/api/bol/extract")
async def api_bol_extract(request: Request):
    """Extract BOL fields from an uploaded image/PDF using Claude Vision."""
    if not getattr(config, "ANTHROPIC_API_KEY", None):
        raise HTTPException(422, "ANTHROPIC_API_KEY not configured — OCR extraction unavailable")

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise HTTPException(400, "Expected multipart/form-data with a file upload")

    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(400, "No file uploaded")

    file_bytes = await file.read()
    filename = getattr(file, "filename", "") or ""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    import anthropic
    import base64

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # Build content blocks based on file type
    if ext in ("png", "jpg", "jpeg", "gif", "webp"):
        media_map = {
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp",
        }
        content = [
            {"type": "image", "source": {
                "type": "base64",
                "media_type": media_map.get(ext, "image/png"),
                "data": base64.b64encode(file_bytes).decode(),
            }},
            {"type": "text", "text": _BOL_EXTRACT_PROMPT},
        ]
    elif ext == "pdf":
        content = [
            {"type": "document", "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.b64encode(file_bytes).decode(),
            }},
            {"type": "text", "text": _BOL_EXTRACT_PROMPT},
        ]
    else:
        raise HTTPException(400, f"Unsupported file type for BOL extraction: .{ext}. Use PNG, JPG, or PDF.")

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": content}],
        )
        response_text = message.content[0].text.strip()
        # Strip markdown code fences if present
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(response_text)
        return JSONResponse(result)
    except json.JSONDecodeError as e:
        log.error("BOL extract: Claude returned invalid JSON: %s", e)
        raise HTTPException(500, "AI extraction returned invalid JSON")
    except Exception as e:
        log.error("BOL extract failed: %s", e)
        raise HTTPException(500, f"AI extraction failed: {e}")


# ---------------------------------------------------------------------------
# Completed loads cache + API — reads "Completed Eli/Radka/John F" tabs
# ---------------------------------------------------------------------------

_completed_cache = {"data": [], "ts": 0}
_completed_lock = threading.Lock()
_COMPLETED_TABS = {
    "Completed Eli": "Eli",
    "Completed Radka": "Radka",
    "Completed John F": "John F",
}


def _refresh_completed_cache():
    """Fetch completed loads from all 3 Completed tabs in Master Tracker.
    Enriches account from PG shipments table and sorts newest-first."""
    now = _time.time()
    if now - _completed_cache["ts"] < CACHE_TTL:
        return
    with _completed_lock:
        if _time.time() - _completed_cache["ts"] < CACHE_TTL:
            return
        try:
            creds = Credentials.from_service_account_file(
                CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            gc_local = gspread.authorize(creds)
            sh = gc_local.open_by_key(SHEET_ID)
            tab_names = list(_COMPLETED_TABS.keys())
            ranges = [f"\'{t}\'!A:P" for t in tab_names]
            batch_result = sh.values_batch_get(ranges)
            value_ranges = batch_result.get("valueRanges", [])
            loads = []
            for vr, tab_name in zip(value_ranges, tab_names):
                rep = _COMPLETED_TABS[tab_name]
                rows = vr.get("values", [])
                if len(rows) < 2:
                    continue
                # Detect header row (skip title rows)
                hdr_idx = 0
                if len(rows) > 1:
                    r0 = sum(1 for c in rows[0] if c.strip())
                    r1 = sum(1 for c in rows[1] if c.strip())
                    if r1 > r0:
                        hdr_idx = 1
                for row in rows[hdr_idx + 1:]:
                    efj = row[COL["efj"]].strip() if len(row) > COL["efj"] else ""
                    ctr = row[COL["container"]].strip() if len(row) > COL["container"] else ""
                    if not efj and not ctr:
                        continue
                    def cell(key, r=row):
                        idx = COL[key]
                        return r[idx].strip() if len(r) > idx else ""
                    loads.append({
                        "efj": efj,
                        "move_type": cell("move_type"),
                        "container": ctr,
                        "bol": cell("bol"),
                        "ssl": cell("ssl"),
                        "carrier": cell("carrier"),
                        "origin": cell("origin"),
                        "destination": cell("destination"),
                        "eta": cell("eta"),
                        "lfd": cell("lfd"),
                        "pickup": cell("pickup"),
                        "delivery": cell("delivery"),
                        "status": cell("status"),
                        "notes": cell("notes"),
                        "bot_alert": cell("bot_alert"),
                        "return_port": cell("return_port"),
                        "rep": rep,
                        "account": "",  # enriched below from PG
                    })

            # --- Enrich account from PG shipments table ---
            efj_list = [l["efj"] for l in loads if l["efj"]]
            pg_accounts = {}
            if efj_list:
                try:
                    with db.get_cursor() as cursor:
                        cursor.execute(
                            "SELECT efj, account FROM shipments WHERE efj = ANY(%s)",
                            (efj_list,)
                        )
                        pg_accounts = {r["efj"]: r["account"] for r in cursor.fetchall() if r.get("account")}
                except Exception as pg_err:
                    log.warning("Completed cache PG account lookup failed: %s", pg_err)

            # Fallback: reverse rep_map from sheet_cache (account -> rep)
            rep_map = getattr(sheet_cache, "rep_map", {})
            # Build reverse: rep -> list of accounts
            rev_rep = {}
            for acct, r in rep_map.items():
                rev_rep.setdefault(r, []).append(acct)

            for load in loads:
                efj = load["efj"]
                if efj in pg_accounts:
                    load["account"] = pg_accounts[efj]
                else:
                    # If only one account for this rep, use it; otherwise leave blank
                    accts = rev_rep.get(load["rep"], [])
                    load["account"] = accts[0] if len(accts) == 1 else ""

            # --- Sort by delivery date descending (newest first) ---
            import re as _re
            def _delivery_sort_key(load):
                """Parse delivery date for sorting. Returns sortable string, empty last."""
                d = load.get("delivery", "") or load.get("pickup", "") or ""
                # Try to extract date portion (handles "MM-DD HH:MM", "MM/DD", "YYYY-MM-DD", etc.)
                # Normalize to comparable form
                d = d.strip().split()[0] if d.strip() else ""  # take date part only
                if not d:
                    return "0000-00-00"
                # Handle MM-DD or MM/DD format
                m = _re.match(r"(\d{1,2})[/-](\d{1,2})", d)
                if m:
                    return f"2026-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
                # Handle YYYY-MM-DD
                m2 = _re.match(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", d)
                if m2:
                    return f"{m2.group(1)}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
                return d

            loads.sort(key=_delivery_sort_key, reverse=True)

            # --- Merge PG-archived shipments (Tolead, Boviet, and any PG-only archives) ---
            try:
                with db.get_cursor() as _pg_cur:
                    _pg_cur.execute("""
                        SELECT efj, move_type, container, bol, vessel, carrier,
                               origin, destination, eta, lfd,
                               pickup_date::text, delivery_date::text, status,
                               notes, bot_notes, return_date::text,
                               rep, account, hub
                        FROM shipments
                        WHERE archived = TRUE
                        ORDER BY archived_at DESC NULLS LAST
                    """)
                    pg_archived = _pg_cur.fetchall()

                existing_efjs = {l["efj"] for l in loads}
                pg_added = 0
                for row in pg_archived:
                    if row["efj"] not in existing_efjs:
                        loads.append({
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
                            "rep": row["rep"] or "",
                            "account": row["account"] or "",
                        })
                        existing_efjs.add(row["efj"])
                        pg_added += 1
                if pg_added:
                    loads.sort(key=_delivery_sort_key, reverse=True)
                    log.info("Completed cache: merged %d PG-archived shipments", pg_added)
            except Exception as pg_merge_err:
                log.warning("Completed cache PG merge failed: %s", pg_merge_err)

            _completed_cache["data"] = loads
            _completed_cache["ts"] = _time.time()
            log.info("Completed cache: %d total loads (sheets + PG)", len(loads))
        except Exception as e:
            log.error("Completed cache refresh failed: %s", e)




# -- Carrier Performance Scorecard

@router.get("/api/carriers/scorecard")
async def api_carrier_scorecard():
    """Aggregate carrier delivery performance from completed loads."""
    from datetime import datetime as _dt

    _refresh_completed_cache()
    loads = _completed_cache.get("data", [])

    carriers = defaultdict(lambda: {
        "loads": 0, "on_time": 0, "total_transit": 0, "transit_count": 0,
        "lanes": defaultdict(int), "last_delivery": None, "move_types": defaultdict(int),
    })

    def _parse_date(s):
        if not s:
            return None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
            try:
                return _dt.strptime(s.strip(), fmt)
            except ValueError:
                continue
        return None

    for load in loads:
        carrier = (load.get("carrier") or "").strip()
        if not carrier or carrier.lower() in ("", "tbd", "tba", "n/a", "none"):
            continue

        carriers[carrier]["loads"] += 1
        move = load.get("move_type", "").strip()
        if move:
            carriers[carrier]["move_types"][move] += 1

        origin = load.get("origin", "").strip()
        dest = load.get("destination", "").strip()
        if origin and dest:
            lane = f"{origin} \u2192 {dest}"
            carriers[carrier]["lanes"][lane] += 1

        pickup_dt = _parse_date(load.get("pickup"))
        delivery_dt = _parse_date(load.get("delivery"))
        lfd_dt = _parse_date(load.get("lfd"))

        # Transit time
        if pickup_dt and delivery_dt and delivery_dt > pickup_dt:
            delta = (delivery_dt - pickup_dt).days
            if 0 < delta < 60:
                carriers[carrier]["total_transit"] += delta
                carriers[carrier]["transit_count"] += 1

        # On-time: delivery <= LFD (for dray) or delivery exists (for FTL)
        if delivery_dt:
            if lfd_dt:
                if delivery_dt <= lfd_dt:
                    carriers[carrier]["on_time"] += 1
            else:
                carriers[carrier]["on_time"] += 1

        # Track most recent delivery
        if delivery_dt:
            if not carriers[carrier]["last_delivery"] or delivery_dt > carriers[carrier]["last_delivery"]:
                carriers[carrier]["last_delivery"] = delivery_dt

    # Build response
    results = []
    for name, data in carriers.items():
        total = data["loads"]
        on_time_pct = round(data["on_time"] / total * 100) if total > 0 else 0
        avg_transit = round(data["total_transit"] / data["transit_count"], 1) if data["transit_count"] > 0 else None
        top_lanes = sorted(data["lanes"].items(), key=lambda x: -x[1])[:5]
        primary_move = max(data["move_types"].items(), key=lambda x: x[1])[0] if data["move_types"] else None

        results.append({
            "carrier": name,
            "total_loads": total,
            "on_time_pct": on_time_pct,
            "avg_transit_days": avg_transit,
            "lanes_served": len(data["lanes"]),
            "top_lanes": [{"lane": l, "count": c} for l, c in top_lanes],
            "primary_move_type": primary_move,
            "last_delivery": data["last_delivery"].strftime("%Y-%m-%d") if data["last_delivery"] else None,
        })

    results.sort(key=lambda x: -x["total_loads"])
    return JSONResponse({"carriers": results, "total": len(results)})


@router.get("/api/completed")
async def api_completed(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    rep: str = Query(""),
    account: str = Query(""),
):
    """Return paginated completed shipment loads from Completed tabs."""
    _refresh_completed_cache()
    data = list(_completed_cache["data"])

    # --- Assign account from rep_map if available ---
    rep_map = getattr(sheet_cache, "rep_map", {})

    # --- Filter by rep ---
    if rep:
        rep_lower = rep.lower()
        data = [s for s in data if s.get("rep", "").lower() == rep_lower]

    # --- Filter by account ---
    if account:
        acct_lower = account.lower()
        data = [s for s in data if s.get("account", "").lower() == acct_lower]

    # --- Search filter (EFJ, container, carrier, origin, destination, bol) ---
    if search:
        q = search.lower()
        def matches(s):
            for field in ("efj", "container", "carrier", "origin", "destination", "bol", "account"):
                if q in s.get(field, "").lower():
                    return True
            return False
        data = [s for s in data if matches(s)]

    total = len(data)
    start = (page - 1) * limit
    end = start + limit
    page_data = data[start:end]
    return {"loads": page_data, "total": total, "hasMore": end < total}


# ---------------------------------------------------------------------------
# Bot Health - deep per-service diagnostics from journalctl
# ---------------------------------------------------------------------------

def _analyze_service_health(unit: str, name: str, poll_min: int) -> dict:
    """Analyze 24h of journalctl logs for a single service."""
    import subprocess as _sp

    # 1. Active state
    try:
        r = _sp.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
        active_state = r.stdout.strip()
    except Exception:
        active_state = "unknown"

    # 2. Pull 24h of journal logs
    try:
        r = _sp.run(
            ["journalctl", "-u", unit, "--since", "24 hours ago", "--no-pager", "-o", "short"],
            capture_output=True, text=True, timeout=30,
        )
        raw = r.stdout.strip()
        lines = raw.split(chr(10)) if raw else []
    except Exception:
        lines = []

    # 3. Count ACTUAL crashes = systemd restart events (not just any error line)
    crash_pattern = re.compile(
        r"(Failed with result|Main process exited, code=exited, status=1|"
        r"Scheduled restart job, restart counter|"
        r"systemd\[\d+\]: .+: Main process exited)",
        re.IGNORECASE,
    )
    crash_count = sum(1 for l in lines if crash_pattern.search(l))

    # 4. Operational errors (for display, not health determination)
    error_pattern = re.compile(r"error|traceback|failed|exception", re.IGNORECASE)
    error_lines = [l for l in lines if error_pattern.search(l) and not crash_pattern.search(l)]
    recent_errors = []
    for el in (error_lines[-5:] if error_lines else []):
        tm = re.match(r"\w+ \d+ (\d+:\d+:\d+)", el)
        time_str = tm.group(1) if tm else ""
        msg = el.split(":", 3)[-1].strip() if ":" in el else el
        recent_errors.append({"time": time_str, "level": "error", "msg": msg[:120]})

    # Also add crash lines to recent_errors
    crash_lines = [l for l in lines if crash_pattern.search(l)]
    for cl in (crash_lines[-3:] if crash_lines else []):
        tm = re.match(r"\w+ \d+ (\d+:\d+:\d+)", cl)
        time_str = tm.group(1) if tm else ""
        msg = cl.split(":", 3)[-1].strip() if ":" in cl else cl
        recent_errors.append({"time": time_str, "level": "crash", "msg": msg[:120]})
    recent_errors.sort(key=lambda e: e.get("time", ""), reverse=True)
    recent_errors = recent_errors[:8]

    # 5. Email count
    email_pattern = re.compile(r"Sent alert|SMTP|email sent", re.IGNORECASE)
    email_count = sum(1 for l in lines if email_pattern.search(l))

    # 6. Cycle count
    cycle_pattern = re.compile(
        r"\[Dray Import\]|\[Dray Export\]|\[FTL\]|\[Boviet\]|\[Tolead\]|Tab:|Checking |Starting cycle|--- Cycle"
    )
    cycle_count = sum(1 for l in lines if cycle_pattern.search(l))

    # 7. Loads tracked
    loads_pattern = re.compile(r"Tracking|Scraping|Container:|Row \d+:")
    loads_count = sum(1 for l in lines if loads_pattern.search(l))

    # 8. Last successful cycle timestamp
    last_cycle_ts = None
    cycle_end_pattern = re.compile(r"Run complete|poll complete|Done|Sleeping")
    for l in reversed(lines):
        if cycle_end_pattern.search(l):
            tm = re.match(r"(\w+ \d+ \d+:\d+:\d+)", l)
            if tm:
                try:
                    from datetime import datetime as _dt
                    last_cycle_ts = _dt.strptime(f"2026 {tm.group(1)}", "%Y %b %d %H:%M:%S").isoformat()
                except Exception:
                    pass
            break

    # 9. Health status — based on real crashes, not operational errors
    if active_state not in ("active", "activating"):
        health = "down"
    elif crash_count > 10:
        health = "crash_loop"
    elif crash_count > 3:
        health = "degraded"
    else:
        health = "healthy"

    # 10. Uptime
    uptime_str = ""
    try:
        r = _sp.run(
            ["systemctl", "show", unit, "--property=ActiveEnterTimestamp"],
            capture_output=True, text=True, timeout=5,
        )
        ts_line = r.stdout.strip()
        if "=" in ts_line:
            ts_val = ts_line.split("=", 1)[1].strip()
            if ts_val:
                from datetime import datetime as _dt
                try:
                    started = _dt.strptime(ts_val, "%a %Y-%m-%d %H:%M:%S %Z")
                    delta = _dt.now() - started
                    hours = int(delta.total_seconds() // 3600)
                    mins = int((delta.total_seconds() % 3600) // 60)
                    if hours >= 24:
                        uptime_str = f"{hours // 24}d {hours % 24}h"
                    elif hours > 0:
                        uptime_str = f"{hours}h {mins}m"
                    else:
                        uptime_str = f"{mins}m"
                except Exception:
                    pass
    except Exception:
        pass

    # 11. Last run / next run
    last_run = ""
    next_run = ""
    for l in reversed(lines):
        tm = re.match(r"(\w+ \d+ \d+:\d+:\d+)", l)
        if tm:
            try:
                from datetime import datetime as _dt
                ts = _dt.strptime(f"2026 {tm.group(1)}", "%Y %b %d %H:%M:%S")
                mins = int((_dt.now() - ts).total_seconds() / 60)
                last_run = "just now" if mins < 1 else (f"{mins}m ago" if mins < 60 else f"{mins // 60}h {mins % 60}m ago")
                if poll_min > 0:
                    nm = poll_min - mins
                    next_run = "overdue" if nm < 0 else (f"{nm} min" if nm < 60 else f"{nm // 60}h {nm % 60}m")
            except Exception:
                pass
            break

    return {
        "unit": unit,
        "name": name,
        "active_state": active_state,
        "health": health,
        "uptime": uptime_str,
        "poll_min": poll_min,
        "crashes_24h": crash_count,
        "emails_24h": email_count,
        "cycles_24h": cycle_count,
        "loads_24h": loads_count,
        "last_run": last_run or "unknown",
        "next_run": next_run,
        "last_successful_cycle": last_cycle_ts,
        "recent_errors": recent_errors,
        "journal_24h": {
            "crashes": crash_count,
            "emails_sent": email_count,
            "cycles_completed": cycle_count,
            "loads_tracked": loads_count,
        },
    }



@router.get("/api/bot-health")
def api_bot_health():
    """Deep health check for all bot services - 24h window."""
    services = {}
    total_crashes = 0
    total_emails = 0
    total_cycles = 0
    healthy_count = 0

    for svc in BOT_SERVICES:
        info = _analyze_service_health(svc["unit"], svc["name"], svc["poll_min"])
        services[svc["unit"]] = info
        total_crashes += info["crashes_24h"]
        total_emails += info["emails_24h"]
        total_cycles += info["cycles_24h"]
        if info["health"] == "healthy":
            healthy_count += 1

    summary = {
        "total_crashes_24h": total_crashes,
        "total_emails_24h": total_emails,
        "total_cycles_24h": total_cycles,
        "services_healthy": healthy_count,
        "services_total": len(services),
    }

    return {"services": services, "summary": summary, "generated_at": __import__("datetime").datetime.now().isoformat()}




@router.get("/api/health")
async def api_health():
    """Comprehensive health check: PG, sheets, services, crons."""
    import subprocess, datetime
    checks = {}
    overall = "healthy"

    # 1. Postgres check
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE archived=false) as active FROM shipments")
            row = cur.fetchone()
            pg_total = row["total"] if isinstance(row, dict) else row[0]
            pg_active = row["active"] if isinstance(row, dict) else row[1]
        checks["postgres"] = {"status": "ok", "total_shipments": pg_total, "active_shipments": pg_active}
    except Exception as e:
        checks["postgres"] = {"status": "error", "error": str(e)}
        overall = "degraded"

    # 2. Google Sheets cache check
    try:
        age = _time.time() - sheet_cache._last
        sheet_count = len(sheet_cache.shipments)
        checks["sheets_cache"] = {
            "status": "ok" if age < 900 else "stale",
            "shipment_count": sheet_count,
            "cache_age_seconds": round(age, 1),
        }
        if age > 900:
            overall = "degraded"
    except Exception as e:
        checks["sheets_cache"] = {"status": "error", "error": str(e)}
        overall = "degraded"

    # 3. Systemd services check
    svc_names = ["csl-dashboard", "csl-boviet", "csl-tolead", "csl-inbox"]
    svc_status = {}
    for svc in svc_names:
        try:
            r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, timeout=5)
            st = r.stdout.strip()
            svc_status[svc] = st
            if st != "active":
                overall = "degraded"
        except Exception:
            svc_status[svc] = "unknown"
    checks["services"] = svc_status

    # 4. Cron check (most recent logs)
    cron_status = {}
    cron_files = {
        "dray_import": "/tmp/csl_import.log",
        "dray_export": "/tmp/export_monitor.log",
        "ftl_monitor": "/tmp/ftl_monitor.log",
        "sheet_sync": "/tmp/sheet_sync.log",
    }
    for name, logfile in cron_files.items():
        try:
            r = subprocess.run(["tail", "-3", logfile], capture_output=True, text=True, timeout=5)
            lines = r.stdout.strip().split("\n")
            has_error = any("error" in l.lower() or "traceback" in l.lower() for l in lines)
            cron_status[name] = "error" if has_error else "ok"
            if has_error:
                overall = "degraded"
        except Exception:
            cron_status[name] = "unknown"
    checks["cron_jobs"] = cron_status

    # 5. Disk check
    try:
        r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            checks["disk"] = {"status": "ok", "used": parts[2], "available": parts[3], "use_pct": parts[4]}
            pct = int(parts[4].replace("%", ""))
            if pct > 90:
                overall = "critical"
                checks["disk"]["status"] = "critical"
    except Exception:
        checks["disk"] = {"status": "unknown"}

    return {
        "overall": overall,
        "checks": checks,
        "timestamp": datetime.datetime.now().isoformat(),
    }

@router.get("/api/cron-status")
def api_cron_status():
    """Status of cron-based monitors (dray import/export)."""
    import sys
    if "/root/csl-bot" not in sys.path:
        sys.path.insert(0, "/root/csl-bot")
    try:
        from cron_log_parser import get_all_cron_status
        return {"cron_jobs": get_all_cron_status()}
    except Exception as exc:
        return {"cron_jobs": {}, "error": str(exc)}


@router.get("/health")
def health():
    return {"status": "ok"}
