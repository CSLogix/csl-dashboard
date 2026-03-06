#!/usr/bin/env python3
"""
patch_ftl_enhancements.py
Patches app.py to:
  1. ALTER driver_contacts table — add carrier_email, trailer_number, macropoint_url columns
  2. Update _get_driver_contact() to return new fields
  3. Update _upsert_driver_contact() to accept new fields
  4. Update GET/POST /api/load/{efj}/driver to include new fields
  5. Add GET /api/macropoint/batch endpoint for dispatch table MP status column
  6. Add "need pod" to _STATUS_TO_STEP mapping
  7. Update /api/macropoint/{efj} to use driver_contacts.macropoint_url as URL fallback
  8. Add GET /api/shipments/tracking-summary to include mpStatus field

Run: python3 /tmp/patch_ftl_enhancements.py
"""

FILE = "/root/csl-bot/csl-doc-tracker/app.py"

with open(FILE) as f:
    code = f.read()

changes = 0

# ══════════════════════════════════════════════════════════════════════════
# 1) ALTER driver_contacts table — add new columns
# ══════════════════════════════════════════════════════════════════════════
if "carrier_email" in code:
    print("carrier_email already present — skipping ALTER TABLE")
else:
    anchor = 'log.info("driver_contacts table ready")'
    if anchor not in code:
        print("ERROR: Cannot find driver_contacts table ready log")
        exit(1)
    idx = code.index(anchor)
    alter_sql = '''
        # Add new FTL columns if missing
        try:
            with db.get_conn() as conn:
                with db.get_cursor(conn) as cur:
                    cur.execute("""
                        ALTER TABLE driver_contacts
                            ADD COLUMN IF NOT EXISTS carrier_email VARCHAR(200),
                            ADD COLUMN IF NOT EXISTS trailer_number VARCHAR(50),
                            ADD COLUMN IF NOT EXISTS macropoint_url TEXT
                    """)
            log.info("driver_contacts FTL columns ready")
        except Exception as e:
            log.warning("Could not add FTL columns to driver_contacts: %s", e)
'''
    # Insert before the log.info line (find the start of the try block before it)
    code = code[:idx] + alter_sql + '\n    ' + code[idx:]
    changes += 1
    print("Added ALTER TABLE for carrier_email, trailer_number, macropoint_url")

# ══════════════════════════════════════════════════════════════════════════
# 2) Update _get_driver_contact to SELECT new columns
# ══════════════════════════════════════════════════════════════════════════
old_select = (
    '"SELECT driver_name, driver_phone, driver_email, notes "'
)
new_select = (
    '"SELECT driver_name, driver_phone, driver_email, notes, carrier_email, trailer_number, macropoint_url "'
)
if old_select in code:
    code = code.replace(old_select, new_select, 1)
    changes += 1
    print("Updated _get_driver_contact SELECT to include new columns")
else:
    print("_get_driver_contact SELECT already updated or not found")

# ══════════════════════════════════════════════════════════════════════════
# 3) Update _upsert_driver_contact to accept + store new fields
# ══════════════════════════════════════════════════════════════════════════
old_upsert_sig = "def _upsert_driver_contact(efj: str, name: str = None, phone: str = None,\n                           email: str = None, notes: str = None):"
new_upsert_sig = """def _upsert_driver_contact(efj: str, name: str = None, phone: str = None,
                           email: str = None, notes: str = None,
                           carrier_email: str = None, trailer_number: str = None,
                           macropoint_url: str = None):"""

if old_upsert_sig in code:
    code = code.replace(old_upsert_sig, new_upsert_sig)
    changes += 1
    print("Updated _upsert_driver_contact signature")
else:
    print("_upsert_driver_contact signature already updated or not found")

old_upsert_sql = '''            cur.execute("""
                INSERT INTO driver_contacts (efj, driver_name, driver_phone, driver_email, notes)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (efj) DO UPDATE SET
                    driver_name  = COALESCE(EXCLUDED.driver_name,  driver_contacts.driver_name),
                    driver_phone = COALESCE(EXCLUDED.driver_phone, driver_contacts.driver_phone),
                    driver_email = COALESCE(EXCLUDED.driver_email, driver_contacts.driver_email),
                    notes        = COALESCE(EXCLUDED.notes,        driver_contacts.notes),
                    updated_at   = NOW()
            """, (efj, name or None, phone or None, email or None, notes or None))'''

new_upsert_sql = '''            cur.execute("""
                INSERT INTO driver_contacts (efj, driver_name, driver_phone, driver_email, notes,
                                             carrier_email, trailer_number, macropoint_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (efj) DO UPDATE SET
                    driver_name     = COALESCE(EXCLUDED.driver_name,     driver_contacts.driver_name),
                    driver_phone    = COALESCE(EXCLUDED.driver_phone,    driver_contacts.driver_phone),
                    driver_email    = COALESCE(EXCLUDED.driver_email,    driver_contacts.driver_email),
                    notes           = COALESCE(EXCLUDED.notes,           driver_contacts.notes),
                    carrier_email   = COALESCE(EXCLUDED.carrier_email,   driver_contacts.carrier_email),
                    trailer_number  = COALESCE(EXCLUDED.trailer_number,  driver_contacts.trailer_number),
                    macropoint_url  = COALESCE(EXCLUDED.macropoint_url,  driver_contacts.macropoint_url),
                    updated_at      = NOW()
            """, (efj, name or None, phone or None, email or None, notes or None,
                  carrier_email or None, trailer_number or None, macropoint_url or None))'''

if old_upsert_sql in code:
    code = code.replace(old_upsert_sql, new_upsert_sql)
    changes += 1
    print("Updated _upsert_driver_contact SQL")
else:
    print("_upsert_driver_contact SQL already updated or not found")

# ══════════════════════════════════════════════════════════════════════════
# 4) Update GET /api/load/{efj}/driver response
# ══════════════════════════════════════════════════════════════════════════
old_driver_return = '''    return {
        "efj": efj,
        "driverName": contact.get("driver_name") or sheet_driver or "",
        "driverPhone": contact.get("driver_phone") or "",
        "driverEmail": contact.get("driver_email") or "",
        "notes": contact.get("notes") or "",
    }'''

new_driver_return = '''    return {
        "efj": efj,
        "driverName": contact.get("driver_name") or sheet_driver or "",
        "driverPhone": contact.get("driver_phone") or "",
        "driverEmail": contact.get("driver_email") or "",
        "notes": contact.get("notes") or "",
        "carrierEmail": contact.get("carrier_email") or "",
        "trailerNumber": contact.get("trailer_number") or "",
        "macropointUrl": contact.get("macropoint_url") or "",
    }'''

if old_driver_return in code:
    code = code.replace(old_driver_return, new_driver_return)
    changes += 1
    print("Updated GET /api/load/{efj}/driver response with new fields")
else:
    print("GET /api/load/{efj}/driver response already updated or not found")

# ══════════════════════════════════════════════════════════════════════════
# 5) Update POST /api/load/{efj}/driver to accept new fields
# ══════════════════════════════════════════════════════════════════════════
old_upsert_call = '''    _upsert_driver_contact(
        efj,
        name=body.get("driverName"),
        phone=body.get("driverPhone"),
        email=body.get("driverEmail"),
        notes=body.get("notes"),
    )'''

new_upsert_call = '''    _upsert_driver_contact(
        efj,
        name=body.get("driverName"),
        phone=body.get("driverPhone"),
        email=body.get("driverEmail"),
        notes=body.get("notes"),
        carrier_email=body.get("carrierEmail"),
        trailer_number=body.get("trailerNumber"),
        macropoint_url=body.get("macropointUrl"),
    )'''

if old_upsert_call in code:
    code = code.replace(old_upsert_call, new_upsert_call)
    changes += 1
    print("Updated POST /api/load/{efj}/driver to pass new fields")
else:
    print("POST /api/load/{efj}/driver call already updated or not found")

# ══════════════════════════════════════════════════════════════════════════
# 6) Add "need pod" to _STATUS_TO_STEP mapping
# ══════════════════════════════════════════════════════════════════════════
if '"need pod"' in code:
    print('"need pod" already in status mapping — skipping')
else:
    # Find the status mapping and add before "delivered"
    old_status = '"delivered": 5,'
    new_status = '"need pod": 5,\n    "delivered": 5,'
    if old_status in code:
        code = code.replace(old_status, new_status, 1)
        changes += 1
        print('Added "need pod": 5 to _STATUS_TO_STEP')
    else:
        print("WARNING: Could not find delivered status in mapping")

# ══════════════════════════════════════════════════════════════════════════
# 7) Add GET /api/macropoint/batch endpoint
# ══════════════════════════════════════════════════════════════════════════
if "/api/macropoint/batch" in code:
    print("/api/macropoint/batch already exists — skipping")
else:
    # Insert before the individual macropoint endpoint
    anchor = '@app.get("/api/macropoint/{efj}")'
    if anchor not in code:
        print("ERROR: Cannot find /api/macropoint/{efj} endpoint")
        exit(1)
    idx = code.index(anchor)

    batch_endpoint = '''
# ── Batch Macropoint tracking status for dispatch table ──────────────────

@app.get("/api/macropoint/batch")
async def api_macropoint_batch():
    """Return MP tracking status for all cached loads. Used by dispatch table."""
    cache = _read_tracking_cache()
    result = {}
    for key, entry in cache.items():
        efj = entry.get("efj", key)
        result[efj] = {
            "mpStatus": entry.get("mp_status", ""),
            "trackingStatus": entry.get("status", ""),
            "behindSchedule": "BEHIND" in (entry.get("stop_times", {}).get("stop2_eta", "") or "").upper(),
            "cantMakeIt": entry.get("cant_make_it"),
            "macropointUrl": entry.get("macropoint_url", ""),
            "driverPhone": entry.get("driver_phone", ""),
            "trailer": entry.get("trailer", ""),
        }
        # Also key by bare load_num for lookups
        load_num = entry.get("load_num")
        if load_num and load_num != efj:
            result[load_num] = result[efj]
    return {"tracking": result}


'''
    code = code[:idx] + batch_endpoint + code[idx:]
    changes += 1
    print("Added GET /api/macropoint/batch endpoint")

# ══════════════════════════════════════════════════════════════════════════
# 8) Update /api/macropoint/{efj} to use driver_contacts.macropoint_url fallback
# ══════════════════════════════════════════════════════════════════════════
old_mp_url = '"macropointUrl": shipment.get("container_url", ""),'
new_mp_url = '"macropointUrl": shipment.get("container_url", "") or contact.get("macropoint_url", "") or cached.get("macropoint_url", ""),'
if old_mp_url in code:
    code = code.replace(old_mp_url, new_mp_url, 1)
    changes += 1
    print("Updated /api/macropoint/{efj} macropointUrl with DB fallback")
else:
    print("/api/macropoint/{efj} macropointUrl already updated or not found")

# ══════════════════════════════════════════════════════════════════════════
# 9) Add mpStatus to tracking-summary response if endpoint exists
# ══════════════════════════════════════════════════════════════════════════
if "/api/shipments/tracking-summary" in code and "mpStatus" not in code:
    # Find the tracking-summary endpoint and add mpStatus to each entry
    old_tracking_entry = '"behindSchedule": "BEHIND" in'
    if old_tracking_entry in code:
        # Already has behindSchedule — add mpStatus alongside it
        code = code.replace(
            old_tracking_entry,
            '"mpStatus": entry.get("mp_status", ""),\n                "behindSchedule": "BEHIND" in',
            1,
        )
        changes += 1
        print("Added mpStatus to tracking-summary response")
    else:
        print("WARNING: Could not find tracking-summary behindSchedule pattern")
elif "mpStatus" in code:
    print("mpStatus already in code — skipping tracking-summary update")
else:
    print("No /api/shipments/tracking-summary endpoint found")

# ══════════════════════════════════════════════════════════════════════════
# Write
# ══════════════════════════════════════════════════════════════════════════
with open(FILE, "w") as f:
    f.write(code)

print(f"\n{'=' * 60}")
print(f"Applied {changes} changes to app.py")
print("Restart service: systemctl restart csl-dashboard")
