#!/usr/bin/env python3
"""
weekly_profit_report.py — Monday 7 AM digest per account rep.

Covers prior Mon–Sun:
  • Closed loads + margin breakdown
  • Active pipeline status summary
  • Quote activity (customer_rate email threads): Received / Quoted / Won / Lost / Pass / Win-rate
  • Outbound quotes from rate_quotes table

Cron: 0 7 * * 1  (Mondays 7 AM ET)
"""

import os, sys, smtplib
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, "/root/csl-bot")
from dotenv import load_dotenv
load_dotenv(dotenv_path="/root/csl-bot/.env")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASSWORD"]
EMAIL_CC  = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")

REPS = {
    "Radka":  "Radka.White@evansdelivery.com",
    "John F": "John.Feltz@evansdelivery.com",
    "Janice": "Janice.Cortes@evansdelivery.com",
}
SKIP_REPS = {"Boviet", "Tolead", "Unassigned", None, ""}

# ── Styles ─────────────────────────────────────────────────────────────────────
_TH = "padding:6px 10px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.25);color:white;font-size:11px;white-space:nowrap;"
_TD = "padding:6px 10px;border-bottom:1px solid #eee;font-size:11px;"
_TD_RED = "padding:6px 10px;border-bottom:1px solid #eee;font-size:11px;color:#c62828;font-weight:bold;"
_TD_GRN = "padding:6px 10px;border-bottom:1px solid #eee;font-size:11px;color:#2e7d32;font-weight:bold;"
_TD_ORG = "padding:6px 10px;border-bottom:1px solid #eee;font-size:11px;color:#f57c00;font-weight:bold;"


def week_bounds():
    """Return (start, end) for the prior Mon-Sun as timezone-aware ET datetimes."""
    et = ZoneInfo("America/New_York")
    today = datetime.now(et).date()
    this_mon = today - timedelta(days=today.weekday())
    last_mon = this_mon - timedelta(weeks=1)
    last_sun = last_mon + timedelta(days=6)
    start = datetime(last_mon.year, last_mon.month, last_mon.day, 0, 0, 0, tzinfo=et)
    end   = datetime(last_sun.year, last_sun.month, last_sun.day, 23, 59, 59, tzinfo=et)
    label = last_mon.strftime("%m/%d") + "\u2013" + last_sun.strftime("%m/%d/%Y")
    return start, end, label


def _get_conn():
    try:
        from csl_pg_writer import _get_conn as pgconn
        return pgconn()
    except Exception as e:
        print(f"  [DB] connection failed: {e}")
        return None


def _fmt_rate(val):
    if val is None:
        return "\u2014"
    try:
        return f"${float(val):,.0f}"
    except Exception:
        return "\u2014"


def _margin_pct(cx, rc):
    try:
        cx_f = float(cx) if cx is not None else None
        rc_f = float(rc) if rc is not None else None
        if cx_f and rc_f and cx_f > 0:
            return round((cx_f - rc_f) / cx_f * 100, 1)
    except Exception:
        pass
    return None


def _margin_td(pct):
    if pct is None:
        return f'<td style="{_TD}">\u2014</td>'
    if pct < 0:
        return f'<td style="{_TD_RED}">{pct:.1f}%</td>'
    if pct < 10:
        return f'<td style="{_TD_ORG}">{pct:.1f}%</td>'
    return f'<td style="{_TD_GRN}">{pct:.1f}%</td>'


# ── Data queries ───────────────────────────────────────────────────────────────

def query_closed_loads(conn, start, end):
    """Archived loads closed during the week, grouped by rep."""
    cur = conn.cursor()
    cur.execute("""
        SELECT rep, account, efj, origin, destination,
               customer_rate, carrier_pay, archived_at
        FROM shipments
        WHERE archived = TRUE
          AND archived_at >= %s AND archived_at <= %s
        ORDER BY rep, archived_at
    """, (start, end))
    rows = cur.fetchall()
    cur.close()
    by_rep = {}
    for row in rows:
        rep = row[0] or "Unassigned"
        if rep in SKIP_REPS:
            continue
        if rep not in by_rep:
            by_rep[rep] = []
        by_rep[rep].append({
            "account":  row[1],
            "efj":      row[2],
            "origin":   row[3],
            "dest":     row[4],
            "cx_rate":  row[5],
            "rc_pay":   row[6],
            "closed_at": row[7],
        })
    return by_rep


def query_pipeline(conn, rep):
    """Active (non-archived) loads for a rep -- status counts."""
    cur = conn.cursor()
    cur.execute("""
        SELECT status, COUNT(*) as cnt
        FROM shipments
        WHERE archived = FALSE AND rep = %s
        GROUP BY status
        ORDER BY cnt DESC
    """, (rep,))
    rows = cur.fetchall()
    cur.close()
    return {r[0] or "Unknown": r[1] for r in rows}


def query_quote_activity(conn, rep, start, end):
    """customer_rate threads for this rep's accounts during the week."""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE TRUE)                         AS received,
            COUNT(*) FILTER (WHERE quote_status = 'quoted')      AS quoted,
            COUNT(*) FILTER (WHERE quote_status = 'won')         AS won,
            COUNT(*) FILTER (WHERE quote_status = 'lost')        AS lost,
            COUNT(*) FILTER (WHERE quote_status = 'pass')        AS pass_cnt
        FROM email_threads et
        WHERE et.email_type = 'customer_rate'
          AND et.sent_at >= %s AND et.sent_at <= %s
          AND EXISTS (
            SELECT 1 FROM shipments s
            WHERE s.efj = et.efj AND s.rep = %s
          )
    """, (start, end, rep))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    received, quoted, won, lost, pass_cnt = row
    return {
        "received": received or 0,
        "quoted":   quoted or 0,
        "won":      won or 0,
        "lost":     lost or 0,
        "pass":     pass_cnt or 0,
    }


def query_outbound_quotes(conn, rep, start, end):
    """Outbound rate quotes sent for the rep's loads."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT rq.efj, rq.carrier_name, rq.rate_amount, rq.quote_date, rq.lane
            FROM rate_quotes rq
            JOIN shipments s ON s.efj = rq.efj
            WHERE rq.quote_direction = 'outbound'
              AND rq.quote_date >= %s AND rq.quote_date <= %s
              AND s.rep = %s
            ORDER BY rq.quote_date DESC
        """, (start, end, rep))
        rows = cur.fetchall()
        cur.close()
        return [{"efj": r[0], "carrier": r[1], "rate": r[2], "sent_at": r[3], "notes": r[4]} for r in rows]
    except Exception as e:
        print(f"  [Quotes] outbound query failed for {rep}: {e}")
        return []


# ── HTML builders ──────────────────────────────────────────────────────────────

def _closed_table(loads):
    if not loads:
        return '<p style="color:#888;font-size:11px;margin:8px 0;">No closed loads this week.</p>'
    rows = ""
    total_cx = total_rc = total_margin = 0.0
    cx_cnt = rc_cnt = 0
    for i, s in enumerate(loads):
        bg = " background:#f5f8ff;" if i % 2 == 1 else ""
        if s.get("origin") and s.get("dest"):
            lane = s["origin"] + " \u2192 " + s["dest"]
        else:
            lane = s.get("origin") or s.get("dest") or "\u2014"
        pct  = _margin_pct(s["cx_rate"], s["rc_pay"])
        cx   = float(s["cx_rate"]) if s["cx_rate"] is not None else None
        rc   = float(s["rc_pay"])  if s["rc_pay"]  is not None else None
        if cx: total_cx += cx; cx_cnt += 1
        if rc: total_rc += rc; rc_cnt += 1
        if cx and rc: total_margin += (cx - rc)
        rows += (
            f'<tr style="{bg}">'
            f'<td style="{_TD}">{s["account"]}</td>'
            f'<td style="{_TD}"><b>{s["efj"]}</b></td>'
            f'<td style="{_TD}">{lane}</td>'
            f'<td style="{_TD}">{_fmt_rate(s["cx_rate"])}</td>'
            f'<td style="{_TD}">{_fmt_rate(s["rc_pay"])}</td>'
            f'{_margin_td(pct)}'
            f'</tr>'
        )
    total_pct = round(total_margin / total_cx * 100, 1) if total_cx > 0 else None
    rows += (
        f'<tr style="background:#f0f4ff;font-weight:bold;">'
        f'<td style="{_TD}">TOTAL</td>'
        f'<td style="{_TD}">{len(loads)} loads</td>'
        f'<td style="{_TD}"></td>'
        f'<td style="{_TD}">{_fmt_rate(total_cx) if cx_cnt else chr(8212)}</td>'
        f'<td style="{_TD}">{_fmt_rate(total_rc) if rc_cnt else chr(8212)}</td>'
        f'{_margin_td(total_pct)}'
        f'</tr>'
    )
    return (
        f'<table style="border-collapse:collapse;width:100%;border:1px solid #ddd;margin-top:10px;">'
        f'<tr style="background:#1565c0;">'
        f'<th style="{_TH}">Account</th>'
        f'<th style="{_TH}">EFJ</th>'
        f'<th style="{_TH}">Lane</th>'
        f'<th style="{_TH}">CX Rate</th>'
        f'<th style="{_TH}">RC Pay</th>'
        f'<th style="{_TH}">Margin</th>'
        f'</tr>'
        f'{rows}'
        f'</table>'
    )


def _pipeline_pills(status_counts):
    if not status_counts:
        return '<span style="color:#888;font-size:11px;">No active loads</span>'
    STATUS_COLORS = {
        "released": "#1b5e20", "discharged": "#1565c0", "picked up": "#f57f17",
        "in transit": "#e65100", "at terminal": "#0277bd", "vessel arrived": "#6a1b9a",
        "on vessel": "#455a64", "rail": "#4e342e",
    }
    pills = []
    for st, cnt in sorted(status_counts.items(), key=lambda x: -x[1]):
        color = STATUS_COLORS.get(st.lower(), "#333")
        pills.append(
            f'<span style="display:inline-block;margin:2px;padding:3px 10px;border-radius:12px;'
            f'background:{color}18;border:1px solid {color}44;color:{color};'
            f'font-size:10px;font-weight:700;">'
            f'{cnt} {st.title()}</span>'
        )
    return "".join(pills)


def _quote_pills(qa):
    if qa is None:
        return '<span style="color:#888;font-size:11px;">No quote data</span>'
    received = qa["received"]
    quoted   = qa["quoted"]
    won      = qa["won"]
    lost     = qa["lost"]
    pass_cnt = qa["pass"]
    win_rate  = round(won / (won + lost) * 100) if (won + lost) > 0 else None
    resp_rate = round(quoted / received * 100) if received > 0 else None
    parts = [
        f'<span style="font-size:11px;color:#555;">{received} Received</span>',
        f'<span style="padding:2px 8px;border-radius:10px;background:rgba(59,130,246,0.12);color:#1565c0;font-size:10px;font-weight:700;">{quoted} Quoted</span>',
        f'<span style="padding:2px 8px;border-radius:10px;background:rgba(34,197,94,0.12);color:#2e7d32;font-size:10px;font-weight:700;">{won} Won</span>',
        f'<span style="padding:2px 8px;border-radius:10px;background:rgba(239,68,68,0.10);color:#c62828;font-size:10px;font-weight:700;">{lost} Lost</span>',
        f'<span style="padding:2px 8px;border-radius:10px;background:rgba(107,114,128,0.10);color:#6b7280;font-size:10px;font-weight:700;">{pass_cnt} Pass</span>',
    ]
    if win_rate is not None:
        parts.append(f'<span style="font-size:11px;color:#555;">Win Rate: <b style="color:#2e7d32;">{win_rate}%</b></span>')
    if resp_rate is not None:
        parts.append(f'<span style="font-size:11px;color:#555;">Response Rate: <b>{resp_rate}%</b></span>')
    return " &nbsp;|&nbsp; ".join(parts)


def _outbound_table(quotes):
    if not quotes:
        return '<p style="color:#888;font-size:11px;margin:8px 0;">No outbound quotes this week.</p>'
    rows = ""
    for i, q in enumerate(quotes):
        bg = " background:#f5f8ff;" if i % 2 == 1 else ""
        sent = q["sent_at"].strftime("%m/%d %H:%M") if q.get("sent_at") else "\u2014"
        rows += (
            f'<tr style="{bg}">'
            f'<td style="{_TD}"><b>{q["efj"]}</b></td>'
            f'<td style="{_TD}">{q["carrier"] or chr(8212)}</td>'
            f'<td style="{_TD}">{_fmt_rate(q["rate"])}</td>'
            f'<td style="{_TD}">{sent}</td>'
            f'<td style="{_TD}">{q["notes"] or chr(8212)}</td>'
            f'</tr>'
        )
    return (
        f'<table style="border-collapse:collapse;width:100%;border:1px solid #ddd;margin-top:10px;">'
        f'<tr style="background:#37474f;">'
        f'<th style="{_TH}">EFJ</th>'
        f'<th style="{_TH}">Carrier</th>'
        f'<th style="{_TH}">Rate</th>'
        f'<th style="{_TH}">Sent</th>'
        f'<th style="{_TH}">Notes</th>'
        f'</tr>'
        f'{rows}'
        f'</table>'
    )


def build_body(rep_name, closed, pipeline, qa, outbound_quotes, week_label, now_str):
    n_closed = len(closed)
    n_active = sum(pipeline.values()) if pipeline else 0
    return (
        f'<div style="font-family:Arial,sans-serif;max-width:960px;">'
        f'<h2 style="margin:0 0 4px 0;color:#333;">CSL Weekly \u2014 {rep_name} \u2014 {week_label}</h2>'
        f'<p style="color:#888;font-size:11px;margin:0 0 16px 0;">{now_str}</p>'
        f'<h3 style="color:#1565c0;margin:0 0 4px 0;font-size:13px;">Closed Loads ({n_closed})</h3>'
        f'{_closed_table(closed)}'
        f'<h3 style="color:#0277bd;margin:20px 0 6px 0;font-size:13px;">Active Pipeline ({n_active} loads)</h3>'
        f'<div style="margin-bottom:6px;">{_pipeline_pills(pipeline)}</div>'
        f'<h3 style="color:#1b5e20;margin:20px 0 6px 0;font-size:13px;">Quote Activity (Customer Rate Emails)</h3>'
        f'<div style="margin-bottom:6px;">{_quote_pills(qa)}</div>'
        f'<h3 style="color:#37474f;margin:20px 0 4px 0;font-size:13px;">Outbound Quotes ({len(outbound_quotes)})</h3>'
        f'{_outbound_table(outbound_quotes)}'
        f'<p style="color:#aaa;font-size:10px;margin-top:20px;">CSLogix Dispatch &middot; {now_str}</p>'
        f'</div>'
    )


def send_email(to_email, subject, body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    msg["Cc"]      = EMAIL_CC
    msg.attach(MIMEText(body, "html"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo(); smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.sendmail(SMTP_USER, [to_email, EMAIL_CC], msg.as_string())
        print(f"    Sent to {to_email} (cc: {EMAIL_CC})")
    except Exception as e:
        print(f"    ERROR sending to {to_email}: {e}")


def main():
    et = ZoneInfo("America/New_York")
    now_str = datetime.now(et).strftime("%Y-%m-%d %H:%M ET")
    start, end, week_label = week_bounds()

    print(f"\n=== Weekly Profit Report === {now_str} ===")
    print(f"  Week: {week_label}")

    conn = _get_conn()
    if not conn:
        print("ERROR: DB connection failed")
        return

    closed_by_rep = query_closed_loads(conn, start, end)
    print(f"  Closed loads this week: {sum(len(v) for v in closed_by_rep.values())}")

    for rep_name, rep_email in REPS.items():
        closed   = closed_by_rep.get(rep_name, [])
        pipeline = query_pipeline(conn, rep_name)
        qa       = query_quote_activity(conn, rep_name, start, end)
        outbound = query_outbound_quotes(conn, rep_name, start, end)
        n_active = sum(pipeline.values()) if pipeline else 0
        print(f"  [{rep_name}] closed={len(closed)} active={n_active} quotes={qa}")
        subject = f"CSL Weekly \u2014 {rep_name} \u2014 {week_label} \u2014 {len(closed)} Closed"
        body    = build_body(rep_name, closed, pipeline, qa, outbound, week_label, now_str)
        send_email(rep_email, subject, body)

    conn.close()
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
