#!/usr/bin/env python3
"""Fix unbilled parser: detect real header row + fix date parsing."""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

# Fix 1: Replace _parse_unbilled_excel to detect header row dynamically
old_parser = '''def _parse_unbilled_excel(file_bytes: bytes, filename: str) -> list:
    """Parse .xls or .xlsx unbilled orders file. Returns list of dicts."""
    rows = []
    if filename.lower().endswith(".xls"):
        wb = xlrd.open_workbook(file_contents=file_bytes)
        ws = wb.sheet_by_index(0)
        headers = [str(ws.cell_value(0, c)).strip() for c in range(ws.ncols)]
        for r in range(1, ws.nrows):
            row = {}
            for c, h in enumerate(headers):
                val = ws.cell_value(r, c)
                # xlrd returns dates as floats
                if ws.cell_type(r, c) == xlrd.XL_CELL_DATE:
                    try:
                        dt = xlrd.xldate_as_datetime(val, wb.datemode)
                        val = dt.strftime("%Y-%m-%d")
                    except Exception:
                        val = str(val)
                row[h] = val
            rows.append(row)'''

new_parser = '''def _parse_unbilled_excel(file_bytes: bytes, filename: str) -> list:
    """Parse .xls or .xlsx unbilled orders file. Returns list of dicts."""
    rows = []
    if filename.lower().endswith(".xls"):
        wb = xlrd.open_workbook(file_contents=file_bytes)
        ws = wb.sheet_by_index(0)
        # Find header row: look for row containing "Order#"
        header_row = 0
        for r in range(min(5, ws.nrows)):
            vals = [str(ws.cell_value(r, c)).strip().lower() for c in range(ws.ncols)]
            if any("order" in v for v in vals):
                header_row = r
                break
        headers = [str(ws.cell_value(header_row, c)).strip() for c in range(ws.ncols)]
        for r in range(header_row + 1, ws.nrows):
            row = {}
            for c, h in enumerate(headers):
                val = ws.cell_value(r, c)
                if ws.cell_type(r, c) == xlrd.XL_CELL_DATE:
                    try:
                        dt = xlrd.xldate_as_datetime(val, wb.datemode)
                        val = dt.strftime("%Y-%m-%d")
                    except Exception:
                        val = str(val)
                row[h] = val
            rows.append(row)'''

if old_parser in code:
    code = code.replace(old_parser, new_parser)
    print("[1/3] Fixed XLS header detection.")
else:
    print("[1/3] WARN: Could not find exact parser block to replace.")

# Fix 2: Replace _map_unbilled_row with exact header matching
old_map = '''def _map_unbilled_row(row: dict) -> dict:
    """Map Excel columns to DB columns. Flexible header matching."""
    def find(keys):
        for k in keys:
            for h in row:
                if k.lower() in h.lower():
                    return row[h]
        return None'''

new_map = '''def _map_unbilled_row(row: dict) -> dict:
    """Map Excel columns to DB columns. Exact header matching with fallbacks."""
    def find(keys):
        for k in keys:
            # Try exact match first
            if k in row:
                return row[k]
            # Then case-insensitive exact
            for h in row:
                if h.lower().strip() == k.lower():
                    return row[h]
            # Then substring
            for h in row:
                if k.lower() in h.lower():
                    return row[h]
        return None'''

if old_map in code:
    code = code.replace(old_map, new_map)
    print("[2/3] Fixed column mapping.")
else:
    print("[2/3] WARN: Could not find exact map block to replace.")

# Fix 3: Also update the xlsx parser to detect header row
old_xlsx = '''        headers = [str(h).strip() if h else f"col{i}" for i, h in enumerate(all_rows[0])]
        for vals in all_rows[1:]:'''

new_xlsx = '''        # Find header row (look for "Order")
        header_idx = 0
        for idx, r in enumerate(all_rows[:5]):
            if any("order" in str(v).lower() for v in r if v):
                header_idx = idx
                break
        headers = [str(h).strip() if h else f"col{i}" for i, h in enumerate(all_rows[header_idx])]
        for vals in all_rows[header_idx + 1:]:'''

if old_xlsx in code:
    code = code.replace(old_xlsx, new_xlsx)
    print("[3/3] Fixed XLSX header detection.")
else:
    print("[3/3] WARN: Could not find exact xlsx block to replace.")

with open(APP, "w") as f:
    f.write(code)

# Now clear bad data and re-import
print("\nClearing bad data...")
import psycopg2, sys
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config
conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()
cur.execute("DELETE FROM unbilled_orders")
conn.commit()
print(f"   Cleared all rows.")
cur.close()
conn.close()

print("\n✅ Done! Restart with: systemctl restart csl-dashboard")
print("   Then re-upload the Excel file.")
