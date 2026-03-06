"""
Migrate csl-webhook (standalone Flask on port 5003) into the main FastAPI dashboard app.

Adds:
  - POST /macropoint-webhook  (Basic Auth, same behavior as webhook.py)
  - GET  /webhook-test         (health check)
  - STATUS_MAP + _update_tracking_cache_webhook() helper

Updates:
  - PUBLIC_PATHS: adds /macropoint-webhook and /webhook-test
  - BOT_SERVICES: removes csl-webhook entry (no longer a separate service)
"""

import re

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP_PY, "r") as f:
    src = f.read()

# ── 1. Add /macropoint-webhook and /webhook-test to PUBLIC_PATHS ─────────
old_public = 'PUBLIC_PATHS = {"/login", "/setup", "/health", "/logo.svg", "/app", "/assets", "/"}'
new_public = 'PUBLIC_PATHS = {"/login", "/setup", "/health", "/logo.svg", "/app", "/assets", "/", "/macropoint-webhook", "/webhook-test"}'
assert old_public in src, "PUBLIC_PATHS not found"
src = src.replace(old_public, new_public)
print("[1/3] PUBLIC_PATHS updated")

# ── 2. Remove csl-webhook from BOT_SERVICES ──────────────────────────────
old_webhook_line = '    {"unit": "csl-webhook", "name": "Webhook Server", "poll_min": 0},\n'
assert old_webhook_line in src, "csl-webhook BOT_SERVICES entry not found"
src = src.replace(old_webhook_line, '')
print("[2/3] csl-webhook removed from BOT_SERVICES")

# ── 3. Add webhook endpoints before "# ═══ End of v2 endpoints ═══" ──────
WEBHOOK_CODE = '''
# ═══ Macropoint Webhook (migrated from standalone webhook.py) ═══════════

import hmac as _hmac

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
    "CANT_MAKE_IT": "Can\\'t Make It",
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


def _update_tracking_cache_webhook(load_ref: str, status: str, now: str, payload: dict) -> bool:
    """Update ftl_tracking_cache.json when a webhook event arrives."""
    try:
        with open(TRACKING_CACHE_FILE, "r") as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return False

    efj_clean = load_ref.replace("EFJ", "").strip()
    matched_key = None
    for key, entry in cache.items():
        efj = entry.get("efj", "")
        load_num = entry.get("load_num", "")
        mp_load_id = entry.get("mp_load_id", "")
        if (efj == load_ref or efj == efj_clean or
                load_num == load_ref or mp_load_id == load_ref or
                key == efj_clean):
            matched_key = key
            break

    if not matched_key:
        return False

    entry = cache[matched_key]
    old_status = entry.get("status", "")
    entry["status"] = status
    entry["last_scraped"] = now
    entry["webhook_updated"] = True

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

    tmp_path = TRACKING_CACHE_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp_path, TRACKING_CACHE_FILE)

    log.info(f"Webhook cache updated: {matched_key} [{old_status}] -> [{status}]")
    return True


@app.get("/webhook-test")
async def webhook_health():
    now = datetime.now(tz=__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")
    return {"status": "ok", "service": "csl-webhook (integrated)", "time": now}


@app.post("/macropoint-webhook")
async def macropoint_webhook(request: Request):
    # Basic Auth check
    if not _webhook_basic_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": \'Basic realm="csl-bot"\'})

    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    now = datetime.now(tz=__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")

    # Raw payload log
    log_entry = f"\\n{\'=\' * 60}\\n[{now}]\\n{json.dumps(payload, indent=2)}\\n"
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
            f.write(json.dumps(event_record) + "\\n")
    except Exception:
        pass

    # Update tracking cache
    cache_updated = False
    if load_ref and mapped_status:
        cache_updated = _update_tracking_cache_webhook(load_ref, mapped_status, now, payload)

    if not load_ref:
        log.warning(f"Webhook: unknown payload format — keys: {list(payload.keys())}")
        return {"status": "ok", "processed": False, "reason": "unknown format"}

    log.info(f"Webhook processed: {load_ref} -> {mapped_status or \'(no status)\'} (cache_updated={cache_updated})")
    return {
        "status": "ok",
        "processed": True,
        "load_ref": load_ref,
        "mapped_status": mapped_status,
        "cache_updated": cache_updated,
    }


'''

marker = "# ═══ End of v2 endpoints ═══"
assert marker in src, f"Marker '{marker}' not found in app.py"
src = src.replace(marker, WEBHOOK_CODE + marker)
print("[3/3] Webhook endpoints added")

# ── Write ─────────────────────────────────────────────────────────────────
with open(APP_PY, "w") as f:
    f.write(src)

print("\nDone. Restart csl-dashboard to activate.")
