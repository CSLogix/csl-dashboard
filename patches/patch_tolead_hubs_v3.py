#!/usr/bin/env python3
"""
Patch: Update all Tolead hub configs in tolead_monitor.py
1. ORD: add col_phone, col_delivery, col_appt_id, col_loads
2. JFK: add col_phone, col_delivery, default_origin
3. LAX: fix 3 wrong cols (dest, status, trailer) + add origin, phone, delivery, default_origin
4. Generalize POD reminder from DFW-only to all hubs
5. Fix _send_email parameter order bug in POD function
"""

TARGET = "/root/csl-bot/tolead_monitor.py"

with open(TARGET, "r") as f:
    src = f.read()


# ── 1. Update ORD hub config ──────────────────────────────────────────────

old_ord = '''        "name": "ORD",
        "sheet_id": "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac",
        "tab": "Schedule",
        "col_load_id": 1, "col_date": 4, "col_time": 5,
        "col_origin": 6, "col_dest": 7, "col_status": 9,
        "col_efj": 15, "col_trailer": 16,
    },'''

new_ord = '''        "name": "ORD",
        "sheet_id": "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac",
        "tab": "Schedule",
        "col_load_id": 1, "col_date": 4, "col_time": 5,
        "col_origin": 6, "col_dest": 7, "col_status": 9,
        "col_efj": 15, "col_trailer": 16, "col_phone": 17,
        "col_delivery": 3, "col_appt_id": 2, "col_loads": 8,
    },'''

if old_ord in src:
    src = src.replace(old_ord, new_ord)
    print("  + Updated ORD hub config")
else:
    print("  ! Could not find ORD hub config")


# ── 2. Update JFK hub config ──────────────────────────────────────────────

old_jfk = '''        "name": "JFK",
        "sheet_id": "1mfhEsK2zg6GWTqMDTo5VwCgY-QC1tkNPknurHMxtBhs",
        "tab": "Schedule",
        "col_load_id": 0, "col_date": 3, "col_time": 4,
        "col_origin": 6, "col_dest": 7, "col_status": 9,
        "col_efj": 14, "col_trailer": 15,
    },'''

new_jfk = '''        "name": "JFK",
        "sheet_id": "1mfhEsK2zg6GWTqMDTo5VwCgY-QC1tkNPknurHMxtBhs",
        "tab": "Schedule",
        "col_load_id": 0, "col_date": 3, "col_time": 4,
        "col_origin": 6, "col_dest": 7, "col_status": 9,
        "col_efj": 14, "col_trailer": 15, "col_phone": 16,
        "col_delivery": 5,
        "default_origin": "Garden City, NY",
    },'''

if old_jfk in src:
    src = src.replace(old_jfk, new_jfk)
    print("  + Updated JFK hub config")
else:
    print("  ! Could not find JFK hub config")


# ── 3. Fix LAX hub config (3 wrong columns + add new) ─────────────────────

old_lax = '''        "name": "LAX",
        "sheet_id": "1YLB6z5LdL0kFYTcfq_H5e6acU8-VLf8nN0XfZrJ-bXo",
        "tab": "LAX",
        "col_load_id": 3, "col_date": 4, "col_time": 5,
        "col_origin": None, "col_dest": 6, "col_status": 8,
        "col_efj": 0, "col_trailer": 10,
    },'''

new_lax = '''        "name": "LAX",
        "sheet_id": "1YLB6z5LdL0kFYTcfq_H5e6acU8-VLf8nN0XfZrJ-bXo",
        "tab": "LAX",
        "col_load_id": 3, "col_date": 4, "col_time": 5,
        "col_origin": 6, "col_dest": 7, "col_status": 9,
        "col_efj": 0, "col_trailer": 11, "col_phone": 12,
        "col_delivery": 8,
        "default_origin": "Vernon, CA",
    },'''

if old_lax in src:
    src = src.replace(old_lax, new_lax)
    print("  + Fixed LAX hub config (dest:6->7, status:8->9, trailer:10->11, +origin/phone/delivery)")
else:
    print("  ! Could not find LAX hub config")


# ── 4. Generalize POD reminder function ───────────────────────────────────
# Rename _send_dfw_pod_reminder → _send_pod_reminder, make hub-generic, fix email param order

old_pod_fn = '''def _send_dfw_pod_reminder(load_id, dest, driver_phone, efj=""):
    """Send POD reminder for DFW loads when Macropoint marks Delivered before Col L."""
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    ref = f"DFW--{load_id}"

    subject = f"POD Needed \\u2014 {ref}({dest}) Has Delivered"

    phone_display = driver_phone if driver_phone else "(not on file)"

    body = f"""<html><body style="font-family:Arial,sans-serif;">
<div style="background:#c62828;color:white;padding:12px 16px;border-radius:6px 6px 0 0;">
  <b>POD Reminder \\u2014 {ref}</b>
</div>
<div style="padding:16px;border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;">
  <p style="font-size:15px;margin:0 0 12px;">
    <b>{ref}({dest})</b> has been marked <b style="color:#c62828;">Delivered</b> by Macropoint tracking.
  </p>
  <p style="font-size:15px;margin:0 0 12px;">
    Please contact the driver to obtain the POD as soon as possible.
  </p>
  <table style="border-collapse:collapse;margin:12px 0;">
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Load #</td><td style="padding:4px 0;"><b>{load_id}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">EFJ #</td><td style="padding:4px 0;"><b>{efj}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Destination</td><td style="padding:4px 0;">{dest}</td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Driver Phone</td><td style="padding:4px 0;"><b>{phone_display}</b></td></tr>
  </table>
  <p style="font-size:12px;color:#888;margin:16px 0 0;">
    Once POD is received and confirmed, mark Column L as "Delivered" to close this load.<br>
    Sent at {now}
  </p>
</div>
</body></html>"""

    try:
        _send_email(subject, body, "tolead-efj@evansdelivery.com")
        print(f"    POD reminder sent for {ref}({dest})")
    except Exception as exc:
        print(f"    WARNING: POD reminder email failed: {exc}")'''

new_pod_fn = '''def _send_pod_reminder(hub_name, load_id, dest, driver_phone, efj=""):
    """Send POD reminder when Macropoint marks Delivered before manual close."""
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    ref = f"{hub_name}--{load_id}"

    subject = f"POD Needed \\u2014 {ref}({dest}) Has Delivered"

    phone_display = driver_phone if driver_phone else "(not on file)"

    body = f"""<html><body style="font-family:Arial,sans-serif;">
<div style="background:#c62828;color:white;padding:12px 16px;border-radius:6px 6px 0 0;">
  <b>POD Reminder \\u2014 {ref}</b>
</div>
<div style="padding:16px;border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;">
  <p style="font-size:15px;margin:0 0 12px;">
    <b>{ref}({dest})</b> has been marked <b style="color:#c62828;">Delivered</b> by Macropoint tracking.
  </p>
  <p style="font-size:15px;margin:0 0 12px;">
    Please contact the driver to obtain the POD as soon as possible.
  </p>
  <table style="border-collapse:collapse;margin:12px 0;">
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Hub</td><td style="padding:4px 0;"><b>{hub_name}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Load #</td><td style="padding:4px 0;"><b>{load_id}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">EFJ #</td><td style="padding:4px 0;"><b>{efj}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Destination</td><td style="padding:4px 0;">{dest}</td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Driver Phone</td><td style="padding:4px 0;"><b>{phone_display}</b></td></tr>
  </table>
  <p style="font-size:12px;color:#888;margin:16px 0 0;">
    Once POD is received, mark the Status column as "Delivered" to close this load.<br>
    Sent at {now}
  </p>
</div>
</body></html>"""

    try:
        _send_email("tolead-efj@evansdelivery.com", subject, body)
        print(f"    POD reminder sent for {ref}({dest})")
    except Exception as exc:
        print(f"    WARNING: POD reminder email failed: {exc}")'''

if old_pod_fn in src:
    src = src.replace(old_pod_fn, new_pod_fn)
    print("  + Generalized POD reminder (all hubs) + fixed _send_email param order")
else:
    print("  ! Could not find _send_dfw_pod_reminder function")


# ── 5. Generalize POD trigger in processing loop ─────────────────────────

old_trigger = '''            # DFW: if Macropoint says Delivered but Col L is still empty \u2192 POD reminder
            if (name == "DFW"
                    and ("delivered" in mp_status.lower() or "tracking completed" in mp_status.lower())
                    and not sheet_status_L):
                _send_dfw_pod_reminder(load_id, dest, driver_phone, efj)'''

new_trigger = '''            # All hubs: if Macropoint says Delivered but status not yet Delivered \u2192 POD reminder
            if (("delivered" in mp_status.lower() or "tracking completed" in mp_status.lower())
                    and sheet_status_L.lower() != "delivered"):
                _send_pod_reminder(name, load_id, dest, driver_phone, efj)'''

if old_trigger in src:
    src = src.replace(old_trigger, new_trigger)
    print("  + Generalized POD trigger for all hubs")
else:
    print("  ! Could not find POD trigger block")


with open(TARGET, "w") as f:
    f.write(src)

print(f"\n  Patched: {TARGET}")
print("  Done.")
