#!/usr/bin/env python3
"""
dray_daily_summary.py — Daily dray import digest per account rep.

Scans all account tabs in the Master Tracker sheet, groups active loads
by rep, and sends one email per rep with all their accounts.

Cron: 0 7 * * 1-5  (runs alongside daily_summary.py)
"""

import os, sys, smtplib
from datetime import datetime, date
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

sys.path.insert(0, '/root/csl-bot')
load_dotenv(dotenv_path='/root/csl-bot/.env')

SHEET_ID   = os.environ["SHEET_ID"]
CREDS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "/root/csl-bot/csl-credentials.json")
SMTP_HOST  = "smtp.gmail.com"
SMTP_PORT  = 587
SMTP_USER  = os.environ["SMTP_USER"]
SMTP_PASS  = os.environ["SMTP_PASSWORD"]
EMAIL_CC   = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")

SKIP_TABS = {
    "Sheet 4", "DTCELNJW", "Account Rep", "SSL Links",
    "Completed Eli", "Completed Radka", "Completed John F",
    "Boviet", "Summary", "Settings", "Lists",
}

SKIP_STATUSES = {
    "delivered", "completed", "empty returned",
    "returned to port", "billed/closed", "cancelled", "canceled",
}

# Col indices (0-based) — Master Tracker A-P
C_EFJ      = 0
C_MOVETYPE = 1
C_CONT     = 2
C_BOL      = 3
C_SSL      = 4
C_CARRIER  = 5
C_ORIGIN   = 6
C_DEST     = 7
C_ETA      = 8
C_LFD      = 9
C_PICKUP   = 10
C_DELIVERY = 11
C_STATUS   = 12
C_DRIVER   = 13
C_NOTES    = 14

ACCOUNT_REPS = {
    "Allround":  {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "Cadi":      {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "DHL":       {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "DSV":       {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "EShipping": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "IWS":       {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "Kripke":    {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "MAO":       {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "MGF":       {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "Rose":      {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "USHA":      {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "MD Metal":  {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "Kishco":    {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "CNL":       {"rep": "Janice", "email": "Janice.Cortes@evansdelivery.com"},
    "Mamata":    {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
}

# ── Styles ────────────────────────────────────────────────────────────────────
_TH = 'style="padding:8px 10px;text-align:left;border-bottom:2px solid #ffffff;color:#ffffff;font-size:12px;font-family:Arial,sans-serif;white-space:nowrap;"'
_TD = 'style="padding:8px 10px;border-bottom:1px solid #eeeeee;font-size:12px;font-family:Arial,sans-serif;"'
_TD_RED = 'style="padding:8px 10px;border-bottom:1px solid #eeeeee;font-size:12px;font-family:Arial,sans-serif;color:#c62828;font-weight:bold;"'
_TD_ORG = 'style="padding:8px 10px;border-bottom:1px solid #eeeeee;font-size:12px;font-family:Arial,sans-serif;color:#f57c00;font-weight:bold;"'

STATUS_COLORS = {
    "released":       "#1b5e20",
    "discharged":     "#1565c0",
    "vessel arrived": "#6a1b9a",
    "on vessel":      "#455a64",
    "vessel":         "#455a64",
    "rail":           "#4e342e",
    "picked up":      "#f57f17",
    "in transit":     "#e65100",
    "at terminal":    "#0277bd",
}


def _status_style(status):
    color = STATUS_COLORS.get((status or "").lower(), "#333")
    return f'style="padding:8px 10px;border-bottom:1px solid #eeeeee;font-size:12px;font-family:Arial,sans-serif;color:{color};font-weight:bold;"'


def _g(row, col, default=""):
    try:
        v = row[col].strip()
        return v if v else default
    except IndexError:
        return default


def _lfd_style(lfd):
    """Return red/orange TD style if LFD is within 3 days, else default."""
    if not lfd:
        return _TD
    today = date.today()
    for fmt in ("%m-%d", "%m/%d"):
        try:
            parsed = datetime.strptime(f"{lfd}/{today.year}", fmt + "/%Y").date()
            days = (parsed - today).days
            if days <= 1:
                return _TD_RED
            elif days <= 3:
                return _TD_ORG
            return _TD
        except ValueError:
            continue
    return _TD


# ── PG dedup: fetch active export EFJs so we can skip them in sheet scan ──────
def _get_export_efjs():
    """Return set of EFJs that are active Dray Export loads in Postgres."""
    try:
        from csl_pg_writer import _get_conn
        conn = _get_conn()
        if not conn:
            return set()
        cur = conn.cursor()
        cur.execute("""
            SELECT efj FROM shipments
            WHERE move_type = 'Dray Export' AND archived = FALSE
        """)
        efjs = {r[0] for r in cur.fetchall()}
        cur.close()
        print(f"  [Dedup] {len(efjs)} active export EFJ(s) will be excluded from import scan")
        return efjs
    except Exception as e:
        print(f"  [Dedup] PG query failed, skipping dedup: {e}")
        return set()


# ── Sheet reader ──────────────────────────────────────────────────────────────
def scan_master(gc):
    sh = gc.open_by_key(SHEET_ID)
    by_rep = {}
    export_efjs = _get_export_efjs()  # exclude export loads from import digest

    for ws in sh.worksheets():
        tab = ws.title.strip()
        if tab in SKIP_TABS:
            continue
        rep_info = ACCOUNT_REPS.get(tab)
        if not rep_info:
            print(f"  [SKIP] {tab} — no rep mapping")
            continue

        rows = ws.get_all_values()
        if len(rows) < 2:
            continue

        # Find first data row (skip header rows)
        data_start = 1
        for i, r in enumerate(rows[:5]):
            if r and "efj" in r[0].lower():
                data_start = i + 1
                break

        active = []
        for row in rows[data_start:]:
            if not row or not row[0].strip():
                continue
            efj = _g(row, C_EFJ)
            if not efj.upper().startswith("EFJ") and not efj.replace("-", "").isdigit():
                continue
            if efj in export_efjs:
                continue  # handled by export_daily_summary.py — skip here
            status = _g(row, C_STATUS)
            if status.lower() in SKIP_STATUSES:
                continue
            active.append({
                "efj":      efj,
                "move":     _g(row, C_MOVETYPE),
                "cont":     _g(row, C_CONT),
                "ssl":      _g(row, C_SSL),
                "origin":   _g(row, C_ORIGIN),
                "dest":     _g(row, C_DEST),
                "eta":      _g(row, C_ETA),
                "lfd":      _g(row, C_LFD),
                "pickup":   _g(row, C_PICKUP),
                "delivery": _g(row, C_DELIVERY),
                "status":   status,
                "notes":    _g(row, C_NOTES),
            })

        if not active:
            print(f"  [{tab}] 0 active — skip")
            continue

        rep_email = rep_info["email"]
        rep_name  = rep_info["rep"]
        if rep_email not in by_rep:
            by_rep[rep_email] = {"rep": rep_name, "accounts": {}}
        by_rep[rep_email]["accounts"][tab] = active
        print(f"  [{tab}] {len(active)} active → {rep_name}")

    return by_rep


# ── HTML builders ─────────────────────────────────────────────────────────────
# Column order: Customer | EFJ # | Container/Load | Lane | Status | Pickup | Delivery
# LFD is surfaced as a sub-line under Pickup when present and urgent
HEADERS = ["Customer", "EFJ #", "Container/Load", "Lane", "Status", "Pickup", "Delivery"]


def _build_account_section(account_name, loads):
    color = "#1565c0"
    hdr_cells = "".join(f'<th {_TH}>{h}</th>' for h in HEADERS)
    rows_html = ""
    for i, s in enumerate(loads):
        bg = ' style="background:#f5f8ff;"' if i % 2 == 1 else ""
        lfd_st = _lfd_style(s["lfd"])

        # Lane: Origin → Dest, fallback to either
        origin = s.get("origin", "")
        dest   = s.get("dest", "")
        if origin and dest:
            lane = f'{origin} &#8594; {dest}'
        else:
            lane = origin or dest or "&mdash;"

        # Pickup cell: date + LFD sub-line if within 3 days
        pickup_html = s["pickup"] or "&mdash;"
        if s["lfd"] and _lfd_style(s["lfd"]) != _TD:
            lfd_color = "#c62828" if _lfd_style(s["lfd"]) == _TD_RED else "#f57c00"
            pickup_html += (
                f'<br><span style="font-size:11px;color:{lfd_color};font-weight:bold;">'
                f'LFD: {s["lfd"]}</span>'
            )

        rows_html += (
            f'<tr{bg}>'
            f'<td {_TD}><b style="color:#1565c0;">{account_name}</b></td>'
            f'<td {_TD}><b>{s["efj"]}</b></td>'
            f'<td {_TD}>{s["cont"] or "&mdash;"}</td>'
            f'<td {_TD}>{lane}</td>'
            f'<td {_status_style(s["status"])}>{s["status"] or "&mdash;"}</td>'
            f'<td {_TD}>{pickup_html}</td>'
            f'<td {_TD}>{s["delivery"] or "&mdash;"}</td>'
            f'</tr>'
        )
    return (
        f'<table cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;width:100%;border:1px solid #dddddd;margin-top:20px;table-layout:fixed;">'
        f'<tr style="background:{color};">{hdr_cells}</tr>'
        f'{rows_html}'
        f'</table>'
    )


def build_dray_body(rep_name, accounts_data, now_str):
    total = sum(len(v) for v in accounts_data.values())

    # Status breakdown for ribbon
    buckets = {}
    for loads in accounts_data.values():
        for s in loads:
            st = (s["status"] or "Unknown").title()
            buckets[st] = buckets.get(st, 0) + 1

    ribbon_parts = [f'<b style="color:#1565c0;">{total} Active</b>']
    for st, cnt in sorted(buckets.items(), key=lambda x: -x[1])[:6]:
        ribbon_parts.append(f'<span style="color:#555;">{cnt} {st}</span>')
    ribbon_html = " &nbsp;|&nbsp; ".join(ribbon_parts)

    # All accounts in one continuous table — Customer column provides grouping context
    sections = "".join(
        _build_account_section(name, accounts_data[name])
        for name in sorted(accounts_data.keys())
    )

    return (
        f'<table cellpadding="0" cellspacing="0" width="960" style="font-family:Arial,sans-serif;max-width:960px;"><tr><td>'
        f'<h2 style="margin:0 0 4px 0;color:#333;">'
        f'CSL Daily &mdash; Dray Import &mdash; {rep_name}</h2>'
        f'<p style="color:#888;font-size:12px;margin:0 0 8px 0;">{now_str}</p>'
        f'<div style="background:#f5f5f5;border-left:4px solid #1565c0;padding:8px 14px;'
        f'border-radius:0 6px 6px 0;font-size:13px;margin-bottom:12px;">{ribbon_html}</div>'
        f'{sections}'
        f'<p style="color:#aaa;font-size:11px;margin-top:20px;font-family:Arial,sans-serif;">'
        f'CSLogix Dispatch &middot; {now_str}</p>'
        f'</td></tr></table>'
    )


# ── Mailer ────────────────────────────────────────────────────────────────────
def send_email(to_email, subject, body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    msg["Cc"]      = EMAIL_CC
    msg.attach(MIMEText(body, "html"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.sendmail(SMTP_USER, [to_email, EMAIL_CC], msg.as_string())
        print(f"    Sent → {to_email} (cc: {EMAIL_CC})")
    except Exception as e:
        print(f"    ERROR sending to {to_email}: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now_str    = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    today_fmt  = datetime.now(ZoneInfo("America/New_York")).strftime("%m/%d")

    print(f"\n=== Dray Daily Summary === {now_str} ===")

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc    = gspread.authorize(creds)

    print("\nScanning Master Tracker...")
    by_rep = scan_master(gc)

    if not by_rep:
        print("No active loads found.")
        return

    print(f"\nSending to {len(by_rep)} rep(s)...")
    for rep_email, data in by_rep.items():
        rep_name  = data["rep"]
        accounts  = data["accounts"]
        total     = sum(len(v) for v in accounts.values())
        acct_list = ", ".join(sorted(accounts.keys()))
        subject   = f"CSL Daily \u2014 Dray Import / {rep_name} \u2014 {today_fmt} \u2014 {total} Active"
        body      = build_dray_body(rep_name, accounts, now_str)
        print(f"\n  [{rep_name}] {total} loads | {acct_list}")
        send_email(rep_email, subject, body)

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
