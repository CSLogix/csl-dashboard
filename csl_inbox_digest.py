#!/usr/bin/env python3
"""
CSL Bot — Daily Inbox Digest
Sends digest emails to account reps with pending inbox items and unbilled orders.
Runs at 7:00 AM ET Mon-Fri via cron with --once flag.
"""

import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from collections import defaultdict

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Guard: require --once
# ---------------------------------------------------------------------------
if "--once" not in sys.argv:
    sys.exit("Usage: python3 csl_inbox_digest.py --once")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Load both .env files — doc-tracker has DB creds, main has SMTP creds
load_dotenv("/root/csl-bot/csl-doc-tracker/.env")
load_dotenv("/root/csl-bot/.env", override=False)

SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_CC = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "csl_doc_tracker")
DB_USER = os.getenv("DB_USER", "csl_admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "changeme")

DASHBOARD_URL = "https://cslogixdispatch.com/app"

# ---------------------------------------------------------------------------
# Rep / Account mapping
# ---------------------------------------------------------------------------
ACCOUNT_REP_MAP = {
    "DSV": "Eli",
    "EShipping": "Eli",
    "Kishco": "Eli",
    "MAO": "Eli",
    "Rose": "Eli",
    "Allround": "Radka",
    "Cadi": "Radka",
    "IWS": "Radka",
    "Kripke": "Radka",
    "MGF": "Radka",
    "Meiko": "Radka",
    "Sutton": "Radka",
    "Tanera": "Radka",
    "TCR": "Radka",
    "Texas International": "Radka",
    "USHA": "Radka",
    "DHL": "John F",
    "Mamata": "John F",
    "SEI Acquisition": "John F",
    "CNL": "Janice",
}

REP_EMAILS = {
    "Eli": "eli@evansdelivery.com",
    "Radka": "radka@evansdelivery.com",
    "John F": "john.feltz@commonsenselogistics.com",
    "Janice": "janice@evansdelivery.com",
}

# Reverse map: account → rep (lowercase-safe lookup built at bottom)
ACCOUNT_REP_LOWER = {k.lower(): v for k, v in ACCOUNT_REP_MAP.items()}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
from csl_logging import get_logger

log = get_logger("inbox_digest")

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


def fetch_unsent_digest_items(conn):
    """Return all unsent digest queue items."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, efj, email_type, sender, subject, summary, rep, created_at
            FROM inbox_digest_queue
            WHERE sent = false
            ORDER BY created_at ASC
        """)
        return cur.fetchall()


def fetch_unbilled_orders(conn):
    """Return non-dismissed unbilled orders."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT bill_to AS customer_name, order_num AS order_number,
                   age_days,
                   rep
            FROM unbilled_orders
            WHERE dismissed = false OR dismissed IS NULL
            ORDER BY created_at ASC
        """)
        return cur.fetchall()


def resolve_rep_for_item(item, conn):
    """Determine which rep an inbox digest item belongs to."""
    # 1. Explicit rep field
    if item.get("rep"):
        return item["rep"]
    # 2. Look up EFJ → account in shipments table
    if item.get("efj"):
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT account FROM shipments WHERE efj = %s LIMIT 1",
                (item["efj"],),
            )
            row = cur.fetchone()
            if row and row["account"]:
                rep = ACCOUNT_REP_LOWER.get(row["account"].lower())
                if rep:
                    return rep
    # 3. Fallback
    return "John F"


def resolve_rep_for_unbilled(order):
    """Determine which rep an unbilled order belongs to."""
    if order.get("rep"):
        # Check if it matches a known rep name
        for rep_name in REP_EMAILS:
            if order["rep"].lower() == rep_name.lower():
                return rep_name
        # Check if it matches an account name
        rep = ACCOUNT_REP_LOWER.get(order["rep"].lower())
        if rep:
            return rep
    if order.get("customer_name"):
        rep = ACCOUNT_REP_LOWER.get(order["customer_name"].lower())
        if rep:
            return rep
    return "John F"


def mark_items_sent(conn, item_ids):
    """Mark digest queue items as sent."""
    if not item_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE inbox_digest_queue SET sent = true WHERE id = ANY(%s)",
            (item_ids,),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Detect Boviet project / Tolead hub
# ---------------------------------------------------------------------------

def detect_boviet_project(item):
    """Return 'Piedra', 'Hanson', or 'Other' based on subject/summary."""
    text = ((item.get("subject") or "") + " " + (item.get("summary") or "")).lower()
    if "piedra" in text:
        return "Piedra"
    if "hanson" in text:
        return "Hanson"
    return "Other"


def detect_tolead_hub(item):
    """Return ORD/JFK/LAX/DFW or 'Other' from subject/EFJ."""
    text = ((item.get("subject") or "") + " " + (item.get("efj") or "")).upper()
    for hub in ("ORD", "JFK", "LAX", "DFW"):
        if hub in text:
            return hub
    return "Other"


# ---------------------------------------------------------------------------
# Email HTML builder
# ---------------------------------------------------------------------------

HTML_STYLE = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1a1a2e; margin: 0; padding: 0; }
  .container { max-width: 680px; margin: 0 auto; padding: 24px; }
  h2 { color: #1e40af; font-size: 18px; margin: 24px 0 8px; border-bottom: 2px solid #e5e7eb; padding-bottom: 4px; }
  h3 { color: #374151; font-size: 15px; margin: 16px 0 6px; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 16px; font-size: 13px; }
  th { background: #f1f5f9; color: #334155; text-align: left; padding: 8px 10px; border: 1px solid #e2e8f0; font-weight: 600; }
  td { padding: 6px 10px; border: 1px solid #e2e8f0; vertical-align: top; }
  tr:nth-child(even) td { background: #f8fafc; }
  .footer { margin-top: 24px; padding-top: 12px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
  .section-label { color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
</style>
"""


def build_inbox_table(items):
    """Build HTML table for inbox digest items."""
    if not items:
        return ""
    rows = ""
    for it in items:
        efj = it.get("efj") or "—"
        etype = it.get("email_type") or "—"
        sender = it.get("sender") or "—"
        summary = it.get("summary") or "—"
        rows += f"<tr><td>{efj}</td><td>{etype}</td><td>{sender}</td><td>{summary}</td></tr>\n"
    return f"""
    <h3>Inbox Items ({len(items)})</h3>
    <table>
      <tr><th>EFJ</th><th>Type</th><th>Sender</th><th>Summary</th></tr>
      {rows}
    </table>
    """


def build_unbilled_table(orders):
    """Build HTML table for unbilled orders."""
    if not orders:
        return ""
    rows = ""
    for o in orders:
        customer = o.get("customer_name") or "—"
        order_num = o.get("order_number") or "—"
        age = o.get("age_days")
        age_str = f"{age}d" if age is not None else "—"
        rows += f"<tr><td>{customer}</td><td>{order_num}</td><td>{age_str}</td></tr>\n"
    return f"""
    <h3>Unbilled Orders ({len(orders)})</h3>
    <table>
      <tr><th>Customer</th><th>Order #</th><th>Age</th></tr>
      {rows}
    </table>
    """


def build_digest_html(title, sections_html, extra_note=""):
    """Wrap section HTML in a full email body."""
    today = datetime.now().strftime("%A, %B %d, %Y")
    return f"""<!DOCTYPE html>
<html><head>{HTML_STYLE}</head>
<body>
<div class="container">
  <h2>{title}</h2>
  <p class="section-label">{today}</p>
  {extra_note}
  {sections_html}
  <div class="footer">
    <a href="{DASHBOARD_URL}">Open CSLogix Dashboard</a> &middot; CSL Bot Daily Digest
  </div>
</div>
</body></html>"""


# ---------------------------------------------------------------------------
# Send email
# ---------------------------------------------------------------------------

def send_email(to_addr, subject, html_body, cc=None):
    """Send an HTML email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_USER
    msg["To"] = to_addr
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    msg.attach(MIMEText(html_body, "html"))

    recipients = [to_addr]
    if cc:
        recipients.append(cc)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        log.info("Sent digest to %s (cc=%s) — %s", to_addr, cc or "none", subject)
        return True
    except Exception:
        log.exception("Failed to send digest to %s", to_addr)
        return False


# ---------------------------------------------------------------------------
# Main digest logic
# ---------------------------------------------------------------------------

def run_digest():
    conn = get_conn()
    try:
        # ------------------------------------------------------------------
        # 1. Fetch data
        # ------------------------------------------------------------------
        digest_items = fetch_unsent_digest_items(conn)
        unbilled_orders = fetch_unbilled_orders(conn)
        log.info("Fetched %d unsent digest items, %d unbilled orders",
                 len(digest_items), len(unbilled_orders))

        if not digest_items and not unbilled_orders:
            log.info("Nothing to send. Exiting.")
            return

        # ------------------------------------------------------------------
        # 2. Classify items by target: master reps, Boviet, Tolead
        # ------------------------------------------------------------------
        master_items = defaultdict(list)   # rep -> [items]
        boviet_items = []
        tolead_items = []
        sent_item_ids = []

        for item in digest_items:
            # Resolve rep for the item
            rep = resolve_rep_for_item(item, conn)
            account = None

            # Determine account from EFJ
            if item.get("efj"):
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT account FROM shipments WHERE efj = %s LIMIT 1",
                        (item["efj"],),
                    )
                    row = cur.fetchone()
                    if row:
                        account = row["account"]

            # Route to Boviet / Tolead / Master rep buckets
            if account and account.lower() == "boviet":
                boviet_items.append(item)
            elif account and account.lower() == "tolead":
                tolead_items.append(item)
            else:
                item["_account"] = account or "Unknown"
                master_items[rep].append(item)

        # Classify unbilled by rep
        unbilled_by_rep = defaultdict(list)
        for order in unbilled_orders:
            rep = resolve_rep_for_unbilled(order)
            unbilled_by_rep[rep].append(order)

        # ------------------------------------------------------------------
        # 3. Send Master Rep digests
        # ------------------------------------------------------------------
        for rep_name, email_addr in REP_EMAILS.items():
            rep_inbox = master_items.get(rep_name, [])
            rep_unbilled = unbilled_by_rep.get(rep_name, [])

            if not rep_inbox and not rep_unbilled:
                log.info("No items for %s, skipping.", rep_name)
                continue

            # Group inbox items by account
            by_account = defaultdict(list)
            for it in rep_inbox:
                by_account[it.get("_account", "Unknown")].append(it)

            sections = ""
            if rep_inbox:
                sections += f"<h2>Inbox Updates ({len(rep_inbox)})</h2>\n"
                for acct in sorted(by_account.keys()):
                    sections += f"<h3>{acct}</h3>\n"
                    sections += build_inbox_table(by_account[acct])

            if rep_unbilled:
                sections += build_unbilled_table(rep_unbilled)

            total_items = len(rep_inbox) + len(rep_unbilled)
            subject = f"\U0001f4ec {rep_name} Daily Digest \u2014 {total_items} items"
            html = build_digest_html(
                f"{rep_name} \u2014 Daily Digest",
                sections,
            )

            if send_email(email_addr, subject, html, cc=EMAIL_CC):
                sent_item_ids.extend(it["id"] for it in rep_inbox)

        # ------------------------------------------------------------------
        # 4. Boviet digest
        # ------------------------------------------------------------------
        if boviet_items:
            by_project = defaultdict(list)
            for it in boviet_items:
                proj = detect_boviet_project(it)
                by_project[proj].append(it)

            sections = ""
            for proj in sorted(by_project.keys()):
                sections += f"<h3>Project: {proj}</h3>\n"
                sections += build_inbox_table(by_project[proj])

            subject = f"\U0001f4ec Boviet Daily Digest \u2014 {len(boviet_items)} items"
            html = build_digest_html("Boviet Daily Digest", sections)

            if send_email("boviet-efj@evansdelivery.com", subject, html):
                sent_item_ids.extend(it["id"] for it in boviet_items)

        # ------------------------------------------------------------------
        # 5. Tolead digest
        # ------------------------------------------------------------------
        if tolead_items:
            by_hub = defaultdict(list)
            for it in tolead_items:
                hub = detect_tolead_hub(it)
                by_hub[hub].append(it)

            sections = ""
            for hub in sorted(by_hub.keys()):
                sections += f"<h3>Hub: {hub} ({len(by_hub[hub])})</h3>\n"
                sections += build_inbox_table(by_hub[hub])

            n_hubs = len(by_hub)
            subject = (
                f"\U0001f4ec Tolead Daily Digest \u2014 "
                f"{len(tolead_items)} items across {n_hubs} hub{'s' if n_hubs != 1 else ''}"
            )
            html = build_digest_html("Tolead Daily Digest", sections)

            if send_email("tolead-efj@evansdelivery.com", subject, html):
                sent_item_ids.extend(it["id"] for it in tolead_items)

        # ------------------------------------------------------------------
        # 6. Mark sent
        # ------------------------------------------------------------------
        mark_items_sent(conn, sent_item_ids)
        log.info("Marked %d items as sent. Done.", len(sent_item_ids))

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("Starting daily inbox digest...")
    try:
        run_digest()
    except Exception:
        log.exception("Digest failed")
        sys.exit(1)
    log.info("Digest complete.")
