"""
Migrate ftl_monitor.py from Google Sheets + Playwright scraping to Postgres + webhook cache.

Removes:
  - All Playwright/Macropoint scraping (scrape_macropoint, _parse_macropoint, etc.)
  - All Google Sheets I/O (gspread, _get_hyperlinks, get_ftl_rows, etc.)
  - Sheet writes (ws.batch_update) and sheet archive (append + delete)
  - One-time cleanup/backfill functions

Replaces:
  - run_once() → reads from PG shipments table, reads status from webhook-updated tracking cache
  - archive_ftl_row() → PG archive only (pg_archive_shipment)
  - main() / __main__ → supports --once flag for cron

Keeps untouched:
  - Email functions (send_ftl_email, _send_email, send_pro_alert, _send_pod_reminder_ftl)
  - Alert dedup (load_sent_alerts, save_sent_alerts, already_sent, mark_sent)
  - Tracking cache I/O (load_tracking_cache, save_tracking_cache, update_tracking_cache)
  - Unresponsive driver logic (send_unresponsive_alert, check_unresponsive)
  - State file management (ftl_sent_alerts.json, ftl_tracking_cache.json, unresponsive_state.json)
"""

import shutil
from datetime import datetime

BOT_PY = "/root/csl-bot/ftl_monitor.py"

# Backup
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(BOT_PY, f"{BOT_PY}.bak.{ts}")
print(f"Backup: {BOT_PY}.bak.{ts}")

with open(BOT_PY, "r") as f:
    src = f.read()

# ═══════════════════════════════════════════════════════════════════════════
# Step 1: Fix log.info/log.warning bugs (undefined `log` variable)
#         Add logging import + logger setup
# ═══════════════════════════════════════════════════════════════════════════

old_imports = """import os
import re
import smtplib
import time
import requests
import gspread
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

load_dotenv()

from csl_pg_writer import pg_update_shipment, pg_archive_shipment"""

new_imports = """import os
import re
import smtplib
import time
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

import psycopg2
import psycopg2.extras
from csl_pg_writer import pg_update_shipment, pg_archive_shipment

log = logging.getLogger("ftl_monitor")
logging.basicConfig(level=logging.INFO, format='%(message)s')"""

assert old_imports in src, "Import block not found"
src = src.replace(old_imports, new_imports)
print("[1/5] Replaced imports (removed gspread/playwright/google, added psycopg2/logging)")


# ═══════════════════════════════════════════════════════════════════════════
# Step 2: Remove _retry_on_quota through everything before _build_note
#         Insert PG config + ACCOUNT_REPS_PG + _pg_connect
# ═══════════════════════════════════════════════════════════════════════════

remove_start_marker = "def _retry_on_quota(func, *args, max_retries=3, **kwargs):"
remove_end_marker = "def _build_note(existing_notes: str, new_part: str) -> str:"

assert remove_start_marker in src, f"Start marker not found: {remove_start_marker}"
assert remove_end_marker in src, f"End marker not found: {remove_end_marker}"

idx_start = src.index(remove_start_marker)
idx_end = src.index(remove_end_marker)

PG_CONFIG_BLOCK = '''# ── Config ──────────────────────────────────────────────────────────────────────
SENT_ALERTS_FILE    = "/root/csl-bot/ftl_sent_alerts.json"
TRACKING_CACHE_FILE = "/root/csl-bot/ftl_tracking_cache.json"

ALERT_CUTOFF_DATE   = "2026-03-01"
POLL_INTERVAL       = 30 * 60  # seconds

# ── SMTP / email ─────────────────────────────────────────────────────────────────
SMTP_HOST      = "smtp.gmail.com"
SMTP_PORT      = 587
SMTP_USER      = os.environ["SMTP_USER"]
SMTP_PASSWORD  = os.environ["SMTP_PASSWORD"]
EMAIL_CC       = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")
EMAIL_FALLBACK = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")


# ── Postgres ─────────────────────────────────────────────────────────────────────
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
    "Kischo":   {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "Kripke":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MAO":      {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "Mamata":   {"rep": "John F","email": "John.Feltz@evansdelivery.com"},
    "Meiko":    {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MGF":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Mitchell\\'s Transport": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Rose":     {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "SEI Acquisition": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Sutton":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Tanera":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Talatrans":{"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "TCR":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Texas International": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Tolead":   {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "USHA":     {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
}


STATUS_TO_DROPDOWN = {
    "Driver Arrived at Pickup": "At Pickup",
    "Departed Pickup - En Route": "In Transit",
    "Arrived at Delivery": "At Delivery",
    "Departed Delivery": "Departed Delivery",
    "Running Late": "Running Behind",
    "Tracking Behind Schedule": "Running Behind",
    "Tracking Waiting for Update": "Tracking Waiting for",
    "Delivered": "Delivered",
    "Driver Phone Unresponsive": "Driver Phone Unresponsive",
}


def _find_cache_entry(cache, efj):
    """Find a tracking cache entry matching the given EFJ."""
    efj_clean = efj.replace("EFJ", "").strip()
    if efj in cache:
        return efj, cache[efj]
    if efj_clean in cache:
        return efj_clean, cache[efj_clean]
    for key, entry in cache.items():
        entry_efj = entry.get("efj", "")
        if (entry_efj == efj or entry_efj == efj_clean or
                entry.get("mp_load_id") == efj or entry.get("mp_load_id") == efj_clean):
            return key, entry
    return None, None


'''

src = src[:idx_start] + PG_CONFIG_BLOCK + src[idx_end:]
print("[2/5] Replaced config + parser + scraper + sheets with PG config block")


# ═══════════════════════════════════════════════════════════════════════════
# Step 3: Replace archive functions + one-time cleanup/backfill
#         with archive_ftl_row_pg
# ═══════════════════════════════════════════════════════════════════════════

archive_start_marker = "# ── Archive helpers ──"
assert archive_start_marker in src, f"Archive marker not found: {archive_start_marker}"
archive_start = src.index(archive_start_marker)

run_once_marker = "\ndef run_once("
assert run_once_marker in src, "run_once marker not found"
run_once_start = src.index(run_once_marker)

NEW_ARCHIVE = '''# ── Archive (Postgres only) ────────────────────────────────────────────────────
def archive_ftl_row_pg(efj, load_num, dest, tab_name, pickup_val, delivery_val,
                       account_lookup, mp_load_id=None):
    """Archive FTL row — Postgres only (no sheet writes)."""
    rep_info = account_lookup.get(tab_name, {})
    rep_email = rep_info.get("email", "")
    rep_name = rep_info.get("rep", "")
    try:
        pg_archive_shipment(efj)
        print(f"    Archived {efj} (Delivered)")

        # Send archive email
        if rep_email:
            timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
            subject = f"CSL Archived | {load_num} | {efj} | Delivered"
            body = (
                f"FTL load {efj} ({load_num}) has been archived.\\n\\n"
                f"Account:  {tab_name}\\n"
                f"Rep:      {rep_name}\\n\\n"
                f"Pickup:   {pickup_val or chr(8212)}\\n"
                f"Delivery: {delivery_val or chr(8212)}\\n"
                f"Status:   Delivered\\n"
                f"Archived: {timestamp}\\n"
            )
            cc = None if tab_name.lower() == "boviet" else EMAIL_CC
            _send_email(rep_email, cc, subject, body)

        # Send POD reminder
        _send_pod_reminder_ftl(efj, load_num, dest, tab_name, account_lookup, mp_load_id=mp_load_id)
        return True
    except Exception as e:
        print(f"    WARNING: Archive failed: {e}")
        return False


'''

src = src[:archive_start] + NEW_ARCHIVE + src[run_once_start:]
print("[3/4] Replaced archive + cleanup/backfill with PG-only archive")


# ═══════════════════════════════════════════════════════════════════════════
# Step 4: Replace run_once + main + __main__ with PG versions
# ═══════════════════════════════════════════════════════════════════════════

run_once_start = src.index("\ndef run_once(")

NEW_TAIL = '''
def run_once():
    """FTL poll cycle — reads from Postgres, checks webhook-updated tracking cache."""
    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    print(f"\\n[{now_str}] FTL poll cycle (Postgres mode)...")

    # ── Read active FTL loads from Postgres ────────────────────────────────
    try:
        conn = _pg_connect()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT efj, container, bol, vessel, carrier, origin, destination,
                       CAST(eta AS TEXT) AS eta, CAST(lfd AS TEXT) AS lfd,
                       CAST(pickup_date AS TEXT) AS pickup_date,
                       CAST(delivery_date AS TEXT) AS delivery_date,
                       status, bot_notes, account, rep
                FROM shipments
                WHERE move_type = 'FTL' AND archived = FALSE
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
    print(f"  Loaded {len(all_loads)} active FTL load(s) across {len(account_tabs)} account(s)")
    if not account_tabs:
        print("  No active FTL loads found.")
        return

    sent = load_sent_alerts()
    tracking_cache = load_tracking_cache()

    for tab_name in account_tabs:
        loads = by_account[tab_name]
        print(f"\\n  Checking {tab_name}... ({len(loads)} FTL row(s))")

        for row in loads:
            efj = (row["efj"] or "").strip()
            container = (row["container"] or "").strip()
            load_num = container or efj  # FTL uses container/load# as identifier
            dest = (row["destination"] or "").strip()
            existing_pickup = (row["pickup_date"] or "").strip()
            existing_delivery = (row["delivery_date"] or "").strip()
            existing_status = (row["status"] or "").strip()
            existing_notes = (row["bot_notes"] or "").strip()

            if not efj:
                continue

            key = f"{efj}|{load_num}"

            # ── Find or initialize cache entry ────────────────────────────
            cache_key, cached = _find_cache_entry(tracking_cache, efj)
            if cached is None:
                # Initialize so webhook can update it later
                cache_key = efj.replace("EFJ", "").strip()
                tracking_cache[cache_key] = {
                    "efj": efj,
                    "load_num": load_num,
                    "status": existing_status,
                    "mp_load_id": efj,
                    "cant_make_it": None,
                    "stop_times": {},
                    "macropoint_url": "",
                    "last_scraped": "",
                    "driver_phone": "",
                }
                cached = tracking_cache[cache_key]
                print(f"  -> {key} (initialized cache entry)")

            cached_status = cached.get("status", "")
            stop_times = cached.get("stop_times", {})
            mp_load_id = cached.get("mp_load_id", "")
            cant_make_it = cached.get("cant_make_it")
            driver_phone = cached.get("driver_phone", "")

            print(f"  -> {key} cached={cached_status!r} pg={existing_status!r}")

            if not cached_status:
                continue  # No webhook data yet

            # ── Map webhook status to dropdown ────────────────────────────
            dropdown_val = STATUS_TO_DROPDOWN.get(cached_status)

            note_parts = []
            final_pickup = existing_pickup
            final_delivery = existing_delivery
            final_notes = existing_notes

            # Extract dates from stop_times (webhook provides these)
            stop1_date = stop_times.get("stop1_arrived")
            stop2_date = stop_times.get("stop2_departed") or stop_times.get("stop2_arrived")

            # Update pickup from cache if PG has no value
            if stop1_date and not existing_pickup:
                final_pickup = stop1_date
                note_parts.append(f"Pickup {stop1_date}")

            # Update delivery from cache if PG has no value
            if stop2_date and not existing_delivery:
                final_delivery = stop2_date
                note_parts.append(f"Delivery {stop2_date}")

            # Check if status changed
            if dropdown_val and existing_status != dropdown_val:
                note_parts.append(dropdown_val)
                print(f"    Status change: {existing_status!r} -> {dropdown_val!r}")

            # ── Write to PG if anything changed ──────────────────────────
            if note_parts:
                note = _build_note(existing_notes, ", ".join(note_parts))
                final_notes = note
                pg_update_shipment(
                    efj,
                    pickup_date=final_pickup or None,
                    delivery_date=final_delivery or None,
                    status=dropdown_val or None,
                    bot_notes=final_notes or None,
                    account=tab_name,
                    move_type="FTL",
                )
                print(f"    PG updated")

            # ── Check for unresponsive driver ─────────────────────────────
            rep_info = ACCOUNT_REPS_PG.get(tab_name, {})
            rep_email = rep_info.get("email", EMAIL_FALLBACK)
            if cached_status and "unresponsive" in cached_status.lower():
                check_unresponsive(
                    efj, load_num, cached_status, tab_name,
                    row.get("carrier", ""), driver_phone, "",
                    rep_email, tracking_cache
                )

            # ── Skip alerts for loads with pickup before cutoff ───────────
            _skip_old = False
            _date_src = existing_pickup or final_pickup
            if ALERT_CUTOFF_DATE and _date_src:
                try:
                    _m = re.search(r"(\\d{2})[-/](\\d{2})", _date_src)
                    if _m:
                        _pickup_dt = datetime.strptime(
                            f"{datetime.now().year}-{_m.group(1)}-{_m.group(2)}", "%Y-%m-%d"
                        )
                        _cutoff_dt = datetime.strptime(ALERT_CUTOFF_DATE, "%Y-%m-%d")
                        if _pickup_dt < _cutoff_dt:
                            _skip_old = True
                except (ValueError, IndexError):
                    pass
            if _skip_old:
                print(f"    Pickup {_date_src} before cutoff {ALERT_CUTOFF_DATE} — skipping email")
                continue

            # ── Only alert on actual status CHANGES ──────────────────────
            if existing_status.strip().lower() == cached_status.strip().lower():
                mark_sent(sent, key, cached_status)
                continue

            if already_sent(sent, key, cached_status):
                print(f"    Already alerted for '{cached_status}' — skipping")
            else:
                send_ftl_email(efj, load_num, cached_status, tab_name, ACCOUNT_REPS_PG,
                               mp_load_id=mp_load_id, stop_times=stop_times)
                mark_sent(sent, key, cached_status)

            # ── CAN'T MAKE IT alert ──────────────────────────────────────
            if cant_make_it:
                cmi_status = f"Can't Make It - {cant_make_it}"
                if not already_sent(sent, key, cmi_status):
                    print(f"    CAN'T MAKE IT detected: {cant_make_it}")
                    send_ftl_email(efj, load_num, cmi_status, tab_name, ACCOUNT_REPS_PG,
                                   mp_load_id=mp_load_id)
                    mark_sent(sent, key, cmi_status)

            # ── Archive if Delivered ──────────────────────────────────────
            if "delivered" in cached_status.lower():
                archive_ftl_row_pg(efj, load_num, dest, tab_name,
                                    final_pickup, final_delivery, ACCOUNT_REPS_PG,
                                    mp_load_id=mp_load_id)

    save_tracking_cache(tracking_cache)
    save_sent_alerts(sent)
    print("FTL poll complete.")


def main():
    print("FTL Monitor v3 (Postgres mode) started.")
    while True:
        run_once()
        print(f"  Sleeping {POLL_INTERVAL // 60} minutes...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        print("FTL Monitor v3 — single run (Postgres)")
        run_once()
        print("Run complete.")
    else:
        main()
'''

src = src[:run_once_start] + NEW_TAIL
print("[4/4] Replaced run_once + main + __main__ with PG versions")


# ═══════════════════════════════════════════════════════════════════════════
# Write
# ═══════════════════════════════════════════════════════════════════════════
with open(BOT_PY, "w") as f:
    f.write(src)

print(f"\nDone. ftl_monitor.py now reads from Postgres + webhook cache.")
print("Test with: python3 /root/csl-bot/ftl_monitor.py --once")
