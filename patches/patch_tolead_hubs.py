#!/usr/bin/env python3
"""
Patch: Add Tolead JFK, LAX, DFW sheets to dashboard.
"""
import shutil, sys

APP = "/root/csl-bot/csl-doc-tracker/app.py"
shutil.copy(APP, APP + ".bak.tolead_hubs")

with open(APP, "r") as f:
    code = f.read()

# ── 1. Add new sheet configs after existing TOLEAD_SKIP_STATUSES ──
old_skip = 'TOLEAD_SKIP_STATUSES = {"Delivered", "Canceled"}'
new_skip = '''TOLEAD_SKIP_STATUSES = {"Delivered", "Canceled"}

# --- Tolead JFK ---
TOLEAD_JFK_SHEET_ID = "1mfhEsK2zg6GWTqMDTo5VwCgY-QC1tkNPknurHMxtBhs"
TOLEAD_JFK_TAB = "Schedule"
TOLEAD_JFK_COLS = {
    "efj": 14, "load_id": 0, "status": 9, "origin": 6,
    "destination": 7, "pickup_date": 3, "pickup_time": 4,
    "delivery": 5, "driver": 15,
}

# --- Tolead LAX ---
TOLEAD_LAX_SHEET_ID = "1YLB6z5LdL0kFYTcfq_H5e6acU8-VLf8nN0XfZrJ-bXo"
TOLEAD_LAX_TAB = "LAX"
TOLEAD_LAX_COLS = {
    "efj": 0, "load_id": 3, "status": 1, "origin": None,
    "destination": 6, "pickup_date": 4, "pickup_time": 5,
    "delivery": 7, "driver": 10,
}

# --- Tolead DFW ---
TOLEAD_DFW_SHEET_ID = "1RfGcq25x4qshlBDWDJD-xBJDlJm6fvDM_w2RTHhn9oI"
TOLEAD_DFW_TAB = "DFW"
TOLEAD_DFW_COLS = {
    "efj": 10, "load_id": 4, "status": 11, "origin": None,
    "destination": 3, "pickup_date": 5, "pickup_time": 6,
    "delivery": None, "driver": 6,
}

TOLEAD_HUB_CONFIGS = {
    "JFK": {"sheet_id": TOLEAD_JFK_SHEET_ID, "tab": TOLEAD_JFK_TAB, "cols": TOLEAD_JFK_COLS, "default_origin": "JFK"},
    "LAX": {"sheet_id": TOLEAD_LAX_SHEET_ID, "tab": TOLEAD_LAX_TAB, "cols": TOLEAD_LAX_COLS, "default_origin": "LAX"},
    "DFW": {"sheet_id": TOLEAD_DFW_SHEET_ID, "tab": TOLEAD_DFW_TAB, "cols": TOLEAD_DFW_COLS, "default_origin": "DFW"},
}'''

assert old_skip in code, "ERROR: Could not find TOLEAD_SKIP_STATUSES"
code = code.replace(old_skip, new_skip)
print("[1/3] Added Tolead JFK/LAX/DFW sheet configs")

# ── 2. Add hub="ORD" to existing Tolead append + new hub reader ──
# Use a unique anchor: the container_url line inside the Tolead append
old_container_url = '                    "container_url": mp_url,\n                })'
new_container_url = '                    "container_url": mp_url,\n                    "hub": "ORD",\n                })'

assert old_container_url in code, "ERROR: Could not find container_url line in Tolead append"
code = code.replace(old_container_url, new_container_url, 1)
print("[2/3] Added hub='ORD' to existing Tolead shipments")

# ── 3. Add hub reader loop after the Tolead except block ──
old_except = '        except Exception as e:\n            log.warning("Tolead sheet read failed: %s", e)'
new_except = '''        except Exception as e:
            log.warning("Tolead ORD sheet read failed: %s", e)

        # --- Read Tolead JFK / LAX / DFW sheets ---
        for hub_name, hub_cfg in TOLEAD_HUB_CONFIGS.items():
            try:
                _time.sleep(1)
                hub_sh = gc.open_by_key(hub_cfg["sheet_id"])
                hub_ws = hub_sh.worksheet(hub_cfg["tab"])
                hub_rows = hub_ws.get_all_values()
                cols = hub_cfg["cols"]
                hub_count = 0
                for ri, row in enumerate(hub_rows[1:], start=1):
                    def _cell(idx, r=row):
                        if idx is None:
                            return ""
                        return r[idx].strip() if len(r) > idx else ""
                    efj = _cell(cols["efj"])
                    load_id = _cell(cols["load_id"])
                    status = _cell(cols["status"])
                    if not efj and not load_id:
                        continue
                    if not status or status in TOLEAD_SKIP_STATUSES:
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
                    })
                    hub_count += 1
                log.info("Tolead %s: %d active loads", hub_name, hub_count)
            except Exception as e:
                log.warning("Tolead %s sheet read failed: %s", hub_name, e)'''

assert old_except in code, "ERROR: Could not find Tolead except block"
code = code.replace(old_except, new_except, 1)
print("[3/3] Added Tolead JFK/LAX/DFW reader loop")

with open(APP, "w") as f:
    f.write(code)

print("\nPatch applied! Restart: systemctl restart csl-dashboard")
