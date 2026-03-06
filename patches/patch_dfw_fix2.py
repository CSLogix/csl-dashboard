#!/usr/bin/env python3
"""
Patch v2: Fix DFW Tolead hub — correct status derivation logic

DFW status logic (per user):
  - "Needs to Cover" = Col E (LINE#) has text + Col J (Loads) is NOT "Scheduled"
  - Once Col J = "Scheduled" → load is covered/assigned
  - Col J = "Picked" → picked up
  - Col L = "Delivered" → done, skip
  - Col M (12) = driver trailer#, Col N (13) = driver phone#
  - Col K (10) = EFJ Pro# with Macropoint hyperlink
  - Origin always "Irving, TX"
"""

# ═══════════════════════════════════════════════════════════════════════════
# 1. Patch tolead_monitor.py
# ═══════════════════════════════════════════════════════════════════════════

MONITOR = "/root/csl-bot/tolead_monitor.py"

with open(MONITOR, "r") as f:
    src = f.read()

# Fix the status filter
old_filter_monitor = '''        status = _col(row, col_status)
        load_id_val = _col(row, hub["col_load_id"])
        if status and status.lower() in SKIP_STATUSES:
            continue
        # DFW: empty status + populated LINE# = "Needs to Cover"
        if not status:
            if hub["name"] == "DFW" and load_id_val:
                status = "Needs to Cover"
            else:
                continue
        mp_url = links[i - 1] if i - 1 < len(links) else ""
        if not mp_url or "macropoint" not in mp_url.lower():
            continue
        to_process.append((i, row, mp_url))'''

new_filter_monitor = '''        status = _col(row, col_status)
        load_id_val = _col(row, hub["col_load_id"])

        # DFW: status derived from Col E (LINE#) + Col J (Loads)
        if hub["name"] == "DFW":
            if not load_id_val:
                continue  # No LINE# = no load
            if status and status.lower() in SKIP_STATUSES:
                continue
            col_j = _col(row, 9)  # Col J = "Loads" / scheduling status
            if col_j.lower() not in ("scheduled", "picked"):
                # E has text + J not scheduled = needs covering, no MP to scrape
                continue
            # Covered load — use J value as status if L is empty
            if not status:
                status = col_j.capitalize()
        else:
            if status and status.lower() in SKIP_STATUSES:
                continue
            if not status:
                continue

        mp_url = links[i - 1] if i - 1 < len(links) else ""
        if not mp_url or "macropoint" not in mp_url.lower():
            continue
        to_process.append((i, row, mp_url))'''

if old_filter_monitor in src:
    src = src.replace(old_filter_monitor, new_filter_monitor)
    print("  + Fixed tolead_monitor.py — DFW uses Col E + Col J logic")
else:
    print("  ! Could not find monitor filter block — check manually")

with open(MONITOR, "w") as f:
    f.write(src)

print(f"  tolead_monitor.py patched\n")


# ═══════════════════════════════════════════════════════════════════════════
# 2. Patch app.py (dashboard API)
# ═══════════════════════════════════════════════════════════════════════════

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    src2 = f.read()

# Fix the DFW status filter + add driver/phone + MP link
old_filter_api = '''                    efj = _cell(cols["efj"])
                    load_id = _cell(cols["load_id"])
                    status = _cell(cols["status"])
                    if not efj and not load_id:
                        continue
                    if status and status in TOLEAD_SKIP_STATUSES:
                        continue
                    # DFW: empty status + populated LINE# = "Needs to Cover"
                    if not status:
                        if hub_name == "DFW" and load_id:
                            status = "Needs to Cover"
                        else:
                            continue
                    origin = _cell(cols["origin"]) or hub_cfg["default_origin"]
                    pickup_date = _cell(cols["pickup_date"])
                    pickup_time = _cell(cols["pickup_time"])
                    pickup = f"{pickup_date} {pickup_time}".strip() if pickup_date else ""
                    delivery = _cell(cols["delivery"])
                    all_shipments.append({
                        "account": "Tolead", "efj": efj or load_id,
                        "move_type": "FTL", "container": load_id, "bol": "",
                        "ssl": "", "carrier": "",
                        "origin": origin,
                        "destination": _cell(cols["destination"]),
                        "eta": pickup_date, "lfd": "",
                        "pickup": pickup, "delivery": delivery,
                        "status": status, "notes": "", "bot_alert": "",
                        "return_port": "", "rep": "Tolead",
                        "container_url": "",
                        "hub": hub_name,
                    })'''

new_filter_api = '''                    efj = _cell(cols["efj"])
                    load_id = _cell(cols["load_id"])
                    status = _cell(cols["status"])

                    # DFW: status derived from Col E (LINE#) + Col J (Loads)
                    if hub_name == "DFW":
                        if not load_id:
                            continue  # No LINE# = no load
                        if status and status in TOLEAD_SKIP_STATUSES:
                            continue
                        col_j = row[9].strip() if len(row) > 9 else ""
                        if col_j.lower() not in ("scheduled", "picked"):
                            # E has text + J not scheduled → "Needs to Cover"
                            status = "Needs to Cover"
                        elif not status:
                            status = col_j.capitalize()
                    else:
                        if not efj and not load_id:
                            continue
                        if status and status in TOLEAD_SKIP_STATUSES:
                            continue
                        if not status:
                            continue

                    origin = _cell(cols["origin"]) or hub_cfg["default_origin"]
                    pickup_date = _cell(cols["pickup_date"])
                    pickup_time = _cell(cols["pickup_time"])
                    pickup = f"{pickup_date} {pickup_time}".strip() if pickup_date else ""
                    delivery = _cell(cols["delivery"])
                    driver_trailer = _cell(cols.get("driver")) if cols.get("driver") is not None else ""
                    driver_phone = _cell(cols.get("phone")) if cols.get("phone") is not None else ""

                    all_shipments.append({
                        "account": "Tolead", "efj": efj or load_id,
                        "move_type": "FTL", "container": load_id, "bol": "",
                        "ssl": "", "carrier": "",
                        "origin": origin,
                        "destination": _cell(cols["destination"]),
                        "eta": pickup_date, "lfd": "",
                        "pickup": pickup, "delivery": delivery,
                        "status": status, "notes": "", "bot_alert": "",
                        "return_port": "", "rep": "Tolead",
                        "container_url": "",
                        "hub": hub_name,
                        "driver": driver_trailer,
                        "driver_phone": driver_phone,
                    })'''

if old_filter_api in src2:
    src2 = src2.replace(old_filter_api, new_filter_api)
    print("  + Fixed app.py — DFW uses Col E + Col J logic, extracts driver/phone")
else:
    print("  ! Could not find API filter block — check manually")

with open(APP, "w") as f:
    f.write(src2)

print(f"  app.py patched\n")
print("  Done. Restart csl-tolead and csl-dashboard.")
