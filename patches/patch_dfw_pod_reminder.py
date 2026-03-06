#!/usr/bin/env python3
"""
Patch: DFW Delivered → POD reminder email

When Macropoint marks a DFW load as Delivered but Col L is still empty,
send tolead-efj@evansdelivery.com:
  "DFW--{LINE#}({Destination}) Has Delivered, contact driver for POD"
  Include driver phone# from Col N.
"""

MONITOR = "/root/csl-bot/tolead_monitor.py"

with open(MONITOR, "r") as f:
    src = f.read()

# ── 1. Extract driver phone + trailer + sheet status (Col L) in processing loop ──

old_extract = '''    for sheet_row, row, mp_url in to_process:
        load_id     = _col(row, hub["col_load_id"])
        efj         = _col(row, col_efj)
        dest        = _col(row, hub["col_dest"])
        pickup_date = _col(row, hub["col_date"])
        alert_key   = f"{load_id}|{efj}"'''

new_extract = '''    for sheet_row, row, mp_url in to_process:
        load_id     = _col(row, hub["col_load_id"])
        efj         = _col(row, col_efj)
        dest        = _col(row, hub["col_dest"])
        pickup_date = _col(row, hub["col_date"])
        driver_phone = _col(row, hub.get("col_phone", -1))
        driver_trailer = _col(row, hub.get("col_trailer", -1))
        sheet_status_L = _col(row, col_status)  # Col L — manual delivered flag
        alert_key   = f"{load_id}|{efj}"'''

if old_extract in src:
    src = src.replace(old_extract, new_extract)
    print("  + Added driver_phone, driver_trailer, sheet_status_L extraction")
else:
    print("  ! Could not find row extraction block — check manually")


# ── 2. Add DFW POD reminder after the existing delivered alert ──
# Insert right after the main alert send + state update block

old_alert_block = '''        if is_critical or is_behind or has_new_stop:
            send_tolead_alert(name, load_id, efj, mp_status, dest, pickup_date, mp_load_id, stop_times=stop_times)
            changes += 1
        else:
            print("    On time, no new events — no alert needed")

        # Always update tracked state
        update_state(sent, alert_key, mp_status, current_events)'''

new_alert_block = '''        if is_critical or is_behind or has_new_stop:
            send_tolead_alert(name, load_id, efj, mp_status, dest, pickup_date, mp_load_id, stop_times=stop_times)
            changes += 1

            # DFW: if Macropoint says Delivered but Col L is still empty → POD reminder
            if (name == "DFW" and mp_status == "Delivered"
                    and not sheet_status_L):
                _send_dfw_pod_reminder(load_id, dest, driver_phone, efj)
        else:
            print("    On time, no new events — no alert needed")

        # Always update tracked state
        update_state(sent, alert_key, mp_status, current_events)'''

if old_alert_block in src:
    src = src.replace(old_alert_block, new_alert_block)
    print("  + Added DFW POD reminder trigger after Delivered alert")
else:
    print("  ! Could not find alert block — check manually")


# ── 3. Add _send_dfw_pod_reminder function ──
# Insert before send_tolead_alert function

pod_fn = '''
def _send_dfw_pod_reminder(load_id, dest, driver_phone, efj=""):
    """Send POD reminder for DFW loads when Macropoint marks Delivered before Col L."""
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    ref = f"DFW--{load_id}"

    subject = f"POD Needed — {ref}({dest}) Has Delivered"

    phone_line = f"<b>Driver Phone:</b> {driver_phone}" if driver_phone else "<b>Driver Phone:</b> (not on file)"

    body = f"""<html><body style="font-family:Arial,sans-serif;">
<div style="background:#c62828;color:white;padding:12px 16px;border-radius:6px 6px 0 0;">
  <b>POD Reminder — {ref}</b>
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
    <tr><td style="padding:4px 12px 4px 0;color:#555;">{phone_line}</td></tr>
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
        print(f"    WARNING: POD reminder email failed: {exc}")


'''

anchor = "def send_tolead_alert("
if "_send_dfw_pod_reminder" not in src:
    src = src.replace(anchor, pod_fn + anchor)
    print("  + Added _send_dfw_pod_reminder() function")
else:
    print("  ~ _send_dfw_pod_reminder() already exists")


with open(MONITOR, "w") as f:
    f.write(src)

print(f"\n  Patched: {MONITOR}")
print("  Done. Restart csl-tolead.")
