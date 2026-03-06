"""
Patch: Fix Google Sheets API quota exhaustion in dashboard refresh.

Problem: ~60 individual API calls per 5-min refresh cycle. Tolead permanently
rate-limited because quota is exhausted by Master + Boviet tab reads.

Solution: Replace per-tab reads with values_batch_get() — reads ALL tabs in
a single API call. Reduces total calls from ~60 to ~8.

Also increases cache TTL from 5 to 10 minutes as extra safety margin.
"""

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP_PY) as f:
    code = f.read()

with open(APP_PY + ".bak_quota_fix", "w") as f:
    f.write(code)

# 1. Increase cache TTL from 5 to 10 minutes
code = code.replace("CACHE_TTL = 300  # 5 minutes", "CACHE_TTL = 600  # 10 minutes")

# 2. Replace the entire _do_refresh method with batch-read version
old_refresh_start = "    def _do_refresh(self):"
old_refresh_end = '        log.info("Sheet cache: %d shipments", len(all_shipments))'

# Find the boundaries
start_idx = code.index(old_refresh_start)
end_idx = code.index(old_refresh_end) + len(old_refresh_end)

new_refresh = '''    def _do_refresh(self):
        creds = Credentials.from_service_account_file(
            CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)

        # Load account rep mapping (1 API call)
        try:
            rep_rows = sh.worksheet("Account Rep").get_all_values()
            self.rep_map = {}
            for r in rep_rows[2:]:
                if r[0].strip() and len(r) > 1 and r[1].strip():
                    self.rep_map[r[0].strip()] = r[1].strip()
        except Exception:
            pass

        # --- BATCH read all master tabs (1 API call instead of ~36) ---
        all_shipments = []
        tabs = [ws.title for ws in sh.worksheets() if ws.title not in SKIP_TABS]
        ranges = [f"'{t}'!A:P" for t in tabs]
        try:
            batch_result = sh.values_batch_get(ranges)
            value_ranges = batch_result.get("valueRanges", [])
            for vr, tab_name in zip(value_ranges, tabs):
                rows = vr.get("values", [])
                if len(rows) < 2:
                    continue
                hdr_idx = 0
                if len(rows) > 1:
                    r0 = sum(1 for c in rows[0] if c.strip())
                    r1 = sum(1 for c in rows[1] if c.strip())
                    if r1 > r0:
                        hdr_idx = 1
                for row in rows[hdr_idx + 1:]:
                    efj = row[COL["efj"]].strip() if len(row) > COL["efj"] else ""
                    ctr = row[COL["container"]].strip() if len(row) > COL["container"] else ""
                    if not efj and not ctr:
                        continue
                    def cell(key, r=row):
                        idx = COL[key]
                        return r[idx].strip() if len(r) > idx else ""
                    all_shipments.append({
                        "account": tab_name,
                        "efj": efj, "move_type": cell("move_type"),
                        "container": ctr, "bol": cell("bol"),
                        "ssl": cell("ssl"), "carrier": cell("carrier"),
                        "origin": cell("origin"), "destination": cell("destination"),
                        "eta": cell("eta"), "lfd": cell("lfd"),
                        "pickup": cell("pickup"), "delivery": cell("delivery"),
                        "status": cell("status"), "notes": cell("notes"),
                        "bot_alert": cell("bot_alert"), "return_port": cell("return_port"),
                        "container_url": "",
                        "rep": self.rep_map.get(tab_name, "Unassigned"),
                    })
        except Exception as e:
            log.warning("Master batch read failed: %s", e)

        _time.sleep(2)  # breathing room between sheets

        # --- BATCH read Boviet tabs (2 API calls: metadata + batch values) ---
        try:
            bov_sh = gc.open_by_key(BOVIET_SHEET_ID)
            bov_tabs = [ws.title for ws in bov_sh.worksheets()
                        if ws.title not in BOVIET_SKIP_TABS and ws.title in BOVIET_TAB_CONFIGS]
            bov_ranges = [f"'{t}'!A:Z" for t in bov_tabs]
            bov_batch = bov_sh.values_batch_get(bov_ranges)
            bov_value_ranges = bov_batch.get("valueRanges", [])
            for vr, tab_name in zip(bov_value_ranges, bov_tabs):
                try:
                    cfg = BOVIET_TAB_CONFIGS[tab_name]
                    rows = vr.get("values", [])
                    # Get hyperlinks separately (1 call per tab — needed for Macropoint URLs)
                    bov_links = _get_sheet_hyperlinks(creds, BOVIET_SHEET_ID, tab_name)
                    for ri, row in enumerate(rows[1:], start=1):
                        efj = row[cfg["efj_col"]].strip() if len(row) > cfg["efj_col"] else ""
                        load_id = row[cfg["load_id_col"]].strip() if len(row) > cfg["load_id_col"] else ""
                        status = row[cfg["status_col"]].strip() if len(row) > cfg["status_col"] else ""
                        if not efj or status in BOVIET_DONE_STATUSES:
                            continue
                        bov_mp_url = ""
                        if ri < len(bov_links) and len(bov_links[ri]) > cfg["efj_col"]:
                            bov_mp_url = bov_links[ri][cfg["efj_col"]] or ""
                        all_shipments.append({
                            "account": "Boviet", "efj": efj, "move_type": "FTL",
                            "container": load_id, "bol": "", "ssl": "",
                            "carrier": "", "origin": "", "destination": "",
                            "eta": "", "lfd": "", "pickup": "", "delivery": "",
                            "status": status, "notes": "", "bot_alert": "",
                            "return_port": "", "rep": "Boviet",
                            "container_url": bov_mp_url,
                        })
                    _time.sleep(1)
                except Exception as e:
                    log.warning("Boviet tab %s: %s", tab_name, e)
        except Exception as e:
            log.warning("Boviet sheet read failed: %s", e)

        _time.sleep(2)  # breathing room before Tolead

        # --- Read Tolead sheet (2 API calls: values + hyperlinks) ---
        try:
            tol_sh = gc.open_by_key(TOLEAD_SHEET_ID)
            ws = tol_sh.worksheet(TOLEAD_TAB)
            rows = ws.get_all_values()
            tol_links = _get_sheet_hyperlinks(creds, TOLEAD_SHEET_ID, TOLEAD_TAB)
            for ri, row in enumerate(rows[1:], start=1):
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
                })
        except Exception as e:
            log.warning("Tolead sheet read failed: %s", e)

        self.shipments = all_shipments
        self._compute_stats()
        self._last = _time.time()
        log.info("Sheet cache: %d shipments", len(all_shipments))'''

code = code[:start_idx] + new_refresh + code[end_idx:]

with open(APP_PY, "w") as f:
    f.write(code)

print("Patch applied!")
print("  - Master tabs: values_batch_get (1 call vs ~36)")
print("  - Boviet tabs: values_batch_get (1 call vs ~12)")
print("  - 2-second pauses between sheets")
print("  - Cache TTL increased to 10 minutes")
print("  - Total: ~12 calls per cycle vs ~60")
