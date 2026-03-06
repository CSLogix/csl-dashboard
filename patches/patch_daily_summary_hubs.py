#!/usr/bin/env python3
"""
Patch: daily_summary.py — Update ORD/JFK/LAX hub configs + generalize Needs to Cover

1. ORD: add col_phone, col_delivery, col_appt_id, col_loads, col_loads_j
2. JFK: add col_phone, col_delivery, col_loads_j, default_origin
3. LAX: fix col_dest/col_status + add col_origin, col_phone, col_delivery, col_loads_j, default_origin
4. Generalize DFW "Needs to Cover" collection to all hubs
"""

TARGET = "/root/csl-bot/daily_summary.py"

with open(TARGET, "r") as f:
    src = f.read()


# ── 1. Update ORD hub config ──────────────────────────────────────────────

old_ord = '''        "name": "ORD",
        "sheet_id": "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac",
        "tab": "Schedule",
        "col_load_id": 1, "col_date": 4, "col_origin": 6,
        "col_dest": 7, "col_status": 9, "col_efj": 15,
    },'''

new_ord = '''        "name": "ORD",
        "sheet_id": "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac",
        "tab": "Schedule",
        "col_load_id": 1, "col_date": 4, "col_origin": 6,
        "col_dest": 7, "col_status": 9, "col_efj": 15,
        "col_phone": 17, "col_trailer": 16,
        "col_delivery": 3, "col_appt_id": 2, "col_loads_j": 8,
        "needs_cover_statuses": {"new"},
    },'''

if old_ord in src:
    src = src.replace(old_ord, new_ord)
    print("  + Updated ORD hub config in daily_summary.py")
else:
    print("  ! Could not find ORD hub config")


# ── 2. Update JFK hub config ──────────────────────────────────────────────

old_jfk = '''        "name": "JFK",
        "sheet_id": "1mfhEsK2zg6GWTqMDTo5VwCgY-QC1tkNPknurHMxtBhs",
        "tab": "Schedule",
        "col_load_id": 0, "col_date": 3, "col_origin": 6,
        "col_dest": 7, "col_status": 9, "col_efj": 14,
    },'''

new_jfk = '''        "name": "JFK",
        "sheet_id": "1mfhEsK2zg6GWTqMDTo5VwCgY-QC1tkNPknurHMxtBhs",
        "tab": "Schedule",
        "col_load_id": 0, "col_date": 3, "col_origin": 6,
        "col_dest": 7, "col_status": 9, "col_efj": 14,
        "col_phone": 16, "col_trailer": 15,
        "col_delivery": 5, "col_loads_j": 9,
        "default_origin": "Garden City, NY",
        "needs_cover_statuses": {"new"},
    },'''

if old_jfk in src:
    src = src.replace(old_jfk, new_jfk)
    print("  + Updated JFK hub config")
else:
    print("  ! Could not find JFK hub config")


# ── 3. Fix LAX hub config ────────────────────────────────────────────────

old_lax = '''        "name": "LAX",
        "sheet_id": "1YLB6z5LdL0kFYTcfq_H5e6acU8-VLf8nN0XfZrJ-bXo",
        "tab": "LAX",
        "col_load_id": 3, "col_date": 4, "col_origin": None,
        "col_dest": 6, "col_status": 8, "col_efj": 0,
    },'''

new_lax = '''        "name": "LAX",
        "sheet_id": "1YLB6z5LdL0kFYTcfq_H5e6acU8-VLf8nN0XfZrJ-bXo",
        "tab": "LAX",
        "col_load_id": 3, "col_date": 4, "col_origin": 6,
        "col_dest": 7, "col_status": 9, "col_efj": 0,
        "col_phone": 12, "col_trailer": 11,
        "col_delivery": 8, "col_loads_j": 9,
        "default_origin": "Vernon, CA",
        "needs_cover_statuses": {"unassigned"},
    },'''

if old_lax in src:
    src = src.replace(old_lax, new_lax)
    print("  + Fixed LAX hub config (dest:6->7, status:8->9, +origin/phone/trailer/delivery)")
else:
    print("  ! Could not find LAX hub config")


# ── 4. Generalize "Needs to Cover" from DFW-only to all hubs ─────────────
# Replace the DFW-specific logic in scan_tolead() with generic logic

old_scan_logic = '''            # DFW: derive status from E (LINE#) + J (Loads)
            if hub_name == "DFW":
                if not load_id_val:
                    continue
                if status and status in TOLEAD_SKIP_STATUSES:
                    continue
                col_j = _safe_get(row, hub.get("col_loads_j", 9))
                if col_j.lower() not in ("scheduled", "picked"):
                    # E populated + J not scheduled = needs covering
                    dest = _safe_get(row, hub["col_dest"])
                    pickup = _safe_get(row, hub["col_date"])
                    phone = _safe_get(row, hub.get("col_phone", 13))
                    needs_cover.append({
                        "load_id": load_id_val,
                        "efj": _safe_get(row, col_efj),
                        "dest": dest,
                        "pickup": pickup,
                        "phone": phone,
                    })
                    continue
            else:
                if status in TOLEAD_SKIP_STATUSES:
                    continue'''

new_scan_logic = '''            if status and status in TOLEAD_SKIP_STATUSES:
                continue
            if not load_id_val:
                continue

            # Check if load "Needs to Cover" based on hub-specific logic
            ntc_statuses = hub.get("needs_cover_statuses")
            if ntc_statuses and status.lower() in ntc_statuses:
                # Status indicates uncovered load
                dest = _safe_get(row, hub["col_dest"])
                pickup = _safe_get(row, hub["col_date"])
                phone = _safe_get(row, hub.get("col_phone", -1)) if hub.get("col_phone") else ""
                needs_cover.append({
                    "load_id": load_id_val,
                    "efj": _safe_get(row, col_efj),
                    "dest": dest,
                    "pickup": pickup,
                    "phone": phone,
                })
                continue
            # DFW: derive from col_loads_j (scheduling column separate from status)
            if hub_name == "DFW":
                col_j = _safe_get(row, hub.get("col_loads_j", 9))
                if col_j.lower() not in ("scheduled", "picked"):
                    dest = _safe_get(row, hub["col_dest"])
                    pickup = _safe_get(row, hub["col_date"])
                    phone = _safe_get(row, hub.get("col_phone", 13))
                    needs_cover.append({
                        "load_id": load_id_val,
                        "efj": _safe_get(row, col_efj),
                        "dest": dest,
                        "pickup": pickup,
                        "phone": phone,
                    })
                    continue'''

if old_scan_logic in src:
    src = src.replace(old_scan_logic, new_scan_logic)
    print("  + Generalized Needs to Cover logic for all hubs")
else:
    print("  ! Could not find DFW scan logic block")


# ── 5. Update _build_needs_cover_section docstring ────────────────────────

old_ntc_doc = '"""Build orange \'Needs to Cover\' section for DFW daily summary."""'
new_ntc_doc = '"""Build orange \'Needs to Cover\' section for Tolead daily summary."""'

if old_ntc_doc in src:
    src = src.replace(old_ntc_doc, new_ntc_doc)
    print("  + Updated _build_needs_cover_section docstring")


# ── 6. Remove "DFW" restriction from Needs to Cover email append ─────────

old_ntc_comment = '                # Append Needs to Cover section for DFW'
new_ntc_comment = '                # Append Needs to Cover section if any'

if old_ntc_comment in src:
    src = src.replace(old_ntc_comment, new_ntc_comment)
    print("  + Updated Needs to Cover comment")


with open(TARGET, "w") as f:
    f.write(src)

print(f"\n  Patched: {TARGET}")
print("  Done.")
