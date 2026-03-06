#!/usr/bin/env python3
"""
patch_unresponsive_alert.py
Patches ftl_monitor.py to:
  1. Detect "Driver Phone Unresponsive" MP status
  2. Send email alert to account rep (dedup: max once per 2 hours)
  3. Escalation after 3 consecutive polls (1.5 hrs) → escalation email
  4. After 6 consecutive (3 hrs) → flag as cantMakeIt in tracking cache
  5. Reset counter when status changes

Run: python3 /tmp/patch_unresponsive_alert.py
"""
import re, os

FILE = "/root/csl-bot/ftl_monitor.py"
STATE_FILE = "/root/csl-bot/unresponsive_state.json"

with open(FILE) as f:
    code = f.read()

changes = 0

# ══════════════════════════════════════════════════════════════════════════
# 1) Add unresponsive state tracking (load/save functions)
# ══════════════════════════════════════════════════════════════════════════
if "unresponsive_state" in code or "load_unresponsive_state" in code:
    print("Unresponsive state tracking already exists — skipping")
else:
    # Add near the top, after imports
    import_anchor = re.search(r'^import json\b', code, re.MULTILINE)
    if not import_anchor:
        import_anchor = re.search(r'^from datetime import', code, re.MULTILINE)

    if import_anchor:
        insert_pos = code.index('\n', import_anchor.end()) + 1
    else:
        # Fallback: after all imports
        insert_pos = 0
        for m in re.finditer(r'^(?:import |from )', code, re.MULTILINE):
            insert_pos = code.index('\n', m.end()) + 1

    state_code = f'''
# ── Unresponsive driver state tracking ──
UNRESPONSIVE_STATE_FILE = "{STATE_FILE}"

def load_unresponsive_state():
    try:
        with open(UNRESPONSIVE_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {{}}

def save_unresponsive_state(state):
    tmp = UNRESPONSIVE_STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, UNRESPONSIVE_STATE_FILE)

'''
    code = code[:insert_pos] + state_code + code[insert_pos:]
    changes += 1
    print("Added unresponsive state load/save functions")

# ══════════════════════════════════════════════════════════════════════════
# 2) Add unresponsive detection + alert + escalation logic
# ══════════════════════════════════════════════════════════════════════════
if "unresponsive" in code.lower() and "send_unresponsive_alert" in code:
    print("Unresponsive alert logic already exists — skipping")
else:
    # Add the alert function near other email/alert functions
    # Look for send_alert or send_email function
    alert_func_match = re.search(r'^def send_\w*alert', code, re.MULTILINE)
    if not alert_func_match:
        alert_func_match = re.search(r'^def send_email', code, re.MULTILINE)

    if alert_func_match:
        insert_pos = alert_func_match.start()
    else:
        # Fallback: find a good insertion point after helper functions
        insert_pos = len(code) // 3  # rough middle of file

    alert_func = '''
# ── Unresponsive driver alert ────────────────────────────────────────────

def send_unresponsive_alert(efj, load_num, account, carrier, driver_phone,
                            carrier_email, rep_email, escalation=False):
    """Send email alert when driver phone is unresponsive."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_user = os.getenv("SMTP_USER", "jfeltzjr@gmail.com")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    cc_addr = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")

    if not rep_email:
        rep_email = cc_addr

    prefix = "ESCALATION: " if escalation else ""
    subject = f"{prefix}Driver Phone Unresponsive — {efj} {load_num}"

    bg_color = "#c62828" if escalation else "#e65100"
    body = f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;">
<div style="background:{bg_color};color:white;padding:12px 20px;border-radius:8px 8px 0 0;">
<h3 style="margin:0;">{'ESCALATION: ' if escalation else ''}Driver Phone Unresponsive</h3>
</div>
<div style="padding:16px 20px;background:#fafafa;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px;">
<table style="border-collapse:collapse;width:100%;">
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">EFJ #</td><td style="padding:6px 12px;">{efj}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Load #</td><td style="padding:6px 12px;">{load_num}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Account</td><td style="padding:6px 12px;">{account}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Carrier</td><td style="padding:6px 12px;">{carrier}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Driver Phone</td><td style="padding:6px 12px;">{driver_phone or 'N/A'}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Carrier Email</td><td style="padding:6px 12px;">{carrier_email or 'N/A'}</td></tr>
</table>
{'<p style="color:#c62828;font-weight:bold;margin-top:12px;">This load has been unresponsive for over 1.5 hours. Please contact carrier directly.</p>' if escalation else '<p style="color:#e65100;margin-top:12px;">Macropoint cannot reach the driver phone. The system will retry automatically.</p>'}
</div>
</body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = rep_email
        msg["Cc"] = cc_addr
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(smtp_user, smtp_pass)
            recipients = [rep_email]
            if cc_addr and cc_addr != rep_email:
                recipients.append(cc_addr)
            smtp.sendmail(smtp_user, recipients, msg.as_string())
        log.info("Sent %sunresponsive alert for %s to %s",
                 "ESCALATION " if escalation else "", efj, rep_email)
    except Exception as e:
        log.warning("Failed to send unresponsive alert for %s: %s", efj, e)


def check_unresponsive(efj, load_num, mp_load_status, account, carrier,
                       driver_phone, carrier_email, rep_email, tracking_cache):
    """Check and handle unresponsive driver status with escalation."""
    state = load_unresponsive_state()
    key = efj

    if mp_load_status and "unresponsive" in mp_load_status.lower():
        entry = state.get(key, {"count": 0, "last_alert": None})
        entry["count"] = entry.get("count", 0) + 1
        count = entry["count"]

        # First detection or every 4 polls (2 hours) — send alert
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()
        last_alert = entry.get("last_alert")

        should_alert = False
        if count == 1:
            should_alert = True
        elif last_alert:
            try:
                last_dt = datetime.fromisoformat(last_alert)
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if elapsed >= 7200:  # 2 hours
                    should_alert = True
            except (ValueError, TypeError):
                should_alert = True

        if should_alert:
            escalation = count >= 3  # 3+ consecutive = 1.5+ hours
            send_unresponsive_alert(efj, load_num, account, carrier,
                                   driver_phone, carrier_email, rep_email,
                                   escalation=escalation)
            entry["last_alert"] = now_str

        # After 6 consecutive (3 hours) — flag cantMakeIt
        if count >= 6:
            if efj in tracking_cache:
                tracking_cache[efj]["cant_make_it"] = "Driver Phone Unresponsive (3+ hrs)"
                log.warning("Flagged %s as cantMakeIt (6+ unresponsive polls)", efj)

        state[key] = entry
        save_unresponsive_state(state)
        log.info("Unresponsive count for %s: %d", efj, count)

    else:
        # Status is NOT unresponsive — reset counter
        if key in state:
            if state[key].get("count", 0) > 0:
                log.info("Unresponsive cleared for %s (was %d polls)", efj, state[key]["count"])
            del state[key]
            save_unresponsive_state(state)


'''
    code = code[:insert_pos] + alert_func + code[insert_pos:]
    changes += 1
    print("Added send_unresponsive_alert and check_unresponsive functions")

# ══════════════════════════════════════════════════════════════════════════
# 3) Call check_unresponsive in the main scraping loop
# ══════════════════════════════════════════════════════════════════════════
if "check_unresponsive(" in code:
    print("check_unresponsive call already exists — skipping")
else:
    # Find the update_tracking_cache call and add check_unresponsive after it
    update_call = re.search(r'update_tracking_cache\([^)]+\)', code)
    if update_call:
        end_pos = update_call.end()
        next_nl = code.index('\n', end_pos)
        line_start = code.rfind('\n', 0, update_call.start()) + 1
        indent = ' ' * (update_call.start() - line_start)

        check_call = f'''
{indent}# Check for unresponsive driver and handle alerts/escalation
{indent}try:
{indent}    _rep_email = ""
{indent}    for _s in sheet_cache_shipments if 'sheet_cache_shipments' in dir() else []:
{indent}        if _s.get("efj") == efj:
{indent}            _rep_email = _s.get("rep_email", "")
{indent}            break
{indent}    check_unresponsive(
{indent}        efj=efj, load_num=load_num,
{indent}        mp_load_status=mp_load_status if 'mp_load_status' in dir() else "",
{indent}        account=account if 'account' in dir() else "",
{indent}        carrier=carrier if 'carrier' in dir() else "",
{indent}        driver_phone=driver_phone if 'driver_phone' in dir() else "",
{indent}        carrier_email="",
{indent}        rep_email=_rep_email,
{indent}        tracking_cache=cache if 'cache' in dir() else {{}},
{indent}    )
{indent}except Exception as _ue:
{indent}    log.warning("check_unresponsive error for %s: %s", efj, _ue)
'''
        code = code[:next_nl + 1] + check_call + code[next_nl + 1:]
        changes += 1
        print("Added check_unresponsive call in scraping loop")
    else:
        print("WARNING: Could not find update_tracking_cache call — check_unresponsive not injected")
        print("         You may need to manually add check_unresponsive() call to the scraping loop")

# ══════════════════════════════════════════════════════════════════════════
# Write
# ══════════════════════════════════════════════════════════════════════════
with open(FILE, "w") as f:
    f.write(code)

print(f"\n{'=' * 60}")
print(f"Applied {changes} changes to ftl_monitor.py")
print("Restart service: systemctl restart csl-ftl")
