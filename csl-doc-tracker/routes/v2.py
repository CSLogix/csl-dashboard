import logging
import os
from datetime import datetime

import gspread
from fastapi import APIRouter, Query, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from google.oauth2.service_account import Credentials

import database as db
from routes.email_drafts import generate_milestone_draft, MILESTONES
from shared import (
    sheet_cache,
    SHEET_ID, CREDS_FILE, COL,
    BOVIET_SHEET_ID, BOVIET_TAB_CONFIGS,
    TOLEAD_HUB_CONFIGS,
    TRACKING_PHONE, DISPATCH_EMAIL,
    send_delivery_email,
    _read_tracking_cache, _find_tracking_entry, _classify_mp_display_status,
    _archive_shipment_on_close,
)

log = logging.getLogger(__name__)
router = APIRouter()

# Shared accounts that still need Google Sheet writes
_SHARED_SHEET_ACCOUNTS = {"Tolead", "Boviet"}

# Post-delivery statuses — load is "done" for active-count / at-risk purposes
_POST_DELIVERY_STATUSES = (
    "'delivered','completed','empty returned','empty_return','returned_to_port',"
    "'need_pod','pod_received','ready_to_close','billed_closed','missing_invoice',"
    "'ppwk_needed','waiting_confirmation','waiting_cx_approval','cx_approved','driver_paid'"
)


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


@router.get("/api/v2/shipments")
async def api_v2_shipments(request: Request, account: str = None, status: str = None,
                            hub: str = None, rep: str = None, archived: bool = False):
    """Return shipments from Postgres, same shape as /api/shipments."""
    where_clauses = ["archived = %s"]
    params = [archived]

    if account:
        where_clauses.append("LOWER(account) = LOWER(%s)")
        params.append(account)
    if status:
        where_clauses.append("LOWER(status) = LOWER(%s)")
        params.append(status)
    if hub:
        where_clauses.append("LOWER(hub) = LOWER(%s)")
        params.append(hub)
    if rep:
        where_clauses.append("LOWER(rep) = LOWER(%s)")
        params.append(rep)

    where = " AND ".join(where_clauses)

    with db.get_cursor() as cur:
        cur.execute(
        f"SELECT * FROM shipments WHERE {where} ORDER BY created_at DESC",
        params,
        )
        rows = cur.fetchall()

    shipments = [_shipment_row_to_dict(r) for r in rows]

    # Enrich with invoiced status from DB
    try:
        invoiced_map = db.get_invoiced_map()
    except Exception:
        invoiced_map = {}
    for s in shipments:
        s["_invoiced"] = invoiced_map.get(s["efj"], False)

    # Enrich with email thread stats (count + max priority)
    try:
        with db.get_cursor() as cur:
            cur.execute("""
                SELECT efj, COUNT(*) as email_count, COALESCE(MAX(priority), 0) as email_max_priority
                FROM email_threads
                GROUP BY efj
            """)
            email_stats = {r["efj"]: r for r in cur.fetchall()}
        for s in shipments:
            es = email_stats.get(s["efj"])
            s["email_count"] = es["email_count"] if es else 0
            s["email_max_priority"] = es["email_max_priority"] if es else 0
    except Exception:
        for s in shipments:
            s["email_count"] = 0
            s["email_max_priority"] = 0

    # Enrich with mp_status + mp_display_status from tracking cache
    try:
        _tc = _read_tracking_cache()
        for s in shipments:
            _ce = _find_tracking_entry(_tc, s["efj"])
            if _ce:
                s["mp_status"] = _ce.get("status", "")
                _disp, _detail = _classify_mp_display_status(_ce, s)
                s["mp_display_status"] = _disp
                s["mp_display_detail"] = _detail
                s["mp_last_updated"] = _ce.get("last_event_at") or _ce.get("last_ping_at") or _ce.get("last_scraped") or ""
                if not s.get("container_url") and _ce.get("macropoint_url"):
                    s["container_url"] = _ce["macropoint_url"]
            else:
                s["mp_display_status"] = ""
                s["mp_display_detail"] = ""
                s["mp_last_updated"] = ""
    except Exception:
        pass


    # Enrich with driver_contacts (carrier_email, trailer_number, driver_name)
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT efj, carrier_email, trailer_number, driver_name, driver_phone FROM driver_contacts")
            dc_rows = cur.fetchall()
        dc_map = {r["efj"]: r for r in dc_rows}
        for s in shipments:
            dc = dc_map.get(s["efj"])
            if dc:
                if dc.get("carrier_email") and not s.get("carrier_email"):
                    s["carrier_email"] = dc["carrier_email"]
                if dc.get("trailer_number"):
                    s["trailer"] = dc["trailer_number"]
                if dc.get("driver_name"):
                    s["driver_name"] = dc["driver_name"]
                if dc.get("driver_phone") and not s.get("driver_phone"):
                    s["driver_phone"] = dc["driver_phone"]
    except Exception as e:
        import logging
        logging.getLogger("csl").warning("driver_contacts enrichment failed: %s", e)

    return {"shipments": shipments, "total": len(shipments)}


@router.get("/api/v2/shipments/{efj}")
async def api_v2_shipment_detail(efj: str, request: Request):
    """Return a single shipment from Postgres."""
    with db.get_cursor() as cur:
        cur.execute("SELECT * FROM shipments WHERE efj = %s", (efj,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, f"Shipment {efj} not found")
    return _shipment_row_to_dict(row)


@router.get("/api/v2/stats")
async def api_v2_stats(request: Request):
    """Dashboard stats computed from Postgres."""
    from datetime import datetime as _dt, timedelta as _td
    today = _dt.now().strftime("%Y-%m-%d")
    tomorrow = (_dt.now() + _td(days=1)).strftime("%Y-%m-%d")

    with db.get_cursor() as cur:
        # Active count (not archived, not delivered/completed)
        cur.execute(f"""
            SELECT COUNT(*) as cnt FROM shipments
            WHERE archived = FALSE
              AND LOWER(status) NOT IN ({_POST_DELIVERY_STATUSES})
        """)
        active = cur.fetchone()["cnt"]

        # At risk (LFD is today or tomorrow)
        cur.execute(f"""
            SELECT COUNT(*) as cnt FROM shipments
            WHERE archived = FALSE
              AND LOWER(status) NOT IN ({_POST_DELIVERY_STATUSES})
              AND lfd != '' AND lfd IS NOT NULL
              AND LEFT(lfd, 10) <= %s
        """, (tomorrow,))
        at_risk = cur.fetchone()["cnt"]

        # Completed today
        cur.execute(f"""
            SELECT COUNT(*) as cnt FROM shipments
            WHERE archived = FALSE
              AND LOWER(status) IN ({_POST_DELIVERY_STATUSES})
              AND delivery_date LIKE %s
        """, (f"%{today}%",))
        completed_today = cur.fetchone()["cnt"]

        # ETA changed (bot_notes mentions today)
        cur.execute("""
            SELECT COUNT(*) as cnt FROM shipments
            WHERE archived = FALSE
              AND bot_notes LIKE %s
        """, (f"%{today}%",))
        eta_changed = cur.fetchone()["cnt"]

    on_schedule = max(0, active - at_risk)

    return {
        "active": active,
        "on_schedule": on_schedule,
        "eta_changed": eta_changed,
        "at_risk": at_risk,
        "completed_today": completed_today,
    }


@router.get("/api/v2/accounts")
async def api_v2_accounts(request: Request):
    from datetime import datetime as _dt, timedelta as _td
    """Account list with counts from Postgres."""
    with db.get_cursor() as cur:
        cur.execute(f"""
        SELECT
            account,
            COUNT(*) FILTER (WHERE LOWER(status) NOT IN ({_POST_DELIVERY_STATUSES}) AND archived = FALSE) as active,
            COUNT(*) FILTER (WHERE LOWER(status) IN ({_POST_DELIVERY_STATUSES}) AND archived = FALSE) as done,
            COUNT(*) FILTER (
                WHERE archived = FALSE
                  AND LOWER(status) NOT IN ({_POST_DELIVERY_STATUSES})
                  AND lfd != '' AND lfd IS NOT NULL
                  AND LEFT(lfd, 10) <= %s
            ) as alerts
        FROM shipments
        WHERE archived = FALSE
        GROUP BY account
        ORDER BY active DESC
        """, ((_dt.now() + _td(days=1)).strftime("%Y-%m-%d"),))
        rows = cur.fetchall()

    accounts = [{"name": r["account"], "active": r["active"], "done": r["done"], "alerts": r["alerts"]} for r in rows]
    return {"accounts": accounts}


@router.get("/api/v2/team")
async def api_v2_team(request: Request):
    """Team member summaries from Postgres."""
    with db.get_cursor() as cur:
        cur.execute(f"""
        SELECT rep,
               COUNT(*) FILTER (WHERE LOWER(status) NOT IN ({_POST_DELIVERY_STATUSES}) AND archived = FALSE) as loads,
               array_agg(DISTINCT account) FILTER (WHERE LOWER(status) NOT IN ({_POST_DELIVERY_STATUSES}) AND archived = FALSE) as accounts,
               COUNT(*) FILTER (
                   WHERE archived = FALSE
                     AND LOWER(status) NOT IN ({_POST_DELIVERY_STATUSES})
                     AND lfd != '' AND lfd IS NOT NULL
                     AND LEFT(lfd, 10) <= to_char(NOW() + interval '1 day', 'YYYY-MM-DD')
               ) as at_risk
        FROM shipments
        WHERE archived = FALSE AND rep IS NOT NULL AND rep != ''
        GROUP BY rep
        """)
        rows = cur.fetchall()
    team = {}
    for r in rows:
        accts = r["accounts"] if r["accounts"] else []
        accts = [a for a in accts if a]
        team[r["rep"]] = {"loads": r["loads"], "accounts": sorted(accts), "at_risk": r["at_risk"]}
    return {"team": team}


@router.post("/api/v2/load/{efj}/status")
async def api_v2_update_status(efj: str, request: Request, background_tasks: BackgroundTasks):
    """Update status in Postgres. Write back to Google Sheet if shared account."""
    body = await request.json()
    new_status = body.get("status", "").strip()
    if not new_status:
        raise HTTPException(400, "Missing status")

    # Update Postgres
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE shipments SET status = %s, updated_at = NOW() WHERE efj = %s RETURNING account, hub",
                (new_status, efj),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, f"Shipment {efj} not found")

    account = row["account"]

    # Write back to Google Sheet for shared accounts
    if account in _SHARED_SHEET_ACCOUNTS:
        try:
            _v2_write_status_to_sheet(efj, new_status, account, row.get("hub"))
        except Exception as e:
            log.warning("Sheet write-back failed for %s: %s (Postgres updated OK)", efj, e)
    elif account:
        # Write back to Master Sheet for non-shared accounts (prevents sync overwrite)
        background_tasks.add_task(_write_fields_to_master_sheet, efj, account, {"status": new_status})

    # Auto-advance dray loads: delivered → need_pod (skip for FTL — FTL uses its own flow)
    normalized = new_status.strip().lower().replace(" ", "_")
    if normalized == "delivered":
        try:
            with db.get_cursor() as cur:
                cur.execute("SELECT move_type, account FROM shipments WHERE efj = %s", (efj,))
                _ship = cur.fetchone()
            if _ship:
                _mt = (_ship["move_type"] or "").lower()
                _acct = (_ship["account"] or "")
                # Dray loads (not FTL, not Boviet/Tolead shared accounts which use FTL flow)
                _is_dray = "dray" in _mt or "transload" in _mt
                _is_ftl_account = _acct in ("Boviet", "Tolead")
                if _is_dray and not _is_ftl_account:
                    # Check if POD already uploaded — if so, skip straight to pod_received
                    with db.get_cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM load_documents WHERE efj = %s AND doc_type = 'pod' LIMIT 1",
                            (efj,),
                        )
                        has_pod = cur.fetchone()
                    next_status = "pod_received" if has_pod else "need_pod"
                    with db.get_conn() as conn:
                        with db.get_cursor(conn) as cur:
                            cur.execute(
                                "UPDATE shipments SET status = %s, updated_at = NOW() WHERE efj = %s",
                                (next_status, efj),
                            )
                    log.info("Auto-advanced %s: delivered → %s", efj, next_status)
                    new_status = next_status  # update for sheet write-back + response
        except Exception as e:
            log.warning("Auto-advance check failed for %s: %s", efj, e)

    # Billing gate: if closing as billed, check for open unbilled orders
    if new_status.strip().lower() in ("billed_closed", "billed and closed"):
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute(
                    "SELECT id FROM unbilled_orders "
                    "WHERE REPLACE(order_num, ' ', '') = %s "
                    "AND dismissed = FALSE AND billing_status != 'closed' "
                    "LIMIT 1",
                    (efj,),
                )
                open_unbilled = cur.fetchone()
        if open_unbilled:
            raise HTTPException(
                409,
                "Cannot close: Active billing record found. "
                "Please close this load via the Unbilled Orders dashboard.",
            )
        # No active unbilled order — archive now (load has no billing record)
        _archive_shipment_on_close(efj)
        log.info("billed_closed: no unbilled order for %s — archived directly", efj)

    # Auto-generate email draft for milestone statuses
    draft_id = None
    normalized = new_status.strip().lower().replace(" ", "_")
    if normalized in MILESTONES:
        try:
            draft_id = generate_milestone_draft(efj, normalized)
        except Exception as e:
            log.warning("Email draft generation failed for %s/%s: %s", efj, normalized, e)

    resp = {"ok": True, "efj": efj, "status": new_status}
    if draft_id:
        resp["draft_id"] = draft_id
    return resp


def _v2_write_status_to_sheet(efj: str, new_status: str, account: str, hub: str = None):
    """Write status back to Google Sheet for shared accounts (Tolead/Boviet)."""
    creds = Credentials.from_service_account_file(
        CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)

    if account == "Tolead" and hub and hub in TOLEAD_HUB_CONFIGS:
        cfg = TOLEAD_HUB_CONFIGS[hub]
        sh = gc.open_by_key(cfg["sheet_id"])
        ws = sh.worksheet(cfg["tab"])
        rows = ws.get_all_values()
        cols = cfg["cols"]
        for i, row in enumerate(rows):
            efj_val = row[cols["efj"]].strip() if len(row) > cols["efj"] else ""
            load_val = row[cols["load_id"]].strip() if len(row) > cols["load_id"] else ""
            if efj_val == efj or load_val == efj:
                ws.update_cell(i + 1, cols["status"] + 1, new_status)
                log.info("Sheet write-back: Tolead %s %s → %s (row %d)", hub, efj, new_status, i + 1)
                return
        log.warning("Sheet write-back: %s not found in Tolead %s", efj, hub)

    elif account == "Boviet":
        sh = gc.open_by_key(BOVIET_SHEET_ID)
        for bov_tab, cfg in BOVIET_TAB_CONFIGS.items():
            try:
                ws = sh.worksheet(bov_tab)
                rows = ws.get_all_values()
                for i, row in enumerate(rows):
                    if len(row) > cfg["efj_col"] and row[cfg["efj_col"]].strip() == efj:
                        ws.update_cell(i + 1, cfg["status_col"] + 1, new_status)
                        log.info("Sheet write-back: Boviet/%s %s → %s (row %d)", bov_tab, efj, new_status, i + 1)
                        return
            except Exception:
                continue
        log.warning("Sheet write-back: %s not found in Boviet tabs", efj)


@router.post("/api/v2/load/{efj}/update")
async def api_v2_update_field(efj: str, request: Request, background_tasks: BackgroundTasks):
    """Update any field(s) on a shipment in Postgres + write back to Master Sheet."""
    body = await request.json()

    # Allowed fields to update
    ALLOWED = {
        "move_type", "container", "bol", "vessel", "carrier",
        "origin", "destination", "eta", "lfd", "pickup_date", "delivery_date",
        "status", "notes", "driver", "bot_notes", "return_date",
        "rep", "customer_ref", "equipment_type", "container_url",
        "driver_phone", "hub", "archived", "customer_rate", "carrier_pay",
    }
    updates = {k: v for k, v in body.items() if k in ALLOWED}
    if not updates:
        raise HTTPException(400, "No valid fields to update")

    set_clauses = [f"{k} = %({k})s" for k in updates]
    set_clauses.append("updated_at = NOW()")
    updates["efj"] = efj

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                f"UPDATE shipments SET {', '.join(set_clauses)} WHERE efj = %(efj)s RETURNING *",
                updates,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, f"Shipment {efj} not found")

    # Fire-and-forget: write changed fields back to Master Sheet
    account = row["account"] or ""
    if account and account not in _SHARED_SHEET_ACCOUNTS:
        sheet_fields = {k: v for k, v in body.items() if k in ALLOWED and k != "archived"}
        if sheet_fields:
            background_tasks.add_task(_write_fields_to_master_sheet, efj, account, sheet_fields)

    return {"ok": True, "shipment": _shipment_row_to_dict(row)}


@router.post("/api/v2/load/add")
async def api_v2_add_shipment(request: Request, background_tasks: BackgroundTasks):
    """Insert a new shipment into Postgres. Write to Google Sheet."""
    body = await request.json()
    efj = body.get("efj", "").strip()
    account = body.get("account", "").strip()
    if not efj:
        raise HTTPException(400, "Missing EFJ #")
    if not account:
        raise HTTPException(400, "Missing account")

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO shipments (
                    efj, move_type, container, bol, vessel, carrier,
                    origin, destination, eta, lfd, pickup_date, delivery_date,
                    status, notes, driver, bot_notes, return_date,
                    account, hub, rep, source
                ) VALUES (
                    %(efj)s, %(move_type)s, %(container)s, %(bol)s, %(vessel)s, %(carrier)s,
                    %(origin)s, %(destination)s, %(eta)s, %(lfd)s, %(pickup_date)s, %(delivery_date)s,
                    %(status)s, %(notes)s, %(driver)s, %(bot_notes)s, %(return_date)s,
                    %(account)s, %(hub)s, %(rep)s, 'dashboard'
                )
                ON CONFLICT (efj) DO NOTHING
                RETURNING *
            """, {
                "efj": efj,
                "move_type": body.get("move_type", ""),
                "container": body.get("container", ""),
                "bol": body.get("bol", ""),
                "vessel": body.get("vessel", ""),
                "carrier": body.get("carrier", ""),
                "origin": body.get("origin", ""),
                "destination": body.get("destination", ""),
                "eta": body.get("eta", ""),
                "lfd": body.get("lfd", ""),
                "pickup_date": body.get("pickup_date", ""),
                "delivery_date": body.get("delivery_date", ""),
                "status": body.get("status", ""),
                "notes": body.get("notes", ""),
                "driver": body.get("driver", ""),
                "bot_notes": body.get("bot_notes", ""),
                "return_date": body.get("return_date", ""),
                "account": account,
                "hub": body.get("hub", ""),
                "rep": body.get("rep", "Unassigned"),
            })
            row = cur.fetchone()

    if not row:
        raise HTTPException(409, f"Shipment {efj} already exists")

    # Fire-and-forget: add new row to Master Sheet
    if account and account not in _SHARED_SHEET_ACCOUNTS:
        background_tasks.add_task(_add_load_to_master_sheet, efj, account, body)

    return {"ok": True, "shipment": _shipment_row_to_dict(row)}


def _write_fields_to_master_sheet(efj: str, account: str, fields: dict):
    """Background task: write dashboard field edits back to Master Sheet."""
    try:
        from csl_sheet_writer import sheet_update_field
        sheet_update_field(efj, account, fields)
    except Exception as e:
        log.warning("Sheet write-back failed for %s [%s]: %s (PG update succeeded)", efj, account, e)


def _add_load_to_master_sheet(efj: str, account: str, body: dict):
    """Background task: append new dashboard-created load to Master Sheet."""
    try:
        from csl_sheet_writer import sheet_add_row
        sheet_add_row(efj, account, body)
    except Exception as e:
        log.warning("Sheet add-row failed for %s [%s]: %s (PG insert succeeded)", efj, account, e)


# ═══ Tracking Events Persistence ═══════════════════════════════════════════

def _persist_tracking_event(efj: str, load_ref: str, event_code: str, stop_name: str,
                            stop_type: str, status_mapped: str, lat: str, lon: str,
                            city: str, state: str, event_time: str, mp_order_id: str,
                            raw_params: dict = None):
    """Persist a webhook event to tracking_events PG table. Fire-and-forget."""
    try:
        import json as _json
        # Fix "ET" timestamps — PG doesn't recognize "ET" as a timezone.
        # Convert "2026-03-09 10:33:18 ET" → "2026-03-09 10:33:18-04:00"
        _et = event_time
        if _et and isinstance(_et, str) and _et.rstrip().endswith(" ET"):
            from zoneinfo import ZoneInfo
            from datetime import datetime as _dt
            try:
                _naive_str = _et.rstrip()[:-3]  # strip " ET"
                _naive = _dt.strptime(_naive_str, "%Y-%m-%d %H:%M:%S")
                _aware = _naive.replace(tzinfo=ZoneInfo("America/New_York"))
                _et = _aware.isoformat()
            except Exception:
                pass  # fall through with original value
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    INSERT INTO tracking_events (
                        efj, load_ref, event_code, event_type, stop_name, stop_type,
                        status_mapped, lat, lon, city, state, event_time,
                        mp_order_id, raw_params
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (efj, load_ref, event_code, event_code, stop_name, stop_type,
                      status_mapped, lat, lon, city, state, _et or None,
                      mp_order_id, _json.dumps(raw_params) if raw_params else None))
    except Exception as e:
        log.warning(f"Failed to persist tracking event for {efj}: {e}")


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
