#!/usr/bin/env python3
"""
Patch: Fix driver endpoint to return carrierEmail, trailerNumber, macropointUrl
- _get_driver_contact() now SELECTs all columns
- GET /api/load/{efj}/driver response includes all driver fields
"""

import sys

APP = "/root/csl-bot/csl-doc-tracker/app.py"

print("[1/1] Patching driver contact query + response...")

with open(APP, "r") as f:
    code = f.read()

# Fix 1: _get_driver_contact query to include all columns
OLD_QUERY = '''def _get_driver_contact(efj: str) -> dict:
    """Get driver contact info from PostgreSQL."""
    try:
        with db.get_cursor() as cur:
            cur.execute(
                "SELECT driver_name, driver_phone, driver_email, notes "
                "FROM driver_contacts WHERE efj = %s",
                (efj,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
    except Exception as e:
        log.warning("Failed to read driver contact for %s: %s", efj, e)
    return {}'''

NEW_QUERY = '''def _get_driver_contact(efj: str) -> dict:
    """Get driver contact info from PostgreSQL."""
    try:
        with db.get_cursor() as cur:
            cur.execute(
                "SELECT driver_name, driver_phone, driver_email, notes, "
                "carrier_email, trailer_number, macropoint_url "
                "FROM driver_contacts WHERE efj = %s",
                (efj,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
    except Exception as e:
        log.warning("Failed to read driver contact for %s: %s", efj, e)
    return {}'''

if OLD_QUERY in code:
    code = code.replace(OLD_QUERY, NEW_QUERY)
    print("   Fixed _get_driver_contact query.")
else:
    print("   WARNING: Could not find old driver query — may already be updated")

# Fix 2: api_get_driver response to include all fields
OLD_RETURN = '''    return {
        "efj": efj,
        "driverName": contact.get("driver_name") or sheet_driver or "",
        "driverPhone": contact.get("driver_phone") or cached_phone or "",
        "driverEmail": contact.get("driver_email") or "",
        "notes": contact.get("notes") or "",
        "phoneSource": "db" if contact.get("driver_phone") else ("macropoint" if cached_phone else ""),
    }'''

NEW_RETURN = '''    return {
        "efj": efj,
        "driverName": contact.get("driver_name") or sheet_driver or "",
        "driverPhone": contact.get("driver_phone") or cached_phone or "",
        "driverEmail": contact.get("driver_email") or "",
        "carrierEmail": contact.get("carrier_email") or "",
        "trailerNumber": contact.get("trailer_number") or "",
        "macropointUrl": contact.get("macropoint_url") or "",
        "notes": contact.get("notes") or "",
        "phoneSource": "db" if contact.get("driver_phone") else ("macropoint" if cached_phone else ""),
    }'''

if OLD_RETURN in code:
    code = code.replace(OLD_RETURN, NEW_RETURN)
    print("   Fixed api_get_driver response.")
else:
    print("   WARNING: Could not find old return block — may already be updated")

with open(APP, "w") as f:
    f.write(code)

print("   Done! Driver fields patch applied.")
print("   Restart: systemctl restart csl-dashboard")
