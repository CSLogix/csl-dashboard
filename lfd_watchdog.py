#!/usr/bin/env python3
"""
LFD Watchdog — fires email alerts to account reps when a container is
within 0, 1, or 2 days of its Last Free Day.

State file: /root/csl-bot/lfd_sent_alerts.json
  Key: "{efj}_{lfd_date}"  e.g. "107423_2026-03-12"
  Prevents duplicate sends across cron runs.

Cron: 30 6 * * 1-5  (6:30 AM ET, Mon-Fri)
"""
import os
import re
import json
import psycopg2
import smtplib
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# ── Load credentials from both .env files (same pattern as csl_bot.py) ──
load_dotenv('/root/csl-bot/.env')                           # SMTP creds
load_dotenv('/root/csl-bot/csl-doc-tracker/.env', override=True)  # DB creds

STATE_FILE = '/root/csl-bot/lfd_sent_alerts.json'

# Full account → rep email mapping (mirrors ACCOUNT_REPS in csl_bot.py)
ACCOUNT_REPS = {
    "Allround":            "Radka.White@evansdelivery.com",
    "Boviet":              "Boviet-efj@evansdelivery.com",
    "Cadi":                "Radka.White@evansdelivery.com",
    "CNL":                 "Janice.Cortes@evansdelivery.com",
    "DHL":                 "John.Feltz@evansdelivery.com",
    "DSV":                 "Eli.Luchuk@evansdelivery.com",
    "EShipping":           "Eli.Luchuk@evansdelivery.com",
    "IWS":                 "Radka.White@evansdelivery.com",
    "Kishco":              "Eli.Luchuk@evansdelivery.com",
    "Kripke":              "Radka.White@evansdelivery.com",
    "MAO":                 "Eli.Luchuk@evansdelivery.com",
    "Mamata":              "John.Feltz@evansdelivery.com",
    "Meiko":               "Radka.White@evansdelivery.com",
    "MGF":                 "Radka.White@evansdelivery.com",
    "Mitchell's Transport":"John.Feltz@evansdelivery.com",
    "Rose":                "Eli.Luchuk@evansdelivery.com",
    "SEI Acquisition":     "John.Feltz@evansdelivery.com",
    "Sutton":              "Radka.White@evansdelivery.com",
    "Tanera":              "Radka.White@evansdelivery.com",
    "TCR":                 "Radka.White@evansdelivery.com",
    "Texas International": "Radka.White@evansdelivery.com",
    "USHA":                "Radka.White@evansdelivery.com",
    "MD Metal":            "Radka.White@evansdelivery.com",
}
FALLBACK_EMAIL = "efj-operations@evansdelivery.com"
CC_EMAIL = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")

MONTH_MAP = {
    'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
    'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12
}

SKIP_STATUSES = {
    'Delivered', 'Completed', 'Empty Returned',
    'Returned to Port', 'Billed/Closed', 'Cancelled'
}


def parse_lfd(text):
    """Parse LFD text (many formats) into a date, or None if unparseable."""
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    today = date.today()

    # Excel serial number (5 digits in plausible range 2009–2036)
    if re.match(r'^\d{5}$', s):
        serial = int(s)
        if 40000 <= serial <= 55000:
            return date(1899, 12, 30) + timedelta(days=serial)
        return None

    # ISO: YYYY-MM-DD
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    # MM/DD/YY or MM/DD/YYYY or MM/DD
    m = re.match(r'^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$', s)
    if m:
        try:
            month, day = int(m.group(1)), int(m.group(2))
            yr = m.group(3)
            if yr:
                year = int(yr)
                if year < 100:
                    year += 2000
            else:
                year = today.year
                d = date(year, month, day)
                if (d - today).days < -30:
                    year += 1
            return date(year, month, day)
        except (ValueError, TypeError):
            return None

    # DD-Mon (e.g. "29-Mar")
    m = re.match(r'^(\d{1,2})-([A-Za-z]{3})$', s)
    if m:
        mon = m.group(2).lower()
        if mon in MONTH_MAP:
            try:
                day, month = int(m.group(1)), MONTH_MAP[mon]
                year = today.year
                d = date(year, month, day)
                if (d - today).days < -30:
                    year += 1
                return date(year, month, day)
            except ValueError:
                return None

    # Mon-DD or Mon DD (e.g. "Mar-29" or "Mar 29")
    m = re.match(r'^([A-Za-z]{3})[\s-](\d{1,2})$', s)
    if m:
        mon = m.group(1).lower()
        if mon in MONTH_MAP:
            try:
                month, day = MONTH_MAP[mon], int(m.group(2))
                year = today.year
                d = date(year, month, day)
                if (d - today).days < -30:
                    year += 1
                return date(year, month, day)
            except ValueError:
                return None

    return None


def _pg_connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "csl_doc_tracker"),
        user=os.getenv("DB_USER", "csl_admin"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def send_alert(to_email, subject, html_body):
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg["Cc"] = CC_EMAIL
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to_email, CC_EMAIL], msg.as_string())


def run_watchdog():
    state = load_state()
    conn = _pg_connect()
    cur = conn.cursor()

    # Fetch all active shipments with an LFD value — parse dates in Python
    # because the lfd column stores many free-text formats
    cur.execute("""
        SELECT efj, account, container, lfd, status
        FROM shipments
        WHERE lfd IS NOT NULL
          AND lfd <> ''
          AND COALESCE(status, '') NOT IN (
              'Delivered','Completed','Empty Returned',
              'Returned to Port','Billed/Closed','Cancelled'
          )
          AND COALESCE(archived, false) = false
          AND COALESCE(move_type, '') NOT ILIKE '%ftl%'
        ORDER BY efj ASC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    today = date.today()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sent = 0
    in_window = 0

    for efj, account, container, lfd_raw, status in rows:
        lfd_date = parse_lfd(lfd_raw)
        if lfd_date is None:
            continue  # unparseable (e.g. "ON SHIP", "TBD")

        days_left = (lfd_date - today).days
        if days_left < 0 or days_left > 2:
            continue  # outside 0-2 day window

        in_window += 1
        state_key = f"{efj}_{lfd_date}"

        if state_key in state:
            print(f"  skip {state_key} (already sent)")
            continue

        if days_left == 0:
            subject = f"\U0001f6a8 PICK UP TODAY \u2014 {container or efj} [{efj}]"
            timing = "TODAY"
            color = "#d32f2f"
        elif days_left == 1:
            subject = f"\u26a0\ufe0f PICK UP TOMORROW \u2014 {container or efj} [{efj}]"
            timing = "TOMORROW"
            color = "#f57c00"
        else:
            subject = f"\U0001f4cb LFD in 2 days \u2014 {container or efj} [{efj}]"
            timing = str(lfd_date)
            color = "#1976d2"

        to_email = ACCOUNT_REPS.get(account or "", FALLBACK_EMAIL)

        html_body = f"""
        <html><body style="font-family:Arial,sans-serif;font-size:14px;color:#333">
        <h3 style="color:{color}">LFD Alert \u2014 {timing}</h3>
        <table cellpadding="6" style="border-collapse:collapse">
            <tr><td><b>Container:</b></td><td>{container or '\u2014'}</td></tr>
            <tr><td><b>EFJ#:</b></td><td>{efj}</td></tr>
            <tr><td><b>Account:</b></td><td>{account or '\u2014'}</td></tr>
            <tr><td><b>Last Free Day:</b></td><td><b>{timing}</b> ({lfd_date})</td></tr>
            <tr><td><b>Status:</b></td><td>{status or '\u2014'}</td></tr>
        </table>
        <p style="margin-top:16px"><b>Action required:</b> Schedule pickup immediately to avoid demurrage fees.</p>
        <p style="color:#888;font-size:11px">LFD Watchdog \u00b7 CSLogix Dispatch \u00b7 {now_str}</p>
        </body></html>
        """

        try:
            send_alert(to_email, subject, html_body)
            state[state_key] = now_str
            sent += 1
            print(f"  SENT: {subject} \u2192 {to_email}")
        except Exception as e:
            print(f"  ERROR: {efj} \u2192 {e}")

    save_state(state)
    print(f"Done. {sent} alert(s) sent, {in_window} container(s) in 0\u20132 day window.")


if __name__ == "__main__":
    print(f"--- LFD Watchdog {datetime.now()} ---")
    run_watchdog()
