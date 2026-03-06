#!/usr/bin/env python3
"""
Patch: boviet_monitor.py — Fix Piedra columns + add phone/trailer + POD reminder

1. Fix Piedra: pickup_col 5->6, delivery_col 6->7, status_col 7->8
2. Add phone_col/trailer_col to Piedra and Hanson
3. Add _send_pod_reminder() function
4. Trigger POD reminder on Delivered status
"""

TARGET = "/root/csl-bot/boviet_monitor.py"

with open(TARGET, "r") as f:
    src = f.read()


# ── 1. Fix Piedra config + add phone/trailer ──────────────────────────────

old_piedra = '''    "Piedra": {
        "efj_col":       0,
        "load_id_col":   2,   # C \u2014 Load ID is col C for Piedra
        "pickup_col":    5,   # F
        "delivery_col":  6,   # G
        "status_col":    7,   # H
    },'''

new_piedra = '''    "Piedra": {
        "efj_col":       0,
        "load_id_col":   2,   # C \u2014 Load ID is col C for Piedra
        "pickup_col":    6,   # G \u2014 Pickup Date/Time
        "delivery_col":  7,   # H \u2014 Delivery Date/Time
        "status_col":    8,   # I \u2014 Status
        "phone_col":    11,   # L \u2014 Driver Phone#
        "trailer_col":  12,   # M \u2014 Trailer#
    },'''

if old_piedra in src:
    src = src.replace(old_piedra, new_piedra)
    print("  + Fixed Piedra config (pickup:5->6, delivery:6->7, status:7->8, +phone/trailer)")
else:
    print("  ! Could not find Piedra config")


# ── 2. Add phone/trailer to Hanson config ─────────────────────────────────

old_hanson = '''    "Hanson": {
        "efj_col":       0,
        "load_id_col":   1,   # B
        "pickup_col":    4,   # E
        "delivery_col":  5,   # F
        "status_col":    6,   # G
    },'''

new_hanson = '''    "Hanson": {
        "efj_col":       0,
        "load_id_col":   1,   # B
        "pickup_col":    4,   # E
        "delivery_col":  5,   # F
        "status_col":    6,   # G
        "phone_col":     8,   # I \u2014 Driver Phone#
        "trailer_col":  10,   # K \u2014 Trailer#
    },'''

if old_hanson in src:
    src = src.replace(old_hanson, new_hanson)
    print("  + Updated Hanson config (+phone/trailer)")
else:
    print("  ! Could not find Hanson config")


# ── 3. Add _send_pod_reminder() function ──────────────────────────────────

pod_fn = '''
def _send_pod_reminder(tab_name, efj, load_id, dest, driver_phone):
    """Send POD reminder when Macropoint marks Delivered."""
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    ref = f"Boviet/{tab_name}--{load_id}"
    subject = f"POD Needed \\u2014 {ref} Has Delivered"

    phone_display = driver_phone if driver_phone else "(not on file)"

    body = f"""<html><body style="font-family:Arial,sans-serif;">
<div style="background:#c62828;color:white;padding:12px 16px;border-radius:6px 6px 0 0;">
  <b>POD Reminder \\u2014 {ref}</b>
</div>
<div style="padding:16px;border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;">
  <p style="font-size:15px;margin:0 0 12px;">
    <b>{ref}</b> has been marked <b style="color:#c62828;">Delivered</b> by Macropoint tracking.
  </p>
  <p style="font-size:15px;margin:0 0 12px;">
    Please contact the driver to obtain the POD as soon as possible.
  </p>
  <table style="border-collapse:collapse;margin:12px 0;">
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Account</td><td style="padding:4px 0;"><b>{tab_name}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">EFJ #</td><td style="padding:4px 0;"><b>{efj}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Load #</td><td style="padding:4px 0;"><b>{load_id}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Destination</td><td style="padding:4px 0;">{dest}</td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Driver Phone</td><td style="padding:4px 0;"><b>{phone_display}</b></td></tr>
  </table>
  <p style="font-size:12px;color:#888;margin:16px 0 0;">
    Once POD is received, update the Status column accordingly.<br>
    Sent at {now}
  </p>
</div>
</body></html>"""

    try:
        _send_email(ALERT_EMAIL, subject, body)
        print(f"      POD reminder sent for {ref}")
    except Exception as exc:
        print(f"      WARNING: POD reminder email failed: {exc}")


'''

if "def _send_pod_reminder" not in src:
    anchor = "def send_boviet_alert("
    if anchor in src:
        src = src.replace(anchor, pod_fn + anchor)
        print("  + Added _send_pod_reminder() function")
    else:
        print("  ! Could not find send_boviet_alert anchor")
else:
    print("  ~ _send_pod_reminder() already exists")


# ── 4. Extract driver phone in processing loop + trigger POD reminder ─────

old_process = '''                for item in to_process:
                    alert_key = f"{tab_name}|{item[\'efj\']}|{item[\'load_id\']}"
                    print(f"\\n    [{item[\'sheet_row\']}] {item[\'efj\']} / {item[\'load_id\']}")
                    print(f"      Scraping: {item[\'mp_url\'][:60]}...")'''

new_process = '''                for item in to_process:
                    alert_key = f"{tab_name}|{item[\'efj\']}|{item[\'load_id\']}"
                    driver_phone = item.get("phone", "")
                    dest = item.get("dest", "")
                    print(f"\\n    [{item[\'sheet_row\']}] {item[\'efj\']} / {item[\'load_id\']}")
                    print(f"      Scraping: {item[\'mp_url\'][:60]}...")'''

if old_process in src:
    src = src.replace(old_process, new_process)
    print("  + Added driver_phone/dest extraction in processing loop")
else:
    print("  ! Could not find processing loop header")


# ── 5. Add POD trigger after alert send ───────────────────────────────────

old_alert_send = '''                    if is_critical or is_behind or has_new_stop:
                        send_boviet_alert(
                            item["efj"], item["load_id"], mp_status, tab_name,
                            pickup=item["pickup"], delivery=item["delivery"],
                            mp_load_id=mp_load_id, stop_times=stop_times,
                        )
                        total_alerts += 1
                    else:'''

new_alert_send = '''                    if is_critical or is_behind or has_new_stop:
                        send_boviet_alert(
                            item["efj"], item["load_id"], mp_status, tab_name,
                            pickup=item["pickup"], delivery=item["delivery"],
                            mp_load_id=mp_load_id, stop_times=stop_times,
                        )
                        total_alerts += 1

                        # POD reminder when Macropoint marks Delivered
                        if ("delivered" in mp_status.lower()
                                or "tracking completed" in mp_status.lower()):
                            _send_pod_reminder(tab_name, item["efj"], item["load_id"],
                                               dest, driver_phone)
                    else:'''

if old_alert_send in src:
    src = src.replace(old_alert_send, new_alert_send)
    print("  + Added POD reminder trigger after Boviet alert")
else:
    print("  ! Could not find Boviet alert send block")


# ── 6. Add phone/dest to to_process items ─────────────────────────────────
# Need to extract phone + dest when building to_process list

old_to_process_append = '''                    to_process.append({
                        "sheet_row": i,
                        "efj": efj,
                        "load_id": load_id,
                        "mp_url": mp_url,
                        "pickup": pickup,
                        "delivery": delivery,
                    })'''

new_to_process_append = '''                    phone = _safe_get(row, cfg.get("phone_col", -1)) if cfg.get("phone_col") is not None else ""
                    dest = _safe_get(row, cfg.get("delivery_col", -1)) if cfg.get("delivery_col") is not None else ""
                    to_process.append({
                        "sheet_row": i,
                        "efj": efj,
                        "load_id": load_id,
                        "mp_url": mp_url,
                        "pickup": pickup,
                        "delivery": delivery,
                        "phone": phone,
                        "dest": dest,
                    })'''

if old_to_process_append in src:
    src = src.replace(old_to_process_append, new_to_process_append)
    print("  + Added phone/dest to to_process items")
else:
    print("  ! Could not find to_process append block — checking alternative format")
    # Try without the exact whitespace
    if "to_process.append({" in src and '"phone"' not in src.split("to_process.append({")[1][:200]:
        print("    Found to_process.append but format differs — needs manual patch")


with open(TARGET, "w") as f:
    f.write(src)

print(f"\n  Patched: {TARGET}")
print("  Done. Restart csl-boviet.")
