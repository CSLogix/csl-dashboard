#!/usr/bin/env python3
"""
Patch: Add start_row=45 to Boviet Piedra tab config.
Applied to: boviet_monitor.py, app.py, daily_summary.py
"""


# ═══════════════════════════════════════════════════════════════════════════
# 1. boviet_monitor.py — add start_row to Piedra config + filter in loop
# ═══════════════════════════════════════════════════════════════════════════

TARGET = "/root/csl-bot/boviet_monitor.py"
with open(TARGET, "r") as f:
    src = f.read()

# Add start_row to Piedra config
old_piedra = '''"Piedra": {
        "efj_col":       0,
        "load_id_col":   2,   # C — Load ID is col C for Piedra
        "pickup_col":    6,   # G — Pickup Date/Time
        "delivery_col":  7,   # H — Delivery Date/Time
        "status_col":    8,   # I — Status
        "phone_col":    11,   # L — Driver Phone#
        "trailer_col":  12,   # M — Trailer#'''

new_piedra = '''"Piedra": {
        "efj_col":       0,
        "load_id_col":   2,   # C — Load ID is col C for Piedra
        "pickup_col":    6,   # G — Pickup Date/Time
        "delivery_col":  7,   # H — Delivery Date/Time
        "status_col":    8,   # I — Status
        "phone_col":    11,   # L — Driver Phone#
        "trailer_col":  12,   # M — Trailer#
        "start_row":    45,   # skip historical rows'''

if old_piedra in src:
    src = src.replace(old_piedra, new_piedra)
    print("  + boviet_monitor.py: Added start_row=45 to Piedra")
else:
    print("  ! boviet_monitor.py: Could not find Piedra config")

# Add start_row filter to processing loop
old_loop = '''                to_process = []
                for i, row in enumerate(rows):
                    if i == 0:  # skip header
                        continue'''

new_loop = '''                start_row = cfg.get("start_row", 1)
                to_process = []
                for i, row in enumerate(rows):
                    if i == 0:  # skip header
                        continue
                    if i < start_row:
                        continue'''

if old_loop in src:
    src = src.replace(old_loop, new_loop)
    print("  + boviet_monitor.py: Added start_row filter to processing loop")
else:
    print("  ! boviet_monitor.py: Could not find processing loop")

with open(TARGET, "w") as f:
    f.write(src)
print()


# ═══════════════════════════════════════════════════════════════════════════
# 2. app.py — add start_row to Piedra in BOVIET_TAB_CONFIGS + filter loop
# ═══════════════════════════════════════════════════════════════════════════

APP = "/root/csl-bot/csl-doc-tracker/app.py"
with open(APP, "r") as f:
    src2 = f.read()

old_app_piedra = '''"Piedra":           {"efj_col": 0, "load_id_col": 2, "status_col": 8,
                         "pickup_col": 6, "delivery_col": 7,
                         "phone_col": 11, "trailer_col": 12,
                         "default_origin": "Greenville, NC", "default_dest": "Mexia, TX"},'''

new_app_piedra = '''"Piedra":           {"efj_col": 0, "load_id_col": 2, "status_col": 8,
                         "pickup_col": 6, "delivery_col": 7,
                         "phone_col": 11, "trailer_col": 12,
                         "default_origin": "Greenville, NC", "default_dest": "Mexia, TX",
                         "start_row": 45},'''

if old_app_piedra in src2:
    src2 = src2.replace(old_app_piedra, new_app_piedra)
    print("  + app.py: Added start_row=45 to Piedra")
else:
    print("  ! app.py: Could not find Piedra config")

# Add start_row filter to Boviet loop
old_app_loop = '''                    for ri, row in enumerate(rows[1:], start=1):
                        efj = row[cfg["efj_col"]].strip() if len(row) > cfg["efj_col"] else ""'''

new_app_loop = '''                    bov_start = cfg.get("start_row", 1)
                    for ri, row in enumerate(rows[1:], start=1):
                        if ri + 1 < bov_start:
                            continue
                        efj = row[cfg["efj_col"]].strip() if len(row) > cfg["efj_col"] else ""'''

if old_app_loop in src2:
    src2 = src2.replace(old_app_loop, new_app_loop)
    print("  + app.py: Added start_row filter to Boviet loop")
else:
    print("  ! app.py: Could not find Boviet loop")

with open(APP, "w") as f:
    f.write(src2)
print()


# ═══════════════════════════════════════════════════════════════════════════
# 3. daily_summary.py — add start_row to Piedra config + filter loop
# ═══════════════════════════════════════════════════════════════════════════

DS = "/root/csl-bot/daily_summary.py"
with open(DS, "r") as f:
    src3 = f.read()

old_ds_piedra = '"Piedra":          {"efj_col": 0, "load_id_col": 2, "pickup_col": 5, "delivery_col": 6, "status_col": 7},'
new_ds_piedra = '"Piedra":          {"efj_col": 0, "load_id_col": 2, "pickup_col": 5, "delivery_col": 6, "status_col": 7, "start_row": 45},'

if old_ds_piedra in src3:
    src3 = src3.replace(old_ds_piedra, new_ds_piedra)
    print("  + daily_summary.py: Added start_row=45 to Piedra")
else:
    print("  ! daily_summary.py: Could not find Piedra config")

# Add start_row filter to Boviet scan loop
old_ds_loop = '''        entries = []
        for i, row in enumerate(rows):
            if i == 0:
                continue
            status = _safe_get(row, cfg["status_col"])
            if status.lower() in BOVIET_SKIP_STATUSES:'''

new_ds_loop = '''        bov_start = cfg.get("start_row", 1)
        entries = []
        for i, row in enumerate(rows):
            if i == 0:
                continue
            if i < bov_start:
                continue
            status = _safe_get(row, cfg["status_col"])
            if status.lower() in BOVIET_SKIP_STATUSES:'''

if old_ds_loop in src3:
    src3 = src3.replace(old_ds_loop, new_ds_loop)
    print("  + daily_summary.py: Added start_row filter to Boviet scan loop")
else:
    print("  ! daily_summary.py: Could not find Boviet scan loop")

with open(DS, "w") as f:
    f.write(src3)


print("\n  All patched. Restart csl-boviet, csl-dashboard.")
