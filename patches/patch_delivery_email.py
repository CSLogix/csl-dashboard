#!/usr/bin/env python3
"""
Patch: Add delivery email notifications to app.py
- Creates delivery_emails_sent table for dedup
- Adds send_delivery_email() function with SMTP
- Hooks into POST /api/load/{efj}/status to fire email on "Delivered" for Master loads
"""

import sys, psycopg2

APP = "/root/csl-bot/csl-doc-tracker/app.py"

# ── Step 1: Create dedup table ─────────────────────────────────────────────
print("[1/3] Creating delivery_emails_sent table...")
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS delivery_emails_sent (
    efj         TEXT PRIMARY KEY,
    account     TEXT,
    sent_at     TIMESTAMPTZ DEFAULT NOW()
);
""")
conn.commit()
cur.close()
conn.close()
print("   Table ready.")

# ── Step 2: Add delivery email function + hook to app.py ───────────────────
print("[2/3] Patching app.py with delivery email function...")

with open(APP, "r") as f:
    code = f.read()

# Check if already patched
if "send_delivery_email" in code:
    print("   Already patched — skipping.")
    sys.exit(0)

# Insert the email function after the imports section (after DISPATCH_EMAIL line)
EMAIL_FUNC = '''
# ── Delivery Email Notification ──────────────────────────────────────────
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import threading

JANICE_EMAIL = "Janice.Cortes@evansdelivery.com"
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

def _has_delivery_email_been_sent(efj: str) -> bool:
    """Check if delivery email was already sent for this EFJ."""
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT efj FROM delivery_emails_sent WHERE efj = %s", (efj,))
            return cur.fetchone() is not None
    except Exception:
        return False

def _record_delivery_email(efj: str, account: str):
    """Record that delivery email was sent for this EFJ."""
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute(
                    "INSERT INTO delivery_emails_sent (efj, account) VALUES (%s, %s) ON CONFLICT (efj) DO NOTHING",
                    (efj, account)
                )
    except Exception as e:
        log.error("Failed to record delivery email for %s: %s", efj, e)

def send_delivery_email(shipment: dict):
    """Send delivery notification email to Janice for Master loads."""
    efj = shipment.get("efj", "")
    account = shipment.get("account", "")

    # Only Master loads (not Tolead/Boviet)
    if account in ("Tolead", "Boviet"):
        return
    # Dedup check
    if _has_delivery_email_been_sent(efj):
        log.info("Delivery email already sent for %s — skipping", efj)
        return
    if not SMTP_USER or not SMTP_PASSWORD:
        log.warning("SMTP credentials not configured — skipping delivery email for %s", efj)
        return

    container = shipment.get("container", "") or shipment.get("loadNumber", "")
    carrier = shipment.get("carrier", "")
    origin = shipment.get("origin", "")
    destination = shipment.get("destination", "")
    delivery_date = shipment.get("delivery", "")
    rep = shipment.get("rep", "")

    subject = f"CSL — Delivered: {efj} | {account} | {container}"
    deep_link = f"https://cslogixdispatch.com/app?view=billing&load={efj}"

    body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
      <div style="background: linear-gradient(135deg, #22C55E, #4ADE80); padding: 16px 24px; border-radius: 12px 12px 0 0;">
        <h2 style="color: white; margin: 0; font-size: 18px;">&#10022; Load Delivered</h2>
      </div>
      <div style="background: #141A28; padding: 24px; border: 1px solid #1E293B; border-top: none; border-radius: 0 0 12px 12px;">
        <table style="width: 100%; border-collapse: collapse; color: #F0F2F5; font-size: 14px;">
          <tr><td style="padding: 8px 0; color: #8B95A8; width: 120px;">EFJ #</td><td style="padding: 8px 0; font-weight: 600;">{efj}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Account</td><td style="padding: 8px 0; font-weight: 600;">{account}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Container/Load</td><td style="padding: 8px 0;">{container}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Carrier</td><td style="padding: 8px 0;">{carrier}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Route</td><td style="padding: 8px 0;">{origin} &#8594; {destination}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Delivery Date</td><td style="padding: 8px 0;">{delivery_date}</td></tr>
          <tr><td style="padding: 8px 0; color: #8B95A8;">Rep</td><td style="padding: 8px 0;">{rep}</td></tr>
        </table>
        <div style="margin-top: 20px; text-align: center;">
          <a href="{deep_link}" style="display: inline-block; background: #00D4AA; color: #0A0E17; padding: 10px 28px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 14px;">
            Open in Billing Dashboard
          </a>
        </div>
      </div>
      <p style="color: #64748B; font-size: 11px; margin-top: 12px; text-align: center;">
        CSLogix Dispatch &mdash; Automated delivery notification
      </p>
    </div>
    """

    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = SMTP_USER
            msg["To"] = JANICE_EMAIL
            msg["Cc"] = DISPATCH_EMAIL
            msg.attach(MIMEText(body, "html"))

            recipients = [JANICE_EMAIL, DISPATCH_EMAIL]
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(SMTP_USER, SMTP_PASSWORD)
                smtp.sendmail(SMTP_USER, recipients, msg.as_string())

            _record_delivery_email(efj, account)
            log.info("Delivery email sent for %s → %s (cc: %s)", efj, JANICE_EMAIL, DISPATCH_EMAIL)
        except Exception as exc:
            log.error("Failed to send delivery email for %s: %s", efj, exc)

    threading.Thread(target=_send, daemon=True).start()
'''

# Insert after the DISPATCH_EMAIL line
anchor = 'DISPATCH_EMAIL = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")'
if anchor not in code:
    print("   ERROR: Could not find DISPATCH_EMAIL anchor line")
    sys.exit(1)

code = code.replace(anchor, anchor + "\n" + EMAIL_FUNC)

# ── Step 3: Hook into status update endpoint ──────────────────────────────
print("[3/3] Hooking into status update endpoint...")

# Find the line after status cache update and before return
old_hook = '''        # Update cache
        shipment["status"] = new_status
        log.info("Status updated: %s → %s (tab=%s)", efj, new_status, tab)
        return {"status": "ok", "efj": efj, "new_status": new_status}'''

new_hook = '''        # Update cache
        shipment["status"] = new_status
        log.info("Status updated: %s → %s (tab=%s)", efj, new_status, tab)

        # Send delivery email for Master loads
        _normalized = new_status.strip().lower()
        if _normalized == "delivered" and tab not in ("Tolead", "Boviet"):
            send_delivery_email(shipment)

        return {"status": "ok", "efj": efj, "new_status": new_status}'''

if old_hook not in code:
    print("   ERROR: Could not find status update hook point")
    sys.exit(1)

code = code.replace(old_hook, new_hook)

with open(APP, "w") as f:
    f.write(code)

print("   Done! Delivery email patch applied.")
print("   Restart: systemctl restart csl-dashboard")
