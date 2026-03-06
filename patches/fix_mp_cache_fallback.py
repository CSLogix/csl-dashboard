#!/usr/bin/env python3
"""Fix macropoint endpoint to use cached driver_phone as fallback."""

FILE = "/root/csl-bot/csl-doc-tracker/app.py"

with open(FILE) as f:
    code = f.read()

old = '    # ── Driver contact info (from DB) ──\n    contact = _get_driver_contact(efj)\n    driver_name = contact.get("driver_name") or ""\n    driver_phone = contact.get("driver_phone") or ""\n    driver_email = contact.get("driver_email") or ""\n\n    # ── Tracking cache (stop timeline from ftl_monitor) ──\n    tracking_cache = _read_tracking_cache()\n    cached = tracking_cache.get(efj, {})'

new = '    # ── Tracking cache (stop timeline from ftl_monitor) ──\n    tracking_cache = _read_tracking_cache()\n    cached = tracking_cache.get(efj, {})\n\n    # ── Driver contact info (from DB, with cache fallback) ──\n    contact = _get_driver_contact(efj)\n    driver_name = contact.get("driver_name") or ""\n    driver_phone = contact.get("driver_phone") or cached.get("driver_phone") or ""\n    driver_email = contact.get("driver_email") or ""'

if old in code:
    code = code.replace(old, new)
    with open(FILE, "w") as f:
        f.write(code)
    print("Fixed: macropoint endpoint now uses cache fallback for driver_phone")
else:
    print("Block not found or already fixed")
