"""
Auto-Status Email Drafter — generates email drafts on milestone status changes.
Reps review and send with one click from the dashboard.
"""

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

import database as db

log = logging.getLogger(__name__)
router = APIRouter()

ET = ZoneInfo("America/New_York")

# ── SMTP Config ──
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
DISPATCH_EMAIL = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")

# ── Account → Rep email mapping ──
ACCOUNT_REPS = {
    "Allround": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Boviet":   {"rep": "Radka", "email": "Boviet-efj@evansdelivery.com"},
    "Cadi":     {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "CNL":      {"rep": "Janice", "email": "Janice.Cortes@evansdelivery.com"},
    "DHL":      {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "DSV":      {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "EShipping": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "IWS":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Kishco":   {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Kripke":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MAO":      {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Mamata":   {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Meiko":    {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MGF":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Mitchell's Transport": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Rose":     {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "SEI Acquisition": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Sutton":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Tanera":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "TCR":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Texas International": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "USHA":     {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MD Metal": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Prolog":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Talatrans": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "LS Cargo": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "GW-World": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Tolead":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
}

# ── Milestone definitions ──
MILESTONES = {
    "picked_up": {
        "label": "Picked Up",
        "color": "#2563eb",
        "gradient": "linear-gradient(135deg, #2563eb, #60a5fa)",
        "icon": "&#128666;",  # truck
        "message": "Your container has been picked up and is on the way.",
    },
    "in_transit": {
        "label": "In Transit",
        "color": "#4f46e5",
        "gradient": "linear-gradient(135deg, #4f46e5, #818cf8)",
        "icon": "&#128667;",  # delivery truck
        "message": "Your shipment is currently in transit to the destination.",
    },
    "out_for_delivery": {
        "label": "Out for Delivery",
        "color": "#ea580c",
        "gradient": "linear-gradient(135deg, #ea580c, #fb923c)",
        "icon": "&#128230;",  # package
        "message": "Your shipment is out for delivery and will arrive shortly.",
    },
    "delivered": {
        "label": "Delivered",
        "color": "#16a34a",
        "gradient": "linear-gradient(135deg, #16a34a, #4ade80)",
        "icon": "&#10004;",  # check
        "message": "Your shipment has been delivered successfully.",
    },
    "empty_return": {
        "label": "Empty Returned",
        "color": "#0d9488",
        "gradient": "linear-gradient(135deg, #0d9488, #2dd4bf)",
        "icon": "&#9850;",  # recycle
        "message": "The empty container has been returned to the port/terminal.",
    },
}


def _build_email_html(shipment: dict, milestone_key: str) -> str:
    """Build HTML email body for a milestone notification."""
    m = MILESTONES[milestone_key]
    efj = shipment.get("efj", "")
    account = shipment.get("account", "")
    container = shipment.get("container", "") or ""
    carrier = shipment.get("carrier", "") or ""
    origin = shipment.get("origin", "") or ""
    destination = shipment.get("destination", "") or ""
    eta = shipment.get("eta", "") or ""
    lfd = shipment.get("lfd", "") or ""
    delivery_date = shipment.get("delivery_date", "") or ""
    pickup_date = shipment.get("pickup_date", "") or ""
    driver = shipment.get("driver", "") or ""
    return_date = shipment.get("return_date", "") or ""
    rep = shipment.get("rep", "") or ""
    now_et = datetime.now(ET).strftime("%b %d, %Y at %I:%M %p ET")
    deep_link = f"https://cslogixdispatch.com/app?view=dispatch&load={efj}"

    # Build rows based on milestone
    rows = f"""
        <tr><td style="padding: 8px 0; color: #8B95A8; width: 130px;">EFJ #</td><td style="padding: 8px 0; font-weight: 600;">{efj}</td></tr>
        <tr><td style="padding: 8px 0; color: #8B95A8;">Account</td><td style="padding: 8px 0; font-weight: 600;">{account}</td></tr>
        <tr><td style="padding: 8px 0; color: #8B95A8;">Container/Load</td><td style="padding: 8px 0;">{container}</td></tr>
        <tr><td style="padding: 8px 0; color: #8B95A8;">Carrier</td><td style="padding: 8px 0;">{carrier}</td></tr>
        <tr><td style="padding: 8px 0; color: #8B95A8;">Route</td><td style="padding: 8px 0;">{origin} &#8594; {destination}</td></tr>
    """

    if milestone_key == "picked_up":
        rows += f'<tr><td style="padding: 8px 0; color: #8B95A8;">Pickup Date</td><td style="padding: 8px 0;">{pickup_date or now_et.split(" at")[0]}</td></tr>'
        if eta:
            rows += f'<tr><td style="padding: 8px 0; color: #8B95A8;">ETA</td><td style="padding: 8px 0;">{eta}</td></tr>'
    elif milestone_key == "in_transit":
        if eta:
            rows += f'<tr><td style="padding: 8px 0; color: #8B95A8;">ETA</td><td style="padding: 8px 0;">{eta}</td></tr>'
    elif milestone_key == "out_for_delivery":
        if driver:
            rows += f'<tr><td style="padding: 8px 0; color: #8B95A8;">Driver</td><td style="padding: 8px 0;">{driver}</td></tr>'
    elif milestone_key == "delivered":
        rows += f'<tr><td style="padding: 8px 0; color: #8B95A8;">Delivery Date</td><td style="padding: 8px 0;">{delivery_date or now_et.split(" at")[0]}</td></tr>'
    elif milestone_key == "empty_return":
        rows += f'<tr><td style="padding: 8px 0; color: #8B95A8;">Return Date</td><td style="padding: 8px 0;">{return_date or now_et.split(" at")[0]}</td></tr>'

    rows += f'<tr><td style="padding: 8px 0; color: #8B95A8;">Rep</td><td style="padding: 8px 0;">{rep}</td></tr>'

    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
      <div style="background: {m['gradient']}; padding: 16px 24px; border-radius: 12px 12px 0 0;">
        <h2 style="color: white; margin: 0; font-size: 18px;">{m['icon']} {m['label']}</h2>
        <p style="color: rgba(255,255,255,0.85); margin: 4px 0 0; font-size: 13px;">{m['message']}</p>
      </div>
      <div style="background: #141A28; padding: 24px; border: 1px solid #1E293B; border-top: none; border-radius: 0 0 12px 12px;">
        <table style="width: 100%; border-collapse: collapse; color: #F0F2F5; font-size: 14px;">
          {rows}
        </table>
        <div style="margin-top: 20px; text-align: center;">
          <a href="{deep_link}" style="display: inline-block; background: #00D4AA; color: #0A0E17; padding: 10px 28px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 14px;">
            View in Dashboard
          </a>
        </div>
      </div>
      <p style="color: #64748B; font-size: 11px; margin-top: 12px; text-align: center;">
        CSLogix Dispatch &mdash; {now_et}
      </p>
    </div>
    """


def generate_milestone_draft(efj: str, new_status: str) -> int | None:
    """Generate an email draft for a milestone status change. Returns draft ID or None."""
    milestone_key = new_status.lower().replace(" ", "_")
    if milestone_key not in MILESTONES:
        return None

    # Dedup: skip if draft already exists for this EFJ + milestone
    try:
        with db.get_cursor() as cur:
            cur.execute(
                "SELECT id FROM email_drafts WHERE efj = %s AND milestone = %s AND status = 'draft'",
                (efj, milestone_key),
            )
            if cur.fetchone():
                log.info("Draft already exists for %s/%s — skipping", efj, milestone_key)
                return None
    except Exception:
        pass

    # Fetch shipment
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT * FROM shipments WHERE efj = %s", (efj,))
            row = cur.fetchone()
            if not row:
                log.warning("No shipment found for %s — skipping draft", efj)
                return None
            shipment = dict(row)
    except Exception as e:
        log.error("Failed to fetch shipment %s for draft: %s", efj, e)
        return None

    account = shipment.get("account", "")
    rep_info = ACCOUNT_REPS.get(account, {})
    to_email = rep_info.get("email", DISPATCH_EMAIL)
    m = MILESTONES[milestone_key]
    container = shipment.get("container", "") or shipment.get("bol", "") or efj

    subject = f"CSL — {m['label']}: {container} — {account}"
    body_html = _build_email_html(shipment, milestone_key)

    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    INSERT INTO email_drafts (efj, account, milestone, to_email, cc_email, subject, body_html)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (efj, account, milestone_key, to_email, DISPATCH_EMAIL, subject, body_html))
                draft_id = cur.fetchone()["id"]
                log.info("Email draft #%d created for %s → %s (%s)", draft_id, efj, milestone_key, to_email)
                return draft_id
    except Exception as e:
        log.error("Failed to create email draft for %s: %s", efj, e)
        return None


# ── API Endpoints ──


@router.get("/api/email-drafts")
async def list_email_drafts(request: Request, status: str = "draft"):
    """List email drafts, optionally filtered by status."""
    try:
        with db.get_cursor() as cur:
            cur.execute("""
                SELECT id, efj, account, milestone, to_email, cc_email, subject, status, created_at, sent_at, sent_by
                FROM email_drafts
                WHERE status = %s
                ORDER BY created_at DESC
                LIMIT 50
            """, (status,))
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        log.exception("list_email_drafts error")
        raise HTTPException(500, str(e))


@router.get("/api/email-drafts/{draft_id}")
async def get_email_draft(draft_id: int):
    """Get a single email draft with full HTML body."""
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT * FROM email_drafts WHERE id = %s", (draft_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Draft not found")
            return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.patch("/api/email-drafts/{draft_id}")
async def update_email_draft(draft_id: int, request: Request):
    """Edit a draft (subject, body_html, to_email, cc_email)."""
    body = await request.json()
    allowed = {"subject", "body_html", "to_email", "cc_email"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields to update")

    sets = ", ".join(f"{k} = %({k})s" for k in updates)
    updates["id"] = draft_id
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute(f"UPDATE email_drafts SET {sets} WHERE id = %(id)s AND status = 'draft' RETURNING id", updates)
                if not cur.fetchone():
                    raise HTTPException(404, "Draft not found or already sent")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/email-drafts/{draft_id}/send")
async def send_email_draft(draft_id: int, request: Request):
    """Send an email draft via SMTP and mark as sent."""
    if not SMTP_USER or not SMTP_PASSWORD:
        raise HTTPException(500, "SMTP credentials not configured")

    # Get current user for sent_by
    sent_by = "system"
    if hasattr(request.state, "user") and request.state.user:
        sent_by = request.state.user.get("rep_name", request.state.user.get("username", "system"))

    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT * FROM email_drafts WHERE id = %s AND status = 'draft'", (draft_id,))
            draft = cur.fetchone()
            if not draft:
                raise HTTPException(404, "Draft not found or already sent")
            draft = dict(draft)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

    # Send via SMTP
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = draft["subject"]
        msg["From"] = SMTP_USER
        msg["To"] = draft["to_email"]
        if draft.get("cc_email"):
            msg["Cc"] = draft["cc_email"]
        msg.attach(MIMEText(draft["body_html"], "html"))

        recipients = [draft["to_email"]]
        if draft.get("cc_email"):
            recipients.extend([e.strip() for e in draft["cc_email"].split(",") if e.strip()])

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_USER, recipients, msg.as_string())

        log.info("Email draft #%d sent for %s → %s", draft_id, draft["efj"], draft["to_email"])
    except Exception as e:
        log.error("Failed to send email draft #%d: %s", draft_id, e)
        raise HTTPException(500, f"SMTP send failed: {e}")

    # Mark as sent
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute(
                    "UPDATE email_drafts SET status = 'sent', sent_at = NOW(), sent_by = %s WHERE id = %s",
                    (sent_by, draft_id),
                )
    except Exception as e:
        log.warning("Draft #%d was sent but DB update failed: %s", draft_id, e)

    return {"ok": True, "message": f"Email sent to {draft['to_email']}"}


@router.post("/api/email-drafts/{draft_id}/dismiss")
async def dismiss_email_draft(draft_id: int):
    """Dismiss a draft (don't send)."""
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("UPDATE email_drafts SET status = 'dismissed' WHERE id = %s AND status = 'draft' RETURNING id", (draft_id,))
                if not cur.fetchone():
                    raise HTTPException(404, "Draft not found or already processed")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
