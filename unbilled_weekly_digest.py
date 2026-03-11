#!/usr/bin/env python3
"""
Unbilled Orders Weekly Digest — Email for Janice (billing coordinator)
Sends Monday mornings with aging breakdown, customer totals, and 30-day warnings.

Usage:
    python3 unbilled_weekly_digest.py           # Send digest email
    python3 unbilled_weekly_digest.py --dry-run  # Print HTML to stdout, don't send
"""

import os
import sys
import smtplib
import logging
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Config ──
sys.path.insert(0, "/root/csl-bot")
from dotenv import load_dotenv
load_dotenv("/root/csl-bot/.env")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASSWORD"]
EMAIL_CC  = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")

# Janice is the billing coordinator
TO_EMAIL = "Janice.Cortes@evansdelivery.com"

log = logging.getLogger("unbilled_digest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

DRY_RUN = "--dry-run" in sys.argv


# ── Database ──
def get_conn():
    import psycopg2
    import psycopg2.extras
    sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
    import config
    conn = psycopg2.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD,
    )
    return conn


def fetch_unbilled_data():
    """Fetch all non-dismissed unbilled orders with computed metrics."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=__import__("psycopg2").extras.RealDictCursor)

    # Summary by customer
    cur.execute("""
        SELECT
            bill_to,
            COUNT(*) AS orders,
            ROUND(AVG(age_days)) AS avg_age,
            MAX(age_days) AS max_age,
            SUM(CASE WHEN age_days BETWEEN 0 AND 7 THEN 1 ELSE 0 END) AS bucket_0_7,
            SUM(CASE WHEN age_days BETWEEN 8 AND 14 THEN 1 ELSE 0 END) AS bucket_8_14,
            SUM(CASE WHEN age_days BETWEEN 15 AND 30 THEN 1 ELSE 0 END) AS bucket_15_30,
            SUM(CASE WHEN age_days > 30 THEN 1 ELSE 0 END) AS bucket_30_plus
        FROM unbilled_orders
        WHERE dismissed = false
        GROUP BY bill_to
        ORDER BY COUNT(*) DESC
    """)
    by_customer = cur.fetchall()

    # Global totals
    cur.execute("""
        SELECT
            COUNT(*) AS total,
            ROUND(AVG(age_days)) AS avg_age,
            MAX(age_days) AS max_age,
            SUM(CASE WHEN age_days BETWEEN 0 AND 7 THEN 1 ELSE 0 END) AS bucket_0_7,
            SUM(CASE WHEN age_days BETWEEN 8 AND 14 THEN 1 ELSE 0 END) AS bucket_8_14,
            SUM(CASE WHEN age_days BETWEEN 15 AND 30 THEN 1 ELSE 0 END) AS bucket_15_30,
            SUM(CASE WHEN age_days > 30 THEN 1 ELSE 0 END) AS bucket_30_plus
        FROM unbilled_orders
        WHERE dismissed = false
    """)
    totals = cur.fetchone()

    # Orders approaching 30-day threshold (age 25-30 days)
    cur.execute("""
        SELECT order_num, bill_to, age_days, ref1, dliv_dt
        FROM unbilled_orders
        WHERE dismissed = false AND age_days BETWEEN 25 AND 30
        ORDER BY age_days DESC, bill_to
    """)
    approaching_30 = cur.fetchall()

    # New since last week (created in last 7 days)
    cur.execute("""
        SELECT COUNT(*) AS new_count
        FROM unbilled_orders
        WHERE dismissed = false AND created_at >= NOW() - INTERVAL '7 days'
    """)
    new_this_week = cur.fetchone()["new_count"]

    # Dismissed this week
    cur.execute("""
        SELECT COUNT(*) AS dismissed_count
        FROM unbilled_orders
        WHERE dismissed = true AND dismissed_at >= NOW() - INTERVAL '7 days'
    """)
    dismissed_this_week = cur.fetchone()["dismissed_count"]

    conn.close()
    return {
        "by_customer": by_customer,
        "totals": totals,
        "approaching_30": approaching_30,
        "new_this_week": new_this_week,
        "dismissed_this_week": dismissed_this_week,
    }


# ── HTML Builder (Outlook-safe) ──

def _color(age):
    """Return color based on age severity."""
    if age > 30: return "#EF4444"
    if age > 20: return "#F97316"
    if age > 14: return "#EAB308"
    return "#6B7280"


def build_html(data):
    t = data["totals"]
    today = datetime.now().strftime("%B %d, %Y")

    # ── Header + Summary Cards ──
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0; padding:0; background:#111827; font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#111827;">
<tr><td align="center" style="padding:20px 10px;">
<table width="640" cellpadding="0" cellspacing="0" border="0" style="background:#1F2937; border-radius:8px; border:1px solid #374151;">

<!-- Header -->
<tr><td style="padding:24px 28px 16px; border-bottom:1px solid #374151;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td style="font-family:Arial,Helvetica,sans-serif; font-size:20px; font-weight:bold; color:#F9FAFB;">
      Unbilled Orders Digest
    </td>
    <td align="right" style="font-family:Arial,Helvetica,sans-serif; font-size:11px; color:#9CA3AF;">
      {today}
    </td>
  </tr>
  </table>
</td></tr>

<!-- Summary Cards -->
<tr><td style="padding:20px 28px 12px;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td width="25%" align="center" style="padding:12px 8px; background:#111827; border-radius:8px; border:1px solid #374151;">
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:28px; font-weight:bold; color:#F9FAFB;">{t['total']}</div>
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:9px; color:#9CA3AF; text-transform:uppercase; letter-spacing:1px; margin-top:4px;">Total Open</div>
    </td>
    <td width="4"></td>
    <td width="25%" align="center" style="padding:12px 8px; background:#111827; border-radius:8px; border:1px solid #374151;">
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:28px; font-weight:bold; color:#F97316;">{t['avg_age']}</div>
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:9px; color:#9CA3AF; text-transform:uppercase; letter-spacing:1px; margin-top:4px;">Avg Days</div>
    </td>
    <td width="4"></td>
    <td width="25%" align="center" style="padding:12px 8px; background:#111827; border-radius:8px; border:1px solid #374151;">
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:28px; font-weight:bold; color:#22C55E;">+{data['new_this_week']}</div>
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:9px; color:#9CA3AF; text-transform:uppercase; letter-spacing:1px; margin-top:4px;">New This Week</div>
    </td>
    <td width="4"></td>
    <td width="25%" align="center" style="padding:12px 8px; background:#111827; border-radius:8px; border:1px solid #374151;">
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:28px; font-weight:bold; color:#A78BFA;">{data['dismissed_this_week']}</div>
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:9px; color:#9CA3AF; text-transform:uppercase; letter-spacing:1px; margin-top:4px;">Cleared</div>
    </td>
  </tr>
  </table>
</td></tr>

<!-- Aging Buckets -->
<tr><td style="padding:16px 28px 8px;">
  <div style="font-family:Arial,Helvetica,sans-serif; font-size:10px; font-weight:bold; color:#9CA3AF; text-transform:uppercase; letter-spacing:2px; margin-bottom:10px;">Aging Breakdown</div>
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td width="25%" style="padding:10px 0; text-align:center;">
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:22px; font-weight:bold; color:#22C55E;">{t['bucket_0_7']}</div>
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:9px; color:#6B7280; margin-top:2px;">0–7 days</div>
    </td>
    <td width="25%" style="padding:10px 0; text-align:center;">
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:22px; font-weight:bold; color:#EAB308;">{t['bucket_8_14']}</div>
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:9px; color:#6B7280; margin-top:2px;">8–14 days</div>
    </td>
    <td width="25%" style="padding:10px 0; text-align:center;">
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:22px; font-weight:bold; color:#F97316;">{t['bucket_15_30']}</div>
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:9px; color:#6B7280; margin-top:2px;">15–30 days</div>
    </td>
    <td width="25%" style="padding:10px 0; text-align:center;">
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:22px; font-weight:bold; color:#EF4444;">{t['bucket_30_plus']}</div>
      <div style="font-family:Arial,Helvetica,sans-serif; font-size:9px; color:#6B7280; margin-top:2px;">30+ days</div>
    </td>
  </tr>
  </table>
</td></tr>
"""

    # ── Approaching 30-Day Warning ──
    if data["approaching_30"]:
        html += """
<!-- 30-Day Warning -->
<tr><td style="padding:16px 28px 8px;">
  <div style="font-family:Arial,Helvetica,sans-serif; font-size:10px; font-weight:bold; color:#EF4444; text-transform:uppercase; letter-spacing:2px; margin-bottom:10px;">⚠ Approaching 30 Days</div>
  <table width="100%" cellpadding="6" cellspacing="0" border="0" style="border:1px solid #7F1D1D; border-radius:6px; background:rgba(127,29,29,0.15);">
  <tr style="border-bottom:1px solid #374151;">
    <td style="font-family:Arial,Helvetica,sans-serif; font-size:9px; font-weight:bold; color:#9CA3AF; text-transform:uppercase; padding:8px 6px;">Order#</td>
    <td style="font-family:Arial,Helvetica,sans-serif; font-size:9px; font-weight:bold; color:#9CA3AF; text-transform:uppercase; padding:8px 6px;">Customer</td>
    <td style="font-family:Arial,Helvetica,sans-serif; font-size:9px; font-weight:bold; color:#9CA3AF; text-transform:uppercase; padding:8px 6px;" align="center">Age</td>
    <td style="font-family:Arial,Helvetica,sans-serif; font-size:9px; font-weight:bold; color:#9CA3AF; text-transform:uppercase; padding:8px 6px;">Ref</td>
  </tr>
"""
        for row in data["approaching_30"]:
            age_color = "#EF4444" if row["age_days"] >= 28 else "#F97316"
            html += f"""  <tr>
    <td style="font-family:'Courier New',monospace; font-size:11px; color:#E5E7EB; padding:6px;">{row['order_num'] or '—'}</td>
    <td style="font-family:Arial,Helvetica,sans-serif; font-size:10px; color:#D1D5DB; padding:6px;">{_truncate(row['bill_to'], 28)}</td>
    <td style="font-family:'Courier New',monospace; font-size:11px; font-weight:bold; color:{age_color}; padding:6px;" align="center">{row['age_days']}d</td>
    <td style="font-family:Arial,Helvetica,sans-serif; font-size:10px; color:#9CA3AF; padding:6px;">{row['ref1'] or '—'}</td>
  </tr>
"""
        html += """  </table>
</td></tr>
"""

    # ── Customer Breakdown Table ──
    html += """
<!-- Customer Breakdown -->
<tr><td style="padding:16px 28px 8px;">
  <div style="font-family:Arial,Helvetica,sans-serif; font-size:10px; font-weight:bold; color:#9CA3AF; text-transform:uppercase; letter-spacing:2px; margin-bottom:10px;">By Customer</div>
  <table width="100%" cellpadding="6" cellspacing="0" border="0" style="table-layout:fixed; border-collapse:collapse;">
  <tr style="border-bottom:1px solid #374151;">
    <td width="40%" style="font-family:Arial,Helvetica,sans-serif; font-size:9px; font-weight:bold; color:#9CA3AF; text-transform:uppercase; padding:8px 6px;">Customer</td>
    <td width="12%" style="font-family:Arial,Helvetica,sans-serif; font-size:9px; font-weight:bold; color:#9CA3AF; text-transform:uppercase; padding:8px 6px;" align="center">Orders</td>
    <td width="12%" style="font-family:Arial,Helvetica,sans-serif; font-size:9px; font-weight:bold; color:#9CA3AF; text-transform:uppercase; padding:8px 6px;" align="center">Avg</td>
    <td width="12%" style="font-family:Arial,Helvetica,sans-serif; font-size:9px; font-weight:bold; color:#9CA3AF; text-transform:uppercase; padding:8px 6px;" align="center">Max</td>
    <td width="24%" style="font-family:Arial,Helvetica,sans-serif; font-size:9px; font-weight:bold; color:#9CA3AF; text-transform:uppercase; padding:8px 6px;" align="center">Buckets</td>
  </tr>
"""
    for i, row in enumerate(data["by_customer"]):
        bg = "#111827" if i % 2 == 0 else "#1F2937"
        age_color = _color(int(row["max_age"] or 0))
        # Mini bucket bar
        b0 = int(row["bucket_0_7"] or 0)
        b1 = int(row["bucket_8_14"] or 0)
        b2 = int(row["bucket_15_30"] or 0)
        b3 = int(row["bucket_30_plus"] or 0)
        total = max(int(row["orders"]), 1)
        buckets_html = ""
        if b0: buckets_html += f'<span style="color:#22C55E; font-size:9px;">{b0}</span> '
        if b1: buckets_html += f'<span style="color:#EAB308; font-size:9px;">{b1}</span> '
        if b2: buckets_html += f'<span style="color:#F97316; font-size:9px;">{b2}</span> '
        if b3: buckets_html += f'<span style="color:#EF4444; font-size:9px; font-weight:bold;">{b3}</span>'
        if not buckets_html:
            buckets_html = '<span style="color:#6B7280; font-size:9px;">—</span>'

        html += f"""  <tr style="background:{bg};">
    <td style="font-family:Arial,Helvetica,sans-serif; font-size:10px; color:#E5E7EB; padding:6px; overflow:hidden; white-space:nowrap;">{_truncate(row['bill_to'], 30)}</td>
    <td style="font-family:'Courier New',monospace; font-size:11px; font-weight:bold; color:#F9FAFB; padding:6px;" align="center">{row['orders']}</td>
    <td style="font-family:'Courier New',monospace; font-size:11px; color:#9CA3AF; padding:6px;" align="center">{row['avg_age']}d</td>
    <td style="font-family:'Courier New',monospace; font-size:11px; font-weight:bold; color:{age_color}; padding:6px;" align="center">{row['max_age']}d</td>
    <td style="font-family:Arial,Helvetica,sans-serif; padding:6px;" align="center">{buckets_html}</td>
  </tr>
"""
    html += """  </table>
</td></tr>
"""

    # ── Footer ──
    html += f"""
<!-- Footer -->
<tr><td style="padding:20px 28px; border-top:1px solid #374151;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td style="font-family:Arial,Helvetica,sans-serif; font-size:10px; color:#6B7280;">
      View full details: <a href="https://cslogixdispatch.com/app" style="color:#38BDF8; text-decoration:none;">cslogixdispatch.com/app</a> → Unbilled tab
    </td>
    <td align="right" style="font-family:Arial,Helvetica,sans-serif; font-size:9px; color:#4B5563;">
      CSLogix Bot · Auto-generated
    </td>
  </tr>
  </table>
</td></tr>

</table>
</td></tr></table>
</body></html>"""

    return html


def _truncate(s, maxlen):
    """Truncate string with ellipsis."""
    if not s:
        return "—"
    s = str(s).strip()
    return s[:maxlen-1] + "…" if len(s) > maxlen else s


# ── Send ──
def send_digest(html):
    subject = f"CSL Unbilled Orders Digest — {datetime.now().strftime('%b %d, %Y')}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = TO_EMAIL
    msg["Cc"] = EMAIL_CC
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.sendmail(SMTP_USER, [TO_EMAIL, EMAIL_CC], msg.as_string())
        log.info("Sent unbilled digest → %s (cc: %s)", TO_EMAIL, EMAIL_CC)
    except Exception as e:
        log.error("Failed to send digest: %s", e)
        raise


# ── Main ──
def main():
    log.info("Generating unbilled orders weekly digest...")
    data = fetch_unbilled_data()

    if data["totals"]["total"] == 0:
        log.info("No unbilled orders — skipping digest.")
        return

    html = build_html(data)

    if DRY_RUN:
        print(html)
        log.info("Dry run — HTML printed to stdout, no email sent.")
        return

    send_digest(html)
    log.info("Done. %d orders across %d customers.",
             data["totals"]["total"], len(data["by_customer"]))


if __name__ == "__main__":
    main()
