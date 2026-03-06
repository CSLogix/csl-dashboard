#!/usr/bin/env python3
"""
patch_tolead_lax_cols.py
Updates Tolead LAX column mapping to include:
  - driver_phone at index 11
  - carrier_email at index 12

Also patches the Tolead shipment reader to store driver phone and carrier email
in the driver_contacts PostgreSQL table when processing LAX loads.

Run: python3 /tmp/patch_tolead_lax_cols.py
"""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

changes = 0

# ══════════════════════════════════════════════════════════════════════════
# 1) Update LAX column mapping to include driver_phone and carrier_email
# ══════════════════════════════════════════════════════════════════════════
old_lax = '''TOLEAD_LAX_COLS = {
    "efj": 0, "load_id": 3, "status": 8, "origin": None,
    "destination": 6, "pickup_date": 4, "pickup_time": 5,
    "delivery": 7, "driver": 10,
}'''

new_lax = '''TOLEAD_LAX_COLS = {
    "efj": 0, "load_id": 3, "status": 8, "origin": None,
    "destination": 6, "pickup_date": 4, "pickup_time": 5,
    "delivery": 7, "driver": 10,
    "driver_phone": 11, "carrier_email": 12,
}'''

if old_lax in code:
    code = code.replace(old_lax, new_lax)
    changes += 1
    print("[1] Updated LAX cols: added driver_phone (11), carrier_email (12)")
elif '"driver_phone": 11' in code and 'TOLEAD_LAX_COLS' in code:
    print("LAX driver_phone already mapped — skipping")
else:
    print("ERROR: Could not find LAX cols block to update")
    print("       Current TOLEAD_LAX_COLS may have been modified.")
    print("       Please check app.py manually.")

# ══════════════════════════════════════════════════════════════════════════
# 2) Update Tolead shipment reader to extract and store driver contact data
# ══════════════════════════════════════════════════════════════════════════
# The Tolead reader processes each row and builds a shipment dict.
# We need to find where it reads the "driver" column and also read
# driver_phone and carrier_email, then upsert to driver_contacts DB.

if "driver_phone_col" in code or 'cols.get("driver_phone")' in code:
    print("Tolead driver_phone reading already exists — skipping")
else:
    # Find where the Tolead reader extracts the driver column
    # Pattern: driver = row[cols["driver"]] or similar
    # Or: s["driver"] = safe_get(row, cols.get("driver"))
    driver_read_pattern = 'cols.get("driver")'
    if driver_read_pattern in code:
        # Find the line that reads the driver column and add phone/email reading after it
        idx = code.index(driver_read_pattern)
        line_end = code.index('\n', idx)
        indent_start = code.rfind('\n', 0, idx) + 1
        indent = ' ' * (idx - indent_start - len(code[indent_start:idx].lstrip()) + len(code[indent_start:idx]) - len(code[indent_start:idx].lstrip()))

        # Get the actual line
        line = code[indent_start:line_end].rstrip()
        # Determine the indentation
        indent = line[:len(line) - len(line.lstrip())]

        driver_phone_code = f'''
{indent}# Read driver phone and carrier email if columns are mapped
{indent}driver_phone_col = cols.get("driver_phone")
{indent}carrier_email_col = cols.get("carrier_email")
{indent}_dp = safe_get(row, driver_phone_col) if driver_phone_col is not None else ""
{indent}_ce = safe_get(row, carrier_email_col) if carrier_email_col is not None else ""
{indent}# Auto-sync to driver_contacts DB if we have data
{indent}if (_dp or _ce) and s.get("efj"):
{indent}    try:
{indent}        _upsert_driver_contact(
{indent}            s["efj"],
{indent}            phone=_dp if _dp else None,
{indent}            carrier_email=_ce if _ce else None,
{indent}        )
{indent}    except Exception:
{indent}        pass
'''
        code = code[:line_end + 1] + driver_phone_code + code[line_end + 1:]
        changes += 1
        print("[2] Added driver_phone/carrier_email reading in Tolead shipment reader")
    else:
        print("WARNING: Could not find Tolead driver column reading pattern")
        print("         Driver phone/carrier email will need manual mapping")

# ══════════════════════════════════════════════════════════════════════════
# Write
# ══════════════════════════════════════════════════════════════════════════
with open(APP, "w") as f:
    f.write(code)

print(f"\n{'=' * 60}")
print(f"Applied {changes} changes to app.py")
print("Restart: systemctl restart csl-dashboard csl-tolead")
