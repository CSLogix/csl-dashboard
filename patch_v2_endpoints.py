#!/usr/bin/env python3
"""
Postgres Migration — Phase 1: Add v2 API endpoints that read/write from Postgres.

Run on server:
    python3 /tmp/patch_v2_endpoints.py

Adds to app.py:
  GET  /api/v2/shipments          — all shipments from Postgres
  GET  /api/v2/shipments/{efj}    — single shipment
  GET  /api/v2/stats              — dashboard stats from Postgres
  GET  /api/v2/accounts           — account list + counts
  POST /api/v2/load/{efj}/status  — update status (Postgres + sheet for shared accounts)
  POST /api/v2/load/{efj}/update  — update any field
  POST /api/v2/load/add           — insert new shipment
"""

import re
import sys
import shutil
from datetime import datetime

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

# Backup
backup = f"{APP_PY}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
shutil.copy2(APP_PY, backup)
print(f"Backup: {backup}")

with open(APP_PY, "r") as f:
    code = f.read()

# ---------------------------------------------------------------------------
# The v2 endpoint block — injected before the final uvicorn.run or at EOF
# ---------------------------------------------------------------------------
V2_BLOCK = '''

# ═══════════════════════════════════════════════════════════════════════════
# V2 API ENDPOINTS — Postgres-backed (Phase 1 migration)
# Coexist with existing sheet-based /api/ endpoints.
# ═══════════════════════════════════════════════════════════════════════════

# Shared accounts that still need Google Sheet writes
_SHARED_SHEET_ACCOUNTS = {"Tolead", "Boviet"}


def _shipment_row_to_dict(row: dict) -> dict:
    """Convert a Postgres shipments row to the same JSON shape as sheet_cache."""
    return {
        "efj": row["efj"] or "",
        "move_type": row["move_type"] or "",
        "container": row["container"] or "",
        "bol": row["bol"] or "",
        "ssl": row["vessel"] or "",
        "carrier": row["carrier"] or "",
        "origin": row["origin"] or "",
        "destination": row["destination"] or "",
        "eta": row["eta"] or "",
        "lfd": row["lfd"] or "",
        "pickup": row["pickup_date"] or "",
        "delivery": row["delivery_date"] or "",
        "status": row["status"] or "",
        "notes": row["notes"] or "",
        "bot_alert": row["bot_notes"] or "",
        "return_port": row["return_date"] or "",
        "container_url": row["container_url"] or "",
        "rep": row["rep"] or "Unassigned",
        "account": row["account"] or "",
        "hub": row["hub"] or "",
        "driver": row["driver"] or "",
        "driver_phone": row["driver_phone"] or "",
        "source": row["source"] or "sheet",
        "archived": row.get("archived", False),
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


@app.get("/api/v2/shipments")
async def api_v2_shipments(request: Request, account: str = None, status: str = None,
                            hub: str = None, rep: str = None, archived: bool = False):
    """Return shipments from Postgres, same shape as /api/shipments."""
    where_clauses = ["archived = %s"]
    params = [archived]

    if account:
        where_clauses.append("LOWER(account) = LOWER(%s)")
        params.append(account)
    if status:
        where_clauses.append("LOWER(status) = LOWER(%s)")
        params.append(status)
    if hub:
        where_clauses.append("LOWER(hub) = LOWER(%s)")
        params.append(hub)
    if rep:
        where_clauses.append("LOWER(rep) = LOWER(%s)")
        params.append(rep)

    where = " AND ".join(where_clauses)

    with db.get_cursor() as cur:
        cur.execute(
            f"SELECT * FROM shipments WHERE {where} ORDER BY created_at DESC",
            params,
        )
        rows = cur.fetchall()

    shipments = [_shipment_row_to_dict(r) for r in rows]

    # Enrich with invoiced status from DB
    try:
        invoiced_map = db.get_invoiced_map()
    except Exception:
        invoiced_map = {}
    for s in shipments:
        s["_invoiced"] = invoiced_map.get(s["efj"], False)

    return {"shipments": shipments, "total": len(shipments)}


@app.get("/api/v2/shipments/{efj}")
async def api_v2_shipment_detail(efj: str, request: Request):
    """Return a single shipment from Postgres."""
    with db.get_cursor() as cur:
        cur.execute("SELECT * FROM shipments WHERE efj = %s", (efj,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, f"Shipment {efj} not found")
    return _shipment_row_to_dict(row)


@app.get("/api/v2/stats")
async def api_v2_stats(request: Request):
    """Dashboard stats computed from Postgres."""
    from datetime import datetime as _dt, timedelta as _td
    today = _dt.now().strftime("%Y-%m-%d")
    tomorrow = (_dt.now() + _td(days=1)).strftime("%Y-%m-%d")

    with db.get_cursor() as cur:
        # Active count (not archived, not delivered/completed)
        cur.execute("""
            SELECT COUNT(*) as cnt FROM shipments
            WHERE archived = FALSE
              AND LOWER(status) NOT IN ('delivered', 'completed', 'empty returned', 'billed_closed')
        """)
        active = cur.fetchone()["cnt"]

        # At risk (LFD is today or tomorrow)
        cur.execute("""
            SELECT COUNT(*) as cnt FROM shipments
            WHERE archived = FALSE
              AND LOWER(status) NOT IN ('delivered', 'completed', 'empty returned', 'billed_closed')
              AND lfd != '' AND lfd IS NOT NULL
              AND LEFT(lfd, 10) <= %s
        """, (tomorrow,))
        at_risk = cur.fetchone()["cnt"]

        # Completed today
        cur.execute("""
            SELECT COUNT(*) as cnt FROM shipments
            WHERE archived = FALSE
              AND LOWER(status) IN ('delivered', 'completed')
              AND delivery_date LIKE %s
        """, (f"%{today}%",))
        completed_today = cur.fetchone()["cnt"]

        # ETA changed (bot_notes mentions today)
        cur.execute("""
            SELECT COUNT(*) as cnt FROM shipments
            WHERE archived = FALSE
              AND bot_notes LIKE %s
        """, (f"%{today}%",))
        eta_changed = cur.fetchone()["cnt"]

    on_schedule = max(0, active - at_risk)

    return {
        "active": active,
        "on_schedule": on_schedule,
        "eta_changed": eta_changed,
        "at_risk": at_risk,
        "completed_today": completed_today,
    }


@app.get("/api/v2/accounts")
async def api_v2_accounts(request: Request):
    """Account list with counts from Postgres."""
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT
                account,
                COUNT(*) FILTER (WHERE LOWER(status) NOT IN ('delivered','completed','empty returned','billed_closed') AND archived = FALSE) as active,
                COUNT(*) FILTER (WHERE LOWER(status) IN ('delivered','completed','empty returned','billed_closed') AND archived = FALSE) as done,
                COUNT(*) FILTER (
                    WHERE archived = FALSE
                      AND LOWER(status) NOT IN ('delivered','completed','empty returned','billed_closed')
                      AND lfd != '' AND lfd IS NOT NULL
                      AND LEFT(lfd, 10) <= %s
                ) as alerts
            FROM shipments
            WHERE archived = FALSE
            GROUP BY account
            ORDER BY active DESC
        """, ((_dt.now() + _td(days=1)).strftime("%Y-%m-%d"),))
        rows = cur.fetchall()

    accounts = [{"name": r["account"], "active": r["active"], "done": r["done"], "alerts": r["alerts"]} for r in rows]
    return {"accounts": accounts}


@app.get("/api/v2/team")
async def api_v2_team(request: Request):
    """Team member summaries from Postgres."""
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT rep,
                   COUNT(*) FILTER (WHERE LOWER(status) NOT IN ('delivered','completed','empty returned','billed_closed') AND archived = FALSE) as loads,
                   array_agg(DISTINCT account) FILTER (WHERE LOWER(status) NOT IN ('delivered','completed','empty returned','billed_closed') AND archived = FALSE) as accounts,
                   COUNT(*) FILTER (
                       WHERE archived = FALSE
                         AND LOWER(status) NOT IN ('delivered','completed','empty returned','billed_closed')
                         AND lfd != '' AND lfd IS NOT NULL
                         AND LEFT(lfd, 10) <= to_char(NOW() + interval '1 day', 'YYYY-MM-DD')
                   ) as at_risk
            FROM shipments
            WHERE archived = FALSE AND rep IS NOT NULL AND rep != ''
            GROUP BY rep
        """)
        rows = cur.fetchall()
    team = {}
    for r in rows:
        accts = r["accounts"] if r["accounts"] else []
        accts = [a for a in accts if a]
        team[r["rep"]] = {"loads": r["loads"], "accounts": sorted(accts), "at_risk": r["at_risk"]}
    return {"team": team}


@app.post("/api/v2/load/{efj}/status")
async def api_v2_update_status(efj: str, request: Request):
    """Update status in Postgres. Write back to Google Sheet if shared account."""
    body = await request.json()
    new_status = body.get("status", "").strip()
    if not new_status:
        raise HTTPException(400, "Missing status")

    # Update Postgres
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE shipments SET status = %s, updated_at = NOW() WHERE efj = %s RETURNING account, hub",
                (new_status, efj),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, f"Shipment {efj} not found")

    account = row["account"]

    # Write back to Google Sheet for shared accounts
    if account in _SHARED_SHEET_ACCOUNTS:
        try:
            _v2_write_status_to_sheet(efj, new_status, account, row.get("hub"))
        except Exception as e:
            log.warning("Sheet write-back failed for %s: %s (Postgres updated OK)", efj, e)

    return {"ok": True, "efj": efj, "status": new_status}


def _v2_write_status_to_sheet(efj: str, new_status: str, account: str, hub: str = None):
    """Write status back to Google Sheet for shared accounts (Tolead/Boviet)."""
    creds = Credentials.from_service_account_file(
        CREDS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)

    if account == "Tolead" and hub and hub in TOLEAD_HUB_CONFIGS:
        cfg = TOLEAD_HUB_CONFIGS[hub]
        sh = gc.open_by_key(cfg["sheet_id"])
        ws = sh.worksheet(cfg["tab"])
        rows = ws.get_all_values()
        cols = cfg["cols"]
        for i, row in enumerate(rows):
            efj_val = row[cols["efj"]].strip() if len(row) > cols["efj"] else ""
            load_val = row[cols["load_id"]].strip() if len(row) > cols["load_id"] else ""
            if efj_val == efj or load_val == efj:
                ws.update_cell(i + 1, cols["status"] + 1, new_status)
                log.info("Sheet write-back: Tolead %s %s → %s (row %d)", hub, efj, new_status, i + 1)
                return
        log.warning("Sheet write-back: %s not found in Tolead %s", efj, hub)

    elif account == "Boviet":
        sh = gc.open_by_key(BOVIET_SHEET_ID)
        for bov_tab, cfg in BOVIET_TAB_CONFIGS.items():
            try:
                ws = sh.worksheet(bov_tab)
                rows = ws.get_all_values()
                for i, row in enumerate(rows):
                    if len(row) > cfg["efj_col"] and row[cfg["efj_col"]].strip() == efj:
                        ws.update_cell(i + 1, cfg["status_col"] + 1, new_status)
                        log.info("Sheet write-back: Boviet/%s %s → %s (row %d)", bov_tab, efj, new_status, i + 1)
                        return
            except Exception:
                continue
        log.warning("Sheet write-back: %s not found in Boviet tabs", efj)


@app.post("/api/v2/load/{efj}/update")
async def api_v2_update_field(efj: str, request: Request):
    """Update any field(s) on a shipment in Postgres."""
    body = await request.json()

    # Allowed fields to update
    ALLOWED = {
        "move_type", "container", "bol", "vessel", "carrier",
        "origin", "destination", "eta", "lfd", "pickup_date", "delivery_date",
        "status", "notes", "driver", "bot_notes", "return_date",
        "rep", "customer_ref", "equipment_type", "container_url",
        "driver_phone", "hub", "archived",
    }
    updates = {k: v for k, v in body.items() if k in ALLOWED}
    if not updates:
        raise HTTPException(400, "No valid fields to update")

    set_clauses = [f"{k} = %({k})s" for k in updates]
    set_clauses.append("updated_at = NOW()")
    updates["efj"] = efj

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                f"UPDATE shipments SET {', '.join(set_clauses)} WHERE efj = %(efj)s RETURNING *",
                updates,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, f"Shipment {efj} not found")

    return {"ok": True, "shipment": _shipment_row_to_dict(row)}


@app.post("/api/v2/load/add")
async def api_v2_add_shipment(request: Request):
    """Insert a new shipment into Postgres. Write to Google Sheet if shared account."""
    body = await request.json()
    efj = body.get("efj", "").strip()
    account = body.get("account", "").strip()
    if not efj:
        raise HTTPException(400, "Missing EFJ #")
    if not account:
        raise HTTPException(400, "Missing account")

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO shipments (
                    efj, move_type, container, bol, vessel, carrier,
                    origin, destination, eta, lfd, pickup_date, delivery_date,
                    status, notes, driver, bot_notes, return_date,
                    account, hub, rep, source
                ) VALUES (
                    %(efj)s, %(move_type)s, %(container)s, %(bol)s, %(vessel)s, %(carrier)s,
                    %(origin)s, %(destination)s, %(eta)s, %(lfd)s, %(pickup_date)s, %(delivery_date)s,
                    %(status)s, %(notes)s, %(driver)s, %(bot_notes)s, %(return_date)s,
                    %(account)s, %(hub)s, %(rep)s, 'dashboard'
                )
                ON CONFLICT (efj) DO NOTHING
                RETURNING *
            """, {
                "efj": efj,
                "move_type": body.get("move_type", ""),
                "container": body.get("container", ""),
                "bol": body.get("bol", ""),
                "vessel": body.get("vessel", ""),
                "carrier": body.get("carrier", ""),
                "origin": body.get("origin", ""),
                "destination": body.get("destination", ""),
                "eta": body.get("eta", ""),
                "lfd": body.get("lfd", ""),
                "pickup_date": body.get("pickup_date", ""),
                "delivery_date": body.get("delivery_date", ""),
                "status": body.get("status", ""),
                "notes": body.get("notes", ""),
                "driver": body.get("driver", ""),
                "bot_notes": body.get("bot_notes", ""),
                "return_date": body.get("return_date", ""),
                "account": account,
                "hub": body.get("hub", ""),
                "rep": body.get("rep", "Unassigned"),
            })
            row = cur.fetchone()

    if not row:
        raise HTTPException(409, f"Shipment {efj} already exists")

    return {"ok": True, "shipment": _shipment_row_to_dict(row)}

# ═══ End of v2 endpoints ═══
'''

# ---------------------------------------------------------------------------
# Find insertion point: before the final `if __name__` block or at end
# ---------------------------------------------------------------------------
# Check if there's already a v2 block
if "/api/v2/shipments" in code:
    print("v2 endpoints already present in app.py — skipping")
    sys.exit(0)

# Insert before `if __name__ == "__main__":`
main_match = re.search(r'\nif __name__\s*==\s*["\']__main__["\']:', code)
if main_match:
    insert_pos = main_match.start()
    code = code[:insert_pos] + V2_BLOCK + code[insert_pos:]
    print(f"Inserted v2 endpoints before __main__ block at position {insert_pos}")
else:
    # Append to end
    code += V2_BLOCK
    print("Appended v2 endpoints at end of file")

with open(APP_PY, "w") as f:
    f.write(code)

print("patch_v2_endpoints.py applied successfully")
print("Restart: systemctl restart csl-dashboard")
