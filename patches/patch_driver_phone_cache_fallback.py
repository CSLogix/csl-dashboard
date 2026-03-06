#!/usr/bin/env python3
"""
patch_driver_phone_cache_fallback.py
Patches app.py so both /api/load/{efj}/driver and /api/macropoint/{efj}
read driver_phone from the ftl_tracking_cache.json as a fallback when
the driver_contacts DB doesn't have it yet.

Also auto-saves the cached phone to the DB so manual edits aren't overwritten.

Run: python3 /tmp/patch_driver_phone_cache_fallback.py
"""

FILE = "/root/csl-bot/csl-doc-tracker/app.py"

with open(FILE) as f:
    code = f.read()

changes = 0

# ══════════════════════════════════════════════════════════════════════════
# 1) Update GET /api/load/{efj}/driver to fall back to tracking cache
# ══════════════════════════════════════════════════════════════════════════
old_driver_get = '''    """Return driver contact info for a load."""
    contact = _get_driver_contact(efj)
    # Also check Column N (driver/truck) from sheet cache as fallback for name
    sheet_driver = ""
    for s in sheet_cache.shipments:
        if s["efj"] == efj:
            sheet_driver = s.get("notes", "")  # COL index 13 = Column N = Driver/Truck
            break
    return {
        "efj": efj,
        "driverName": contact.get("driver_name") or sheet_driver or "",
        "driverPhone": contact.get("driver_phone") or "",
        "driverEmail": contact.get("driver_email") or "",
        "notes": contact.get("notes") or "",
    }'''

new_driver_get = '''    """Return driver contact info for a load."""
    contact = _get_driver_contact(efj)
    # Also check Column N (driver/truck) from sheet cache as fallback for name
    sheet_driver = ""
    for s in sheet_cache.shipments:
        if s["efj"] == efj:
            sheet_driver = s.get("notes", "")  # COL index 13 = Column N = Driver/Truck
            break

    # Fall back to tracking cache for driver_phone (scraped from MP portal)
    cached_phone = ""
    tracking_cache = _read_tracking_cache()
    cached = tracking_cache.get(efj, {})
    if cached.get("driver_phone"):
        cached_phone = cached["driver_phone"]
        # Auto-save scraped phone to DB if DB doesn't have one yet
        if not contact.get("driver_phone"):
            try:
                _upsert_driver_contact(efj, phone=cached_phone)
            except Exception:
                pass

    return {
        "efj": efj,
        "driverName": contact.get("driver_name") or sheet_driver or "",
        "driverPhone": contact.get("driver_phone") or cached_phone or "",
        "driverEmail": contact.get("driver_email") or "",
        "notes": contact.get("notes") or "",
        "phoneSource": "db" if contact.get("driver_phone") else ("macropoint" if cached_phone else ""),
    }'''

if "cached_phone" in code and "phoneSource" in code:
    print("[1] Driver GET endpoint already has cache fallback — skipping")
elif old_driver_get in code:
    code = code.replace(old_driver_get, new_driver_get)
    changes += 1
    print("[1] Updated GET /api/load/{efj}/driver with tracking cache fallback")
else:
    print("WARNING: Could not find exact driver GET endpoint block")

# ══════════════════════════════════════════════════════════════════════════
# 2) Update /api/macropoint/{efj} to use cached driver_phone as fallback
# ══════════════════════════════════════════════════════════════════════════
old_mp_driver = '''    # ── Driver contact info (from DB) ──
    contact = _get_driver_contact(efj)
    driver_name = contact.get("driver_name") or ""
    driver_phone = contact.get("driver_phone") or ""
    driver_email = contact.get("driver_email") or ""

    # ── Tracking cache (stop timeline from ftl_monitor) ──
    tracking_cache = _read_tracking_cache()
    cached = tracking_cache.get(efj, {})'''

new_mp_driver = '''    # ── Tracking cache (stop timeline from ftl_monitor) ──
    tracking_cache = _read_tracking_cache()
    cached = tracking_cache.get(efj, {})

    # ── Driver contact info (from DB, with cache fallback) ──
    contact = _get_driver_contact(efj)
    driver_name = contact.get("driver_name") or ""
    driver_phone = contact.get("driver_phone") or cached.get("driver_phone") or ""
    driver_email = contact.get("driver_email") or ""

    # Auto-save scraped phone to DB if DB doesn't have one
    if cached.get("driver_phone") and not contact.get("driver_phone"):
        try:
            _upsert_driver_contact(efj, phone=cached["driver_phone"])
        except Exception:
            pass'''

if 'cached.get("driver_phone")' in code and "Auto-save scraped phone" in code:
    print("[2] Macropoint endpoint already has cache fallback — skipping")
elif old_mp_driver in code:
    code = code.replace(old_mp_driver, new_mp_driver)
    changes += 1
    print("[2] Updated /api/macropoint/{efj} with tracking cache driver_phone fallback")
else:
    print("WARNING: Could not find exact macropoint driver block")

with open(FILE, "w") as f:
    f.write(code)

print(f"\n✅ app.py patched ({changes} changes)")
print("   Driver phone now falls back to tracking cache (scraped from MP portal)")
print("   Auto-saves to DB when found in cache")
print("   Restart: systemctl restart csl-dashboard")
