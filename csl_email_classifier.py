"""
CSL Email Classifier — Smart email classification + rate extraction + 15-min reply alerts.

Standalone module imported by csl_inbox_scanner.py. Handles:
  - Carrier vs customer email classification by sender + content patterns
  - Lane detection (City, ST -> City, ST)
  - Rate extraction from carrier emails -> rate_quotes table
  - 15-min unreplied customer email alert -> SMTP to assigned rep
"""
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from csl_logging import get_logger

log = get_logger("csl-inbox")

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_CC = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")

REP_EMAILS = {
    "Radka": "radka@evansdelivery.com",
    "John F": "john.feltz@commonsenselogistics.com",
    "Janice": "janice@evansdelivery.com",
}

ACCOUNT_REP_MAP = {
    "DSV": "John F", "EShipping": "John F", "Kishco": "John F", "MAO": "John F", "Rose": "John F",
    "Allround": "Radka", "Cadi": "Radka", "IWS": "Radka", "Kripke": "Radka",
    "MGF": "Radka", "Meiko": "Radka", "Sutton": "Radka", "Tanera": "Radka",
    "TCR": "Radka", "Texas International": "Radka", "USHA": "Radka",
    "DHL": "John F", "Mamata": "John F", "SEI Acquisition": "John F",
    "CNL": "Janice",
    "Boviet": "John F", "Tolead": "John F",
}

# ═══════════════════════════════════════════════════════════════
# CLASSIFICATION PATTERNS
# ═══════════════════════════════════════════════════════════════

CSL_TEAM_SENDERS = re.compile(
    r"commonsenselogistics\.com|evansdelivery\.com|cslogi",
    re.IGNORECASE,
)

KNOWN_CUSTOMER_SENDERS = re.compile(
    r"dsv\.com|dhl\.com|kripke|allround|cadi|iwsgroup|maoinc|maogroup|eshipping"
    r"|mgfusa|rose.?int|boviet|tolead|mamata|sutton|tanera|meiko|kishco"
    r"|sei.?acq|cnl|manitoulin|tcr|texas.?int|md.?metal|usha",
    re.IGNORECASE,
)



KNOWN_CARRIER_SENDERS = re.compile(
    r"xpo\.com|jbhunt|schneider|knight.?trans|werner\.com|heartland"
    r"|usxpress|saia\.com|estes|odfl\.com|landstar|echo\.com|coyote"
    r"|ch\.?robinson|ryder\.com|penske|averitt|roadrunner"
    r"|@.*(?:trucking|transport|freight|drayage|cartage|dispatch|hauling)\.com",
    re.IGNORECASE,
)

CUSTOMER_QUOTE_LANGUAGE = re.compile(
    # Polite rate request verbs (broader match)
    r"(can\s+I|may\s+I|could\s+(you|we)|please)\s+(get|have|receive|send|quote|provide).*(quote|rate|pricing|estimate)"
    r"|please\s+(send|provide|quote).*(?:rate|quote|dray|pricing|trucking|crossdock|inland)"
    r"|quote\s+(your\s+best|us|me|the\s+below|below|attached|following)"
    # Container sizes (20/40/45/53ft + HC/GP/ST variants)
    r"|(20|40|45|53)\s*(?:ft|foot|'|hc|gp|st|ot|fr|rf)"
    r"|\d+\s*[x\xd7]\s*(?:20|40|45|53)\s*(?:'|ft|hc|gp|st|ot|fr|rf)?"
    # Port / ramp / intermodal references
    r"|port\s+of|rail\s+ramp|intermodal\s+ramp"
    r"|memphis.*rail|savannah.*port|norfolk|newark|los\s+angeles.*port"
    # Service types that indicate a quote request
    r"|(?:send|need|quote).*(?:dray|cross.?dock|transload|stripping|trucking)"
    r"|(?:dray|cross.?dock|transload|stripping).*(?:quote|rate|pricing)"
    r"|inland\s+rate|dray.*(?:and|\+|,)\s*(?:cross.?dock|delivery|trucking)"
    # OOG / specialty equipment
    r"|flat\s*rack|open\s*top|step\s*deck|flatrack|(?:40|20)\s*(?:'\s*)?(?:fr|ot|rf)"
    r"|over.?(?:weight|dimension|height|width|size|gauge)|out\s*of\s*gauge|OOG"
    # Cargo dimensions/weight (strong RFQ signal)
    r"|\d{2,4}\s*(?:cm|mm|in|kg|lbs|kgs)\s*[x\xd7*]\s*\d{2,4}\s*(?:cm|mm|in|kg|lbs|kgs)?"
    r"|gross\s+weight\s+\d|(?:\d[.,]\d{3})\s*(?:kg|lb|kgs|lbs)"
    # Hazmat in quote context
    r"|(?:IMO|hazmat|haz.?mat|DG\s+cargo|dangerous\s+goods|UN\s*\d{4}).*(?:quote|rate|dray|container|trucking)"
    r"|(?:quote|rate|dray|container|trucking).*(?:IMO|hazmat|haz.?mat|DG\s+cargo)"
    r"|\d+\s*(?:'|ft|hc)?\s*IMO",
    re.IGNORECASE,
)



CARRIER_RATE_LANGUAGE = re.compile(
    r"MC[#\s-]?\d{4,7}"
    r"|rate\s+per\s+mile|\$\d+(\.\d{2})?\s*/\s*mi"
    r"|available.*truck|have\s+(a\s+)?truck|can\s+cover"
    r"|deadhead|all\s+in\s+rate|\d+\s*(rpm|cpm)"
    r"|team\s+rate|solo\s+rate|flat\s*bed|dry\s*van|reefer"
    r"|load\s+details|load\s+info|interested\s+in.*load",
    re.IGNORECASE,
)

LANE_PATTERN = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,?\s*[A-Z]{2})\s*(?:to|\u2192|->|-)\s*"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,?\s*[A-Z]{2})"
    r"(?:.*?(\d{2,4})\s*mi)?",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════
# CLASSIFICATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def classify_email_type(sender, subject, body):
    """
    Classify the email as carrier_rate / customer_rate by sender, MC#, lane, content.
    Returns (email_type, lane) or (None, None).
    """
    if CSL_TEAM_SENDERS.search(sender):
        return None, None

    text = f"{subject} {body}"

    # Extract lane if present
    lane_match = LANE_PATTERN.search(subject) or LANE_PATTERN.search(body or "")
    lane = None
    if lane_match:
        origin_city = lane_match.group(1).strip()
        dest_city = lane_match.group(2).strip()
        miles = lane_match.group(3)
        lane = f"{origin_city} \u2192 {dest_city}"
        if miles:
            lane += f" ({miles} mi)"

    # Carrier detection scoring
    carrier_signals = 0
    if KNOWN_CARRIER_SENDERS.search(sender):
        carrier_signals += 2
    if re.search(r"MC[#\s-]?\d{4,7}", text):
        carrier_signals += 2
    if re.search(r"transport|trucking|freight|hauling", sender, re.IGNORECASE):
        carrier_signals += 1
    if LANE_PATTERN.search(subject):
        carrier_signals += 1
    if CARRIER_RATE_LANGUAGE.search(text):
        carrier_signals += 1
    if carrier_signals >= 2:
        return "carrier_rate", lane

    # Customer detection
    if KNOWN_CUSTOMER_SENDERS.search(sender):
        return "customer_rate", lane
    if CUSTOMER_QUOTE_LANGUAGE.search(text):
        return "customer_rate", lane

    return None, None


def classify_rate_doc(filename, sender, subject, body):
    """
    For rate-related filenames, determine carrier_rate vs customer_rate vs unclassified.
    Returns doc_type string.
    """
    if not re.search(r"rate.?con|rate.?confirm|quote", filename, re.IGNORECASE):
        return None  # not a rate doc

    if KNOWN_CARRIER_SENDERS.search(sender):
        return "carrier_rate"
    if KNOWN_CUSTOMER_SENDERS.search(sender):
        return "customer_rate"

    text = f"{subject} {body}"
    if CARRIER_RATE_LANGUAGE.search(text):
        return "carrier_rate"
    if CUSTOMER_QUOTE_LANGUAGE.search(text):
        return "customer_rate"

    return "unclassified"


def extract_rate_from_email(subject, body, sender, lane, email_type):
    """
    Extract rate data from carrier email using AI (Haiku) with regex fallback.
    Returns dict with rate_amount, rate_unit, move_type, origin, dest, miles.
    """
    if email_type != "carrier_rate":
        return None

    text = f"{subject} {body[:1500]}"
    sender_name = sender.split("<")[0].strip().strip('"') if "<" in sender else sender
    carrier_email = sender.split("<")[-1].replace(">", "").strip() if "<" in sender else sender

    # AI extraction first
    result = _ai_extract_rate(subject, body[:1200], sender_name)

    # Regex fallback for missing fields
    if not result.get("rate_amount"):
        m = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
        if m:
            try:
                result["rate_amount"] = float(m.group(1).replace(",", ""))
            except ValueError:
                pass

    if not result.get("rate_unit"):
        result["rate_unit"] = "per_mile" if re.search(r"/\s*mi|per\s+mile|rpm|cpm", text, re.IGNORECASE) else "flat"

    if not result.get("move_type"):
        if re.search(r"(20|40)\s*(?:ft|foot|'|hc|gp|st)|drayage|chassis|port|rail\s+ramp", text, re.IGNORECASE):
            result["move_type"] = "dray"
        elif re.search(r"ltl|less.than.truck|pallet|cwt", text, re.IGNORECASE):
            result["move_type"] = "ltl"
        else:
            result["move_type"] = "ftl"

    if not result.get("origin") and not result.get("destination"):
        lm = LANE_PATTERN.search(subject) or LANE_PATTERN.search(body or "")
        if lm:
            result["origin"] = lm.group(1).strip()
            result["destination"] = lm.group(2).strip()
            if lm.group(3):
                try:
                    result["miles"] = int(lm.group(3))
                except ValueError:
                    pass

    result["carrier_name"] = result.get("carrier_name") or sender_name
    result["carrier_email"] = carrier_email
    return result if result.get("rate_amount") or result.get("origin") else None


def _ai_extract_rate(subject, body, sender_name):
    """Use Claude Haiku to extract rate fields from a carrier email. Returns dict."""
    import json, os
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        env_path = "/root/csl-bot/.env"
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        return {}
    prompt = f"""Extract freight rate data from this carrier email. Return ONLY valid JSON.

FROM: {sender_name}
SUBJECT: {subject}
BODY: {body}

{{
  "rate_amount": <flat dollar amount as number, null if not found>,
  "rate_unit": "<flat or per_mile>",
  "move_type": "<dray or ftl or ltl>",
  "origin": "<origin city/port or null>",
  "destination": "<destination city/state or null>",
  "miles": <integer or null>,
  "carrier_name": "<company name from signature or null>"
}}

rate_amount = all-in or linehaul flat rate. If per-mile rate, set rate_unit=per_mile.
move_type=dray if mentions port/chassis/drayage/container."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
        out = {}
        if data.get("rate_amount") is not None:
            try:
                out["rate_amount"] = float(data["rate_amount"])
            except (TypeError, ValueError):
                pass
        for f in ("rate_unit", "move_type", "origin", "destination", "carrier_name"):
            if data.get(f):
                out[f] = str(data[f]).strip()
        if data.get("miles"):
            try:
                out["miles"] = int(data["miles"])
            except (TypeError, ValueError):
                pass
        return out
    except Exception as e:
        log.debug("AI rate extraction failed: %s", e)
        return {}

def save_rate_quote(get_conn_fn, put_conn_fn, email_thread_id, efj, lane, rate_data, sent_at):
    """Save extracted rate quote to rate_quotes table."""
    if not rate_data:
        return
    conn = get_conn_fn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO rate_quotes
                    (email_thread_id, efj, lane, origin, destination, miles,
                     move_type, carrier_name, carrier_email,
                     rate_amount, rate_unit, quote_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (
                email_thread_id, efj, lane,
                rate_data.get("origin"), rate_data.get("destination"),
                rate_data.get("miles"),
                rate_data.get("move_type", "ftl"),
                rate_data.get("carrier_name"),
                rate_data.get("carrier_email"),
                rate_data.get("rate_amount"),
                rate_data.get("rate_unit", "flat"),
                sent_at,
            ))
        conn.commit()
        log.info("  Rate quote saved: %s %s -> %s",
                 rate_data.get("carrier_name", "?"),
                 f"${rate_data['rate_amount']}" if rate_data.get("rate_amount") else "no $",
                 lane or "unknown lane")
    except Exception as e:
        conn.rollback()
        log.error("  rate_quotes insert failed: %s", e)
    finally:
        put_conn_fn(conn)


def ensure_classifier_tables(conn):
    """Create/migrate tables needed for email classification + Rate IQ."""
    with conn.cursor() as cur:
        # Add email_type and lane columns to existing tables
        for table in ["email_threads", "unmatched_inbox_emails"]:
            for col, ctype in [("email_type", "TEXT"), ("lane", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ctype}")
                    log.info(f"Added {col} to {table}")
                except Exception:
                    conn.rollback()

        # Rate quotes table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rate_quotes (
                id              SERIAL PRIMARY KEY,
                email_thread_id INTEGER,
                efj             TEXT,
                lane            TEXT,
                origin          TEXT,
                destination     TEXT,
                miles           INTEGER,
                move_type       TEXT DEFAULT 'ftl',
                carrier_name    TEXT,
                carrier_email   TEXT,
                rate_amount     DECIMAL(10,2),
                rate_unit       TEXT DEFAULT 'flat',
                quote_date      TIMESTAMP WITH TIME ZONE,
                indexed_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                status          TEXT DEFAULT 'pending'
            );
            CREATE INDEX IF NOT EXISTS idx_rate_quotes_lane ON rate_quotes(lane);
            CREATE INDEX IF NOT EXISTS idx_rate_quotes_efj ON rate_quotes(efj);
        """)

        # Customer reply alerts
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customer_reply_alerts (
                id              SERIAL PRIMARY KEY,
                email_thread_id INTEGER,
                efj             TEXT,
                sender          TEXT,
                subject         TEXT,
                alerted_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                dismissed       BOOLEAN DEFAULT FALSE
            );
        """)
    conn.commit()
    log.info("Classifier tables ensured")


# ═══════════════════════════════════════════════════════════════
# 15-MIN REPLY ALERTS
# ═══════════════════════════════════════════════════════════════

def _send_alert_email(to_email, subject, body_html):
    """Send an alert email via SMTP."""
    if not SMTP_USER or not SMTP_PASSWORD:
        log.warning("SMTP not configured -- skipping alert email")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = SMTP_USER
        msg["To"] = to_email
        msg["Cc"] = EMAIL_CC
        msg["Subject"] = subject
        msg.attach(MIMEText(body_html, "html"))
        recipients = [to_email]
        if EMAIL_CC:
            recipients.append(EMAIL_CC)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_USER, recipients, msg.as_string())
        log.info("Alert email sent to %s: %s", to_email, subject)
    except Exception as e:
        log.error("Failed to send alert email to %s: %s", to_email, e)


def _get_rep_email_for_efj(get_conn_fn, put_conn_fn, efj):
    """Look up the rep email for an EFJ."""
    from psycopg2.extras import RealDictCursor
    if not efj:
        return REP_EMAILS.get("John F", EMAIL_CC)
    conn = get_conn_fn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT sender FROM email_threads WHERE efj = %s AND email_type = 'customer_rate' LIMIT 1",
                (efj,),
            )
            row = cur.fetchone()
            if row:
                sender = (row["sender"] or "").lower()
                for account, rep in ACCOUNT_REP_MAP.items():
                    if account.lower().replace(" ", "") in sender:
                        return REP_EMAILS.get(rep, EMAIL_CC)
    finally:
        put_conn_fn(conn)
    return REP_EMAILS.get("John F", EMAIL_CC)


def check_unreplied_customer_emails(get_conn_fn, put_conn_fn):
    """
    Check for customer quote emails unreplied for 15+ min.
    Insert alert + send email to assigned rep.
    """
    from psycopg2.extras import RealDictCursor
    conn = get_conn_fn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT et.id, et.efj, et.sender, et.subject, et.lane, et.sent_at
                FROM email_threads et
                WHERE et.email_type = 'customer_rate'
                  AND et.sent_at < NOW() - INTERVAL '15 minutes'
                  AND NOT EXISTS (
                    SELECT 1 FROM email_threads reply
                    WHERE reply.gmail_thread_id = et.gmail_thread_id
                      AND (reply.sender ILIKE '%%commonsenselogistics%%'
                           OR reply.sender ILIKE '%%evansdelivery%%')
                      AND reply.sent_at > et.sent_at
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM customer_reply_alerts cra
                    WHERE cra.email_thread_id = et.id
                  )
                LIMIT 10
            """)
            unreplied = cur.fetchall()

            for email in unreplied:
                cur.execute("""
                    INSERT INTO customer_reply_alerts (email_thread_id, efj, sender, subject)
                    VALUES (%s, %s, %s, %s)
                """, (email["id"], email["efj"], email["sender"], email["subject"]))
                log.info("UNREPLIED ALERT: %s [%s] from %s -- no reply for 15+ min",
                         email["efj"], email["subject"][:50], email["sender"][:40])

                rep_email = _get_rep_email_for_efj(get_conn_fn, put_conn_fn, email["efj"])
                lane_info = f" | Lane: {email['lane']}" if email.get("lane") else ""
                efj_display = email["efj"] or "No EFJ"
                lane_display = email.get("lane") or "N/A"
                _send_alert_email(
                    rep_email,
                    f"CSL Alert: No reply to customer quote -- {efj_display}{lane_info}",
                    f'<div style="font-family:Arial,sans-serif;max-width:600px">'
                    f'<h3 style="color:#F59E0B;margin:0 0 12px 0">Customer Quote -- No Reply for 15+ Minutes</h3>'
                    f'<table style="border-collapse:collapse;width:100%">'
                    f'<tr><td style="padding:6px 12px;font-weight:bold;color:#555">EFJ</td>'
                    f'<td style="padding:6px 12px">{efj_display}</td></tr>'
                    f'<tr><td style="padding:6px 12px;font-weight:bold;color:#555">From</td>'
                    f'<td style="padding:6px 12px">{email["sender"]}</td></tr>'
                    f'<tr><td style="padding:6px 12px;font-weight:bold;color:#555">Subject</td>'
                    f'<td style="padding:6px 12px">{email["subject"]}</td></tr>'
                    f'<tr><td style="padding:6px 12px;font-weight:bold;color:#555">Lane</td>'
                    f'<td style="padding:6px 12px">{lane_display}</td></tr>'
                    f'<tr><td style="padding:6px 12px;font-weight:bold;color:#555">Received</td>'
                    f'<td style="padding:6px 12px">{email["sent_at"]}</td></tr>'
                    f'</table>'
                    f'<p style="color:#888;font-size:12px;margin-top:16px">'
                    f'This customer has been waiting 15+ minutes. Please reply ASAP.</p>'
                    f'<p style="margin-top:12px"><a href="https://cslogixdispatch.com/app" '
                    f'style="color:#3B82F6">Open Dashboard</a></p></div>',
                )

        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error("Unreplied check failed: %s", e)
    finally:
        put_conn_fn(conn)



# ── AI Email Classification (Claude Haiku) ──────────────────────────

def ai_classify_email(sender, subject, body_preview, attachment_names=""):
    """
    Use Claude Haiku to classify an email with type, priority, and summary.
    Returns dict with: type, priority (1-5), suggested_rep, summary.
    Falls back to empty dict on error.
    """
    import json, os

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        env_path = "/root/csl-bot/.env"
        if os.path.exists(env_path):
            with open(env_path) as ef:
                for line in ef:
                    if line.startswith("ANTHROPIC_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not api_key:
        return {}

    prompt = f"""Classify this logistics email for a freight broker (Evans Delivery / CSL).

FROM: {sender}
SUBJECT: {subject}
BODY: {body_preview[:800]}
ATTACHMENTS: {attachment_names or "none"}

Respond with ONLY valid JSON (no markdown, no extra text):
{{
  "type": "<one of: carrier_rate, customer_rate, pod, bol, appointment, detention, delivery_update, tracking_update, invoice, general>",
  "priority": <1-5>,
  "suggested_rep": "<rep name if identifiable from content, otherwise null>",
  "summary": "<one-line operational summary, max 80 chars>"
}}

CUSTOMER_RATE indicators (classify as customer_rate, priority 4):
- Customer/broker asking for dray, trucking, crossdock, transload, or inland rates
- Container quantities (3x40HC, 1x20'STD), cargo dimensions/weights
- OOG/specialty: flat rack, open top, step deck, overweight, hazmat/IMO
- Service combos: "dray + crossdock + delivery", "stripping and trucking"
- Port/ramp/intermodal references with quote language
- Incoterms (FCA, FOB, CIF), commodity descriptions
- "Please send rates", "can you quote", "need pricing for"

CARRIER_RATE indicators (classify as carrier_rate):
- MC#, truck availability, per-mile rates, "can cover", "have a truck"
- Carrier domains offering capacity or responding to load posts

Priority scale:
5 = CRITICAL: detention/demurrage charges, customs hold, delivery failure, cargo damage
4 = HIGH: rate quotes needing response (BOTH customer and carrier), appointment changes, ETA changes, missing docs
3 = NORMAL: routine updates, standard confirmations, POD received
2 = LOW: informational, FYI, carrier newsletters
1 = NOISE: marketing, spam, auto-replies, out-of-office"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        result["priority"] = max(1, min(5, int(result.get("priority", 3))))
        result["type"] = result.get("type", "general")
        result["summary"] = (result.get("summary") or "")[:120]
        result["suggested_rep"] = result.get("suggested_rep") or None
        return result
    except Exception as e:
        log.warning("AI classify failed: %s", e)
        return {}
