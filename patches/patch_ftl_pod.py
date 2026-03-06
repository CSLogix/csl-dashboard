#!/usr/bin/env python3
"""
Patch: ftl_monitor.py — Add POD reminder email after Need POD auto-status

When Macropoint tracking completes and status auto-transitions to "Need POD",
send a dedicated POD reminder email to the account rep.
"""

TARGET = "/root/csl-bot/ftl_monitor.py"

with open(TARGET, "r") as f:
    src = f.read()


# ── 1. Add _send_pod_reminder_ftl() function ─────────────────────────────
# Insert before send_ftl_email function

pod_fn = '''def _send_pod_reminder_ftl(efj, load_num, dest, tab_name, account_lookup, mp_load_id=None):
    """Send POD reminder email when FTL tracking completes."""
    info = account_lookup.get(tab_name, {})
    rep_email = info.get("email", "")
    to_email = rep_email if rep_email else EMAIL_FALLBACK

    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    load_ref = mp_load_id or load_num
    ref = f"{tab_name}--{load_ref}"

    subject = f"POD Needed \\u2014 {ref}({dest}) Has Delivered"

    body = f"""<html><body style="font-family:Arial,sans-serif;">
<div style="background:#c62828;color:white;padding:12px 16px;border-radius:6px 6px 0 0;">
  <b>POD Reminder \\u2014 {ref}</b>
</div>
<div style="padding:16px;border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;">
  <p style="font-size:15px;margin:0 0 12px;">
    <b>{ref}({dest})</b> has been marked <b style="color:#c62828;">Delivered</b> by Macropoint tracking.
  </p>
  <p style="font-size:15px;margin:0 0 12px;">
    Please obtain the POD from the driver/carrier as soon as possible.
  </p>
  <table style="border-collapse:collapse;margin:12px 0;">
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Account</td><td style="padding:4px 0;"><b>{tab_name}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">EFJ #</td><td style="padding:4px 0;"><b>{efj}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Load #</td><td style="padding:4px 0;"><b>{load_num}</b></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555;">Destination</td><td style="padding:4px 0;">{dest}</td></tr>
  </table>
  <p style="font-size:12px;color:#888;margin:16px 0 0;">
    Status has been auto-set to "Need POD". Update to "POD Received" once obtained.<br>
    Sent at {now}
  </p>
</div>
</body></html>"""

    try:
        cc = None if tab_name.lower() == "boviet" else EMAIL_CC
        _send_email(to_email, cc, subject, body)
        log.info("POD reminder sent for %s to %s", ref, to_email)
    except Exception as exc:
        log.warning("POD reminder email failed for %s: %s", ref, exc)


'''

if "def _send_pod_reminder_ftl" not in src:
    anchor = "def send_ftl_email("
    if anchor in src:
        src = src.replace(anchor, pod_fn + anchor)
        print("  + Added _send_pod_reminder_ftl() function")
    else:
        print("  ! Could not find send_ftl_email anchor")
else:
    print("  ~ _send_pod_reminder_ftl() already exists")


# ── 2. Trigger POD reminder after Need POD auto-transition ────────────────

old_auto_status = '''                # Auto-transition: Tracking Completed \u2192 Need POD
                if status and "tracking completed" in status.lower():
                    current_status = (row_data.get("status") or "").strip().lower() if isinstance(row_data, dict) else ""
                    if current_status not in ("need pod", "pod received", "pod rc\\'d", "driver paid"):
                        try:
                            ws.update_cell(row_number, STATUS_COL + 1, "Need POD")
                            log.info("Auto-status: %s -> Need POD (tracking completed)", efj)
                        except Exception as e:
                            log.warning("Failed to auto-status %s to Need POD: %s", efj, e)'''

new_auto_status = '''                # Auto-transition: Tracking Completed \u2192 Need POD
                if status and "tracking completed" in status.lower():
                    current_status = (row_data.get("status") or "").strip().lower() if isinstance(row_data, dict) else ""
                    if current_status not in ("need pod", "pod received", "pod rc\\'d", "driver paid"):
                        try:
                            ws.update_cell(row_number, STATUS_COL + 1, "Need POD")
                            log.info("Auto-status: %s -> Need POD (tracking completed)", efj)
                            # Send POD reminder email
                            dest_val = row.get("dest", "") if isinstance(row, dict) else ""
                            _send_pod_reminder_ftl(efj, row.get("load_num", ""), dest_val,
                                                   tab_name, account_lookup, mp_load_id=mp_load_id)
                        except Exception as e:
                            log.warning("Failed to auto-status %s to Need POD: %s", efj, e)'''

if old_auto_status in src:
    src = src.replace(old_auto_status, new_auto_status)
    print("  + Added POD reminder trigger after Need POD auto-transition")
else:
    print("  ! Could not find auto-status block — trying alternative format")
    # The quote escaping might differ — try without escaped quotes
    alt_old = old_auto_status.replace("\\'", "'")
    if alt_old in src:
        alt_new = new_auto_status.replace("\\'", "'")
        src = src.replace(alt_old, alt_new)
        print("  + Added POD reminder trigger (alt format)")
    else:
        print("  ! Could not find auto-status block in either format")


with open(TARGET, "w") as f:
    f.write(src)

print(f"\n  Patched: {TARGET}")
print("  Done. Restart csl-ftl.")
