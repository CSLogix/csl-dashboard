#!/usr/bin/env python3
"""
Patch: Add processing logic to webhook.py

- Parse incoming Macropoint webhook payloads for load ID + status
- Update ftl_tracking_cache.json when a matching load is found
- Log structured events to webhook_events.log
- Add /webhook-test GET endpoint for health checking
- Keep raw payload logging as-is
"""

TARGET = "/root/csl-bot/webhook.py"

with open(TARGET, "r") as f:
    src = f.read()

# Full replacement — the file is only 51 lines, easier to rewrite cleanly
new_src = '''import hmac
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from flask import Flask, request, jsonify

load_dotenv()

app = Flask(__name__)

BASIC_AUTH_USERNAME = os.environ["WEBHOOK_AUTH_USERNAME"]
BASIC_AUTH_PASSWORD = os.environ["WEBHOOK_AUTH_PASSWORD"]
LOG_FILE = "/root/csl-bot/webhook_payloads.log"
EVENTS_LOG = "/root/csl-bot/webhook_events.log"
TRACKING_CACHE = "/root/csl-bot/ftl_tracking_cache.json"

# Macropoint status mapping — webhook event types to our internal statuses
STATUS_MAP = {
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


def _now():
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")


def auth_valid() -> bool:
    creds = request.authorization
    if not creds:
        return False
    user_ok = hmac.compare_digest(creds.username, BASIC_AUTH_USERNAME)
    pass_ok = hmac.compare_digest(creds.password, BASIC_AUTH_PASSWORD)
    return user_ok and pass_ok


@app.before_request
def check_auth():
    # Skip auth for health check
    if request.path == "/webhook-test" and request.method == "GET":
        return None
    if not auth_valid():
        return jsonify({"error": "Unauthorized"}), 401, {"WWW-Authenticate": \'Basic realm="csl-bot"\'}


# ── Health check ─────────────────────────────────────────────────────────
@app.route("/webhook-test", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "csl-webhook", "time": _now()}), 200


# ── Webhook receiver ────────────────────────────────────────────────────
@app.route("/macropoint-webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True) or {}
    now = _now()

    # 1. Raw payload log (always — for debugging)
    log_entry = f"\\n{\'=\'*60}\\n[{now}]\\n{json.dumps(payload, indent=2)}\\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(log_entry)
    except Exception:
        pass

    print(f"[{now}] Webhook received: {json.dumps(payload)[:200]}")

    # 2. Skip test payloads
    if payload.get("test"):
        print(f"[{now}] Test payload — skipping processing")
        return jsonify({"status": "ok", "processed": False, "reason": "test payload"}), 200

    # 3. Extract load identifier and status
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

    # 4. Map event to our internal status
    mapped_status = STATUS_MAP.get(event_type.upper().replace(" ", "_"), "")
    if not mapped_status and event_type:
        # Try direct match (Macropoint might send our format)
        mapped_status = event_type

    # 5. Log structured event
    event_record = {
        "time": now,
        "load_ref": load_ref,
        "raw_event": event_type,
        "mapped_status": mapped_status,
        "payload_keys": list(payload.keys()),
    }
    try:
        with open(EVENTS_LOG, "a") as f:
            f.write(json.dumps(event_record) + "\\n")
    except Exception:
        pass

    # 6. Try to update tracking cache if we have a load reference
    cache_updated = False
    if load_ref and mapped_status:
        cache_updated = _update_tracking_cache(load_ref, mapped_status, now, payload)

    if not load_ref:
        print(f"[{now}] Unknown payload format — keys: {list(payload.keys())}")
        return jsonify({"status": "ok", "processed": False, "reason": "unknown format"}), 200

    print(f"[{now}] Processed: {load_ref} -> {mapped_status or \'(no status)\'} "
          f"(cache_updated={cache_updated})")
    return jsonify({
        "status": "ok",
        "processed": True,
        "load_ref": load_ref,
        "mapped_status": mapped_status,
        "cache_updated": cache_updated,
    }), 200


def _update_tracking_cache(load_ref, status, now, payload):
    """Update ftl_tracking_cache.json if the load is found."""
    try:
        with open(TRACKING_CACHE, "r") as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return False

    # Search for matching load — by EFJ number or load number
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

    # Update cache entry
    entry = cache[matched_key]
    old_status = entry.get("status", "")
    entry["status"] = status
    entry["last_scraped"] = now
    entry["webhook_updated"] = True

    # Update stop times from payload if available
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

    # Atomic write
    tmp_path = TRACKING_CACHE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp_path, TRACKING_CACHE)

    print(f"  Cache updated: {matched_key} [{old_status}] -> [{status}]")
    return True


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003)
'''

with open(TARGET, "w") as f:
    f.write(new_src)

print(f"  Webhook processing logic written to {TARGET}")
print("  Done.")
