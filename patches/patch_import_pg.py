"""
Migrate csl_bot.py (Dray Import) from Google Sheets to Postgres.

Replaces run_once() to:
  - Read active loads from shipments table instead of Google Sheets
  - Write tracking results to Postgres only (no sheet writes)
  - Archive via pg_archive_shipment() only (no sheet append/delete)
  - Use hardcoded SSL_LINKS + ACCOUNT_REPS dicts (no sheet lookups)

Tracking logic (dray_import_workflow, all scrapers, APIs) is UNTOUCHED.
"""

import re

BOT_PY = "/root/csl-bot/csl_bot.py"

with open(BOT_PY, "r") as f:
    src = f.read()

# ═══════════════════════════════════════════════════════════════════════════
# 1. Add SSL_LINKS and ACCOUNT_REPS dicts after the existing imports section
# ═══════════════════════════════════════════════════════════════════════════

# Find a good insertion point — after the BOT_MANAGED_STATUSES block
marker = "BOT_MANAGED_STATUSES ="
assert marker in src, f"Could not find '{marker}' in csl_bot.py"

# Find the end of the BOT_MANAGED_STATUSES set literal
idx = src.index(marker)
# Find the closing brace
brace_end = src.index("}", idx) + 1
# Find end of that line
line_end = src.index("\n", brace_end) + 1

PG_DICTS = '''
# ── Postgres migration: hardcoded lookups (replaces sheet tabs) ──────────
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv as _pg_load_dotenv
_pg_load_dotenv("/root/csl-bot/csl-doc-tracker/.env")

def _pg_connect():
    """Connect to Postgres using dashboard .env credentials."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "csl_dispatch"),
        user=os.getenv("DB_USER", "csl_user"),
        password=os.getenv("DB_PASSWORD", ""),
    )

SSL_LINKS = {
    "maersk":    {"code": "MAERSK",      "url": "https://www.maersk.com/tracking"},
    "hapag":     {"code": "HAPAG_LLOYD",  "url": "https://www.hapag-lloyd.com/en/online-business/track"},
    "hapag-lloyd": {"code": "HAPAG_LLOYD","url": "https://www.hapag-lloyd.com/en/online-business/track"},
    "one":       {"code": "ONE",          "url": "https://ecomm.one-line.com/one-ecom/manage-shipment/cargo-tracking"},
    "evergreen": {"code": "EVERGREEN",    "url": "https://www.shipmentlink.com/tvs2/jsp/TVS2_498.jsp"},
    "hmm":       {"code": "HMM",          "url": "https://www.hmm21.com/cms/business/ebiz/trackTrace"},
    "cma cgm":   {"code": "CMA_CGM",      "url": "https://www.cma-cgm.com/ebusiness/tracking"},
    "cma":       {"code": "CMA_CGM",      "url": "https://www.cma-cgm.com/ebusiness/tracking"},
    "apl":       {"code": "CMA_CGM",      "url": "https://www.apl.com/tracking"},
    "msc":       {"code": "MSC",          "url": "https://www.msc.com/en/track-a-shipment"},
    "cosco":     {"code": "COSCO",        "url": "https://elines.coscoshipping.com/ebusiness/cargoTracking"},
    "zim":       {"code": "ZIM",          "url": "https://www.zim.com/tools/track-a-shipment"},
    "yang ming": {"code": "YANG_MING",    "url": "https://www.yangming.com/e-service/Track_Trace/track_trace_cargo_tracking.aspx"},
    "acl":       {"code": "CMA_CGM",      "url": "https://www.aclcargo.com/track-trace/"},
    "sm line":   {"code": "SM_LINE",      "url": "https://www.smlines.com/smline/CUP_HOM_3000.do"},
    "sml":       {"code": "SM_LINE",      "url": "https://www.smlines.com/smline/CUP_HOM_3000.do"},
    "matson":    {"code": "MATSON",        "url": "https://www.matson.com/tracking"},
}

ACCOUNT_REPS = {
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


def _resolve_ssl_pg(vessel, carrier):
    """Resolve SSL code + URL from vessel/carrier text using hardcoded SSL_LINKS."""
    for text in (vessel or "", carrier or ""):
        val = text.strip().lower()
        if not val:
            continue
        # Exact match
        if val in SSL_LINKS:
            return SSL_LINKS[val]
        # Substring match
        for key, info in SSL_LINKS.items():
            if key in val:
                return info
        # Word-boundary match
        for key, info in SSL_LINKS.items():
            if any(w.startswith(key) for w in val.split()):
                return info
    return None

'''

src = src[:line_end] + PG_DICTS + src[line_end:]
print("[1/2] Added SSL_LINKS, ACCOUNT_REPS, _pg_connect, _resolve_ssl_pg")


# ═══════════════════════════════════════════════════════════════════════════
# 2. Replace run_once() entirely
# ═══════════════════════════════════════════════════════════════════════════

# Find the run_once function
run_once_start = src.index("def run_once(args):")
# Find the next top-level def (main)
main_start = src.index("\ndef main():", run_once_start)

NEW_RUN_ONCE = '''def run_once(args):
    from zoneinfo import ZoneInfo as _ZI
    from collections import defaultdict
    now_str = _time.strftime("%Y-%m-%d %H:%M ET", _time.localtime())
    print(f"\\n[{now_str}] Dray Import cycle (Postgres mode)...")

    # ── Read active dray import loads from Postgres ──────────────────────────
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
                WHERE move_type = 'Dray Import' AND archived = FALSE
                ORDER BY account, efj
            """)
            all_loads = cur.fetchall()
        conn.close()
    except Exception as exc:
        print(f"FATAL: Could not read from Postgres: {exc}")
        return

    # Group by account
    by_account = defaultdict(list)
    for row in all_loads:
        acct = row["account"] or "Unknown"
        by_account[acct].append(row)

    account_tabs = sorted(by_account.keys())
    print(f"  Loaded {len(all_loads)} active Dray Import load(s) across {len(account_tabs)} account(s)")
    print(f"  Accounts: {account_tabs}")

    if args.tab:
        if args.tab in by_account:
            account_tabs = [args.tab]
        else:
            print(f"Tab '{args.tab}' not found. Available: {account_tabs}")
            return

    if not account_tabs:
        print("No active Dray Import loads found.")
        return

    last_check = load_last_check()
    new_check  = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            proxy={
                "server":   os.environ["PROXY_SERVER"],
                "username": os.environ["PROXY_USERNAME"],
                "password": os.environ["PROXY_PASSWORD"],
            },
        )
        circuit_breaker = CircuitBreaker(threshold=3)

        # Quick proxy health check before scraping
        proxy_ok = check_proxy_health(browser)
        if not proxy_ok:
            print()
            print("  WARNING: Proxy is down - browser scrapers will be skipped.")
            print("  Only API-based routes will run.")
            print()

        for tab_name in account_tabs:
            loads = by_account[tab_name]
            print(f"\\n{'='*60}")
            print(f"Account: {tab_name}")
            print(f"  Loads: {len(loads)}")

            dray_jobs = []
            for row in loads:
                efj_val = (row["efj"] or "").strip()
                container = (row["container"] or "").strip()
                bol = (row["bol"] or "").strip()
                vessel = (row["vessel"] or "").strip()
                carrier = (row["carrier"] or "").strip()

                if not efj_val:
                    continue

                # Resolve SSL code from vessel/carrier
                ssl_match = _resolve_ssl_pg(vessel, carrier)

                dray_jobs.append({
                    "efj":       efj_val,
                    "sheet_row": 0,  # Not used in PG mode
                    "container": container,
                    "url":       ssl_match["url"] if ssl_match else None,
                    "ssl_code":  ssl_match["code"] if ssl_match else None,
                    "bol":       bol,
                    "vessel":    vessel,
                    "carrier":   carrier,
                    "account":   tab_name,
                    "rep":       (row["rep"] or "").strip(),
                    "row_data":  [
                        efj_val, "Dray Import", container, bol, vessel, carrier,
                        row["origin"] or "", row["destination"] or "",
                        row["eta"] or "", row["lfd"] or "",
                        row["pickup_date"] or "", row["delivery_date"] or "",
                        row["status"] or "", "", row["bot_notes"] or "",
                        row["return_date"] or "",
                    ],
                    # Existing values for overwrite guard
                    "existing_eta":    row["eta"] or "",
                    "existing_pickup": row["pickup_date"] or "",
                    "existing_return": row["return_date"] or "",
                    "existing_status": row["status"] or "",
                })

            print(f"  Dray Import rows: {len(dray_jobs)}")

            tab_changes  = []
            archive_jobs = []
            for job in dray_jobs:
                if not job["ssl_code"] and not job["url"]:
                    print(f"  {job['efj']}: no SSL match for vessel={job['vessel']!r} carrier={job['carrier']!r} — skipped.")
                    continue
                if not job["bol"] and not job["container"]:
                    print(f"  {job['efj']}: no BOL or container — skipped.")
                    continue

                # Use a throwaway list for pending_updates (sheet writes we discard)
                _discard = []
                try:
                    eta, pickup, ret, status = dray_import_workflow(
                        browser, None, job["sheet_row"], job["url"], job["bol"],
                        job["container"], circuit_breaker=circuit_breaker,
                        vessel=job.get("vessel", ""),
                        carrier_name=job.get("carrier", ""),
                        pending_updates=_discard,
                        proxy_ok=proxy_ok,
                        ssl_code=job.get("ssl_code"),
                        existing_row=job.get("row_data"),
                    )
                except Exception as _wf_err:
                    print(f"    ERROR: Workflow crashed for {job['container']}: {_wf_err}")
                    eta, pickup, ret, status = None, None, None, None

                container_id  = job["container"].strip() or job["efj"]
                container_key = f"{tab_name}:{container_id}"

                current = {
                    "eta":         eta    or "",
                    "lfd":         pickup or "",
                    "return_date": ret    or "",
                    "status":      status or "",
                }
                new_check[container_key] = current

                # ── Write to Postgres (primary) ──────────────────────────────
                if job["efj"] and not args.dry_run:
                    # Apply same overwrite guards as sheet mode
                    write_eta = eta if (eta and not job["existing_eta"]) else None
                    write_pickup = pickup if (pickup and not job["existing_pickup"]) else None
                    write_return = ret if (ret and not job["existing_return"]) else None
                    write_status = status if (status and job["existing_status"] in BOT_MANAGED_STATUSES) else None

                    ts = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
                    pg_update_shipment(
                        job["efj"],
                        eta=write_eta,
                        pickup_date=write_pickup,
                        return_date=write_return,
                        status=write_status,
                        bot_notes=ts,
                        account=tab_name,
                        move_type="Dray Import",
                    )

                prev           = last_check.get(container_key, {})
                changed_fields = [
                    field.replace("_", " ").title()
                    for field in ("eta", "lfd", "return_date", "status")
                    if current[field] != prev.get(field, "")
                ]

                if changed_fields:
                    tab_changes.append({
                        "container":      container_id,
                        "eta":            current["eta"],
                        "lfd":            current["lfd"],
                        "return_date":    current["return_date"],
                        "status":         current["status"],
                        "changed_fields": changed_fields,
                    })

                # Queue for archiving if container has been returned to port
                if status == "Returned to Port":
                    archive_jobs.append({
                        "efj":         job["efj"],
                        "container":   container_id,
                        "eta":         eta,
                        "pickup":      pickup,
                        "return_date": ret,
                        "status":      status,
                    })

            # ── Archive completed loads (Postgres only) ──────────────────────
            if archive_jobs and not args.dry_run:
                print(f"\\n  Archiving {len(archive_jobs)} completed load(s)...")
                for aj in archive_jobs:
                    pg_archive_shipment(aj["efj"])
                    print(f"  Archived {aj['efj']} (Returned to Port)")

                    # Remove from new_check
                    archived_key = f"{tab_name}:{aj['container']}"
                    new_check.pop(archived_key, None)

                    # Send archive email
                    rep_info  = ACCOUNT_REPS.get(tab_name, {})
                    rep_email = rep_info.get("email", "")
                    rep_name  = rep_info.get("rep", "")
                    if rep_email:
                        timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
                        subject = f"CSL Archived | {aj['efj']} | {aj['container']} | Returned to Port"
                        _td = 'style="padding:4px 10px;font-size:13px;"'
                        _tl = 'style="padding:4px 10px;color:#555;font-size:13px;"'
                        body = (
                            f'<div style="font-family:Arial,sans-serif;max-width:700px;">'
                            f'<div style="background:#1b5e20;color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:15px;">'
                            f'<b>Container Archived &mdash; Returned to Port</b></div>'
                            f'<div style="border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:12px;">'
                            f'<p style="margin:0 0 8px 0;font-size:12px;color:#888;">Archived: {timestamp}</p>'
                            f'<table style="border-collapse:collapse;">'
                            f'<tr><td {_tl}>EFJ#</td><td {_td}><b>{aj["efj"]}</b></td></tr>'
                            f'<tr><td {_tl}>Container</td><td {_td}><b>{aj["container"]}</b></td></tr>'
                            f'<tr><td {_tl}>Account</td><td {_td}>{tab_name}</td></tr>'
                            f'<tr><td {_tl}>Rep</td><td {_td}>{rep_name}</td></tr>'
                            f'<tr><td {_tl}>ETA</td><td {_td}>{aj["eta"] or "—"}</td></tr>'
                            f'<tr><td {_tl}>Pickup</td><td {_td}>{aj["pickup"] or "—"}</td></tr>'
                            f'<tr><td {_tl}>Returned</td><td {_td}>{aj["return_date"] or "—"}</td></tr>'
                            f'<tr><td {_tl}>Status</td><td {_td}>{aj["status"]}</td></tr>'
                            f'</table></div></div>'
                        )
                        _send_email(rep_email, EMAIL_CC, subject, body)

            if tab_changes:
                print(f"\\n  {len(tab_changes)} change(s) detected — sending email...")
                send_account_notification(tab_name, ACCOUNT_REPS, tab_changes)
            else:
                print(f"\\n  No changes in '{tab_name}'.")

        browser.close()

    save_last_check(new_check)
    print("\\nRun complete.")

'''

src = src[:run_once_start] + NEW_RUN_ONCE + src[main_start:]
print("[2/2] Replaced run_once() with Postgres-native version")

# ═══════════════════════════════════════════════════════════════════════════
# Write
# ═══════════════════════════════════════════════════════════════════════════
with open(BOT_PY, "w") as f:
    f.write(src)

print("\nDone. csl_bot.py now reads from Postgres.")
print("Test with: python3 /root/csl-bot/csl_bot.py --once --dry-run")
