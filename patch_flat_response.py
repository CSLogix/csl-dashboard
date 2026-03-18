#!/usr/bin/env python3
"""
Patch: Update JsonCargo response parsing to use flat format as primary path.

The API no longer returns events[]/moves[] arrays — all responses are flat with
container_status, eta_final_destination, etc. as top-level fields in data{}.

Changes:
1. csl_bot.py: Rewrite _jsoncargo_container_track() to parse flat response first
2. export_monitor.py: Rewrite jsoncargo_container_track() to detect gate-in from flat status
"""
import shutil
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════
# Patch csl_bot.py
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Patching csl_bot.py ===")

with open("/root/csl-bot/csl_bot.py", "r") as f:
    content = f.read()
backup = "/root/csl-bot/csl_bot.py.pre-flat-" + datetime.now().strftime("%Y%m%d")
shutil.copy2("/root/csl-bot/csl_bot.py", backup)
print(f"  Backup: {backup}")

# Replace the JsonCargo response parsing block (after the API call, error check)
OLD_PARSE = '''        events = []
        raw = (data.get("data", {}).get("events", [])
               or data.get("data", {}).get("moves", []) or [])
        for ev in raw:
            desc = (ev.get("description") or ev.get("move")
                    or ev.get("status") or "").lower()
            if desc:
                events.append(desc)

        # Flat response fallback (e.g. Evergreen) -- no events array,
        # status + dates are top-level fields in data
        d = data.get("data", {})
        flat_status = (d.get("container_status") or "").lower()
        if not events and flat_status:
            events.append(flat_status)
            print(f"    JsonCargo: flat response -- container_status=\\"{flat_status}\\"")
        else:
            print(f"    JsonCargo: {len(events)} events found")

        all_text = " ".join(events)
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

        eta = pickup = ret = None
        for ev in raw:
            desc = (ev.get("description") or ev.get("move")
                    or ev.get("status") or "").lower()
            d = (ev.get("date") or ev.get("actual_date")
                 or ev.get("estimated_date") or "")
            if not d:
                continue
            if not eta and any(k in desc for k in [
                "vessel eta", "estimated arrival", "expected", "arrival"]):
                eta = d
            if not pickup and any(k in desc for k in [
                "gate out", "full out", "pick-up", "available"]):
                pickup = d
            if not ret and any(k in desc for k in [
                "empty container return", "empty return", "empty in", "gate in empty"]):
                ret = d

        # Flat response date fallback (e.g. Evergreen, some Maersk)
        if not raw and d:
            ts = d.get("timestamp_of_last_location") or d.get("last_movement_timestamp") or ""
            if not eta:
                eta = d.get("eta_final_destination") or d.get("eta_next_destination") or None
            if not pickup and ts:
                if flat_status and any(k in flat_status for k in [
                    "gate out", "full out", "pick-up", "discharged", "discharge",
                    "unloaded from vessel", "container to consignee"]):
                    pickup = ts
            if not ret and ts:
                if flat_status and any(k in flat_status for k in [
                    "empty container return", "empty return", "empty in"]):
                    ret = ts'''

NEW_PARSE = '''        # -- Parse flat response (API returns top-level fields, no events array) --
        d = data.get("data", {})
        flat_status = (d.get("container_status") or "").lower()
        print(f"    JsonCargo: container_status=\\"{flat_status}\\"")

        # Status extraction from container_status field
        status = None
        for kw in ["empty container returned", "empty container return",
                    "empty return", "empty in", "gate in empty",
                    "empty received"]:
            if kw in flat_status:
                status = "Returned to Port"; break
        if not status:
            for kw in ["gate out", "full out", "out gate",
                        "pick-up by merchant haulage"]:
                if kw in flat_status:
                    status = "Released"; break
        if not status and ("discharged" in flat_status or "discharge" in flat_status
                           or "unloaded from vessel" in flat_status):
            status = "Discharged"
        if not status:
            for kw in ["container to consignee", "pick up by consignee",
                        "delivery to consignee"]:
                if kw in flat_status:
                    status = "Released"; break
        if not status:
            for kw in ["vessel departure", "vessel sailed", "departed by vessel",
                        "departed from"]:
                if kw in flat_status:
                    status = "Vessel"; break
        if not status:
            for kw in ["vessel arrived", "actual arrival", "arrival in",
                        "arrived at port"]:
                if kw in flat_status:
                    status = "Vessel Arrived"; break
        if not status:
            for kw in ["rail", "on rail", "ramp arrival", "intermodal"]:
                if kw in flat_status:
                    status = "Rail"; break
        if not status:
            for kw in ["vessel eta", "estimated arrival", "expected arrival"]:
                if kw in flat_status:
                    status = "Vessel"; break
        if not status and flat_status:
            # Catch-all: if we have a status string but no keyword match, log it
            print(f"    JsonCargo: unrecognized status \\"{flat_status}\\"")

        # Date extraction from flat fields
        eta = d.get("eta_final_destination") or d.get("eta_next_destination") or None
        ts = d.get("timestamp_of_last_location") or d.get("last_movement_timestamp") or ""

        pickup = None
        if ts and any(k in flat_status for k in [
            "gate out", "full out", "pick-up", "discharged", "discharge",
            "unloaded from vessel", "container to consignee",
            "import discharged"]):
            pickup = ts

        ret = None
        if ts and any(k in flat_status for k in [
            "empty container return", "empty return", "empty in",
            "empty received", "gate in empty"]):
            ret = ts'''

if OLD_PARSE in content:
    content = content.replace(OLD_PARSE, NEW_PARSE)
    print("  Patched: flat response as primary parsing path")
else:
    print("  WARNING: parsing block not found verbatim")

with open("/root/csl-bot/csl_bot.py", "w") as f:
    f.write(content)
print("  Written: /root/csl-bot/csl_bot.py")


# ═══════════════════════════════════════════════════════════════════════════
# Patch export_monitor.py
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== Patching export_monitor.py ===")

with open("/root/csl-bot/export_monitor.py", "r") as f:
    content = f.read()
backup = "/root/csl-bot/export_monitor.py.pre-flat-" + datetime.now().strftime("%Y%m%d")
shutil.copy2("/root/csl-bot/export_monitor.py", backup)
print(f"  Backup: {backup}")

OLD_TRACK = '''def jsoncargo_container_track(container_num, ssl_line):
    cached = _jc_cache_get(container_num)
    if cached is not None:
        print(f"    Container track: cache hit for {container_num}")
        return cached
    try:
        url=f"{JSONCARGO_BASE}/containers/{container_num}/"
        resp=requests.get(url,headers={"x-api-key":JSONCARGO_API_KEY},
                         params={"shipping_line":ssl_line},timeout=20)
        data=resp.json()
        if "error" in data:
            print(f"    Container track: {data[\'error\'].get(\'title\',\'error\')}")
            return None
        events=[]
        raw_events=data.get("data",{}).get("events",[]) or data.get("data",{}).get("moves",[]) or []
        for ev in raw_events:
            desc=(ev.get("description") or ev.get("move") or ev.get("status") or "").lower()
            if desc: events.append(desc)
        print(f"    Container track: {len(events)} events found")
        gate_in=None
        all_text=" ".join(events)
        for status in GATE_IN_STATUSES:
            if status in all_text:
                gate_in=status.title(); break
        result = {"events":events,"gate_in":gate_in}
        _jc_cache_set(container_num, result)
        return result
    except Exception as e:
        print(f"    Container track error: {e}"); return None'''

NEW_TRACK = '''def jsoncargo_container_track(container_num, ssl_line):
    cached = _jc_cache_get(container_num)
    if cached is not None:
        print(f"    Container track: cache hit for {container_num}")
        return cached
    try:
        url=f"{JSONCARGO_BASE}/containers/{container_num}/"
        resp=requests.get(url,headers={"x-api-key":JSONCARGO_API_KEY},
                         params={"shipping_line":ssl_line},timeout=20)
        data=resp.json()
        if "error" in data:
            print(f"    Container track: {data[\'error\'].get(\'title\',\'error\')}")
            return None
        # Flat response: container_status is a top-level field (no events array)
        d = data.get("data", {})
        flat_status = (d.get("container_status") or "").lower()
        print(f"    Container track: status=\\"{flat_status}\\"")
        gate_in = None
        for kw in GATE_IN_STATUSES:
            if kw in flat_status:
                gate_in = kw.title(); break
        result = {"events": [flat_status] if flat_status else [], "gate_in": gate_in}
        _jc_cache_set(container_num, result)
        return result
    except Exception as e:
        print(f"    Container track error: {e}"); return None'''

if OLD_TRACK in content:
    content = content.replace(OLD_TRACK, NEW_TRACK)
    print("  Patched: container tracking uses flat response")
else:
    print("  WARNING: container track function not found verbatim")

with open("/root/csl-bot/export_monitor.py", "w") as f:
    f.write(content)
print("  Written: /root/csl-bot/export_monitor.py")

print("\n=== DONE ===")
