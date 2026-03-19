import json
import logging
import os
import re
import secrets
import sys
import hmac as _hmac
import threading as _billing_threading
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse

import database as db
from shared import (
    _read_tracking_cache, _ai_quick_parse,
    TRACKING_CACHE_FILE, _find_tracking_entry, _classify_mp_display_status,
    templates, tracking_cache, broadcast_tracking_update,
)
import ai_assistant

log = logging.getLogger(__name__)
router = APIRouter()


# Real-time webhook email alerts
if "/root/csl-bot" not in sys.path:
    sys.path.insert(0, "/root/csl-bot")
from csl_ftl_alerts import send_webhook_alert, STATUS_TO_DROPDOWN as _ALERT_STATUS_MAP

# ── Status hierarchy: higher number = further along in lifecycle ──
_STATUS_RANK = {
    "Tracking Started": 1,
    "Tracking Waiting for Update": 2,
    "Driver Phone Unresponsive": 2,
    "Driver Arrived at Pickup": 3,
    "At Pickup": 3,
    "Departed Pickup - En Route": 4,
    "In Transit": 4,
    "Running Late": 4,
    "Tracking Behind Schedule": 4,
    "Arrived at Delivery": 5,
    "At Delivery": 5,
    "Departed Delivery": 6,
    "Delivered": 7,
    "Tracking Completed Successfully": 8,
}


# Statuses that are "done" — ignore all further webhook/monitor events
_TERMINAL_STATUSES = {"Delivered", "Tracking Completed Successfully", "Billed/Closed", "billed_closed"}

def _status_is_regression(old_status, new_status):
    """Return True if new_status is a regression from old_status."""
    old_rank = _STATUS_RANK.get(old_status, 0)
    new_rank = _STATUS_RANK.get(new_status, 0)
    return new_rank > 0 and old_rank > 0 and new_rank < old_rank


_WEBHOOK_STATUS_MAP = {
    "ARRIVED_PICKUP": "Driver Arrived at Pickup",
    "DEPARTED_PICKUP": "Departed Pickup - En Route",
    "IN_TRANSIT": "Departed Pickup - En Route",
    "ARRIVED_DELIVERY": "Arrived at Delivery",
    "DEPARTED_DELIVERY": "Departed Delivery",
    "DELIVERED": "Delivered",
    "TRACKING_STARTED": "Tracking Started",
    "DRIVER_UNRESPONSIVE": "Driver Phone Unresponsive",
    "RUNNING_LATE": "Running Late",
    "CANT_MAKE_IT": "Can't Make It",
    "TRACKING_COMPLETED_SUCCESSFULLY": "Delivered",
    "TRACKING_COMPLETED": "Delivered",
    "COMPLETED": "Delivered",
    "READY_TO_TRACK": "Tracking Started",
    "TRACKING_NOW": "Tracking Started",
}

_WEBHOOK_LOG = "/root/csl-bot/webhook_payloads.log"
_WEBHOOK_EVENTS_LOG = "/root/csl-bot/webhook_events.log"
_WH_USER = os.getenv("WEBHOOK_AUTH_USERNAME", "")
_WH_PASS = os.getenv("WEBHOOK_AUTH_PASSWORD", "")


def _webhook_basic_auth(request: Request) -> bool:
    """Validate HTTP Basic Auth for Macropoint webhook."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Basic "):
        return False
    import base64 as _b64
    try:
        decoded = _b64.b64decode(auth_header[6:]).decode()
        user, passwd = decoded.split(":", 1)
    except Exception:
        return False
    return (_hmac.compare_digest(user, _WH_USER)
            and _hmac.compare_digest(passwd, _WH_PASS))


def _update_tracking_cache_webhook(load_ref: str, status: str, now: str, payload: dict):
    """Update in-memory tracking cache when a webhook event arrives.

    Uses the TrackingCache singleton (in-memory with debounced disk flush)
    instead of direct file I/O for much lower latency.
    """
    # Find entry in in-memory cache
    matched_key, entry = tracking_cache.find_entry(load_ref)

    # Fallback: look up by container field in Postgres
    if not matched_key:
        try:
            with db.get_cursor() as cur:
                cur.execute(
                    "SELECT efj FROM shipments WHERE container = %s OR container LIKE %s LIMIT 1",
                    (load_ref, f"%{load_ref}%"),
                )
                row = cur.fetchone()
                if row:
                    pg_efj = row["efj"]
                    efj_num = pg_efj.replace("EFJ", "").strip()
                    # Check if this EFJ is in cache
                    existing = tracking_cache.get(efj_num) or tracking_cache.get(pg_efj)
                    if existing:
                        matched_key = efj_num if tracking_cache.get(efj_num) else pg_efj
                        entry = existing
                    else:
                        # Pull driver_phone from driver_contacts if available
                        _init_phone = ""
                        _init_trailer = ""
                        try:
                            cur.execute(
                                "SELECT driver_phone, trailer_number FROM driver_contacts WHERE efj = %s",
                                (pg_efj,),
                            )
                            dc_row = cur.fetchone()
                            if dc_row:
                                _init_phone = (dc_row["driver_phone"] or "").strip()
                                _init_trailer = (dc_row["trailer_number"] or "").strip()
                        except Exception as e:
                            log.debug("driver_contacts lookup for %s failed: %s", pg_efj, e)
                        # Create a new cache entry for this load
                        entry = {
                            "efj": pg_efj,
                            "load_num": load_ref,
                            "status": "",
                            "mp_load_id": load_ref,
                            "cant_make_it": None,
                            "stop_times": {},
                            "macropoint_url": "",
                            "last_scraped": "",
                            "driver_phone": _init_phone,
                            "trailer": _init_trailer,
                        }
                        tracking_cache.set(efj_num, entry)
                        matched_key = efj_num
                        log.info(f"Webhook: created cache entry {efj_num} for container {load_ref}")
        except Exception as exc:
            log.debug(f"Webhook PG container lookup failed: {exc}")

    if not matched_key or not entry:
        return False, None
    old_status = entry.get("status", "")
    # ── Status hierarchy guard: block regressions ──
    if _status_is_regression(old_status, status):
        log.info(
            f"Webhook: BLOCKED status regression {matched_key} [{old_status}] -> [{status}]"
        )
        return False, None
    # ── Distance guard: block premature Delivered from D1 ──────────────
    if status == "Delivered":
        dist_raw = entry.get("distance_to_stop")
        dist_miles = None
        try:
            dist_miles = float(dist_raw) if dist_raw is not None else None
        except (TypeError, ValueError):
            pass
        if dist_miles is not None and dist_miles > 15:
            log.warning(
                "Webhook D1 DEMOTED for %s: truck is %.1f mi from dest — "
                "setting 'Arrived at Delivery' instead to prevent false archive",
                load_ref, dist_miles
            )
            status = "Arrived at Delivery"

    entry["status"] = status
    entry["last_scraped"] = now
    entry["webhook_updated"] = True
    entry["last_event_at"] = now

    # Auto-populate macropoint_url from MPOrderID if available
    mp_order_id = payload.get("mp_order_id") or payload.get("MPOrderID") or ""
    if mp_order_id and not entry.get("macropoint_url"):
        entry["macropoint_url"] = f"https://visibility.macropoint.com/shipments?l={mp_order_id}"

    stop_times = entry.get("stop_times", {})
    event_upper = (payload.get("eventType") or payload.get("event_type") or "").upper()
    event_time = payload.get("eventTime") or payload.get("timestamp") or now

    if "ARRIVED" in event_upper and "PICKUP" in event_upper:
        stop_times["stop1_arrived"] = event_time
    elif "DEPARTED" in event_upper and "PICKUP" in event_upper:
        stop_times["stop1_departed"] = event_time
    elif "ARRIVED" in event_upper and "DELIVERY" in event_upper:
        stop_times["stop2_arrived"] = event_time
    elif "DEPARTED" in event_upper and "DELIVERY" in event_upper:
        stop_times["stop2_departed"] = event_time
    elif "DELIVERED" in event_upper:
        stop_times["stop2_departed"] = event_time

    entry["stop_times"] = stop_times

    # Write to in-memory cache (disk flush happens in background every 2s)
    tracking_cache.set(matched_key, entry)

    log.info(f"Webhook cache updated: {matched_key} [{old_status}] -> [{status}]")

    # ── SSE broadcast: push update to all connected dashboard clients ──
    _ts_disp, _ts_detail = _classify_mp_display_status(entry)
    broadcast_tracking_update(matched_key, {
        "status": status,
        "behindSchedule": "BEHIND" in (entry.get("schedule_alert") or "").upper(),
        "cantMakeIt": bool(entry.get("cant_make_it")),
        "lastScraped": now,
        "stop1Arrived": stop_times.get("stop1_arrived"),
        "stop1Departed": stop_times.get("stop1_departed"),
        "stop2Arrived": stop_times.get("stop2_arrived"),
        "stop2Departed": stop_times.get("stop2_departed"),
        "mpDisplayStatus": _ts_disp,
        "mpDisplayDetail": _ts_detail,
        "driverPhone": entry.get("driver_phone", ""),
        "trailer": entry.get("trailer", ""),
    })

    _match_info = {
        "efj": entry.get("efj", ""),
        "load_num": entry.get("load_num", ""),
        "stop_times": entry.get("stop_times", {}),
        "mp_load_id": entry.get("mp_load_id", ""),
        "matched_key": matched_key,
    }
    return True, _match_info


def _persist_tracking_event(efj: str, load_ref: str, event_code: str, stop_name: str,
                            stop_type: str, status_mapped: str, lat: str, lon: str,
                            city: str, state: str, event_time: str, mp_order_id: str,
                            raw_params: dict = None):
    """Persist a webhook event to tracking_events PG table. Fire-and-forget."""
    try:
        import json as _json
        # Fix "ET" timestamps — PG doesn't recognize "ET" as a timezone.
        # Convert "2026-03-09 10:33:18 ET" → "2026-03-09 10:33:18-04:00" (or -05:00 for EST)
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


# ── Macropoint Billing Bridge: auto-transition Delivered → ready_to_close ──

def _delayed_billing_transition(efj_num: str, delay_seconds: int = 60):
    """After a delay, transition delivered loads to ready_to_close for billing queue.
    Only transitions if status is still 'Delivered' (rep hasn't changed it)."""
    import time
    time.sleep(delay_seconds)
    try:
        with db.get_cursor() as cur:
            cur.execute(
                """UPDATE shipments SET status = 'ready_to_close', updated_at = NOW()
                   WHERE efj = %s AND LOWER(status) IN ('delivered', 'completed')""",
                (efj_num,),
            )
            if cur.rowcount > 0:
                log.info("Billing bridge: auto-transitioned %s to ready_to_close (60s after Delivered)", efj_num)
            else:
                log.info("Billing bridge: skipped %s — status already changed by rep", efj_num)
    except Exception as exc:
        log.error("Billing bridge: failed for %s: %s", efj_num, exc)

def _webhook_send_alert_background(efj: str, load_num: str, status: str,
                                    stop_times: dict, mp_load_id: str,
                                    matched_key: str):
    """Background task: resolve account from PG, write PG status, send email."""
    try:
        # Resolve account from Postgres
        account = ""
        dest = ""
        existing_status = ""
        try:
            with db.get_cursor() as cur:
                cur.execute(
                    "SELECT account, destination, status FROM shipments WHERE efj = %s",
                    (efj,)
                )
                row = cur.fetchone()
                if row:
                    account = row.get("account", "") or ""
                    dest = row.get("destination", "") or ""
                    existing_status = row.get("status", "") or ""
        except Exception as exc:
            log.warning(f"Webhook bg: PG lookup failed for {efj}: {exc}")

        if not account:
            log.warning(f"Webhook bg: no account found for {efj} — skipping email")
            return

        # Map webhook status to dropdown value for PG write
        dropdown = _ALERT_STATUS_MAP.get(status)
        # ── "Assigned" auto-status: when MP shows Tracking Started/Ready to Track ──
        if status == "Tracking Started" and (not dropdown or dropdown == "Tracking Waiting for Update"):
            dropdown = "Assigned"

        # Write PG status update
        # ── Block status regression (skip PG write AND email) ──
        if _status_is_regression(existing_status, status):
            log.info(f"Webhook BG: BLOCKED regression {efj} [{existing_status}] -> [{status}] — skipping entirely")
            return
        # ── Skip if load is already in terminal status ──
        if existing_status in _TERMINAL_STATUSES:
            log.info(f"Webhook BG: SKIP {efj} — already in terminal status [{existing_status}]")
            return
        if dropdown and dropdown != existing_status:
            try:
                from csl_pg_writer import pg_update_shipment as _pg_up
                kwargs = {"status": dropdown}
                # Extract dates from stop_times
                if stop_times.get("stop1_arrived"):
                    kwargs["pickup_date"] = stop_times["stop1_arrived"]
                if stop_times.get("stop2_arrived") or stop_times.get("stop2_departed"):
                    kwargs["delivery_date"] = stop_times.get("stop2_departed") or stop_times.get("stop2_arrived")
                _pg_up(efj, **kwargs)
                log.info(f"Webhook bg: PG updated {efj} -> {dropdown}")
            except Exception as exc:
                log.warning(f"Webhook bg: PG write failed for {efj}: {exc}")

        # ── Billing Bridge: fire delayed transition on Delivered ──
        if dropdown == "Delivered":
            _t = _billing_threading.Thread(
                target=_delayed_billing_transition,
                args=(efj,),
                kwargs={"delay_seconds": 60},
                daemon=True,
            )
            _t.start()
            log.info(f"Billing bridge: scheduled ready_to_close for {efj} in 60s")


        # Write container_url and driver_phone to PG if available from cache
        try:
            _entry_tmp = tracking_cache.get(matched_key) or {}
            _mp_url = _entry_tmp.get("macropoint_url", "")
            if _mp_url:
                with db.get_cursor() as cur:
                    cur.execute(
                        "UPDATE shipments SET container_url = %s WHERE efj = %s AND (container_url IS NULL OR container_url = '')",
                        (_mp_url, efj)
                    )
                    log.info(f"Webhook bg: wrote container_url for {efj}")

            # Sync driver_phone from cache to driver_contacts PG table
            _cached_phone = (_entry_tmp.get("driver_phone") or "").strip()
            _cached_trailer = (_entry_tmp.get("trailer") or "").strip()
            if _cached_phone or _cached_trailer:
                with db.get_cursor() as cur:
                    cur.execute(
                        """INSERT INTO driver_contacts (efj, driver_phone, trailer_number, updated_at)
                           VALUES (%s, %s, %s, NOW())
                           ON CONFLICT (efj) DO UPDATE SET
                               driver_phone = CASE WHEN EXCLUDED.driver_phone != '' THEN EXCLUDED.driver_phone ELSE driver_contacts.driver_phone END,
                               trailer_number = CASE WHEN EXCLUDED.trailer_number != '' THEN EXCLUDED.trailer_number ELSE driver_contacts.trailer_number END,
                               updated_at = NOW()""",
                        (efj, _cached_phone or None, _cached_trailer or None),
                    )
                    log.info(f"Webhook bg: synced driver_contacts for {efj} (phone={bool(_cached_phone)}, trailer={bool(_cached_trailer)})")
        except Exception as _url_exc:
            log.debug(f"Webhook bg: cache→PG sync skipped for {efj}: {_url_exc}")

        # Send real-time email alert (with dedup)
        sent = send_webhook_alert(
            efj=efj,
            load_num=load_num,
            status=status,
            account=account,
            stop_times=stop_times,
            mp_load_id=mp_load_id,
        )
        log.info(f"Webhook bg: alert {'sent' if sent else 'skipped (dedup)'} for {efj} [{status}]")

    except Exception as exc:
        log.error(f"Webhook bg: unhandled error for {efj}: {exc}")

@router.get("/webhook-test")
async def webhook_health():
    now = datetime.now(tz=__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")
    return {"status": "ok", "service": "csl-webhook (integrated)", "time": now}


@router.get("/macropoint-webhook")
async def macropoint_webhook_get(request: Request, background_tasks: BackgroundTasks):
    """Handle Macropoint native protocol callbacks (GET with query params)."""
    from urllib.parse import unquote
    params = dict(request.query_params)
    now = datetime.now(tz=__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")

    load_ref = params.get("ID", "").strip()
    data_source = params.get("DataSource", "").strip()
    mp_order_id = params.get("MPOrderID", "")
    lat = params.get("Latitude", "")
    lon = params.get("Longitude", "")
    city = params.get("City", "")
    state = params.get("State", "")
    street = params.get("Street1", "")
    timestamp = params.get("LocationDateTimeUTC", "") or params.get("ApproxLocationDateTimeInLocalTime", "")

    # Log all incoming events
    event_record = {
        "time": now,
        "load_ref": load_ref,
        "data_source": data_source,
        "mp_order_id": mp_order_id,
        "params": {k: v for k, v in params.items() if k not in ("MPOrderID",)},
    }
    try:
        with open(_WEBHOOK_EVENTS_LOG, "a") as f:
            f.write(json.dumps(event_record) + "\n")
    except Exception:
        pass

    if not load_ref:
        return {"status": "ok", "processed": False, "reason": "no load ID"}

    # ── Location Pings ────────────────────────────────────────────────
    if data_source == "Ping" and lat and lon:
        # Find matching cache entry using in-memory cache
        matched_key, entry = tracking_cache.find_entry(load_ref)

        if matched_key and entry:
            entry["last_location"] = {
                "lat": lat, "lon": lon,
                "city": city, "state": state, "street": street,
                "timestamp": timestamp,
            }
            entry["last_scraped"] = now
            entry["last_ping_at"] = now
            if not entry.get("last_event_at"):
                entry["last_event_at"] = now
            # Gap D: Initialize status if blank — pings prove tracking is active
            if not (entry.get("status") or "").strip():
                entry["status"] = "Tracking Started"
                log.info(f"Webhook: auto-set Tracking Started for {matched_key} (ping received)")

            # ── Infer In Transit from pings ──────────────────────────
            # If truck has arrived at pickup but no X2 departure event yet,
            # detect movement away from pickup via consecutive pings and
            # auto-set status to "Departed Pickup - En Route".
            _stop_times = entry.get("stop_times", {})
            _cur_status = (entry.get("status") or "").strip()
            _pickup_rank = _STATUS_RANK.get(_cur_status, 0)
            if (_stop_times.get("stop1_arrived")
                    and not _stop_times.get("stop1_departed")
                    and _pickup_rank < _STATUS_RANK.get("Departed Pickup - En Route", 4)):
                try:
                    _prev_loc = entry.get("_prev_ping_loc")
                    _cur_lat, _cur_lon = float(lat), float(lon)
                    if _prev_loc:
                        from math import radians, sin, cos, sqrt, atan2
                        _R = 3959  # Earth radius in miles
                        _la1, _lo1 = radians(_prev_loc["lat"]), radians(_prev_loc["lon"])
                        _la2, _lo2 = radians(_cur_lat), radians(_cur_lon)
                        _dlat, _dlon = _la2 - _la1, _lo2 - _lo1
                        _a = sin(_dlat/2)**2 + cos(_la1)*cos(_la2)*sin(_dlon/2)**2
                        _dist = _R * 2 * atan2(sqrt(_a), sqrt(1-_a))
                        # Count consecutive pings showing movement (> 0.5 mi apart)
                        _move_count = entry.get("_ping_move_count", 0)
                        if _dist > 0.5:
                            _move_count += 1
                        else:
                            _move_count = 0
                        entry["_ping_move_count"] = _move_count
                        # 3+ consecutive moving pings = truck has departed pickup
                        if _move_count >= 3:
                            _inferred = "Departed Pickup - En Route"
                            entry["status"] = _inferred
                            _stop_times["stop1_departed"] = now
                            entry["stop_times"] = _stop_times
                            entry["_ping_move_count"] = 0
                            log.info(f"Webhook INFERRED In Transit from pings: {load_ref} "
                                     f"({_move_count} consecutive moving pings)")
                            # Persist inferred event
                            _persist_efj = entry.get("efj")
                            if _persist_efj:
                                _persist_tracking_event(
                                    efj=_persist_efj, load_ref=load_ref,
                                    event_code="X2", stop_name="Pickup (inferred)",
                                    stop_type="Pickup", status_mapped=_inferred,
                                    lat=lat, lon=lon, city=city, state=state,
                                    event_time=now, mp_order_id=mp_order_id,
                                    raw_params={"inferred_from": "consecutive_pings",
                                                "move_count": _move_count},
                                )
                            # SSE broadcast + background alert
                            broadcast_tracking_update(matched_key, {
                                "status": _inferred,
                                "stop1Departed": now,
                                "lastScraped": now,
                                "lastLocation": {"city": city, "state": state},
                            })
                            # Fire background PG write + email alert
                            _inf_efj = entry.get("efj", "")
                            if _inf_efj:
                                background_tasks.add_task(
                                    _webhook_send_alert_background,
                                    efj=_inf_efj,
                                    load_num=entry.get("load_num", load_ref),
                                    status=_inferred,
                                    stop_times=_stop_times,
                                    mp_load_id=entry.get("mp_load_id", ""),
                                    matched_key=matched_key,
                                )
                    entry["_prev_ping_loc"] = {"lat": _cur_lat, "lon": _cur_lon}
                except (ValueError, TypeError):
                    pass  # Bad lat/lon — skip inference

            tracking_cache.set(matched_key, entry)

            # ── SSE: broadcast location ping to dashboard ────────────
            broadcast_tracking_update(matched_key, {
                "lastLocation": {"lat": lat, "lon": lon, "city": city,
                                 "state": state, "street": street,
                                 "timestamp": timestamp},
                "lastScraped": now,
            })

        log.debug(f"Webhook ping: {load_ref} @ {city}, {state}")
        return {"status": "ok", "type": "location_ping", "load": load_ref}

    # ── Trip Events (Event field: X1, X2, X3, X6, AG, AF, etc.) ─────
    event_code = params.get("Event", "").strip()
    stop_name = params.get("Stop", "").strip()
    stop_type = params.get("StopType", "").strip()  # Pickup / DropOff

    # Macropoint event code → internal status mapping

    _MP_EVENT_MAP = {
        "AF": "Tracking Started",
        "X1": None,   # Arrived — need stop context
        "X2": None,   # Departed — need stop context
        "X3": None,   # Position near stop — skip (too noisy)
        "X4": "Departed Pickup - En Route",
        "X6": "Delivered",
        "D1": "Delivered",   # Delivery confirmation
        "AG": "Driver Phone Unresponsive",
    }

    if event_code:
        mapped = _MP_EVENT_MAP.get(event_code)

        # X1 (Arrived) / X2 (Departed) — need to infer pickup vs delivery
        if event_code == "X1":
            # If it's the first stop (pickup) or stop_type=Pickup
            if stop_type.lower() == "pickup" or "pickup" in stop_name.lower():
                mapped = "Driver Arrived at Pickup"
            else:
                mapped = "Arrived at Delivery"
        elif event_code == "X2":
            if stop_type.lower() == "pickup" or "pickup" in stop_name.lower():
                mapped = "Departed Pickup - En Route"
            else:
                mapped = "Departed Delivery"
        elif event_code == "X3":
            # Position update near stop — don't treat as status change
            log.debug(f"Webhook X3 (position near stop): {load_ref} @ {stop_name}")
            return {"status": "ok", "type": "position_near_stop", "load": load_ref}

        if mapped:
            # Map human-readable status back to structured event type for stop_times parsing
            _MAPPED_TO_EVENT_TYPE = {
                "Driver Arrived at Pickup": "ARRIVED_PICKUP",
                "Departed Pickup - En Route": "DEPARTED_PICKUP",
                "Arrived at Delivery": "ARRIVED_DELIVERY",
                "Departed Delivery": "DEPARTED_DELIVERY",
                "Delivered": "DELIVERED",
            }
            structured_event = _MAPPED_TO_EVENT_TYPE.get(mapped, event_code)

            cache_updated, _match_info = _update_tracking_cache_webhook(load_ref, mapped, now, {
                "loadNumber": load_ref,
                "eventType": structured_event,
                "event": event_code,
                "stop": stop_name,
                "timestamp": timestamp,
                "mp_order_id": mp_order_id,
            })
            if cache_updated and _match_info:
                background_tasks.add_task(
                    _webhook_send_alert_background,
                    efj=_match_info["efj"],
                    load_num=_match_info["load_num"],
                    status=mapped,
                    stop_times=_match_info["stop_times"],
                    mp_load_id=_match_info["mp_load_id"],
                    matched_key=_match_info["matched_key"],
                )
            # Persist event to PG for historical timeline
            _persist_efj = _match_info["efj"] if cache_updated and _match_info else None
            if _persist_efj:
                _persist_tracking_event(
                    efj=_persist_efj,
                    load_ref=load_ref,
                    event_code=event_code,
                    stop_name=stop_name,
                    stop_type=stop_type,
                    status_mapped=mapped,
                    lat=params.get("Latitude", ""),
                    lon=params.get("Longitude", ""),
                    city=params.get("City", ""),
                    state=params.get("State", ""),
                    event_time=timestamp,
                    mp_order_id=mp_order_id,
                    raw_params=dict(params),
                )
            log.info(f"Webhook trip event: {load_ref} [{event_code}] -> {mapped} (cache={cache_updated})")
            return {"status": "ok", "type": "trip_event", "load": load_ref, "event": event_code, "status_mapped": mapped}

    # ── Schedule Alerts (ScheduleAlertText field) ─────────────────────
    schedule_alert = params.get("ScheduleAlertText", "").strip()
    distance_str = params.get("DistanceToStopInMiles", "").strip()
    if schedule_alert or (stop_type and distance_str):
        # ── Infer stop arrival/departure from GPS proximity ──
        # Macropoint only sends X1 for delivery stops.  For pickup stops,
        # we infer arrival when DistanceToStopInMiles < 0.5 and departure
        # when distance increases after a recorded arrival.
        ARRIVAL_THRESHOLD = 0.5   # miles — "at the stop"
        DEPARTURE_THRESHOLD = 2.0  # miles — "left the stop"
        try:
            distance_mi = float(distance_str) if distance_str else None
        except (ValueError, TypeError):
            distance_mi = None

        if distance_mi is not None and stop_type:
            stop_key = "stop1" if stop_type.lower() in ("pickup", "origin") else "stop2"
            arrived_key = f"{stop_key}_arrived"
            departed_key = f"{stop_key}_departed"

            # Use in-memory cache
            _sc_matched, _sc_entry = tracking_cache.find_entry(load_ref)

            if _sc_matched and _sc_entry:
                _sc_stops = _sc_entry.get("stop_times", {})
                _changed = False

                # Use the handler's 'now' timestamp (ET) — schedule alerts
                # don't carry ApproxLocationDateTimeInLocalTime (that's on Pings).
                # EtaToStop is the predicted arrival, not the current time.
                event_local_time = now

                # Arrival detection: close to stop and not yet recorded
                if distance_mi < ARRIVAL_THRESHOLD and not _sc_stops.get(arrived_key):
                    _sc_stops[arrived_key] = event_local_time
                    _changed = True
                    _inferred_event = "Arrived at Pickup" if stop_key == "stop1" else "Arrived at Delivery"
                    log.info(f"Webhook INFERRED {_inferred_event}: {load_ref} dist={distance_mi:.2f}mi at {stop_type}")

                    # Persist to PG tracking_events
                    _persist_efj = _sc_entry.get("efj")
                    if _persist_efj:
                        _persist_tracking_event(
                            efj=_persist_efj,
                            load_ref=load_ref,
                            event_code="X1",
                            stop_name=params.get("StopName", ""),
                            stop_type=stop_type,
                            status_mapped=_inferred_event,
                            lat=params.get("Latitude", ""),
                            lon=params.get("Longitude", ""),
                            city=params.get("City", ""),
                            state=params.get("State", ""),
                            event_time=event_local_time,
                            mp_order_id=mp_order_id,
                            raw_params=dict(params),
                        )

                # Departure detection: was at stop, now moved away
                if (distance_mi > DEPARTURE_THRESHOLD and
                        _sc_stops.get(arrived_key) and
                        not _sc_stops.get(departed_key)):
                    _sc_stops[departed_key] = event_local_time
                    _changed = True
                    _inferred_event = "Departed Pickup" if stop_key == "stop1" else "Departed Delivery"
                    log.info(f"Webhook INFERRED {_inferred_event}: {load_ref} dist={distance_mi:.2f}mi from {stop_type}")

                    # Persist to PG tracking_events
                    _persist_efj = _sc_entry.get("efj")
                    if _persist_efj:
                        _persist_tracking_event(
                            efj=_persist_efj,
                            load_ref=load_ref,
                            event_code="X2",
                            stop_name=params.get("StopName", ""),
                            stop_type=stop_type,
                            status_mapped=_inferred_event,
                            lat=params.get("Latitude", ""),
                            lon=params.get("Longitude", ""),
                            city=params.get("City", ""),
                            state=params.get("State", ""),
                            event_time=event_local_time,
                            mp_order_id=mp_order_id,
                            raw_params=dict(params),
                        )

                if _changed:
                    _sc_entry["stop_times"] = _sc_stops
                    tracking_cache.set(_sc_matched, _sc_entry)

        # ── Store schedule alert intelligence in tracking cache ──
        if schedule_alert:
            try:
                _sa_key, _sa_entry = tracking_cache.find_entry(load_ref)
                if _sa_key and _sa_entry:
                    _old_alert = _sa_entry.get("schedule_alert", "")
                    if schedule_alert != _old_alert:
                        _sa_entry["schedule_alert"] = schedule_alert
                        _sa_entry["schedule_alert_code"] = params.get("ScheduleAlertCode", "")
                        _sa_entry["distance_to_stop"] = distance_str
                        _sa_entry["eta_to_stop"] = params.get("EtaToStop", "")
                        _sa_entry["schedule_stop_type"] = stop_type
                        # Gap B: Set cant_make_it from ScheduleAlertCode=3
                        _alert_code = str(params.get("ScheduleAlertCode", "")).strip()
                        if _alert_code == "3":
                            _sa_entry["cant_make_it"] = True
                            log.info(f"Webhook: cant_make_it=True for {_sa_key} (code=3)")
                        elif _alert_code in ("1", "2") and _sa_entry.get("cant_make_it"):
                            _sa_entry["cant_make_it"] = None
                            log.info(f"Webhook: cant_make_it cleared for {_sa_key} (code={_alert_code})")
                        tracking_cache.set(_sa_key, _sa_entry)
                        log.debug(f"Webhook: stored schedule alert for {_sa_key}: {schedule_alert}")
            except Exception as _sa_exc:
                log.debug(f"Webhook: schedule alert storage failed: {_sa_exc}")

        log.info(f"Webhook schedule alert: {load_ref} [{stop_type}] {schedule_alert} (dist={distance_str} mi)")
        return {"status": "ok", "type": "schedule_alert", "load": load_ref, "alert": schedule_alert}

    # ── Fallback: check other event fields ────────────────────────────
    event_type = (
        params.get("EventType", "") or params.get("Status", "") or
        params.get("OrderStatus", "") or data_source
    ).strip()

    if event_type and event_type != "Ping":
        mapped_status = _WEBHOOK_STATUS_MAP.get(event_type.upper().replace(" ", "_"), "")
        if not mapped_status:
            mapped_status = event_type
        if mapped_status:
            cache_updated, _match_info = _update_tracking_cache_webhook(load_ref, mapped_status, now, {
                "loadNumber": load_ref,
                "eventType": event_type.upper().replace(" ", "_"),
                "timestamp": timestamp,
                "mp_order_id": mp_order_id,
            })
            if cache_updated and _match_info:
                background_tasks.add_task(
                    _webhook_send_alert_background,
                    efj=_match_info["efj"],
                    load_num=_match_info["load_num"],
                    status=mapped_status,
                    stop_times=_match_info["stop_times"],
                    mp_load_id=_match_info["mp_load_id"],
                    matched_key=_match_info["matched_key"],
                )
            log.info(f"Webhook GET event: {load_ref} -> {mapped_status} (cache={cache_updated})")
            return {"status": "ok", "type": "status_event", "load": load_ref, "status_mapped": mapped_status}

    return {"status": "ok", "type": data_source or "unknown", "load": load_ref}


@router.post("/macropoint-webhook")
async def macropoint_webhook(request: Request, background_tasks: BackgroundTasks):
    # Basic Auth check
    if not _webhook_basic_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": 'Basic realm="csl-bot"'})

    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    now = datetime.now(tz=__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")

    # Raw payload log
    log_entry = f"\n{'=' * 60}\n[{now}]\n{json.dumps(payload, indent=2)}\n"
    try:
        with open(_WEBHOOK_LOG, "a") as f:
            f.write(log_entry)
    except Exception:
        pass

    log.info(f"Webhook received: {json.dumps(payload)[:200]}")

    # Skip test payloads
    if payload.get("test"):
        log.info("Test payload — skipping processing")
        return {"status": "ok", "processed": False, "reason": "test payload"}

    # Extract load identifier
    load_ref = (
        payload.get("loadNumber")
        or payload.get("pro")
        or payload.get("referenceNumber")
        or payload.get("load_number")
        or payload.get("shipmentId")
        or payload.get("reference_number")
        or ""
    ).strip()

    event_type = (
        payload.get("eventType")
        or payload.get("status")
        or payload.get("event_type")
        or payload.get("event")
        or ""
    ).strip()

    # Map event to internal status
    mapped_status = _WEBHOOK_STATUS_MAP.get(event_type.upper().replace(" ", "_"), "")
    if not mapped_status and event_type:
        mapped_status = event_type

    # Structured event log
    event_record = {
        "time": now,
        "load_ref": load_ref,
        "raw_event": event_type,
        "mapped_status": mapped_status,
        "payload_keys": list(payload.keys()),
    }
    try:
        with open(_WEBHOOK_EVENTS_LOG, "a") as f:
            f.write(json.dumps(event_record) + "\n")
    except Exception:
        pass

    # Update tracking cache
    cache_updated = False
    if load_ref and mapped_status:
        cache_updated, _match_info = _update_tracking_cache_webhook(load_ref, mapped_status, now, payload)

        # Persist event to PG for historical timeline
        if cache_updated and _match_info:
            _persist_tracking_event(
                efj=_match_info["efj"],
                load_ref=load_ref,
                event_code=payload.get("event", payload.get("eventCode", "")),
                stop_name=payload.get("stop", ""),
                stop_type=payload.get("stopType", ""),
                status_mapped=mapped_status,
                lat=payload.get("latitude", ""),
                lon=payload.get("longitude", ""),
                city=payload.get("city", ""),
                state=payload.get("state", ""),
                event_time=payload.get("eventTime", payload.get("timestamp", "")),
                mp_order_id=payload.get("MPOrderID", payload.get("mp_order_id", "")),
                raw_params=payload,
            )

        # Real-time: write PG + send email in background task
        if cache_updated and _match_info:
            background_tasks.add_task(
                _webhook_send_alert_background,
                efj=_match_info["efj"],
                load_num=_match_info["load_num"],
                status=mapped_status,
                stop_times=_match_info["stop_times"],
                mp_load_id=_match_info["mp_load_id"],
                matched_key=_match_info["matched_key"],
            )

    if not load_ref:
        log.warning(f"Webhook: unknown payload format — keys: {list(payload.keys())}")
        return {"status": "ok", "processed": False, "reason": "unknown format"}

    log.info(f"Webhook processed: {load_ref} -> {mapped_status or '(no status)'} (cache_updated={cache_updated})")
    return {
        "status": "ok",
        "processed": True,
        "load_ref": load_ref,
        "mapped_status": mapped_status,
        "cache_updated": cache_updated,
    }


@router.post("/api/quick-parse")
async def quick_parse(request: Request):
    """Extract freight details from freeform text using Claude Sonnet 4.6."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "text field is required"}, status_code=422)
    if len(text) > 10000:
        return JSONResponse({"error": "text too long (max 10000 chars)"}, status_code=422)

    result = _ai_quick_parse(text)
    if not result:
        return JSONResponse(
            {"error": "Could not extract freight details from provided text"},
            status_code=422
        )
    return JSONResponse(result)



# ── Public Customer Tracking ──────────────────────────────────────────────

@router.post("/api/shipments/{efj}/generate-token")
async def generate_tracking_token(efj: str, request: Request):
    """Generate (or return existing active) public tracking link for a load."""
    try:
        body = await request.json()
        show_driver = bool(body.get("show_driver", False))
    except Exception:
        show_driver = False

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            # Return existing non-expired token if one exists
            cur.execute("""
                SELECT token::text FROM public_tracking_tokens
                WHERE efj = %s AND expires_at > now()
                ORDER BY created_at DESC LIMIT 1
            """, (efj,))
            row = cur.fetchone()
            if row:
                token = row["token"]
            else:
                cur.execute("""
                    INSERT INTO public_tracking_tokens (efj, show_driver)
                    VALUES (%s, %s)
                    RETURNING token::text
                """, (efj, show_driver))
                token = cur.fetchone()["token"]
        conn.commit()

    base_url = str(request.base_url).rstrip("/")
    return {"token": token, "url": f"{base_url}/track/{token}"}


@router.get("/track/{token}", response_class=HTMLResponse)
async def public_tracking_page(token: str, request: Request):
    """Public shipment tracking page — no auth required."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                SELECT
                    s.efj,
                    s.status,
                    s.eta,
                    s.origin,
                    s.destination,
                    te.event_time AS last_ping,
                    CASE WHEN ptt.show_driver THEN d.driver_name ELSE NULL END AS driver_name
                FROM public_tracking_tokens ptt
                JOIN shipments s ON ptt.efj = s.efj
                LEFT JOIN LATERAL (
                    SELECT event_time FROM tracking_events
                    WHERE efj = s.efj ORDER BY event_time DESC LIMIT 1
                ) te ON true
                LEFT JOIN driver_contacts d ON d.efj = s.efj
                WHERE ptt.token = %s::uuid
                  AND ptt.expires_at > now()
            """, (token,))
            row = cur.fetchone()

    if not row:
        expired_html = """<!DOCTYPE html>
<html><head><title>Link Expired | Evans Delivery</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gray-50 flex items-center justify-center min-h-screen">
<div class="text-center p-8">
<p class="text-2xl font-bold text-slate-700">Link Expired</p>
<p class="text-slate-400 mt-2 text-sm">This tracking link is no longer active.<br>
Contact Evans Delivery for an updated link.</p>
</div></body></html>"""
        return HTMLResponse(expired_html, status_code=404)

    # Format timestamp for display
    last_ping = "Awaiting GPS signal"
    if row.get("last_ping"):
        try:
            last_ping = row["last_ping"].strftime("%-m/%-d %H:%M") + " UTC"
        except Exception:
            last_ping = str(row["last_ping"])

    data = {
        "efj":        row["efj"],
        "status":     row["status"] or "In Transit",
        "eta":        row["eta"] or "TBD",
        "origin":     row["origin"] or "\u2014",
        "destination": row["destination"] or "\u2014",
        "last_ping":  last_ping,
        "driver_name": row.get("driver_name"),
    }
    return templates.TemplateResponse(
        "public_track.html", {"request": request, "data": data}
    )



# ── Ask AI Endpoint ──────────────────────────────────────────────────────
@router.post("/api/ask-ai")
async def api_ask_ai(request: Request):
    """AI assistant with tool-calling access to CSL database."""
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "No question provided"}, status_code=400)
    context = body.get("context", {})
    session_id = body.get("session_id")
    result = await ai_assistant.ask_ai(question, context, session_id=session_id)
    return JSONResponse(result)


# ── Knowledge Base CRUD ─────────────────────────────────────────────────
@router.get("/api/knowledge")
async def api_knowledge_list(
    category: str = None,
    scope: str = None,
    q: str = None,
    limit: int = 50,
):
    """List / search knowledge base entries."""
    rows = db.kb_search(category=category, scope=scope, query=q, limit=limit)
    return JSONResponse({"entries": rows, "count": len(rows)})


@router.post("/api/knowledge")
async def api_knowledge_create(request: Request):
    """Create a new knowledge base entry."""
    body = await request.json()
    category = (body.get("category") or "").strip()
    content = (body.get("content") or "").strip()
    if not category or not content:
        return JSONResponse({"error": "category and content are required"}, status_code=400)
    scope = (body.get("scope") or "").strip() or None
    source = (body.get("source") or "admin_entry").strip()
    row = db.kb_insert(category=category, content=content, scope=scope, source=source)
    return JSONResponse({"entry": row})


@router.patch("/api/knowledge/{entry_id}")
async def api_knowledge_update(entry_id: int, request: Request):
    """Update a knowledge base entry."""
    body = await request.json()
    row = db.kb_update(entry_id, **body)
    if not row:
        return JSONResponse({"error": "Not found or no valid fields"}, status_code=404)
    return JSONResponse({"entry": row})


@router.delete("/api/knowledge/{entry_id}")
async def api_knowledge_delete(entry_id: int):
    """Soft-delete a knowledge base entry."""
    ok = db.kb_delete(entry_id)
    if not ok:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse({"ok": True})


@router.post("/api/knowledge/bulk-import")
async def api_knowledge_bulk_import(request: Request):
    """
    Parse a Claude memory dump (raw text) and import as knowledge base entries.
    Accepts { "text": "..." } — each line or paragraph becomes an entry.
    Uses Claude to classify each entry into category + scope.
    """
    body = await request.json()
    raw_text = (body.get("text") or "").strip()
    if not raw_text:
        return JSONResponse({"error": "text field is required"}, status_code=400)

    # Split into individual memory entries
    # Claude memory typically uses line breaks or bullet points
    entries_raw = []
    for line in raw_text.split("\n"):
        line = line.strip().lstrip("•-*→ ")
        if len(line) > 10:  # skip empty/trivial lines
            entries_raw.append(line)

    if not entries_raw:
        return JSONResponse({"error": "No entries found in text"}, status_code=400)

    # Use Claude to classify each entry
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        # Fallback: import as unclassified
        created = []
        for entry_text in entries_raw:
            row = db.kb_insert(
                category="preference",
                content=entry_text,
                scope=None,
                source="memory_import",
            )
            created.append(row)
        return JSONResponse({"imported": len(created), "entries": created})

    # Batch classify with Claude
    classify_prompt = """Classify each knowledge entry below into category and scope.

Categories: account_rule, carrier_note, lane_tip, rate_rule, sop, preference
Scope: the account name, carrier name, or lane this applies to (null if global)

Return ONLY valid JSON array (no markdown):
[{"category": "...", "scope": "..." or null, "content": "original text"}]

Entries:
"""
    for i, entry_text in enumerate(entries_raw[:100], 1):  # cap at 100
        classify_prompt += f"{i}. {entry_text}\n"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": classify_prompt}],
        )
        response_text = response.content[0].text.strip()
        # Parse JSON from response
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if json_match:
            classified = json.loads(json_match.group())
        else:
            classified = json.loads(response_text)
    except Exception as e:
        log.warning("Claude classification failed: %s — importing as unclassified", e)
        classified = [{"category": "preference", "scope": None, "content": t} for t in entries_raw]

    created = []
    for entry in classified:
        try:
            row = db.kb_insert(
                category=entry.get("category", "preference"),
                content=entry.get("content", ""),
                scope=entry.get("scope"),
                source="memory_import",
            )
            created.append(row)
        except Exception as e:
            log.warning("Failed to import KB entry: %s", e)

    return JSONResponse({
        "imported": len(created),
        "total_parsed": len(entries_raw),
        "entries": created,
    })


@router.post("/api/ask-ai/upload")
async def api_ask_ai_upload(
    file: UploadFile = File(...),
    question: str = Form(""),
):
    """Ask AI with a file attachment (PDF, image, Excel, CSV)."""
    import base64

    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        return JSONResponse({"error": "File too large (max 20 MB)"}, status_code=400)

    fname = (file.filename or "").lower()
    content_type = file.content_type or ""
    extracted_text = None
    image_b64 = None

    # ── PDF extraction ──
    if fname.endswith(".pdf") or "pdf" in content_type:
        try:
            import pdfplumber, io
            text_parts = []
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                for page in pdf.pages[:50]:  # cap at 50 pages
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
                    # Also extract tables as text
                    for tbl in (page.extract_tables() or []):
                        rows = [" | ".join(str(c or "") for c in row) for row in tbl]
                        text_parts.append("\n".join(rows))
            extracted_text = "\n\n".join(text_parts)
            if not extracted_text.strip():
                # Scanned PDF — fall back to vision
                image_b64 = base64.b64encode(raw).decode()
        except Exception as e:
            log.warning("pdfplumber failed for %s: %s — falling back to vision", fname, e)
            image_b64 = base64.b64encode(raw).decode()

    # ── Image extraction (use Claude vision) ──
    elif any(fname.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
        image_b64 = base64.b64encode(raw).decode()

    # ── Excel / CSV extraction ──
    elif any(fname.endswith(ext) for ext in (".xlsx", ".xls", ".csv", ".tsv")):
        try:
            import io
            if fname.endswith(".csv") or fname.endswith(".tsv"):
                sep = "\t" if fname.endswith(".tsv") else ","
                lines = raw.decode("utf-8", errors="replace").splitlines()
                extracted_text = "\n".join(lines[:500])
            else:
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
                    parts = []
                    for ws in wb.worksheets[:5]:
                        rows = []
                        for row in ws.iter_rows(max_row=200, values_only=True):
                            rows.append(" | ".join(str(c or "") for c in row))
                        if rows:
                            parts.append(f"Sheet: {ws.title}\n" + "\n".join(rows))
                    extracted_text = "\n\n".join(parts)
                    wb.close()
                except Exception:
                    import xlrd
                    wb = xlrd.open_workbook(file_contents=raw)
                    parts = []
                    for ws in wb.sheets()[:5]:
                        rows = []
                        for r in range(min(ws.nrows, 200)):
                            rows.append(" | ".join(str(ws.cell_value(r, c) or "") for c in range(ws.ncols)))
                        if rows:
                            parts.append(f"Sheet: {ws.name}\n" + "\n".join(rows))
                    extracted_text = "\n\n".join(parts)
        except Exception as e:
            log.warning("Spreadsheet parse failed for %s: %s", fname, e)
            extracted_text = f"[Could not parse spreadsheet: {e}]"

    # ── Email (.msg / .eml) ──
    elif fname.endswith(".eml"):
        try:
            import email as _email
            msg = _email.message_from_bytes(raw)
            subj = msg.get("Subject", "")
            frm = msg.get("From", "")
            body_parts = []
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body_parts.append(part.get_payload(decode=True).decode("utf-8", errors="replace"))
            extracted_text = f"Subject: {subj}\nFrom: {frm}\n\n" + "\n".join(body_parts)
        except Exception as e:
            extracted_text = f"[Could not parse .eml: {e}]"
    else:
        # Try as plain text
        try:
            extracted_text = raw.decode("utf-8", errors="replace")[:20000]
        except Exception:
            return JSONResponse({"error": f"Unsupported file type: {fname}"}, status_code=400)

    # ── Build the AI question ──
    user_q = question.strip() if question else ""
    if not user_q:
        user_q = "Read this document and extract all load/shipment details. Present them in a table with columns: EFJ, Account, Move Type, Carrier, Origin, Destination, Container/Load#, Rate. If there are multiple loads, list them all."

    if image_b64:
        # Use Claude vision — pass image directly
        result = await ai_assistant.ask_ai_with_image(user_q, image_b64, fname)
    elif extracted_text:
        full_q = f"{user_q}\n\n--- Document: {file.filename} ---\n{extracted_text[:30000]}"
        result = await ai_assistant.ask_ai(full_q)
    else:
        return JSONResponse({"error": "Could not extract content from file"}, status_code=400)

    return JSONResponse(result)
