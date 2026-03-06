#!/usr/bin/env python3
"""
Patch: Add PATCH /api/load/{efj}/field endpoint to app.py
Allows updating arbitrary editable fields (pickup, delivery, eta, lfd, carrier, etc.)
in Google Sheets from the dispatch dashboard inline editor.
"""
import re

APP_PATH = "/root/csl-bot/csl-doc-tracker/app.py"

ENDPOINT_CODE = '''

# ─── Field Update Endpoint (added by patch_field_update.py) ───
EDITABLE_FIELDS = {
    "pickup": "pickup",
    "delivery": "delivery",
    "eta": "eta",
    "lfd": "lfd",
    "carrier": "carrier",
    "origin": "origin",
    "destination": "destination",
    "notes": "notes",
    "status": "status",
}

# Tolead field -> column index mapping
TOLEAD_FIELD_COLS = {
    "status": 9,    # J
    "origin": 6,    # G
    "destination": 7, # H
    "pickup": 4,    # E (date col)
    "delivery": None,  # Tolead doesn't have a separate delivery col
}

# Boviet field -> config key mapping
BOVIET_FIELD_KEYS = {
    "status": "status_col",
    "pickup": "pickup_col",
    "delivery": "delivery_col",
    "origin": "origin_col",
}

@app.patch("/api/load/{efj}/field")
async def api_update_field(efj: str, request: Request):
    """Update any editable field for a load in Google Sheet."""
    body = await request.json()
    field = body.get("field", "").strip()
    value = body.get("value", "")
    if isinstance(value, str):
        value = value.strip()

    if field not in EDITABLE_FIELDS:
        raise HTTPException(400, f"Field '{field}' is not editable. Allowed: {list(EDITABLE_FIELDS.keys())}")

    col_key = EDITABLE_FIELDS[field]

    # Find shipment in cache
    shipment = None
    for s in sheet_cache.shipments:
        if s.get("efj") == efj:
            shipment = s
            break
    if not shipment:
        raise HTTPException(404, f"Load {efj} not found")

    tab = shipment.get("account", "")
    if not tab:
        raise HTTPException(400, "Cannot determine sheet tab for this load")

    try:
        creds = Credentials.from_service_account_file(
            CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)

        if tab == "Tolead":
            col_idx = TOLEAD_FIELD_COLS.get(col_key)
            if col_idx is None:
                raise HTTPException(400, f"Field '{field}' not supported for Tolead loads")
            sh = gc.open_by_key(TOLEAD_SHEET_ID)
            ws = sh.worksheet(TOLEAD_TAB)
            rows = ws.get_all_values()
            target_row = None
            for i, row in enumerate(rows):
                if len(row) > TOLEAD_COL_EFJ and row[TOLEAD_COL_EFJ].strip() == efj:
                    target_row = i + 1
                    break
            if not target_row:
                raise HTTPException(404, f"Row for {efj} not found in Tolead")
            ws.update_cell(target_row, col_idx + 1, value)

        elif tab == "Boviet":
            cfg_key = BOVIET_FIELD_KEYS.get(col_key)
            if not cfg_key:
                # Fall back to master COL for fields not in Boviet mapping
                raise HTTPException(400, f"Field '{field}' not supported for Boviet loads")
            sh = gc.open_by_key(BOVIET_SHEET_ID)
            found = False
            for bov_tab, cfg in BOVIET_TAB_CONFIGS.items():
                col_idx = cfg.get(cfg_key)
                if col_idx is None:
                    continue  # This tab doesn't have this column
                try:
                    ws = sh.worksheet(bov_tab)
                    rows = ws.get_all_values()
                    for i, row in enumerate(rows):
                        if len(row) > cfg["efj_col"] and row[cfg["efj_col"]].strip() == efj:
                            ws.update_cell(i + 1, col_idx + 1, value)
                            found = True
                            break
                    if found:
                        break
                except Exception:
                    continue
            if not found:
                raise HTTPException(404, f"Row for {efj} not found in Boviet tabs")

        else:
            # Master sheet
            col_idx = COL.get(col_key)
            if col_idx is None:
                raise HTTPException(400, f"Field '{field}' has no column mapping")
            sh = gc.open_by_key(SHEET_ID)
            ws = sh.worksheet(tab)
            rows = ws.get_all_values()
            target_row = None
            efj_col = COL.get("efj", 0)
            for i, row in enumerate(rows):
                if len(row) > efj_col and row[efj_col].strip() == efj:
                    target_row = i + 1
                    break
            if not target_row:
                raise HTTPException(404, f"Row for {efj} not found in {tab}")
            ws.update_cell(target_row, col_idx + 1, value)

        # Update in-memory cache
        shipment[col_key] = value
        log.info("Field updated: %s.%s → '%s' (tab=%s)", efj, field, value, tab)
        return {"status": "ok", "efj": efj, "field": field, "value": value}

    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to update field %s for %s: %s", field, efj, e)
        raise HTTPException(500, f"Failed to update field: {e}")
'''

def main():
    with open(APP_PATH, "r") as f:
        content = f.read()

    # Check if already patched
    if "api_update_field" in content:
        print("Already patched — api_update_field endpoint exists.")
        return

    # Insert after the api_update_status endpoint
    # Find the end of the status update function by looking for the next @app decorator or function def
    marker = "async def api_update_status(efj: str, request: Request):"
    idx = content.find(marker)
    if idx == -1:
        print("ERROR: Could not find api_update_status endpoint")
        return

    # Find the next @app. decorator after the status endpoint
    next_endpoint = content.find("\n@app.", idx + len(marker))
    if next_endpoint == -1:
        # Insert at end of file
        insert_pos = len(content)
    else:
        insert_pos = next_endpoint

    new_content = content[:insert_pos] + ENDPOINT_CODE + content[insert_pos:]

    with open(APP_PATH, "w") as f:
        f.write(new_content)

    print(f"Patched! Added PATCH /api/load/{{efj}}/field endpoint.")
    print(f"Inserted {len(ENDPOINT_CODE)} chars at position {insert_pos}")

if __name__ == "__main__":
    main()
