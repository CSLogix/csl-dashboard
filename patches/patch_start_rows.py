#!/usr/bin/env python3
"""
Patch: Add start_row offsets to all Tolead hub configs.
ORD: row 790, LAX: row 755, DFW: row 172, JFK: row 184

Applied to: tolead_monitor.py, app.py, daily_summary.py
"""


# ═══════════════════════════════════════════════════════════════════════════
# 1. tolead_monitor.py — add start_row to hub configs + use in filter loop
# ═══════════════════════════════════════════════════════════════════════════

MONITOR = "/root/csl-bot/tolead_monitor.py"
with open(MONITOR, "r") as f:
    src = f.read()

# Add start_row to each hub config
for old, new, label in [
    ('"col_loads": 8,\n    },',
     '"col_loads": 8,\n        "start_row": 790,\n    },',
     "ORD"),
    ('"default_origin": "Garden City, NY",\n    },',
     '"default_origin": "Garden City, NY",\n        "start_row": 184,\n    },',
     "JFK"),
    ('"default_origin": "Vernon, CA",\n    },',
     '"default_origin": "Vernon, CA",\n        "start_row": 755,\n    },',
     "LAX"),
    ('"default_origin": "Irving, TX",\n    },',
     '"default_origin": "Irving, TX",\n        "start_row": 172,\n    },',
     "DFW"),
]:
    if old in src:
        src = src.replace(old, new)
        print(f"  + tolead_monitor.py: Added start_row to {label}")
    else:
        print(f"  ! tolead_monitor.py: Could not find {label} config end")

# Update the filter loop to skip rows before start_row
# The loop is: for i, row in enumerate(rows[1:], start=2):
old_loop = '''    to_process = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) <= col_efj:
            continue
        status = _col(row, col_status)
        load_id_val = _col(row, hub["col_load_id"])'''

new_loop = '''    start_row = hub.get("start_row", 2)
    to_process = []
    for i, row in enumerate(rows[1:], start=2):
        if i < start_row:
            continue
        if len(row) <= col_efj:
            continue
        status = _col(row, col_status)
        load_id_val = _col(row, hub["col_load_id"])'''

if old_loop in src:
    src = src.replace(old_loop, new_loop)
    print("  + tolead_monitor.py: Added start_row filter to processing loop")
else:
    print("  ! tolead_monitor.py: Could not find processing loop header")

with open(MONITOR, "w") as f:
    f.write(src)
print()


# ═══════════════════════════════════════════════════════════════════════════
# 2. app.py — add start_row to hub configs + use in hub loop
# ═══════════════════════════════════════════════════════════════════════════

APP = "/root/csl-bot/csl-doc-tracker/app.py"
with open(APP, "r") as f:
    src2 = f.read()

# Add start_row to TOLEAD_HUB_CONFIGS entries
# ORD
old_ord_cfg = '"ORD": {"sheet_id": TOLEAD_SHEET_ID, "tab": TOLEAD_TAB, "cols": TOLEAD_ORD_COLS, "default_origin": "ORD"},'
new_ord_cfg = '"ORD": {"sheet_id": TOLEAD_SHEET_ID, "tab": TOLEAD_TAB, "cols": TOLEAD_ORD_COLS, "default_origin": "ORD", "start_row": 790},'
if old_ord_cfg in src2:
    src2 = src2.replace(old_ord_cfg, new_ord_cfg)
    print("  + app.py: Added start_row=790 to ORD")
else:
    print("  ! app.py: Could not find ORD hub config")

# JFK
old_jfk_cfg = '"JFK": {"sheet_id": TOLEAD_JFK_SHEET_ID, "tab": TOLEAD_JFK_TAB, "cols": TOLEAD_JFK_COLS, "default_origin": "Garden City, NY"},'
new_jfk_cfg = '"JFK": {"sheet_id": TOLEAD_JFK_SHEET_ID, "tab": TOLEAD_JFK_TAB, "cols": TOLEAD_JFK_COLS, "default_origin": "Garden City, NY", "start_row": 184},'
if old_jfk_cfg in src2:
    src2 = src2.replace(old_jfk_cfg, new_jfk_cfg)
    print("  + app.py: Added start_row=184 to JFK")
else:
    print("  ! app.py: Could not find JFK hub config")

# LAX
old_lax_cfg = '"LAX": {"sheet_id": TOLEAD_LAX_SHEET_ID, "tab": TOLEAD_LAX_TAB, "cols": TOLEAD_LAX_COLS, "default_origin": "Vernon, CA"},'
new_lax_cfg = '"LAX": {"sheet_id": TOLEAD_LAX_SHEET_ID, "tab": TOLEAD_LAX_TAB, "cols": TOLEAD_LAX_COLS, "default_origin": "Vernon, CA", "start_row": 755},'
if old_lax_cfg in src2:
    src2 = src2.replace(old_lax_cfg, new_lax_cfg)
    print("  + app.py: Added start_row=755 to LAX")
else:
    print("  ! app.py: Could not find LAX hub config")

# DFW
old_dfw_cfg = '"DFW": {"sheet_id": TOLEAD_DFW_SHEET_ID, "tab": TOLEAD_DFW_TAB, "cols": TOLEAD_DFW_COLS, "default_origin": "Irving, TX"},'
new_dfw_cfg = '"DFW": {"sheet_id": TOLEAD_DFW_SHEET_ID, "tab": TOLEAD_DFW_TAB, "cols": TOLEAD_DFW_COLS, "default_origin": "Irving, TX", "start_row": 172},'
if old_dfw_cfg in src2:
    src2 = src2.replace(old_dfw_cfg, new_dfw_cfg)
    print("  + app.py: Added start_row=172 to DFW")
else:
    print("  ! app.py: Could not find DFW hub config")

# Update hub loop to use start_row
old_hub_loop = '''            for ri, row in enumerate(hub_rows[1:], start=1):'''
new_hub_loop = '''            hub_start = hub_cfg.get("start_row", 1)
            for ri, row in enumerate(hub_rows[1:], start=1):
                if ri + 1 < hub_start:  # ri is 1-indexed data row, hub_start is sheet row
                    continue'''

if old_hub_loop in src2:
    src2 = src2.replace(old_hub_loop, new_hub_loop)
    print("  + app.py: Added start_row filter to hub loop")
else:
    print("  ! app.py: Could not find hub loop")

with open(APP, "w") as f:
    f.write(src2)
print()


# ═══════════════════════════════════════════════════════════════════════════
# 3. daily_summary.py — add start_row to hub configs + use in scan_tolead
# ═══════════════════════════════════════════════════════════════════════════

DS = "/root/csl-bot/daily_summary.py"
with open(DS, "r") as f:
    src3 = f.read()

# Add start_row to each hub config in TOLEAD_HUBS
for old, new, label in [
    ('"needs_cover_statuses": {"new"},\n    },',
     '"needs_cover_statuses": {"new"},\n        "start_row": 790,\n    },',
     "ORD"),
    ('"needs_cover_statuses": {"new"},\n    },',  # JFK also has this — need to be careful
     '"needs_cover_statuses": {"new"},\n        "start_row": 184,\n    },',
     "JFK"),
    ('"needs_cover_statuses": {"unassigned"},\n    },',
     '"needs_cover_statuses": {"unassigned"},\n        "start_row": 755,\n    },',
     "LAX"),
    ('"default_origin": "Irving, TX",\n    },',
     '"default_origin": "Irving, TX",\n        "start_row": 172,\n    },',
     "DFW"),
]:
    if old in src3:
        src3 = src3.replace(old, new, 1)  # Replace only first occurrence
        print(f"  + daily_summary.py: Added start_row to {label}")
    else:
        print(f"  ! daily_summary.py: Could not find {label} config end")

# Update scan_tolead loop to skip rows before start_row
old_scan_loop = '''        entries = []
        needs_cover = []  # DFW loads needing coverage
        for i, row in enumerate(rows[1:], start=2):  # skip header
            if len(row) <= col_efj:
                continue'''

new_scan_loop = '''        start_row = hub.get("start_row", 2)
        entries = []
        needs_cover = []  # loads needing coverage
        for i, row in enumerate(rows[1:], start=2):  # skip header
            if i < start_row:
                continue
            if len(row) <= col_efj:
                continue'''

if old_scan_loop in src3:
    src3 = src3.replace(old_scan_loop, new_scan_loop)
    print("  + daily_summary.py: Added start_row filter to scan_tolead loop")
else:
    print("  ! daily_summary.py: Could not find scan_tolead loop header")

with open(DS, "w") as f:
    f.write(src3)


# ═══════════════════════════════════════════════════════════════════════════
print("\n  All patched. Restart csl-tolead, csl-dashboard.")
