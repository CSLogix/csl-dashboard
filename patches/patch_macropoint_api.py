"""
Patch: Add Macropoint tracking API + status update endpoint to app.py

Adds:
1. GET /api/macropoint/{efj} — returns tracking progress derived from sheet status
2. POST /api/load/{efj}/status — updates status in Google Sheet + cache
3. Widens sheet API scope to read-write for status updates
"""

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP_PY) as f:
    code = f.read()

# --- Backup ---
with open(APP_PY + ".bak_macropoint_api", "w") as f:
    f.write(code)

# 1. Widen Google Sheets scope from readonly to read-write
code = code.replace(
    'CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]',
    'CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]',
)

# 2. Add Macropoint progress mapping helper + tracking phone constant
# Insert after the existing SKIP_TABS or column mapping section
import_marker = 'import database as db'
macropoint_code = '''
# ── Macropoint tracking constants ──
TRACKING_PHONE = os.getenv("MACROPOINT_TRACKING_PHONE", "4437614954")
DISPATCH_EMAIL = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")

# Status → progress step mapping (cumulative: each status implies all prior steps done)
_MP_PROGRESS_ORDER = [
    "Driver Assigned",
    "Ready To Track",
    "Arrived At Origin",
    "Departed Origin",
    "At Delivery",
    "Delivered",
]

_STATUS_TO_STEP = {
    # Sheet statuses
    "pending": 0,
    "booked": 0,
    "assigned": 1,
    "ready to track": 1,
    "tracking now": 1,
    "tracking waiting for update": 1,
    "at pickup": 2,
    "driver arrived at pickup": 2,
    "arrived at pickup": 2,
    "arrived at origin": 2,
    "loading": 2,
    "in transit": 3,
    "departed pickup": 3,
    "departed pickup - en route": 3,
    "en route": 3,
    "running late": 3,
    "tracking behind schedule": 3,
    "driver phone unresponsive": 3,
    "at delivery": 4,
    "arrived at delivery": 4,
    "unloading": 4,
    "out for delivery": 4,
    "delivered": 5,
    "departed delivery": 5,
    "completed": 5,
    "pod received": 5,
}

def _build_macropoint_progress(status_str: str):
    """Build progress array from a status string."""
    key = (status_str or "").strip().lower()
    step = _STATUS_TO_STEP.get(key, -1)
    # Fuzzy match: check if any known key is contained in the status
    if step == -1:
        for k, v in _STATUS_TO_STEP.items():
            if k in key or key in k:
                step = v
                break
    if step == -1:
        step = 0  # default: only first step done
    return [
        {"label": lbl, "done": i <= step}
        for i, lbl in enumerate(_MP_PROGRESS_ORDER)
    ]
'''

code = code.replace(import_marker, import_marker + macropoint_code)

# 3. Add GET /api/macropoint/{efj} endpoint — before health endpoint
health_marker = '@app.get("/health")'
macropoint_endpoint = '''@app.get("/api/macropoint/{efj}")
async def api_macropoint(efj: str):
    """Return Macropoint tracking data for an FTL load."""
    sheet_cache.refresh_if_needed()
    # Find the shipment
    shipment = None
    for s in sheet_cache.shipments:
        if s["efj"] == efj:
            shipment = s
            break
    if not shipment:
        raise HTTPException(404, f"Load {efj} not found")
    if not shipment.get("container_url"):
        raise HTTPException(404, f"No Macropoint tracking for {efj}")

    status = shipment.get("status", "")
    progress = _build_macropoint_progress(status)

    # Format phone
    phone_raw = TRACKING_PHONE
    if len(phone_raw) == 10:
        phone_fmt = f"({phone_raw[:3]}) {phone_raw[3:6]}-{phone_raw[6:]}"
    else:
        phone_fmt = phone_raw

    return {
        "loadId": shipment.get("container", "") or shipment.get("efj", ""),
        "carrier": "Evans Delivery Company, Inc.",
        "driver": "",
        "phone": phone_fmt,
        "email": DISPATCH_EMAIL,
        "trackingStatus": status or "Unknown",
        "macropointUrl": shipment.get("container_url", ""),
        "progress": progress,
        "origin": shipment.get("origin", ""),
        "destination": shipment.get("destination", ""),
        "pickup": shipment.get("pickup", ""),
        "delivery": shipment.get("delivery", ""),
        "eta": shipment.get("eta", ""),
        "account": shipment.get("account", ""),
        "moveType": shipment.get("move_type", ""),
    }


@app.post("/api/load/{efj}/status")
async def api_update_status(efj: str, request: Request):
    """Update a load's status in Google Sheet."""
    body = await request.json()
    new_status = body.get("status", "").strip()
    if not new_status:
        raise HTTPException(400, "Missing status")

    # Find the shipment in cache to get its tab and row
    shipment = None
    for s in sheet_cache.shipments:
        if s["efj"] == efj:
            shipment = s
            break
    if not shipment:
        raise HTTPException(404, f"Load {efj} not found")

    tab = shipment.get("account", "")
    if not tab:
        raise HTTPException(400, "Cannot determine sheet tab for this load")

    # Write to Google Sheet
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
                          (BOVIET_TABS[0] if tab == "Boviet" else TOLEAD_TAB))

        # Find the row by EFJ number
        rows = ws.get_all_values()
        target_row = None
        efj_col = 0  # Column A for master sheet
        status_col = COL_MAP.get("status", 12)  # Column M (0-indexed: 12)

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
        raise HTTPException(500, f"Failed to update status: {e}")


'''

code = code.replace(health_marker, macropoint_endpoint + health_marker)

with open(APP_PY, "w") as f:
    f.write(code)

print("Patch applied successfully!")
print("  - GET /api/macropoint/{efj} — tracking progress from status")
print("  - POST /api/load/{efj}/status — write status to Google Sheet")
print("  - Sheet scope upgraded to read-write")
print("  - Status-to-progress mapping for 25+ status values")
