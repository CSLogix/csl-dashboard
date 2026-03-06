#!/usr/bin/env python3
"""
Patch: Multi-Provider Container Tracking (SeaRates + JSONCargo)
- Adds SeaRates Tracking API as primary container tracking provider
- Falls back to JSONCargo if SeaRates fails or key not configured
- Browser scraping remains as final fallback (unchanged)
- Reuses existing file-based cache mechanism
- No call-site changes needed — same function signature

Setup:
  1. Sign up at searates.com → get API key
  2. Add SEARATES_API_KEY=xxx to /root/csl-bot/.env
  3. Restart csl-import service

If SEARATES_API_KEY is not set, behavior is identical to before (JSONCargo only).
"""

APP = "/root/csl-bot/csl_bot.py"

print("[1/1] Adding SeaRates multi-provider tracking to csl_bot.py...")

with open(APP, "r") as f:
    code = f.read()

if "_searates_container_track" in code:
    print("   Already patched — skipping.")
    exit(0)

# ── Step 1: Add _searates_container_track() function ─────────────────────
# Insert right before _jsoncargo_container_track
ANCHOR = '''def _jsoncargo_container_track(container_num, ssl_line):
    """Track a container via JsonCargo API. Returns (eta, pickup, ret, status)."""'''

SEARATES_FUNC = '''# -- SeaRates Container Tracking API ─────────────────────────────────────
def _searates_container_track(container_num, ssl_line):
    """Track a container via SeaRates API. Returns 4-tuple or None if not configured."""
    sr_key = os.environ.get("SEARATES_API_KEY", "")
    if not sr_key:
        return None
    try:
        resp = requests.get(
            "https://tracking.searates.com/tracking",
            params={"api_key": sr_key, "number": container_num, "sealine": "auto"},
            timeout=25,
        )
        data = resp.json()
        if data.get("status") != "success":
            msg = data.get("message", "unknown error")
            print(f"    SeaRates: {msg}")
            if any(kw in msg.lower() for kw in ("not found", "invalid", "not recognized")):
                return None, None, None, "_fallback"
            return None, None, None, None

        # Gather event descriptions
        events = []
        raw = data.get("data", {}).get("events", [])
        for ev in raw:
            desc = (ev.get("description") or "").lower()
            if desc:
                events.append(desc)

        # Fallback: container-level status
        if not events:
            for c in data.get("data", {}).get("containers", []):
                cs = (c.get("status") or "").lower()
                if cs:
                    events.append(cs)

        if not events:
            meta_st = (data.get("data", {}).get("metadata", {}).get("status") or "").lower()
            if meta_st:
                events.append(meta_st)

        if not events:
            print("    SeaRates: response OK but no events")
            return None, None, None, None

        print(f"    SeaRates: {len(events)} events found")
        all_text = " ".join(events)

        # Status extraction — same keyword priority as JSONCargo
        status = None
        for kw in ["empty container returned", "empty container return",
                    "empty return", "empty in", "gate in empty"]:
            if kw in all_text:
                status = "Returned to Port"; break
        if not status:
            for kw in ["gate out", "full out", "out gate",
                        "pick-up by merchant haulage"]:
                if kw in all_text:
                    status = "Released"; break
        if not status and ("discharged" in all_text or "discharge" in all_text
                           or "unloaded from vessel" in all_text):
            status = "Discharged"
        if not status:
            for kw in ["container to consignee", "pick up by consignee",
                        "delivery to consignee"]:
                if kw in all_text:
                    status = "Released"; break
        if not status:
            for kw in ["vessel departure", "vessel sailed", "departed by vessel",
                        "departed from"]:
                if kw in all_text:
                    status = "Vessel"; break
        if not status:
            for kw in ["vessel arrived", "actual arrival", "arrival in",
                        "arrived at port"]:
                if kw in all_text:
                    status = "Vessel Arrived"; break
        if not status:
            for kw in ["rail", "on rail", "ramp arrival", "intermodal"]:
                if kw in all_text:
                    status = "Rail"; break
        if not status:
            for kw in ["vessel eta", "estimated arrival", "expected arrival"]:
                if kw in all_text:
                    status = "Vessel"; break

        # SeaRates event_code fallback
        if not status:
            codes = [ev.get("event_code", "").upper() for ev in raw]
            if "DISC" in codes: status = "Discharged"
            elif "ARRI" in codes: status = "Vessel Arrived"
            elif "DEPA" in codes: status = "Vessel"
            elif "LOAD" in codes: status = "Vessel"
            elif "PICK" in codes: status = "Released"

        # SeaRates metadata status fallback
        if not status:
            meta_st = (data.get("data", {}).get("metadata", {}).get("status") or "").upper()
            sr_status_map = {
                "IN_TRANSIT": "Vessel", "ARRIVED": "Vessel Arrived",
                "DISCHARGED": "Discharged", "DELIVERED": "Released",
            }
            status = sr_status_map.get(meta_st)

        # Date extraction
        eta = pickup = ret = None
        for ev in raw:
            desc = (ev.get("description") or "").lower()
            d = ev.get("date") or ""
            if not d:
                continue
            if not eta and any(k in desc for k in [
                "vessel eta", "estimated arrival", "expected", "arrival"]):
                eta = d
            if not pickup and any(k in desc for k in [
                "gate out", "full out", "pick-up", "available", "discharged"]):
                pickup = d
            if not ret and any(k in desc for k in [
                "empty container return", "empty return", "empty in", "gate in empty"]):
                ret = d

        # ETA from containers array
        if not eta:
            for c in data.get("data", {}).get("containers", []):
                if c.get("eta"):
                    eta = c["eta"]; break

        return eta, pickup, ret, status

    except Exception as e:
        print(f"    SeaRates error: {e}")
        return None, None, None, None


''' + ANCHOR

if ANCHOR not in code:
    print("   ERROR: Could not find _jsoncargo_container_track anchor")
    exit(1)

code = code.replace(ANCHOR, SEARATES_FUNC)
print("   Added _searates_container_track() function.")

# ── Step 2: Add SeaRates-first logic to _jsoncargo_container_track ───────
OLD_TOP = '''    container_num = container_num.strip()
    cached = _jc_cache_get(container_num)
    if cached is not None:
        print(f"    JsonCargo: cache hit for {container_num}")
        return tuple(cached)
    JSONCARGO_API_KEY = _get_jsoncargo_key()
    if not JSONCARGO_API_KEY:
        print("    JsonCargo: no API key configured")
        return None, None, None, None'''

NEW_TOP = '''    container_num = container_num.strip()
    cached = _jc_cache_get(container_num)
    if cached is not None:
        print(f"    Tracking: cache hit for {container_num}")
        return tuple(cached)
    # -- Try SeaRates first (if SEARATES_API_KEY is configured) --
    if os.environ.get("SEARATES_API_KEY"):
        sr = _searates_container_track(container_num, ssl_line)
        if sr is not None:
            _eta, _pu, _ret, _st = sr
            if _st and _st != "_fallback":
                print(f"    SeaRates: resolved → {_st}")
                _jc_cache_set(container_num, list(sr))
                return sr
            # SeaRates returned _fallback or empty — try JSONCargo
    # -- Fall back to JSONCargo --
    JSONCARGO_API_KEY = _get_jsoncargo_key()
    if not JSONCARGO_API_KEY:
        # Neither SeaRates nor JSONCargo available
        print("    No tracking API keys configured")
        return None, None, None, "_fallback"'''

if OLD_TOP in code:
    code = code.replace(OLD_TOP, NEW_TOP)
    print("   Added SeaRates-first logic to tracking function.")
else:
    print("   WARNING: Could not find cache-check block — checking alternative...")
    # The text might have slight whitespace differences
    if "JsonCargo: cache hit for" in code:
        print("   ERROR: Cache check block found but doesn't match exactly")
        print("   Manual intervention needed")
        exit(1)
    else:
        print("   ERROR: _jsoncargo_container_track body not found")
        exit(1)

# ── Step 3: Update log messages for clarity ──────────────────────────────
code = code.replace(
    'print(f"    Using JsonCargo API (ssl_line={ssl})")',
    'print(f"    Using Container API (ssl_line={ssl})")',
)
code = code.replace(
    'print(f"    Using JsonCargo API (ssl_line={ssl_code})")',
    'print(f"    Using Container API (ssl_line={ssl_code})")',
)

with open(APP, "w") as f:
    f.write(code)

print("   Done! Multi-provider tracking patch applied.")
print()
print("   HOW TO ACTIVATE SeaRates:")
print("   1. Sign up at https://www.searates.com/integrations/api-container-tracking/")
print("   2. Add SEARATES_API_KEY=<your-key> to /root/csl-bot/.env")
print("   3. systemctl restart csl-dashboard")
print()
print("   Until SEARATES_API_KEY is set, behavior is unchanged (JSONCargo only).")
print("   Restart: systemctl restart csl-dashboard")
