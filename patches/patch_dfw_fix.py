#!/usr/bin/env python3
"""
Patch: Fix DFW Tolead hub — empty status handling + column corrections

Changes to tolead_monitor.py:
- DFW rows with empty status but populated LINE# (col E) → "Needs to Cover"
- Default origin for DFW → "Irving, TX"

Changes to app.py (dashboard API):
- Fix DFW cols: delivery=2 (was None), driver=12 (was 6/wrong), add phone=13
- Default origin for DFW → "Irving, TX"
- Same empty-status → "Needs to Cover" logic
"""

import re

# ═══════════════════════════════════════════════════════════════════════════
# 1. Patch tolead_monitor.py
# ═══════════════════════════════════════════════════════════════════════════

MONITOR = "/root/csl-bot/tolead_monitor.py"

with open(MONITOR, "r") as f:
    src = f.read()

# 1a. Fix DFW default_origin → "Irving, TX" (currently None)
#     The hub config doesn't have a default_origin field, but the
#     send_tolead_alert function uses it. We need to update the hub config.

# Current DFW config block
old_dfw_monitor = '''    {
        "name": "DFW",
        "sheet_id": "1RfGcq25x4qshlBDWDJD-xBJDlJm6fvDM_w2RTHhn9oI",
        "tab": "DFW",
        "col_load_id": 4, "col_date": 5, "col_time": 6,
        "col_origin": None, "col_dest": 3, "col_status": 11,
        "col_efj": 10, "col_trailer": 12,
    },'''

new_dfw_monitor = '''    {
        "name": "DFW",
        "sheet_id": "1RfGcq25x4qshlBDWDJD-xBJDlJm6fvDM_w2RTHhn9oI",
        "tab": "DFW",
        "col_load_id": 4, "col_date": 5, "col_time": 6,
        "col_origin": None, "col_dest": 3, "col_status": 11,
        "col_efj": 10, "col_trailer": 12, "col_phone": 13,
        "col_delivery_date": 2, "col_appt_id": 1, "col_equipment": 8,
        "default_origin": "Irving, TX",
    },'''

if old_dfw_monitor in src:
    src = src.replace(old_dfw_monitor, new_dfw_monitor)
    print("  + Updated DFW hub config (added phone, delivery_date, equipment, default_origin)")
else:
    print("  ! Could not find DFW hub config block — check manually")

# 1b. Fix the status filter to allow DFW empty-status rows
# Current:
#     status = _col(row, col_status)
#     if not status or status.lower() in SKIP_STATUSES:
#         continue
# New: for DFW, if LINE# (col_load_id) is populated and status is empty, treat as active

old_filter = '''        status = _col(row, col_status)
        if not status or status.lower() in SKIP_STATUSES:
            continue'''

new_filter = '''        status = _col(row, col_status)
        load_id_val = _col(row, hub["col_load_id"])
        if status and status.lower() in SKIP_STATUSES:
            continue
        # DFW: empty status + populated LINE# = "Needs to Cover"
        if not status:
            if hub["name"] == "DFW" and load_id_val:
                status = "Needs to Cover"
            else:
                continue'''

if old_filter in src:
    src = src.replace(old_filter, new_filter)
    print("  + Fixed status filter — DFW empty status + LINE# = 'Needs to Cover'")
else:
    print("  ! Could not find status filter block — check manually")

# 1c. Update origin handling — use default_origin from hub config
# Check if there's an origin extraction line
if '"default_origin"' not in src.split("HUBS")[0]:
    # The hub configs for ORD/JFK/LAX don't have default_origin yet
    # Let's check the origin line in the processing loop
    pass

with open(MONITOR, "w") as f:
    f.write(src)

print(f"\n  tolead_monitor.py patched: {MONITOR}")


# ═══════════════════════════════════════════════════════════════════════════
# 2. Patch app.py (dashboard API)
# ═══════════════════════════════════════════════════════════════════════════

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    src2 = f.read()

# 2a. Fix DFW column mapping
old_dfw_cols = '''TOLEAD_DFW_COLS = {
    "efj": 10, "load_id": 4, "status": 11, "origin": None,
    "destination": 3, "pickup_date": 5, "pickup_time": 6,
    "delivery": None, "driver": 6,
}'''

new_dfw_cols = '''TOLEAD_DFW_COLS = {
    "efj": 10, "load_id": 4, "status": 11, "origin": None,
    "destination": 3, "pickup_date": 5, "pickup_time": 6,
    "delivery": 2, "driver": 12, "phone": 13,
    "appt_id": 1, "equipment": 8,
}'''

if old_dfw_cols in src2:
    src2 = src2.replace(old_dfw_cols, new_dfw_cols)
    print("  + Fixed DFW cols (delivery=2, driver=12, phone=13, appt_id=1, equipment=8)")
else:
    print("  ! Could not find DFW cols block — check manually")

# 2b. Fix DFW default_origin to "Irving, TX"
old_dfw_hub_cfg = '''    "DFW": {"sheet_id": TOLEAD_DFW_SHEET_ID, "tab": TOLEAD_DFW_TAB, "cols": TOLEAD_DFW_COLS, "default_origin": "DFW"},'''

new_dfw_hub_cfg = '''    "DFW": {"sheet_id": TOLEAD_DFW_SHEET_ID, "tab": TOLEAD_DFW_TAB, "cols": TOLEAD_DFW_COLS, "default_origin": "Irving, TX"},'''

if old_dfw_hub_cfg in src2:
    src2 = src2.replace(old_dfw_hub_cfg, new_dfw_hub_cfg)
    print("  + Fixed DFW default_origin → 'Irving, TX'")
else:
    print("  ! Could not find DFW hub config line — check manually")

# 2c. Fix the status filter for DFW empty-status rows
# Current:
#     if not status or status in TOLEAD_SKIP_STATUSES:
#         continue
# New: DFW empty status + populated load_id = "Needs to Cover"

old_api_filter = '''                    if not efj and not load_id:
                        continue
                    if not status or status in TOLEAD_SKIP_STATUSES:
                        continue'''

new_api_filter = '''                    if not efj and not load_id:
                        continue
                    if status and status in TOLEAD_SKIP_STATUSES:
                        continue
                    # DFW: empty status + populated LINE# = "Needs to Cover"
                    if not status:
                        if hub_name == "DFW" and load_id:
                            status = "Needs to Cover"
                        else:
                            continue'''

if old_api_filter in src2:
    src2 = src2.replace(old_api_filter, new_api_filter)
    print("  + Fixed API status filter — DFW empty status + LINE# = 'Needs to Cover'")
else:
    print("  ! Could not find API status filter — check manually")

with open(APP, "w") as f:
    f.write(src2)

print(f"\n  app.py patched: {APP}")
print("\n  Done. Restart csl-tolead and csl-dashboard.")
