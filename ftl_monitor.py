#!/usr/bin/env python3
"""
ftl_monitor.py — polls all account tabs every 30 minutes for FTL rows,
uses Playwright to scrape Macropoint tracking status, sends email alerts
routed to the rep assigned to each account tab, and writes pickup/delivery
dates to the sheet.
"""
import json

# ── Unresponsive driver state tracking ──
UNRESPONSIVE_STATE_FILE = "/root/csl-bot/unresponsive_state.json"

def load_unresponsive_state():
    try:
        with open(UNRESPONSIVE_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_unresponsive_state(state):
    tmp = UNRESPONSIVE_STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, UNRESPONSIVE_STATE_FILE)

import os
import re
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

import psycopg2
import psycopg2.extras
from csl_pg_writer import pg_update_shipment, pg_archive_shipment
from csl_sheet_writer import sheet_update_ftl, sheet_archive_row
from csl_ftl_alerts import (
    ACCOUNT_REPS_PG, STATUS_TO_DROPDOWN,
    load_sent_alerts, save_sent_alerts, already_sent, mark_sent,
    _send_email, send_ftl_email, _send_pod_reminder_ftl,
    EMAIL_CC, EMAIL_FALLBACK,
)


log = logging.getLogger("ftl_monitor")
logging.basicConfig(level=logging.INFO, format='%(message)s')


# ── Config ──────────────────────────────────────────────────────────────────────
SENT_ALERTS_FILE    = "/root/csl-bot/ftl_sent_alerts.json"
TRACKING_CACHE_FILE = "/root/csl-bot/ftl_tracking_cache.json"

ALERT_CUTOFF_DATE   = "2026-03-01"
POLL_INTERVAL       = 30 * 60  # seconds

# ── SMTP / email ─────────────────────────────────────────────────────────────────


# ── Postgres ─────────────────────────────────────────────────────────────────────
from dotenv import load_dotenv as _pg_load_dotenv

# ── Status hierarchy: higher number = further along in lifecycle ──
_STATUS_RANK = {
    "Tracking Started": 1,
    "Tracking Waiting for Update": 2,
    "Driver Phone Unresponsive": 2,
    "Driver Arrived at Pickup": 3,
    "At Pickup": 3,
    "Departed Pickup - En Route": 4,
    "In Transit": 4,
    "Running Late": 4,
    "Tracking Behind Schedule": 4,
    "Arrived at Delivery": 5,
    "At Delivery": 5,
    "Departed Delivery": 6,
    "Delivered": 7,
    "Tracking Completed Successfully": 8,
}

_TERMINAL_STATUSES = {"Delivered", "Tracking Completed Successfully", "Billed/Closed", "billed_closed"}

def _status_is_regression(old_status, new_status):
    """Return True if new_status is a regression from old_status."""
    old_rank = _STATUS_RANK.get(old_status, 0)
    new_rank = _STATUS_RANK.get(new_status, 0)
    return new_rank > 0 and old_rank > 0 and new_rank < old_rank

_pg_load_dotenv("/root/csl-bot/csl-doc-tracker/.env")

def _pg_connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "csl_dispatch"),
        user=os.getenv("DB_USER", "csl_user"),
        password=os.getenv("DB_PASSWORD", ""),
    )


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


def _build_note(existing_notes: str, new_part: str) -> str:
    today    = datetime.now(ZoneInfo("America/New_York")).strftime("%m-%d")
    base     = re.sub(r"\s*—\s*updated\s*\d{2}-\d{2}\s*$", "", existing_notes).strip()
    combined = f"{base}, {new_part}".lstrip(", ") if base else new_part
    return f"{combined} — updated {today}"


# ── Alert dedup ──────────────────────────────────────────────────────────────────




# ── Tracking cache (for dashboard) ──────────────────────────────────────
def load_tracking_cache() -> dict:
    """Load the tracking cache from disk."""
    try:
        with open(TRACKING_CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_tracking_cache(cache: dict):
    """Atomically write tracking cache to disk."""
    tmp = TRACKING_CACHE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, TRACKING_CACHE_FILE)


def update_tracking_cache(efj: str, load_num: str, status, mp_load_id,
                          cant_make_it, stop_times: dict, url: str, cache: dict,
                          driver_phone: str = None, mp_status=None):
    """Update a single load entry in the tracking cache dict."""
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")
    cache[efj] = {
        "efj": efj,
        "load_num": load_num,
        "status": status,
        "mp_load_id": mp_load_id,
        "cant_make_it": cant_make_it,
        "stop_times": stop_times or {},
        "macropoint_url": url,
        "mp_status": mp_status or "",
        "last_scraped": now,
        "driver_phone": driver_phone or cache.get(efj, {}).get("driver_phone"),
    }


# ── EFJ Pro alert ───────────────────────────────────────────────────────────────

# ── Unresponsive driver alert ────────────────────────────────────────────

def send_unresponsive_alert(efj, load_num, account, carrier, driver_phone,
                            carrier_email, rep_email, escalation=False):
    """Send email alert when driver phone is unresponsive."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    cc_addr = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")

    if not rep_email:
        rep_email = cc_addr

    prefix = "ESCALATION: " if escalation else ""
    subject = f"{prefix}Driver Phone Unresponsive — {efj} {load_num}"

    bg_color = "#c62828" if escalation else "#e65100"
    body = f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;">
<div style="background:{bg_color};color:white;padding:12px 20px;border-radius:8px 8px 0 0;">
<h3 style="margin:0;">{'ESCALATION: ' if escalation else ''}Driver Phone Unresponsive</h3>
</div>
<div style="padding:16px 20px;background:#fafafa;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px;">
<table style="border-collapse:collapse;width:100%;">
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">EFJ #</td><td style="padding:6px 12px;">{efj}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Load #</td><td style="padding:6px 12px;">{load_num}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Account</td><td style="padding:6px 12px;">{account}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Carrier</td><td style="padding:6px 12px;">{carrier}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Driver Phone</td><td style="padding:6px 12px;">{driver_phone or 'N/A'}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#666;">Carrier Email</td><td style="padding:6px 12px;">{carrier_email or 'N/A'}</td></tr>
</table>
{'<p style="color:#c62828;font-weight:bold;margin-top:12px;">This load has been unresponsive for over 1.5 hours. Please contact carrier directly.</p>' if escalation else '<p style="color:#e65100;margin-top:12px;">Macropoint cannot reach the driver phone. The system will retry automatically.</p>'}
</div>
</body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = rep_email
        msg["Cc"] = cc_addr
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(smtp_user, smtp_pass)
            recipients = [rep_email]
            if cc_addr and cc_addr != rep_email:
                recipients.append(cc_addr)
            smtp.sendmail(smtp_user, recipients, msg.as_string())
        log.info("Sent %sunresponsive alert for %s to %s",
                 "ESCALATION " if escalation else "", efj, rep_email)
    except Exception as e:
        log.warning("Failed to send unresponsive alert for %s: %s", efj, e)


def check_unresponsive(efj, load_num, mp_load_status, account, carrier,
                       driver_phone, carrier_email, rep_email, tracking_cache):
    """Check and handle unresponsive driver status with escalation."""
    state = load_unresponsive_state()
    key = efj

    if mp_load_status and "unresponsive" in mp_load_status.lower():
        entry = state.get(key, {"count": 0, "last_alert": None})
        entry["count"] = entry.get("count", 0) + 1
        count = entry["count"]

        # First detection or every 4 polls (2 hours) — send alert
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()
        last_alert = entry.get("last_alert")

        should_alert = False
        if count == 1:
            should_alert = True
        elif last_alert:
            try:
                last_dt = datetime.fromisoformat(last_alert)
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if elapsed >= 7200:  # 2 hours
                    should_alert = True
            except (ValueError, TypeError):
                should_alert = True

        if should_alert:
            escalation = count >= 3  # 3+ consecutive = 1.5+ hours
            send_unresponsive_alert(efj, load_num, account, carrier,
                                   driver_phone, carrier_email, rep_email,
                                   escalation=escalation)
            entry["last_alert"] = now_str

        # After 6 consecutive (3 hours) — flag cantMakeIt
        if count >= 6:
            if efj in tracking_cache:
                tracking_cache[efj]["cant_make_it"] = "Driver Phone Unresponsive (3+ hrs)"
                log.warning("Flagged %s as cantMakeIt (6+ unresponsive polls)", efj)

        state[key] = entry
        save_unresponsive_state(state)
        log.info("Unresponsive count for %s: %d", efj, count)

    else:
        # Status is NOT unresponsive — reset counter
        if key in state:
            if state[key].get("count", 0) > 0:
                log.info("Unresponsive cleared for %s (was %d polls)", efj, state[key]["count"])
            del state[key]
            save_unresponsive_state(state)


def send_pro_alert(row: list, tab_name: str, account_lookup: dict):
    """Email rep daily when a row has no EFJ# pro number."""
    info      = account_lookup.get(tab_name, {})
    rep_email = info.get("email", "")
    rep_name  = info.get("rep", "")
    to_email  = rep_email if rep_email else EMAIL_FALLBACK
    cc_email  = EMAIL_CC if rep_email else None
    headers   = ["EFJ#","Move Type","Container/Load#","BOL/Booking#","SSL/Vessel",
                 "Carrier","Origin","Destination","ETA/ERD","LFD/Cutoff",
                 "Pickup Date","Delivery Date","Status","Driver/Truck","Notes"]
    detail_rows = ""
    for i, val in enumerate(row):
        if val and val.strip():
            label = headers[i] if i < len(headers) else f"Col {i+1}"
            detail_rows += f"<tr><td style=\"padding:3px 8px;color:#555;\">{label}</td><td style=\"padding:3px 8px;\">{val.strip()}</td></tr>"
    container = row[2].strip() if len(row) > 2 and row[2].strip() else "Unknown"
    vessel    = row[4].strip() if len(row) > 4 and row[4].strip() else "Unknown"
    origin    = row[6].strip() if len(row) > 6 and row[6].strip() else ""
    dest      = row[7].strip() if len(row) > 7 and row[7].strip() else ""
    extra = " | ".join(filter(None, [container, vessel, origin, dest]))
    subject = f"Please Pro Load ASAP: Load Needs EFJ Pro - {extra}"
    body = (
        f"<div style=\"font-family:Arial,sans-serif;max-width:600px;\">"
        f"<div style=\"background:#e65100;color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:16px;\">"
        f"<b>Please Pro Load ASAP</b></div>"
        f"<div style=\"border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:10px;\">"
        f"<table style=\"border-collapse:collapse;\">"
        f"<tr><td style=\"padding:4px 8px;color:#555;\">Account</td><td style=\"padding:4px 8px;\">{tab_name}</td></tr>"
        + (f"<tr><td style=\"padding:4px 8px;color:#555;\">Rep</td><td style=\"padding:4px 8px;\">{rep_name}</td></tr>" if rep_name else "")
        + f"</table>"
        f"<div style=\"margin-top:8px;border-top:1px solid #eee;padding-top:8px;\">"
        f"<b>Load Details</b></div>"
        f"<table style=\"border-collapse:collapse;\">{detail_rows}</table>"
        f"</div></div>"
    )
    _send_email(to_email, cc_email, subject, body)




# ── Archive (Postgres only) ────────────────────────────────────────────────────
def archive_ftl_row_pg(efj, load_num, dest, tab_name, pickup_val, delivery_val,
                       account_lookup, mp_load_id=None, stop_times=None):
    """Archive FTL row — Postgres only (no sheet writes)."""
    rep_info = account_lookup.get(tab_name, {})
    rep_email = rep_info.get("email", "")
    rep_name = rep_info.get("rep", "")
    try:
        pg_archive_shipment(efj)
        sheet_archive_row(efj, tab_name, rep=rep_name)
        print(f"    Archived {efj} (Delivered)")

        # Send archive email
        if rep_email:
            timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
            subject = f"CSL Archived | {load_num} | {efj} | Delivered"
            body = (
                f"FTL load {efj} ({load_num}) has been archived.\n\n"
                f"Account:  {tab_name}\n"
                f"Rep:      {rep_name}\n\n"
                f"Pickup:   {pickup_val or chr(8212)}\n"
                f"Delivery: {delivery_val or chr(8212)}\n"
                f"Status:   Delivered\n"
                f"Archived: {timestamp}\n"
            )
            cc = None if tab_name.lower() == "boviet" else EMAIL_CC
            _send_email(rep_email, cc, subject, body)

        # Send POD reminder
        _send_pod_reminder_ftl(efj, load_num, dest, tab_name, account_lookup, mp_load_id=mp_load_id)
        return True
    except Exception as e:
        print(f"    WARNING: Archive failed: {e}")
        return False



def run_once():
    """FTL poll cycle — reads from Postgres, checks webhook-updated tracking cache."""
    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    print(f"\n[{now_str}] FTL poll cycle (Postgres mode)...")

    # ── Read active FTL loads from Postgres ────────────────────────────────
    conn = None
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
    except Exception as exc:
        print(f"FATAL: Could not read from Postgres: {exc}")
        return
    finally:
        if conn is not None:
            conn.close()

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
        print(f"\n  Checking {tab_name}... ({len(loads)} FTL row(s))")

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
            # ── Block status regression ──
            if dropdown_val and _status_is_regression(existing_status, cached_status):
                log.info(f"FTL monitor: BLOCKED regression {efj} [{existing_status}] -> [{dropdown_val}]")
                dropdown_val = None
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
                # Dual-write: update Master Sheet (best-effort)
                sheet_update_ftl(
                    efj, tab_name,
                    pickup=final_pickup or None,
                    delivery=final_delivery or None,
                    status=dropdown_val or None,
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
                    _m = re.search(r"(\d{2})[-/](\d{2})", _date_src)
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
                cmi_status = "Can't Make It"
                if not already_sent(sent, key, cmi_status):
                    print(f"    CAN'T MAKE IT detected: {cant_make_it}")
                    send_ftl_email(efj, load_num, cmi_status, tab_name, ACCOUNT_REPS_PG,
                                   mp_load_id=mp_load_id, stop_times=stop_times)
                    mark_sent(sent, key, cmi_status)

            # ── Archive if Delivered ──────────────────────────────────────
            if "delivered" in cached_status.lower():
                # Guard: don't archive if truck is still > 15 miles from destination.
                # Macropoint sometimes fires D1 events prematurely (wrong driver,
                # auto-close, or re-tracked shipment). Verify proximity first.
                dist_raw = cached.get("distance_to_stop")
                dist_miles = None
                try:
                    dist_miles = float(dist_raw) if dist_raw is not None else None
                except (TypeError, ValueError):
                    pass
                if dist_miles is not None and dist_miles > 15:
                    print(f"    ⚠️  ARCHIVE BLOCKED for {efj}: D1 received but "
                          f"truck is {dist_miles:.1f} mi from destination — "
                          f"likely false positive (MP re-track?)")
                else:
                    archive_ftl_row_pg(efj, load_num, dest, tab_name,
                                        final_pickup, final_delivery, ACCOUNT_REPS_PG,
                                        mp_load_id=mp_load_id, stop_times=stop_times)

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


# ── scrape_macropoint re-export ───────────────────────────────────────────────
# boviet_monitor and tolead_monitor import scrape_macropoint from this module.
# The implementation lives in daily_summary.py. Re-export it here.
try:
    from daily_summary import scrape_macropoint  # noqa: F401
except ImportError:
    def scrape_macropoint(browser, url, mp_cookies=None):
        raise NotImplementedError("scrape_macropoint not available")
