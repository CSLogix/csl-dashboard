"""
Migrate export_monitor.py (Dray Export) from Google Sheets to Postgres.

Replaces:
  - run_once() → reads from shipments table, writes to PG only
  - main() + --once block → no longer needs sheet credentials for lookups
  - archive_export_row() → PG archive only (no sheet append/delete)

Tracking logic (jsoncargo_bol_lookup, jsoncargo_container_track) is UNTOUCHED.
Email functions (send_export_alert, send_container_assigned_email, send_archive_email) UNTOUCHED.
"""

BOT_PY = "/root/csl-bot/export_monitor.py"

with open(BOT_PY, "r") as f:
    src = f.read()

# ═══════════════════════════════════════════════════════════════════════════
# 1. Add PG imports + SSL_LINKS + ACCOUNT_REPS after the existing constants
# ═══════════════════════════════════════════════════════════════════════════

marker = '_JSONCARGO_CACHE_TTL = 6 * 3600'
assert marker in src, f"Could not find '{marker}'"
idx = src.index(marker)
line_end = src.index("\n", idx) + 1

PG_BLOCK = '''
# ── Postgres migration: hardcoded lookups ────────────────────────────────
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv as _pg_load_dotenv
_pg_load_dotenv("/root/csl-bot/csl-doc-tracker/.env")

def _pg_connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "csl_dispatch"),
        user=os.getenv("DB_USER", "csl_user"),
        password=os.getenv("DB_PASSWORD", ""),
    )

SSL_LINKS_PG = {
    "maersk":      "MAERSK",
    "hapag":       "HAPAG_LLOYD",
    "hapag-lloyd": "HAPAG_LLOYD",
    "one":         "ONE",
    "evergreen":   "EVERGREEN",
    "hmm":         "HMM",
    "cma cgm":     "CMA_CGM",
    "cma":         "CMA_CGM",
    "apl":         "CMA_CGM",
    "msc":         "MSC",
    "cosco":       "COSCO",
    "zim":         "ZIM",
    "yang ming":   "YANG_MING",
    "acl":         "CMA_CGM",
    "sm line":     "SM_LINE",
    "sml":         "SM_LINE",
    "matson":      "MATSON",
}

ACCOUNT_REPS_PG = {
    "Allround": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Boviet":   {"rep": "",      "email": "Boviet-efj@evansdelivery.com"},
    "Cadi":     {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "CNL":      {"rep": "Janice","email": "Janice.Cortes@evansdelivery.com"},
    "DHL":      {"rep": "John F","email": "John.Feltz@evansdelivery.com"},
    "DSV":      {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "EShipping":{"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "IWS":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Kishco":   {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "Kripke":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MAO":      {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "Mamata":   {"rep": "John F","email": "John.Feltz@evansdelivery.com"},
    "Meiko":    {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MGF":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Mitchell's Transport": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Rose":     {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "SEI Acquisition": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Sutton":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Tanera":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "TCR":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Texas International": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "USHA":     {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
}


def _resolve_ssl_export(vessel, carrier):
    """Resolve SSL code from vessel/carrier text."""
    for text in (vessel or "", carrier or ""):
        val = text.strip().lower()
        if not val:
            continue
        if val in SSL_LINKS_PG:
            return SSL_LINKS_PG[val]
        for key, code in SSL_LINKS_PG.items():
            if key in val:
                return code
        for key, code in SSL_LINKS_PG.items():
            if any(w.startswith(key) for w in val.split()):
                return code
    return None

'''

src = src[:line_end] + PG_BLOCK + src[line_end:]
print("[1/3] Added PG imports + SSL_LINKS_PG + ACCOUNT_REPS_PG + _resolve_ssl_export")


# ═══════════════════════════════════════════════════════════════════════════
# 2. Replace run_once() + main() + __main__ block
# ═══════════════════════════════════════════════════════════════════════════

# Find archive_export_row and replace it with PG-only version
old_archive_start = src.index("def archive_export_row(sheet,tab_name,sheet_row,row_data,job,lookup):")
old_archive_end = src.index("\ndef run_once(", old_archive_start)

NEW_ARCHIVE = '''def archive_export_row_pg(job, tab_name):
    """Archive export row — Postgres only (no sheet writes)."""
    try:
        pg_archive_shipment(job["efj"])
        print(f"    Archived {job['efj']} (Gate In)")
        send_archive_email(tab_name, ACCOUNT_REPS_PG, job)
        return True
    except Exception as e:
        print(f"    WARNING: Archive failed: {e}")
        return False

'''

src = src[:old_archive_start] + NEW_ARCHIVE + src[old_archive_end:]
print("[2/3] Replaced archive_export_row with PG-only version")


# Now replace run_once + main + __main__
run_once_start = src.index("\ndef run_once(")
# Everything from run_once to EOF gets replaced
NEW_TAIL = '''
def run_once():
    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    print(f"\\n[{now_str}] Export poll cycle (Postgres mode)...")

    # ── Read active dray export loads from Postgres ──────────────────────────
    try:
        conn = _pg_connect()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT efj, container, bol, vessel, carrier, origin, destination,
                       CAST(eta AS TEXT) AS eta, CAST(lfd AS TEXT) AS lfd,
                       CAST(pickup_date AS TEXT) AS pickup_date,
                       CAST(delivery_date AS TEXT) AS delivery_date,
                       status, bot_notes,
                       CAST(return_date AS TEXT) AS return_date,
                       account, rep
                FROM shipments
                WHERE move_type = 'Dray Export' AND archived = FALSE
                ORDER BY account, efj
            """)
            all_loads = cur.fetchall()
        conn.close()
    except Exception as exc:
        print(f"FATAL: Could not read from Postgres: {exc}")
        return

    # Group by account
    from collections import defaultdict
    by_account = defaultdict(list)
    for row in all_loads:
        acct = row["account"] or "Unknown"
        by_account[acct].append(row)

    account_tabs = sorted(by_account.keys())
    print(f"  Loaded {len(all_loads)} active Dray Export load(s) across {len(account_tabs)} account(s)")
    if not account_tabs:
        print("  No active export loads found.")
        return

    state = load_state()
    new_state = dict(state)

    for tab_name in account_tabs:
        loads = by_account[tab_name]
        print(f"\\n  Checking {tab_name}... ({len(loads)} export row(s))")
        tab_alerts = []

        for row in loads:
            efj = (row["efj"] or "").strip()
            container = (row["container"] or "").strip()
            booking = (row["bol"] or "").strip()
            vessel = (row["vessel"] or "").strip()
            carrier = (row["carrier"] or "").strip()
            origin = (row["origin"] or "").strip()
            dest = (row["destination"] or "").strip()
            # Use lfd as cutoff for exports, eta as ERD
            erd = (row["eta"] or "").strip()
            cutoff = (row["lfd"] or "").strip()

            if not efj:
                continue

            key = f"{tab_name}:{efj}:{container}"
            print(f"\\n  -> {efj}|{container} booking={booking} ERD={erd!r} Cutoff={cutoff!r}")

            prev = state.get(key, {})
            current = {"erd": erd, "cutoff": cutoff, "cutoff_alerted": prev.get("cutoff_alerted", "")}
            changed = [f.upper() for f in ("erd", "cutoff") if current[f] != prev.get(f, "")]
            if "CUTOFF" in changed:
                current["cutoff_alerted"] = ""
            new_state[key] = current

            alert_reason = _cutoff_alert(cutoff) if cutoff else None
            if alert_reason and current["cutoff_alerted"] == cutoff:
                print(f"    Cutoff alert already sent for {cutoff} - skipping")
                alert_reason = None

            if changed or alert_reason:
                if alert_reason:
                    current["cutoff_alerted"] = cutoff
                    new_state[key] = current
                tab_alerts.append({
                    "efj": efj, "container": container, "vessel": vessel,
                    "booking": booking, "erd": erd, "cutoff": cutoff,
                    "alert_reason": alert_reason, "changed": changed,
                })
                today = datetime.now(ZoneInfo("America/New_York")).strftime("%m-%d %H:%M")
                reason = alert_reason or f"Date change: {', '.join(changed)}"
                pg_update_shipment(efj, bot_notes=f"{reason} - {today}",
                                   account=tab_name, move_type="Dray Export")

            # Resolve SSL line
            ssl_line = _resolve_ssl_export(vessel, carrier)
            if not ssl_line:
                print(f"    SSL line not detected for {vessel}/{carrier} - skipping API")
                continue

            # Check if container column has booking# instead of container#
            if not _is_container_num(container):
                print(f"    Col C is booking# - calling BOL lookup...")
                found_container = jsoncargo_bol_lookup(booking, ssl_line)
                if found_container:
                    print(f"    Container# found: {found_container}")
                    # Update container in Postgres
                    pg_update_shipment(efj, container=found_container,
                                       account=tab_name, move_type="Dray Export")
                    send_container_assigned_email(tab_name, ACCOUNT_REPS_PG, efj, booking, found_container)
                    today = datetime.now(ZoneInfo("America/New_York")).strftime("%m-%d %H:%M")
                    pg_update_shipment(efj, bot_notes=f"Container# assigned: {found_container} - {today}")
                    container = found_container
                else:
                    print(f"    No container# yet for {efj}")
                    continue

            print(f"    Tracking container# {container}...")
            track = jsoncargo_container_track(container, ssl_line)
            if not track:
                print(f"    No tracking data for {container}")
                continue
            if track["gate_in"]:
                print(f"    GATE IN: {track['gate_in']} - archiving")
                job = {
                    "efj": efj, "container": container, "booking": booking,
                    "vessel": vessel, "origin": origin, "dest": dest,
                    "erd": erd, "cutoff": cutoff, "gate_in_status": track["gate_in"],
                }
                ok = archive_export_row_pg(job, tab_name)
                if ok:
                    new_state.pop(key, None)
            else:
                print(f"    No gate-in yet for {container}")

        if tab_alerts:
            print(f"\\n  Sending alert for {len(tab_alerts)} row(s)...")
            send_export_alert(tab_name, ACCOUNT_REPS_PG, tab_alerts)
        else:
            print(f"  No alerts for {tab_name}")

    save_state(new_state)
    print("Export poll complete.")


def main():
    print("Export Monitor v3 (Postgres mode) started.")
    while True:
        run_once()
        print("  Sleeping 60 min...")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        print("Export Monitor v3 — single run (Postgres)")
        run_once()
        print("Run complete.")
    else:
        main()
'''

src = src[:run_once_start] + NEW_TAIL
print("[3/3] Replaced run_once + main + __main__ with PG versions")


# ═══════════════════════════════════════════════════════════════════════════
# Write
# ═══════════════════════════════════════════════════════════════════════════
with open(BOT_PY, "w") as f:
    f.write(src)

print("\nDone. export_monitor.py now reads from Postgres.")
print("Test with: python3 /root/csl-bot/export_monitor.py --once")
