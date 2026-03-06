#!/usr/bin/env python3
"""
patch_dray_import_no_overwrite.py
Prevents Dray Import monitor from overwriting existing date fields
(ETA, Pickup/LFD, Return to Port) and carrier name (Col F) that
were manually entered.

Matches the pattern already used in ftl_monitor.py (lines 1129-1149).
Status (M) and Bot Notes (O) are still written freely.

Run: python3 /tmp/patch_dray_import_no_overwrite.py
"""

FILE = "/root/csl-bot/csl_bot.py"

with open(FILE) as f:
    code = f.read()

changes = 0

# ══════════════════════════════════════════════════════════════════
# 1) Add existing_row parameter to dray_import_workflow signature
# ══════════════════════════════════════════════════════════════════
old_sig = (
    "def dray_import_workflow(browser, ws, sheet_row, url, bol, container,\n"
    "                          circuit_breaker=None, vessel=\"\", carrier_name=\"\",\n"
    "                          pending_updates=None, proxy_ok=True, ssl_code=None):"
)
new_sig = (
    "def dray_import_workflow(browser, ws, sheet_row, url, bol, container,\n"
    "                          circuit_breaker=None, vessel=\"\", carrier_name=\"\",\n"
    "                          pending_updates=None, proxy_ok=True, ssl_code=None,\n"
    "                          existing_row=None):"
)

if old_sig in code:
    code = code.replace(old_sig, new_sig, 1)
    changes += 1
    print("[OK] Added existing_row parameter to dray_import_workflow signature")
elif "existing_row=None" in code:
    print("[SKIP] existing_row already in signature")
else:
    print("[WARN] Could not find dray_import_workflow signature — check manually")

# ══════════════════════════════════════════════════════════════════
# 2) Replace unconditional date writes with guarded checks
# ══════════════════════════════════════════════════════════════════
old_writes = """\
    if pending_updates is not None:
        ts = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
        if eta:
            pending_updates.append({"range": f"{col_letter(COL_ETA)}{sheet_row}", "values": [[eta]]})
        if pickup:
            pending_updates.append({"range": f"{col_letter(COL_PICKUP)}{sheet_row}", "values": [[pickup]]})
        if ret:
            pending_updates.append({"range": f"{col_letter(COL_RETURN)}{sheet_row}", "values": [[ret]]})
        if status:
            pending_updates.append({"range": f"{col_letter(COL_STATUS)}{sheet_row}", "values": [[status]]})
        pending_updates.append({"range": f"{col_letter(COL_TIMESTAMP)}{sheet_row}", "values": [[ts]]})\
"""

new_writes = """\
    if pending_updates is not None:
        ts = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
        # Guard: don't overwrite manually-entered dates (ETA/Pickup/Return)
        ex_eta    = (existing_row[COL_ETA - 1].strip()    if existing_row and len(existing_row) > COL_ETA - 1    else "")
        ex_pickup = (existing_row[COL_PICKUP - 1].strip() if existing_row and len(existing_row) > COL_PICKUP - 1 else "")
        ex_return = (existing_row[COL_RETURN - 1].strip() if existing_row and len(existing_row) > COL_RETURN - 1 else "")
        if eta and not ex_eta:
            pending_updates.append({"range": f"{col_letter(COL_ETA)}{sheet_row}", "values": [[eta]]})
        elif eta and ex_eta:
            print(f"    I{sheet_row} already has {ex_eta!r} — not overwriting with {eta!r}")
        if pickup and not ex_pickup:
            pending_updates.append({"range": f"{col_letter(COL_PICKUP)}{sheet_row}", "values": [[pickup]]})
        elif pickup and ex_pickup:
            print(f"    K{sheet_row} already has {ex_pickup!r} — not overwriting with {pickup!r}")
        if ret and not ex_return:
            pending_updates.append({"range": f"{col_letter(COL_RETURN)}{sheet_row}", "values": [[ret]]})
        elif ret and ex_return:
            print(f"    P{sheet_row} already has {ex_return!r} — not overwriting with {ret!r}")
        if status:
            pending_updates.append({"range": f"{col_letter(COL_STATUS)}{sheet_row}", "values": [[status]]})
        pending_updates.append({"range": f"{col_letter(COL_TIMESTAMP)}{sheet_row}", "values": [[ts]]})\
"""

if old_writes in code:
    code = code.replace(old_writes, new_writes, 1)
    changes += 1
    print("[OK] Added date overwrite guards to batched write path")
elif "ex_eta" in code:
    print("[SKIP] Date guards already present")
else:
    print("[WARN] Could not find batched write block — check manually")

# ══════════════════════════════════════════════════════════════════
# 3) Pass existing_row from main loop call site
# ══════════════════════════════════════════════════════════════════
old_call = """\
                    eta, pickup, ret, status = dray_import_workflow(
                        browser, ws, job["sheet_row"], job["url"], job["bol"],
                        job["container"], circuit_breaker=circuit_breaker,
                        vessel=job.get("vessel", ""),
                        carrier_name=job.get("carrier", ""),
                        pending_updates=pending_updates,
                        proxy_ok=proxy_ok,
                        ssl_code=job.get("ssl_code"),
                    )\
"""

new_call = """\
                    eta, pickup, ret, status = dray_import_workflow(
                        browser, ws, job["sheet_row"], job["url"], job["bol"],
                        job["container"], circuit_breaker=circuit_breaker,
                        vessel=job.get("vessel", ""),
                        carrier_name=job.get("carrier", ""),
                        pending_updates=pending_updates,
                        proxy_ok=proxy_ok,
                        ssl_code=job.get("ssl_code"),
                        existing_row=job.get("row_data"),
                    )\
"""

if old_call in code:
    code = code.replace(old_call, new_call, 1)
    changes += 1
    print("[OK] Added existing_row=job.get('row_data') to call site")
elif 'existing_row=job.get("row_data")' in code:
    print("[SKIP] existing_row already passed at call site")
else:
    print("[WARN] Could not find call site — check manually")

# ══════════════════════════════════════════════════════════════════
# Write
# ══════════════════════════════════════════════════════════════════
with open(FILE, "w") as f:
    f.write(code)

print(f"\n{'=' * 60}")
print(f"Applied {changes} changes to csl_bot.py")
if changes > 0:
    print("Restart service: systemctl restart csl-import")
