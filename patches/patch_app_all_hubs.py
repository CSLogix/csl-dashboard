#!/usr/bin/env python3
"""
Patch: app.py — All hub column fixes + address shortening + Boviet fixes

1. Add _shorten_address() helper
2. Convert ORD from legacy constants to TOLEAD_HUB_CONFIGS
3. Fix JFK cols (add phone, default_origin)
4. Fix LAX cols (3 wrong + add missing)
5. Fix Boviet Piedra (status_col wrong + add pickup/delivery/phone/trailer)
6. Fix Boviet Hanson (add pickup/delivery/phone/trailer)
7. Apply _shorten_address() to all Tolead origins/destinations
8. Extract Boviet phone/trailer/pickup/delivery in shipment builder
"""

TARGET = "/root/csl-bot/csl-doc-tracker/app.py"

with open(TARGET, "r") as f:
    src = f.read()


# ── 1. Add _shorten_address() helper ─────────────────────────────────────
# Insert before BOVIET_SKIP_TABS or BOVIET_TAB_CONFIGS

shorten_fn = '''import re as _re

def _shorten_address(addr):
    """Shorten full address to city/state/zip format.
    '640 N Central Ave, Wood Dale, IL 60191' -> 'Wood Dale, IL 60191'
    '(66Z) Kansas City, MO (14hrs)' -> 'Kansas City, MO'
    '(ATL) 495 Horizon Dr Ste 300 Suwanee GA 30024' -> 'Suwanee, GA 30024'
    """
    if not addr:
        return addr
    # Strip leading parenthetical codes like (66Z), (ATL), (LAX)
    addr = _re.sub(r'^\\(\\w+\\)\\s*', '', addr).strip()
    # Strip trailing parenthetical like (14hrs)
    addr = _re.sub(r'\\s*\\([^)]*\\)\\s*$', '', addr).strip()
    # Try to match "City, ST ZIP" at end of address
    m = _re.search(r'([A-Za-z][A-Za-z .]+),\\s*([A-Z]{2})\\s+(\\d{5}(?:-\\d{4})?)\\s*$', addr)
    if m:
        return f"{m.group(1).strip()}, {m.group(2)} {m.group(3)}"
    # Try "City, ST" without zip
    m = _re.search(r'([A-Za-z][A-Za-z .]+),\\s*([A-Z]{2})\\s*$', addr)
    if m:
        return f"{m.group(1).strip()}, {m.group(2)}"
    # Try "City ST ZIP" without comma (common in some formats)
    m = _re.search(r'([A-Za-z][A-Za-z .]+)\\s+([A-Z]{2})\\s+(\\d{5}(?:-\\d{4})?)\\s*$', addr)
    if m:
        return f"{m.group(1).strip()}, {m.group(2)} {m.group(3)}"
    return addr


'''

if "_shorten_address" not in src:
    anchor = "BOVIET_SKIP_TABS"
    if anchor in src:
        src = src.replace(anchor, shorten_fn + anchor)
        print("  + Added _shorten_address() helper")
    else:
        print("  ! Could not find BOVIET_SKIP_TABS anchor for _shorten_address")
else:
    print("  ~ _shorten_address() already exists")


# ── 2. Fix BOVIET_TAB_CONFIGS — Piedra status + add fields ───────────────

old_boviet_configs = '''BOVIET_TAB_CONFIGS = {
    "DTE Fresh/Stock":  {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Sundance":         {"efj_col": 0, "load_id_col": 1, "status_col": 6},
    "Renewable Energy": {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Radiance Solar":   {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Piedra":           {"efj_col": 0, "load_id_col": 2, "status_col": 7},
    "Hanson":           {"efj_col": 0, "load_id_col": 1, "status_col": 6},
}'''

new_boviet_configs = '''BOVIET_TAB_CONFIGS = {
    "DTE Fresh/Stock":  {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Sundance":         {"efj_col": 0, "load_id_col": 1, "status_col": 6},
    "Renewable Energy": {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Radiance Solar":   {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Piedra":           {"efj_col": 0, "load_id_col": 2, "status_col": 8,
                         "pickup_col": 6, "delivery_col": 7,
                         "phone_col": 11, "trailer_col": 12,
                         "default_origin": "Greenville, NC", "default_dest": "Mexia, TX"},
    "Hanson":           {"efj_col": 0, "load_id_col": 1, "status_col": 6,
                         "pickup_col": 4, "delivery_col": 5,
                         "phone_col": 8, "trailer_col": 10},
}'''

if old_boviet_configs in src:
    src = src.replace(old_boviet_configs, new_boviet_configs)
    print("  + Fixed BOVIET_TAB_CONFIGS (Piedra status:7->8, +pickup/delivery/phone/trailer)")
else:
    print("  ! Could not find BOVIET_TAB_CONFIGS")


# ── 3. Update Boviet shipment builder to extract new fields ───────────────

old_boviet_append = '''                all_shipments.append({
                    "account": "Boviet", "efj": efj, "move_type": "FTL",
                    "container": load_id, "bol": "", "ssl": "",
                    "carrier": "", "origin": "", "destination": "",
                    "eta": "", "lfd": "", "pickup": "", "delivery": "",
                    "status": status, "notes": "", "bot_alert": "",
                    "return_port": "", "rep": "Boviet",
                    "container_url": bov_mp_url,
                })'''

new_boviet_append = '''                # Extract optional fields from config
                bov_pickup = ""
                bov_delivery = ""
                bov_phone = ""
                bov_trailer = ""
                bov_origin = cfg.get("default_origin", "")
                bov_dest = cfg.get("default_dest", "")
                if "pickup_col" in cfg:
                    bov_pickup = row[cfg["pickup_col"]].strip() if len(row) > cfg["pickup_col"] else ""
                if "delivery_col" in cfg:
                    bov_delivery = row[cfg["delivery_col"]].strip() if len(row) > cfg["delivery_col"] else ""
                if "phone_col" in cfg:
                    bov_phone = row[cfg["phone_col"]].strip() if len(row) > cfg["phone_col"] else ""
                if "trailer_col" in cfg:
                    bov_trailer = row[cfg["trailer_col"]].strip() if len(row) > cfg["trailer_col"] else ""

                all_shipments.append({
                    "account": "Boviet", "efj": efj, "move_type": "FTL",
                    "container": load_id, "bol": "", "ssl": "",
                    "carrier": "", "origin": bov_origin, "destination": bov_dest,
                    "eta": "", "lfd": "",
                    "pickup": bov_pickup, "delivery": bov_delivery,
                    "status": status, "notes": "", "bot_alert": "",
                    "return_port": "", "rep": "Boviet",
                    "container_url": bov_mp_url,
                    "driver": bov_trailer,
                    "driver_phone": bov_phone,
                    "hub": tab_name,
                })'''

if old_boviet_append in src:
    src = src.replace(old_boviet_append, new_boviet_append)
    print("  + Updated Boviet shipment builder (phone/trailer/pickup/delivery/origin/dest)")
else:
    print("  ! Could not find Boviet shipment append block")


# ── 4. Fix TOLEAD_JFK_COLS — add phone ────────────────────────────────────

old_jfk_cols = '''TOLEAD_JFK_COLS = {
    "efj": 14, "load_id": 0, "status": 9, "origin": 6,
    "destination": 7, "pickup_date": 3, "pickup_time": 4,
    "delivery": 5, "driver": 15,
}'''

new_jfk_cols = '''TOLEAD_JFK_COLS = {
    "efj": 14, "load_id": 0, "status": 9, "origin": 6,
    "destination": 7, "pickup_date": 3, "pickup_time": 4,
    "delivery": 5, "driver": 15, "phone": 16,
}'''

if old_jfk_cols in src:
    src = src.replace(old_jfk_cols, new_jfk_cols)
    print("  + Updated TOLEAD_JFK_COLS (+phone:16)")
else:
    print("  ! Could not find TOLEAD_JFK_COLS")


# ── 5. Fix TOLEAD_LAX_COLS — 3 wrong + add missing ───────────────────────

old_lax_cols = '''TOLEAD_LAX_COLS = {
    "efj": 0, "load_id": 3, "status": 8, "origin": None,
    "destination": 6, "pickup_date": 4, "pickup_time": 5,
    "delivery": 7, "driver": 10,
}'''

new_lax_cols = '''TOLEAD_LAX_COLS = {
    "efj": 0, "load_id": 3, "status": 9, "origin": 6,
    "destination": 7, "pickup_date": 4, "pickup_time": 5,
    "delivery": 8, "driver": 11, "phone": 12,
}'''

if old_lax_cols in src:
    src = src.replace(old_lax_cols, new_lax_cols)
    print("  + Fixed TOLEAD_LAX_COLS (dest:6->7, status:8->9, driver:10->11, +origin/phone)")
else:
    print("  ! Could not find TOLEAD_LAX_COLS")


# ── 6. Update JFK default_origin in TOLEAD_HUB_CONFIGS ───────────────────

old_jfk_hub = '"JFK": {"sheet_id": TOLEAD_JFK_SHEET_ID, "tab": TOLEAD_JFK_TAB, "cols": TOLEAD_JFK_COLS, "default_origin": "JFK"},'
new_jfk_hub = '"JFK": {"sheet_id": TOLEAD_JFK_SHEET_ID, "tab": TOLEAD_JFK_TAB, "cols": TOLEAD_JFK_COLS, "default_origin": "Garden City, NY"},'

if old_jfk_hub in src:
    src = src.replace(old_jfk_hub, new_jfk_hub)
    print("  + Updated JFK default_origin to 'Garden City, NY'")
else:
    print("  ! Could not find JFK hub config entry")


# ── 7. Update LAX default_origin ─────────────────────────────────────────

old_lax_hub = '"LAX": {"sheet_id": TOLEAD_LAX_SHEET_ID, "tab": TOLEAD_LAX_TAB, "cols": TOLEAD_LAX_COLS, "default_origin": "LAX"},'
new_lax_hub = '"LAX": {"sheet_id": TOLEAD_LAX_SHEET_ID, "tab": TOLEAD_LAX_TAB, "cols": TOLEAD_LAX_COLS, "default_origin": "Vernon, CA"},'

if old_lax_hub in src:
    src = src.replace(old_lax_hub, new_lax_hub)
    print("  + Updated LAX default_origin to 'Vernon, CA'")
else:
    print("  ! Could not find LAX hub config entry")


# ── 8. Add ORD to TOLEAD_HUB_CONFIGS + add _shorten_address to hub loop ──
# Convert ORD from legacy to the new hub config pattern

# First, add ORD cols definition before JFK cols
old_jfk_cols_line = "TOLEAD_JFK_COLS = {"
ord_cols_def = '''TOLEAD_ORD_COLS = {
    "efj": 15, "load_id": 1, "status": 9, "origin": 6,
    "destination": 7, "pickup_date": 4, "pickup_time": 5,
    "delivery": 3, "driver": 16, "phone": 17, "appt_id": 2,
}

'''

if "TOLEAD_ORD_COLS" not in src:
    src = src.replace(old_jfk_cols_line, ord_cols_def + old_jfk_cols_line)
    print("  + Added TOLEAD_ORD_COLS definition")
else:
    print("  ~ TOLEAD_ORD_COLS already exists")

# Add ORD to TOLEAD_HUB_CONFIGS
old_hub_configs = '''TOLEAD_HUB_CONFIGS = {
    "JFK":'''

new_hub_configs = '''TOLEAD_HUB_CONFIGS = {
    "ORD": {"sheet_id": TOLEAD_SHEET_ID, "tab": TOLEAD_TAB, "cols": TOLEAD_ORD_COLS, "default_origin": "ORD"},
    "JFK":'''

if '"ORD":' not in src.split("TOLEAD_HUB_CONFIGS")[1][:200] if "TOLEAD_HUB_CONFIGS" in src else True:
    if old_hub_configs in src:
        src = src.replace(old_hub_configs, new_hub_configs)
        print("  + Added ORD to TOLEAD_HUB_CONFIGS")
    else:
        print("  ! Could not find TOLEAD_HUB_CONFIGS")
else:
    print("  ~ ORD already in TOLEAD_HUB_CONFIGS")


# ── 9. Remove legacy ORD direct read + add _shorten_address to hub loop ──
# Remove the old ORD-specific reading block (rows 772+)

old_ord_read = '''    # --- Read Tolead sheet (2 API calls: values + hyperlinks) ---
    try:
        tol_sh = gc.open_by_key(TOLEAD_SHEET_ID)
        ws = tol_sh.worksheet(TOLEAD_TAB)
        rows = ws.get_all_values()
        tol_links = _get_sheet_hyperlinks(creds, TOLEAD_SHEET_ID, TOLEAD_TAB)
        for ri, row in enumerate(rows[772:], start=772):  # Start at row 773
            def tol_cell(idx):
                return row[idx].strip() if len(row) > idx else ""
            efj = tol_cell(TOLEAD_COL_EFJ)
            ord_num = tol_cell(TOLEAD_COL_ORD)
            status = tol_cell(TOLEAD_COL_STATUS)
            if not efj and not ord_num:
                continue
            if not status or status in TOLEAD_SKIP_STATUSES:
                continue
            mp_url = ""
            if ri < len(tol_links) and len(tol_links[ri]) > TOLEAD_COL_EFJ:
                mp_url = tol_links[ri][TOLEAD_COL_EFJ] or ""
            all_shipments.append({
                "account": "Tolead", "efj": efj or ord_num,
                "move_type": "FTL", "container": ord_num, "bol": "",
                "ssl": "", "carrier": "",
                "origin": tol_cell(TOLEAD_COL_ORIGIN),
                "destination": tol_cell(TOLEAD_COL_DEST),
                "eta": tol_cell(TOLEAD_COL_DATE), "lfd": "",
                "pickup": "", "delivery": "",
                "status": status, "notes": "", "bot_alert": "",
                "return_port": "", "rep": "Tolead",
                "container_url": mp_url,
                "hub": "ORD",
            })
    except Exception as e:
        log.warning("Tolead ORD sheet read failed: %s", e)'''

if old_ord_read in src:
    src = src.replace(old_ord_read, "    # ORD now handled via TOLEAD_HUB_CONFIGS (legacy block removed)")
    print("  + Removed legacy ORD direct read block")
else:
    print("  ! Could not find legacy ORD read block (may need manual check)")


# ── 10. Update hub loop status logic for ORD/JFK/LAX + _shorten_address ──
# The current loop has DFW-specific status logic. Add ORD/JFK/LAX logic.

old_hub_status = '''            # DFW: status derived from Col E (LINE#) + Col J (Loads)
            if hub_name == "DFW":
                if not load_id:
                    continue  # No LINE# = no load
                if status and status in TOLEAD_SKIP_STATUSES:
                    continue
                col_j = row[9].strip() if len(row) > 9 else ""
                if col_j.lower() not in ("scheduled", "picked"):
                    # E has text + J not scheduled \u2192 "Needs to Cover"
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

            origin = _cell(cols["origin"]) or hub_cfg["default_origin"]'''

new_hub_status = '''            # Hub-specific status derivation
            if hub_name == "DFW":
                if not load_id:
                    continue
                if status and status in TOLEAD_SKIP_STATUSES:
                    continue
                col_j = row[9].strip() if len(row) > 9 else ""
                if col_j.lower() not in ("scheduled", "picked"):
                    status = "Needs to Cover"
                elif not status:
                    status = col_j.capitalize()
            elif hub_name == "ORD":
                if not load_id:
                    continue
                if status and status in TOLEAD_SKIP_STATUSES:
                    continue
                if status and status.lower() == "new":
                    status = "Needs to Cover"
                elif not status:
                    continue
            elif hub_name == "LAX":
                if not load_id:
                    continue
                if status and status in TOLEAD_SKIP_STATUSES:
                    continue
                if status and status.lower() == "unassigned":
                    status = "Needs to Cover"
                elif not status:
                    continue
            elif hub_name == "JFK":
                if not load_id:
                    continue
                if status and status in TOLEAD_SKIP_STATUSES:
                    continue
                if status and status.lower() == "new":
                    status = "Needs to Cover"
                elif not status:
                    continue
            else:
                if not efj and not load_id:
                    continue
                if status and status in TOLEAD_SKIP_STATUSES:
                    continue
                if not status:
                    continue

            origin = _shorten_address(_cell(cols["origin"]) or hub_cfg["default_origin"])'''

if old_hub_status in src:
    src = src.replace(old_hub_status, new_hub_status)
    print("  + Updated hub status logic (ORD/JFK/LAX Needs to Cover) + _shorten_address on origin")
else:
    print("  ! Could not find hub status block — check manually")


# ── 11. Apply _shorten_address to destination in hub loop ─────────────────

old_dest_line = '''                "destination": _cell(cols["destination"]),'''
new_dest_line = '''                "destination": _shorten_address(_cell(cols["destination"])),'''

if old_dest_line in src:
    src = src.replace(old_dest_line, new_dest_line)
    print("  + Applied _shorten_address to destination")
else:
    print("  ! Could not find destination line in hub shipment builder")


with open(TARGET, "w") as f:
    f.write(src)

print(f"\n  Patched: {TARGET}")
print("  Done.")
