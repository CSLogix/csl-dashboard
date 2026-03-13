#!/usr/bin/env python3
"""
export_daily_summary.py — Daily dray export digest per account rep.

Reads Dray Export shipments from Postgres, groups by rep, sends one
email per rep. Cutoff urgency flagged red/orange when within 3 days.

Cron: 10 7 * * 1-5
"""

import os, sys, smtplib, urllib.parse
from datetime import datetime, date
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, '/root/csl-bot')
from csl_pg_writer import _get_conn
import psycopg2.extras

from dotenv import load_dotenv
load_dotenv(dotenv_path='/root/csl-bot/.env')

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASSWORD"]
EMAIL_CC  = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")

SKIP_STATUSES = {
    "delivered", "completed", "gate in", "loaded on vessel",
    "vessel departed", "billed/closed", "cancelled", "canceled",
}

ACCOUNT_REPS = {
    "Allround":  {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "Cadi":      {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "DHL":       {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "DSV":       {"rep": "Eli",    "email": "Eli.Luchuk@evansdelivery.com"},
    "EShipping": {"rep": "Eli",    "email": "Eli.Luchuk@evansdelivery.com"},
    "IWS":       {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "Kripke":    {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "MAO":       {"rep": "Eli",    "email": "Eli.Luchuk@evansdelivery.com"},
    "MGF":       {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "Rose":      {"rep": "Eli",    "email": "Eli.Luchuk@evansdelivery.com"},
    "USHA":      {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "MD Metal":  {"rep": "Radka",  "email": "Radka.White@evansdelivery.com"},
    "Kishco":    {"rep": "Eli",    "email": "Eli.Luchuk@evansdelivery.com"},
    "CNL":       {"rep": "Janice", "email": "Janice.Cortes@evansdelivery.com"},
    "Mamata":    {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
}

# ── Styles ────────────────────────────────────────────────────────────────────
_TH     = 'style="padding:6px 10px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.3);color:white;font-size:12px;white-space:nowrap;"'
_TD     = 'style="padding:6px 10px;border-bottom:1px solid #eee;font-size:12px;"'
_TD_RED = 'style="padding:6px 10px;border-bottom:1px solid #eee;font-size:12px;color:#c62828;font-weight:bold;"'
_TD_ORG = 'style="padding:6px 10px;border-bottom:1px solid #eee;font-size:12px;color:#f57c00;font-weight:bold;"'

# Export accent color — orange to differentiate from Import (blue)
_EXPORT_COLOR = "#e65100"

STATUS_COLORS = {
    "booking confirmed":  "#1b5e20",
    "in transit":         "#1565c0",
    "at terminal":        "#6a1b9a",
    "gate in":            "#2e7d32",
    "loaded on vessel":   "#455a64",
    "vessel departed":    "#455a64",
    "empty picked up":    "#f57f17",
    "pending":            "#555",
}


def _status_style(status):
    color = STATUS_COLORS.get((status or "").lower(), "#333")
    return f'style="padding:6px 10px;border-bottom:1px solid #eee;font-size:12px;color:{color};font-weight:bold;"'


def _deadline_style(val):
    """Red if <=1 day, orange if <=3 days, default otherwise."""
    if not val:
        return _TD
    today = date.today()
    for fmt in ("%m-%d", "%m/%d"):
        try:
            parsed = datetime.strptime(f"{val}/{today.year}", fmt + "/%Y").date()
            days = (parsed - today).days
            if days <= 1:
                return _TD_RED
            elif days <= 3:
                return _TD_ORG
            return _TD
        except ValueError:
            continue
    return _TD


# ── PG reader ─────────────────────────────────────────────────────────────────
def load_exports():
    """
    Returns dict keyed by rep_email:
    { "Eli.Luchuk@...": {"rep": "Eli", "accounts": {"DSV": [row, ...], ...}} }
    """
    conn = _get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT efj, account, container, bol, vessel, carrier,
               origin, destination, eta, lfd, pickup_date, delivery_date,
               status, notes
        FROM shipments
        WHERE move_type = 'Dray Export'
          AND archived = FALSE
          AND COALESCE(status, '') NOT IN (
              'Delivered','Completed','Gate In','Loaded on Vessel',
              'Vessel Departed','Billed/Closed','Cancelled','Canceled'
          )
        ORDER BY account, efj
    """)
    rows = cur.fetchall()
    cur.close()

    by_rep = {}
    for r in rows:
        account = (r["account"] or "").strip()
        rep_info = ACCOUNT_REPS.get(account)
        if not rep_info:
            print(f"  [SKIP] {account} — no rep mapping")
            continue

        rep_email = rep_info["email"]
        rep_name  = rep_info["rep"]
        if rep_email not in by_rep:
            by_rep[rep_email] = {"rep": rep_name, "accounts": {}}
        if account not in by_rep[rep_email]["accounts"]:
            by_rep[rep_email]["accounts"][account] = []

        by_rep[rep_email]["accounts"][account].append({
            "efj":      r["efj"]         or "",
            "cont":     r["container"]   or "",
            "bol":      r["bol"]         or "",   # booking #
            "vessel":   r["vessel"]      or "",
            "carrier":  r["carrier"]     or "",
            "origin":   r["origin"]      or "",
            "dest":     r["destination"] or "",
            "erd":      r["eta"]         or "",   # eta = ERD for exports
            "cutoff":   r["lfd"]         or "",   # lfd = Cutoff for exports
            "pickup":   r["pickup_date"] or "",
            "delivery": r["delivery_date"] or "",
            "status":   r["status"]      or "",
            "notes":    r["notes"]       or "",
        })

    for rep_email, data in by_rep.items():
        for account, loads in data["accounts"].items():
            print(f"  [{account}] {len(loads)} active export(s) → {data['rep']}")

    return by_rep


# ── HTML builders ─────────────────────────────────────────────────────────────
# Column order: Customer | EFJ # | Container / Booking | Lane | Status | ERD | Port Cutoff
HEADERS = ["Customer", "EFJ #", "Container / Booking", "Lane", "Status", "ERD", "Port Cutoff"]


def _build_account_section(account_name, loads):
    hdr_cells = "".join(f'<th {_TH}>{h}</th>' for h in HEADERS)
    rows_html  = ""
    for i, s in enumerate(loads):
        bg = ' style="background:#fff8f5;"' if i % 2 == 1 else ""

        # Container/Booking cell: container on top, booking sub-line, vessel sub-line
        cont_booking = s["cont"] or s["bol"] or "&mdash;"
        if s["cont"] and s["bol"]:
            cont_booking = f'{s["cont"]}<br><span style="font-size:11px;color:#888;">{s["bol"]}</span>'
        if s["vessel"]:
            cont_booking += f'<br><span style="font-size:11px;color:#1565c0;">&#128674; {s["vessel"]}</span>'

        # Lane
        origin = s.get("origin", "")
        dest   = s.get("dest", "")
        if origin and dest:
            lane = f'{origin} &#8594; {dest}'
        else:
            lane = origin or dest or "&mdash;"

        # Cutoff cell: urgency sub-line + mailto flag link
        cutoff_html = s["cutoff"] or "&mdash;"
        cutoff_st   = _deadline_style(s["cutoff"])

        # Pre-drafted mailto for cutoff corrections — always present, subtle until urgent
        flag_subject = urllib.parse.quote(f'Cutoff Correction — {s["efj"]}')
        flag_body    = urllib.parse.quote(
            f'EFJ: {s["efj"]}\n'
            f'Container: {s["cont"] or s["bol"] or "—"}\n'
            f'Vessel: {s["vessel"] or "—"}\n'
            f'Current Cutoff in System: {s["cutoff"] or "—"}\n'
            f'Correct Cutoff: \n'
            f'Notes: '
        )
        flag_link = (
            f'<br><a href="mailto:{EMAIL_CC}?subject={flag_subject}&body={flag_body}" '
            f'style="font-size:10px;color:#888;text-decoration:none;">&#9998; Flag correction</a>'
        )

        if s["cutoff"] and cutoff_st != _TD:
            cutoff_color = "#c62828" if cutoff_st == _TD_RED else "#f57c00"
            cutoff_html  = (
                f'<b style="color:{cutoff_color};">{s["cutoff"]}</b>'
                f'<br><span style="font-size:10px;color:{cutoff_color};">⚠ CUTOFF</span>'
                f'{flag_link}'
            )
        elif s["cutoff"]:
            cutoff_html = f'{s["cutoff"]}{flag_link}'

        rows_html += (
            f'<tr{bg}>'
            f'<td {_TD}><b style="color:{_EXPORT_COLOR};">{account_name}</b></td>'
            f'<td {_TD}><b>{s["efj"]}</b></td>'
            f'<td {_TD}>{cont_booking}</td>'
            f'<td {_TD}>{lane}</td>'
            f'<td {_status_style(s["status"])}>{s["status"] or "&mdash;"}</td>'
            f'<td {_TD}>{s["erd"] or "&mdash;"}</td>'
            f'<td {cutoff_st}>{cutoff_html}</td>'
            f'</tr>'
        )

    return (
        f'<table style="border-collapse:collapse;width:100%;border:1px solid #ddd;margin-top:20px;">'
        f'<tr style="background:{_EXPORT_COLOR};">{hdr_cells}</tr>'
        f'{rows_html}'
        f'</table>'
    )


def build_export_body(rep_name, accounts_data, now_str):
    total = sum(len(v) for v in accounts_data.values())

    # Ribbon: status breakdown
    buckets = {}
    urgent  = 0
    for loads in accounts_data.values():
        for s in loads:
            st = (s["status"] or "Unknown").title()
            buckets[st] = buckets.get(st, 0) + 1
            if _deadline_style(s["cutoff"]) != _TD:
                urgent += 1

    ribbon_parts = [f'<b style="color:{_EXPORT_COLOR};">{total} Active</b>']
    if urgent:
        ribbon_parts.append(f'<span style="color:#c62828;font-weight:bold;">⚠ {urgent} Cutoff Approaching</span>')
    for st, cnt in sorted(buckets.items(), key=lambda x: -x[1])[:5]:
        ribbon_parts.append(f'<span style="color:#555;">{cnt} {st}</span>')
    ribbon_html = " &nbsp;|&nbsp; ".join(ribbon_parts)

    sections = "".join(
        _build_account_section(name, accounts_data[name])
        for name in sorted(accounts_data.keys())
    )

    return (
        f'<div style="font-family:Arial,sans-serif;max-width:960px;">'
        f'<h2 style="margin:0 0 4px 0;color:#333;">'
        f'CSL Daily &mdash; Dray Export &mdash; {rep_name}</h2>'
        f'<p style="color:#888;font-size:12px;margin:0 0 8px 0;">{now_str}</p>'
        f'<div style="background:#fff3e0;border-left:4px solid {_EXPORT_COLOR};padding:8px 14px;'
        f'border-radius:0 6px 6px 0;font-size:13px;margin-bottom:12px;">{ribbon_html}</div>'
        f'{sections}'
        f'<p style="color:#aaa;font-size:11px;margin-top:20px;">'
        f'CSLogix Dispatch &middot; {now_str}</p>'
        f'</div>'
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
    now_str   = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    today_fmt = datetime.now(ZoneInfo("America/New_York")).strftime("%m/%d")

    print(f"\n=== Export Daily Summary === {now_str} ===")
    print("\nQuerying Postgres for active Dray Export loads...")

    by_rep = load_exports()

    if not by_rep:
        print("No active export loads found.")
        return

    print(f"\nSending to {len(by_rep)} rep(s)...")
    for rep_email, data in by_rep.items():
        rep_name  = data["rep"]
        accounts  = data["accounts"]
        total     = sum(len(v) for v in accounts.values())
        acct_list = ", ".join(sorted(accounts.keys()))
        subject   = f"CSL Daily \u2014 Dray Export / {rep_name} \u2014 {today_fmt} \u2014 {total} Active"
        body      = build_export_body(rep_name, accounts, now_str)
        print(f"\n  [{rep_name}] {total} loads | {acct_list}")
        send_email(rep_email, subject, body)

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
