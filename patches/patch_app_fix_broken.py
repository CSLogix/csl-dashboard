#!/usr/bin/env python3
"""
Fix: Remove the incorrectly inserted _shorten_address in the middle of bov_tabs line.
Then apply the remaining failed patches (Boviet append, ORD read, hub status).
"""

TARGET = "/root/csl-bot/csl-doc-tracker/app.py"

with open(TARGET, "r") as f:
    src = f.read()


# ── 1. Fix the broken bov_tabs line ──────────────────────────────────────
# The _shorten_address function was incorrectly inserted into the middle of
# the list comprehension. Remove the duplicate insertion.

# Build the exact broken text
broken_import = '''import re as _re

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

broken_line = "if ws.title not in " + broken_import + "BOVIET_SKIP_TABS and ws.title in BOVIET_TAB_CONFIGS]"
fixed_line = "if ws.title not in BOVIET_SKIP_TABS and ws.title in BOVIET_TAB_CONFIGS]"

if broken_line in src:
    src = src.replace(broken_line, fixed_line)
    print("  + Fixed broken bov_tabs line (removed duplicate _shorten_address)")
else:
    print("  ! Could not find broken bov_tabs line — checking manually")
    # Try a simpler approach: find and remove the second occurrence of the import block
    idx = src.find("import re as _re\n\ndef _shorten_address")
    if idx >= 0:
        idx2 = src.find("import re as _re\n\ndef _shorten_address", idx + 10)
        if idx2 >= 0:
            # Find where the second block ends (before BOVIET_SKIP_TABS)
            end_marker = "BOVIET_SKIP_TABS and ws.title"
            end_idx = src.find(end_marker, idx2)
            if end_idx >= 0:
                # Remove from idx2 to end_idx
                src = src[:idx2] + src[end_idx:]
                print("  + Fixed broken insertion (removed second _shorten_address block)")
            else:
                print("  ! Could not find end of broken block")
        else:
            print("  ~ Only one _shorten_address block found (already fixed?)")
    else:
        print("  ~ No _shorten_address found at all")


# ── 2. Update Boviet shipment builder ─────────────────────────────────────

old_boviet_append = '''                        all_shipments.append({
                            "account": "Boviet", "efj": efj, "move_type": "FTL",
                            "container": load_id, "bol": "", "ssl": "",
                            "carrier": "", "origin": "", "destination": "",
                            "eta": "", "lfd": "", "pickup": "", "delivery": "",
                            "status": status, "notes": "", "bot_alert": "",
                            "return_port": "", "rep": "Boviet",
                            "container_url": bov_mp_url,
                        })'''

new_boviet_append = '''                        # Extract optional fields from config
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
    print("  + Updated Boviet shipment builder (phone/trailer/pickup/delivery)")
else:
    print("  ! Could not find Boviet shipment append")


# ── 3. Remove legacy ORD direct read block ────────────────────────────────
# Replace with comment since ORD is now in TOLEAD_HUB_CONFIGS

old_ord_read = '''        # --- Read Tolead sheet (2 API calls: values + hyperlinks) ---
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

new_ord_read = '''        # ORD now handled via TOLEAD_HUB_CONFIGS (legacy block removed)'''

if old_ord_read in src:
    src = src.replace(old_ord_read, new_ord_read)
    print("  + Removed legacy ORD direct read block")
else:
    print("  ! Could not find legacy ORD read block")


# ── 4. Update hub loop status logic for all hubs + _shorten_address ───────

old_hub_status = '''                    # DFW: status derived from Col E (LINE#) + Col J (Loads)
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

new_hub_status = '''                    # Hub-specific status derivation
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
    print("  ! Could not find hub status block")


with open(TARGET, "w") as f:
    f.write(src)

print(f"\n  Patched: {TARGET}")
print("  Done.")
