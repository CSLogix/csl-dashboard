#!/usr/bin/env python3
"""
patch_carrier_capabilities.py
Adds can_dray, can_hazmat, can_overweight, can_transload boolean columns
to the carriers table and updates CRUD endpoints to handle them.

Run: python3 /tmp/patch_carrier_capabilities.py
"""
import os

FILE = "/root/csl-bot/csl-doc-tracker/app.py"

with open(FILE) as f:
    code = f.read()

changes = 0

# ══════════════════════════════════════════════════════════════════
# 1) Add capability columns to carriers table (in ensure_tables)
# ══════════════════════════════════════════════════════════════════
# Find the carriers CREATE TABLE and add columns after it via ALTER
# Safer approach: add ALTER TABLE statements after the CREATE TABLE block

CAPABILITY_SQL = '''
        cur.execute("""ALTER TABLE carriers ADD COLUMN IF NOT EXISTS can_dray BOOLEAN DEFAULT FALSE""")
        cur.execute("""ALTER TABLE carriers ADD COLUMN IF NOT EXISTS can_hazmat BOOLEAN DEFAULT FALSE""")
        cur.execute("""ALTER TABLE carriers ADD COLUMN IF NOT EXISTS can_overweight BOOLEAN DEFAULT FALSE""")
        cur.execute("""ALTER TABLE carriers ADD COLUMN IF NOT EXISTS can_transload BOOLEAN DEFAULT FALSE""")
'''

if "can_dray" not in code:
    # Find the carriers CREATE TABLE and add ALTER statements right after
    marker = 'cur.execute("""CREATE TABLE IF NOT EXISTS carriers'
    if marker in code:
        # Find the end of the CREATE TABLE statement (closing """)
        idx = code.index(marker)
        # Find the closing """) for this execute
        end_idx = code.index('""")', idx + len(marker))
        end_idx = code.index('\n', end_idx)
        code = code[:end_idx] + '\n' + CAPABILITY_SQL + code[end_idx:]
        changes += 1
        print("[OK] Added ALTER TABLE for capability columns in ensure_tables()")
    else:
        print("[WARN] Could not find carriers CREATE TABLE — check manually")
else:
    print("[SKIP] can_dray column already in code")

# ══════════════════════════════════════════════════════════════════
# 2) Add capability fields to POST /api/carriers (create)
# ══════════════════════════════════════════════════════════════════
old_create_fields = '''    fields = ["carrier_name", "mc_number", "dot_number", "contact_email", "contact_phone",
              "contact_name", "regions", "ports", "rail_ramps", "equipment_types", "notes", "source", "pickup_area", "destination_area", "date_quoted", "v_code"]
    vals = [body.get(f, "" if f == "carrier_name" else None) for f in fields]'''

new_create_fields = '''    fields = ["carrier_name", "mc_number", "dot_number", "contact_email", "contact_phone",
              "contact_name", "regions", "ports", "rail_ramps", "equipment_types", "notes", "source", "pickup_area", "destination_area", "date_quoted", "v_code",
              "can_dray", "can_hazmat", "can_overweight", "can_transload"]
    bool_fields = {"can_dray", "can_hazmat", "can_overweight", "can_transload"}
    vals = []
    for f in fields:
        if f in bool_fields:
            vals.append(bool(body.get(f, False)))
        elif f == "carrier_name":
            vals.append(body.get(f, ""))
        else:
            vals.append(body.get(f, None))'''

if old_create_fields in code:
    code = code.replace(old_create_fields, new_create_fields, 1)
    changes += 1
    print("[OK] Added capability fields to POST /api/carriers")
elif "can_dray" in code and "bool_fields" in code:
    print("[SKIP] Create endpoint already has capability fields")
else:
    print("[WARN] Could not find create fields block — check manually")

# ══════════════════════════════════════════════════════════════════
# 3) Add capability fields to PUT /api/carriers/{id} (update)
# ══════════════════════════════════════════════════════════════════
old_update_allowed = '''    allowed = {"carrier_name", "mc_number", "dot_number", "contact_email", "contact_phone",
               "contact_name", "regions", "ports", "rail_ramps", "equipment_types", "notes", "pickup_area", "destination_area", "date_quoted", "v_code"}
    sets, params = [], []
    for k, v in body.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            params.append(v)'''

new_update_allowed = '''    allowed = {"carrier_name", "mc_number", "dot_number", "contact_email", "contact_phone",
               "contact_name", "regions", "ports", "rail_ramps", "equipment_types", "notes", "pickup_area", "destination_area", "date_quoted", "v_code",
               "can_dray", "can_hazmat", "can_overweight", "can_transload"}
    bool_fields = {"can_dray", "can_hazmat", "can_overweight", "can_transload"}
    sets, params = [], []
    for k, v in body.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            params.append(bool(v) if k in bool_fields else v)'''

if old_update_allowed in code:
    code = code.replace(old_update_allowed, new_update_allowed, 1)
    changes += 1
    print("[OK] Added capability fields to PUT /api/carriers/{id}")
elif "can_dray" in code and "bool_fields" in code:
    print("[SKIP] Update endpoint already has capability fields")
else:
    print("[WARN] Could not find update allowed block — check manually")

# ══════════════════════════════════════════════════════════════════
# Write
# ══════════════════════════════════════════════════════════════════
with open(FILE, "w") as f:
    f.write(code)

print(f"\n{'=' * 60}")
print(f"Applied {changes} changes to app.py")
if changes > 0:
    print("Restart service: systemctl restart csl-dashboard")
