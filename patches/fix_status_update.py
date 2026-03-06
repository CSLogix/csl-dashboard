"""
Fix: Rewrite status update endpoint to properly handle Boviet multi-tab search
"""

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP_PY) as f:
    code = f.read()

old_block = '''    # Write to Google Sheet
    try:
        creds = Credentials.from_service_account_file(
            CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)

        # Determine which sheet to write to
        sheet_id = SHEET_ID
        if tab == "Boviet":
            sheet_id = BOVIET_SHEET_ID
        elif tab == "Tolead":
            sheet_id = TOLEAD_SHEET_ID

        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet(tab if tab not in ("Boviet", "Tolead") else
                          (list(BOVIET_TAB_CONFIGS.keys())[0] if tab == "Boviet" else TOLEAD_TAB))

        # Find the row by EFJ number
        rows = ws.get_all_values()
        target_row = None
        efj_col = 0  # Column A for master sheet
        status_col = COL.get("status", 12)  # Column M (0-indexed: 12)

        if tab == "Tolead":
            efj_col = TOLEAD_COL_EFJ
            status_col = TOLEAD_COL_STATUS
        elif tab == "Boviet":
            # Boviet uses different column layout per tab
            efj_col = 0  # Usually col A
            status_col = 7  # Usually col H for status

        for i, row in enumerate(rows):
            if len(row) > efj_col and row[efj_col].strip() == efj:
                target_row = i + 1  # gspread is 1-indexed
                break

        if not target_row:
            raise HTTPException(404, f"Row for {efj} not found in {tab}")

        ws.update_cell(target_row, status_col + 1, new_status)  # gspread cols are 1-indexed

        # Update cache
        shipment["status"] = new_status
        log.info("Status updated: %s → %s (tab=%s, row=%d)", efj, new_status, tab, target_row)

        return {"status": "ok", "efj": efj, "new_status": new_status}

    except Exception as e:
        log.error("Failed to update status for %s: %s", efj, e)
        raise HTTPException(500, f"Failed to update status: {e}")'''

new_block = '''    # Write to Google Sheet
    try:
        creds = Credentials.from_service_account_file(
            CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)

        if tab == "Tolead":
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
            ws.update_cell(target_row, TOLEAD_COL_STATUS + 1, new_status)

        elif tab == "Boviet":
            # Search all Boviet tabs for the EFJ
            sh = gc.open_by_key(BOVIET_SHEET_ID)
            found = False
            for bov_tab, cfg in BOVIET_TAB_CONFIGS.items():
                try:
                    ws = sh.worksheet(bov_tab)
                    rows = ws.get_all_values()
                    for i, row in enumerate(rows):
                        if len(row) > cfg["efj_col"] and row[cfg["efj_col"]].strip() == efj:
                            ws.update_cell(i + 1, cfg["status_col"] + 1, new_status)
                            found = True
                            log.info("Status updated: %s → %s (Boviet/%s, row=%d)", efj, new_status, bov_tab, i + 1)
                            break
                    if found:
                        break
                except Exception:
                    continue
            if not found:
                raise HTTPException(404, f"Row for {efj} not found in Boviet tabs")

        else:
            # Master sheet — tab name is the account name
            sh = gc.open_by_key(SHEET_ID)
            ws = sh.worksheet(tab)
            rows = ws.get_all_values()
            target_row = None
            efj_col = COL.get("efj", 0)
            status_col = COL.get("status", 12)
            for i, row in enumerate(rows):
                if len(row) > efj_col and row[efj_col].strip() == efj:
                    target_row = i + 1
                    break
            if not target_row:
                raise HTTPException(404, f"Row for {efj} not found in {tab}")
            ws.update_cell(target_row, status_col + 1, new_status)

        # Update cache
        shipment["status"] = new_status
        log.info("Status updated: %s → %s (tab=%s)", efj, new_status, tab)
        return {"status": "ok", "efj": efj, "new_status": new_status}

    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to update status for %s: %s", efj, e)
        raise HTTPException(500, f"Failed to update status: {e}")'''

if old_block in code:
    code = code.replace(old_block, new_block)
    with open(APP_PY, "w") as f:
        f.write(code)
    print("Fix applied — status update endpoint now searches all Boviet tabs")
else:
    print("ERROR: Could not find the old block to replace")
    # Try to show what's there for debugging
    import re
    m = re.search(r'# Write to Google Sheet.*?raise HTTPException\(500', code, re.DOTALL)
    if m:
        print("Found block starting at:", code[:m.start()].count('\n'))
        print(m.group()[:200])
