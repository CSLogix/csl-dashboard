"""
Patch: Add POST /api/load/add endpoint.
Creates a new shipment row in the appropriate Google Sheet
(Master Tracker, Tolead hub, or Boviet tab) based on account.
"""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

target = '''# ── Email History & Unmatched Inbox Endpoints ──

@app.get("/api/load/{efj}/emails")'''

new_endpoint = '''# ── Add New Load ──

# Master Tracker account tabs (anything NOT in SKIP_TABS, Tolead, or Boviet)
_TOLEAD_ACCOUNTS = {"Tolead", "Tolead ORD", "Tolead JFK", "Tolead LAX", "Tolead DFW"}
_BOVIET_ACCOUNTS = set(BOVIET_TAB_CONFIGS.keys()) | {"Boviet"}

@app.post("/api/load/add")
async def api_add_load(request: Request):
    """Add a new load to the appropriate Google Sheet tab."""
    body = await request.json()
    efj = body.get("efj", "").strip()
    account = body.get("account", "").strip()
    if not efj:
        raise HTTPException(400, "EFJ Pro # is required")
    if not account:
        raise HTTPException(400, "Account is required")

    move_type = body.get("moveType", "Dray Import")
    container = body.get("container", "").strip()
    carrier = body.get("carrier", "").strip()
    origin = body.get("origin", "").strip()
    destination = body.get("destination", "").strip()
    eta = body.get("eta", "")
    lfd = body.get("lfd", "")
    pickup = body.get("pickupDate", "")
    delivery = body.get("deliveryDate", "")
    status = body.get("status", "")
    notes = body.get("notes", "")
    driver_phone = body.get("driverPhone", "")
    trailer = body.get("trailerNumber", "")
    carrier_email = body.get("carrierEmail", "")
    mp_url = body.get("macropointUrl", "")

    try:
        creds = Credentials.from_service_account_file(
            CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)

        # --- Determine which sheet to write to ---
        target_sheet = "master"
        hub_key = None
        boviet_tab = None

        # Check if Tolead hub
        if account in _TOLEAD_ACCOUNTS:
            hub_key = account.replace("Tolead ", "").upper() if account != "Tolead" else "ORD"
            if hub_key not in TOLEAD_HUB_CONFIGS:
                raise HTTPException(400, f"Unknown Tolead hub: {hub_key}")
            target_sheet = "tolead"

        # Check if Boviet tab
        elif account in _BOVIET_ACCOUNTS:
            boviet_tab = account if account != "Boviet" else "Piedra"
            if boviet_tab not in BOVIET_TAB_CONFIGS:
                raise HTTPException(400, f"Unknown Boviet tab: {boviet_tab}")
            target_sheet = "boviet"

        if target_sheet == "master":
            # --- Master Tracker: columns A-P ---
            sh = gc.open_by_key(SHEET_ID)
            try:
                ws = sh.worksheet(account)
            except gspread.WorksheetNotFound:
                raise HTTPException(400, f"Account tab '{account}' not found in Master Tracker")
            status_display = status.replace("_", " ").title() if status else ""
            row = [""] * 16
            row[COL["efj"]] = efj
            row[COL["move_type"]] = move_type
            row[COL["container"]] = container
            row[COL["carrier"]] = carrier
            row[COL["origin"]] = origin
            row[COL["destination"]] = destination
            row[COL["eta"]] = eta
            row[COL["lfd"]] = lfd
            row[COL["pickup"]] = pickup
            row[COL["delivery"]] = delivery
            row[COL["status"]] = status_display
            row[COL["notes"]] = notes
            ws.append_row(row, value_input_option="USER_ENTERED")
            log.info("Added load %s to Master/%s", efj, account)
            result_tab = account

        elif target_sheet == "tolead":
            # --- Tolead hub sheet ---
            hub_cfg = TOLEAD_HUB_CONFIGS[hub_key]
            sh = gc.open_by_key(hub_cfg["sheet_id"])
            ws = sh.worksheet(hub_cfg["tab"])
            cols = hub_cfg["cols"]
            max_col = max(v for v in cols.values() if v is not None) + 1
            row = [""] * max_col
            if cols.get("efj") is not None:
                row[cols["efj"]] = efj
            if cols.get("load_id") is not None:
                row[cols["load_id"]] = container or efj
            if cols.get("status") is not None:
                row[cols["status"]] = status.replace("_", " ").title() if status else ""
            if cols.get("origin") is not None:
                row[cols["origin"]] = origin or hub_cfg.get("default_origin", "")
            if cols.get("destination") is not None:
                row[cols["destination"]] = destination
            if cols.get("pickup_date") is not None:
                row[cols["pickup_date"]] = pickup
            if cols.get("delivery") is not None:
                row[cols["delivery"]] = delivery
            if cols.get("driver") is not None:
                row[cols["driver"]] = trailer
            if cols.get("phone") is not None:
                row[cols["phone"]] = driver_phone
            ws.append_row(row, value_input_option="USER_ENTERED")
            log.info("Added load %s to Tolead/%s", efj, hub_key)
            result_tab = f"Tolead {hub_key}"

        elif target_sheet == "boviet":
            # --- Boviet tab ---
            cfg = BOVIET_TAB_CONFIGS[boviet_tab]
            sh = gc.open_by_key(BOVIET_SHEET_ID)
            ws = sh.worksheet(boviet_tab)
            max_col = max(v for v in cfg.values() if isinstance(v, int)) + 1
            row = [""] * max_col
            row[cfg["efj_col"]] = efj
            row[cfg["load_id_col"]] = container or efj
            row[cfg["status_col"]] = status.replace("_", " ").title() if status else ""
            if cfg.get("pickup_col") is not None:
                row[cfg["pickup_col"]] = pickup
            if cfg.get("delivery_col") is not None:
                row[cfg["delivery_col"]] = delivery
            if cfg.get("phone_col") is not None:
                row[cfg["phone_col"]] = driver_phone
            if cfg.get("trailer_col") is not None:
                row[cfg["trailer_col"]] = trailer
            ws.append_row(row, value_input_option="USER_ENTERED")
            log.info("Added load %s to Boviet/%s", efj, boviet_tab)
            result_tab = f"Boviet {boviet_tab}"

        # Invalidate cache so next fetch picks up the new row
        sheet_cache.last_refresh = 0

        # Store FTL driver info in DB if provided
        if move_type == "FTL" and (driver_phone or trailer or carrier_email or mp_url):
            try:
                with db.get_conn() as conn:
                    with db.get_cursor(conn) as cur:
                        cur.execute(
                            """INSERT INTO driver_contacts (efj, driver_phone, trailer, carrier_email, macropoint_url, updated_at)
                               VALUES (%s, %s, %s, %s, %s, NOW())
                               ON CONFLICT (efj) DO UPDATE SET
                                 driver_phone = EXCLUDED.driver_phone,
                                 trailer = EXCLUDED.trailer,
                                 carrier_email = EXCLUDED.carrier_email,
                                 macropoint_url = EXCLUDED.macropoint_url,
                                 updated_at = NOW()""",
                            (efj, driver_phone or None, trailer or None, carrier_email or None, mp_url or None),
                        )
            except Exception as db_err:
                log.warning("Driver contact save failed for %s: %s", efj, db_err)

        return {"ok": True, "efj": efj, "tab": result_tab, "sheet": target_sheet}

    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to add load %s: %s", efj, e)
        raise HTTPException(500, f"Failed to add load: {e}")


''' + target

if target not in code:
    print("ERROR: target block not found")
    exit(1)

code = code.replace(target, new_endpoint, 1)

with open(APP, "w") as f:
    f.write(code)

print("OK — POST /api/load/add endpoint added")
