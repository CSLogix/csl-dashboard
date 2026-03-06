#!/usr/bin/env python3
"""
Patch: Add _send_dfw_pod_reminder function definition to tolead_monitor.py
(The call site was added but the function itself was missed)

Also broadens the delivered check to catch "Delivered" and any
"tracking completed" variant from Macropoint.
"""

MONITOR = "/root/csl-bot/tolead_monitor.py"

with open(MONITOR, "r") as f:
    src = f.read()

# ── 1. Fix the trigger condition to catch delivered variants ──

old_trigger = '''            # DFW: if Macropoint says Delivered but Col L is still empty → POD reminder
            if (name == "DFW" and mp_status == "Delivered"
                    and not sheet_status_L):
                _send_dfw_pod_reminder(load_id, dest, driver_phone, efj)'''

new_trigger = '''            # DFW: if Macropoint says Delivered but Col L is still empty → POD reminder
            if (name == "DFW"
                    and ("delivered" in mp_status.lower() or "tracking completed" in mp_status.lower())
                    and not sheet_status_L):
                _send_dfw_pod_reminder(load_id, dest, driver_phone, efj)'''

if old_trigger in src:
    src = src.replace(old_trigger, new_trigger)
    print("  + Broadened DFW delivered check to include 'tracking completed'")
else:
    print("  ~ Trigger already updated or not found")


# ── 2. Add the function definition before send_tolead_alert ──

pod_fn = '''def _send_dfw_pod_reminder(load_id, dest, driver_phone, efj=""):
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
        print(f"    WARNING: POD reminder email failed: {exc}")


'''

# Only add if the function DEFINITION doesn't exist (not just the call)
if "def _send_dfw_pod_reminder" not in src:
    anchor = "def send_tolead_alert("
    if anchor in src:
        src = src.replace(anchor, pod_fn + anchor)
        print("  + Added _send_dfw_pod_reminder() function definition")
    else:
        print("  ! Could not find send_tolead_alert anchor")
else:
    print("  ~ _send_dfw_pod_reminder() definition already exists")


with open(MONITOR, "w") as f:
    f.write(src)

print(f"\n  Patched: {MONITOR}")
print("  Done.")
