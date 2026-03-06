#!/usr/bin/env python3
"""
CSL Inbox Scanner — reads john.feltz@commonsenselogistics.com via Gmail API,
matches emails to loads by EFJ#/container#, extracts attachments, and indexes
everything in the dashboard database.

Runs as a systemd service (csl-inbox), polling every 5 minutes.
"""

import os
import re
import sys
import time
import json
import uuid
import base64
import logging
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import csl_email_classifier as classifier
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import httplib2
from google_auth_httplib2 import AuthorizedHttp

from dotenv import load_dotenv

# ── Load env ──
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), "csl-doc-tracker", ".env"))

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("csl_inbox_scanner")

# ── Config ──
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "csl_gmail_token.json")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]
SCAN_INTERVAL = int(os.getenv("INBOX_SCAN_INTERVAL", "300"))  # 5 min default
MAX_MESSAGES_PER_SCAN = 50
UPLOAD_DIR = "/root/csl-bot/csl-doc-tracker/uploads"

# DB config
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "csl_doc_tracker"),
    "user": os.getenv("DB_USER", "csl_admin"),
    "password": os.getenv("DB_PASSWORD", "changeme"),
}

# SMTP config for alert emails
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_CC = os.getenv("EMAIL_CC", "efj-operations@evansdelivery.com")

# Rep → email mapping (matches Account Rep tab in Google Sheet)
REP_EMAILS = {
    "Eli": "eli@evansdelivery.com",
    "Radka": "radka@evansdelivery.com",
    "John F": "john.feltz@commonsenselogistics.com",
    "Janice": "janice@evansdelivery.com",
}
# Account → rep mapping (mirrors frontend REP_ACCOUNTS)
ACCOUNT_REP_MAP = {
    "DSV": "Eli", "EShipping": "Eli", "Kishco": "Eli", "MAO": "Eli", "Rose": "Eli",
    "Allround": "Radka", "Cadi": "Radka", "IWS": "Radka", "Kripke": "Radka",
    "MGF": "Radka", "Meiko": "Radka", "Sutton": "Radka", "Tanera": "Radka",
    "TCR": "Radka", "Texas International": "Radka", "USHA": "Radka",
    "DHL": "John F", "Mamata": "John F", "SEI Acquisition": "John F",
    "CNL": "Janice",
    "Boviet": "John F", "Tolead": "John F",
}

# Attachment types to download
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif",
    ".xlsx", ".xls", ".csv", ".doc", ".docx", ".eml", ".msg",
}

# EFJ# pattern: "EFJ" optionally followed by space/dash, then 5-6 digits
EFJ_PATTERN = re.compile(r"EFJ[\s\-]?(\d{5,6})", re.IGNORECASE)
# Container# pattern: 4 uppercase letters + 7 digits
CONTAINER_PATTERN = re.compile(r"\b([A-Z]{4}\d{7})\b")
# BOL/Booking pattern
BOL_PATTERN = re.compile(r"\b(\d{9,12})\b")

# Doc type classification by filename (rate handled in classify_doc_type)
DOC_CLASSIFIERS = [
    (re.compile(r"bol|bill.of.lading|b/l", re.IGNORECASE), "bol"),
    (re.compile(r"pod|proof.of.delivery|delivery.receipt", re.IGNORECASE), "pod"),
    (re.compile(r"invoice|inv\b", re.IGNORECASE), "invoice"),
    (re.compile(r"screenshot|screen.?shot|snap", re.IGNORECASE), "screenshot"),
]

# Senders that indicate carrier invoices
CARRIER_PAY_SENDERS = re.compile(
    r"carrier.?pay|carrierpay|carrier.?support|freight.?pay|comcheck|triumph|rts|efs|wex",
    re.IGNORECASE,
)

# ── Smart Quote Classification Patterns ──

# CSL team senders (outgoing emails — skip classification)
CSL_TEAM_SENDERS = re.compile(
    r"commonsenselogistics\.com|evansdelivery\.com|cslogi",
    re.IGNORECASE,
)

# Known customer/broker domains
KNOWN_CUSTOMER_SENDERS = re.compile(
    r"dsv\.com|dhl\.com|kripke|allround|cadi|iwsgroup|maogroup|eshipping"
    r"|mgfusa|rose.?int|boviet|tolead|mamata|sutton|tanera|meiko|kishco"
    r"|sei.?acq|cnl",
    re.IGNORECASE,
)

# Known carrier/trucking company patterns
KNOWN_CARRIER_SENDERS = re.compile(
    r"xpo\.com|jbhunt|schneider|knight.?trans|werner\.com|heartland"
    r"|usxpress|saia\.com|estes|odfl\.com|landstar|echo\.com|coyote"
    r"|ch\.?robinson|ryder\.com|penske|averitt|roadrunner"
    r"|@.*(?:trucking|transport|freight|drayage|cartage|dispatch|hauling)\.com",
    re.IGNORECASE,
)

# Customer drayage quote request language
CUSTOMER_QUOTE_LANGUAGE = re.compile(
    r"(can\s+I|may\s+I|could\s+(you|we)|please)\s+(get|have|receive|send).*(quote|rate|pricing)"
    r"|quote.*(below|attached|following)"
    r"|(20|40)\s*(?:ft|foot|'|hc|gp|st)"
    r"|port\s+of|rail\s+ramp|intermodal\s+ramp|chassis"
    r"|memphis.*rail|savannah.*port|norfolk|newark|los\s+angeles.*port",
    re.IGNORECASE,
)

# Carrier rate response language (FTL)
CARRIER_RATE_LANGUAGE = re.compile(
    r"MC[#\s-]?\d{4,7}"
    r"|rate\s+per\s+mile|\$\d+(\.\d{2})?\s*/\s*mi"
    r"|available.*truck|have\s+(a\s+)?truck|can\s+cover"
    r"|deadhead|all\s+in\s+rate|\d+\s*(rpm|cpm)"
    r"|team\s+rate|solo\s+rate|flat\s*bed|dry\s*van|reefer"
    r"|load\s+details|load\s+info|interested\s+in.*load",
    re.IGNORECASE,
)

# Lane pattern: "City, ST to City, ST" with optional miles
LANE_PATTERN = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,?\s*[A-Z]{2})\s*(?:to|→|->|-)\s*"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,?\s*[A-Z]{2})"
    r"(?:.*?(\d{2,4})\s*mi)?",
    re.IGNORECASE,
)

# ── Tag-based classification (for forwarded emails with explicit tags) ──
TAG_PATTERN = re.compile(
    r"\[(CARRIER\s+RATE|CUSTOMER\s+RATE|POD|BOL|WAREHOUSE\s+RATE|CARRIER\s+INFO)\]",
    re.IGNORECASE,
)
TAG_TO_EMAIL_TYPE = {
    "carrier rate": "carrier_rate",
    "customer rate": "customer_rate",
    "pod": "pod",
    "bol": "bol",
    "warehouse rate": "warehouse_rate",
    "carrier info": "carrier_info",
}
TAG_TO_DOC_TYPE = {
    "carrier rate": "carrier_rate",
    "customer rate": "customer_rate",
    "pod": "pod",
    "bol": "bol",
    "warehouse rate": "other",
    "carrier info": "other",
}
FW_PREFIX = re.compile(r"^(?:FW|Fwd)\s*:\s*", re.IGNORECASE)
ORIGINAL_FROM = re.compile(r"From:\s*(.+?)(?:\n|$)", re.IGNORECASE)

# ── DB Pool ──
_pool = None


def init_pool():
    global _pool
    _pool = ThreadedConnectionPool(minconn=1, maxconn=5, **DB_CONFIG)
    log.info("DB pool initialized")


def get_conn():
    return _pool.getconn()


def put_conn(conn):
    _pool.putconn(conn)


def ensure_tables():
    """Create email_threads table if it doesn't exist."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_threads (
                    id              SERIAL PRIMARY KEY,
                    efj             TEXT NOT NULL,
                    gmail_thread_id TEXT,
                    gmail_message_id TEXT,
                    message_id      TEXT,
                    subject         TEXT,
                    sender          TEXT,
                    recipients      TEXT,
                    body_preview    TEXT,
                    has_attachments BOOLEAN DEFAULT FALSE,
                    attachment_names TEXT,
                    sent_at         TIMESTAMP WITH TIME ZONE,
                    indexed_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    email_type      TEXT,
                    lane            TEXT,
                    UNIQUE(gmail_message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_email_threads_efj
                    ON email_threads(efj);
                CREATE INDEX IF NOT EXISTS idx_email_threads_efj_sent
                    ON email_threads(efj, sent_at DESC);
            """)
            # Add email_type and lane columns if they don't exist
            for col, ctype in [("email_type", "TEXT"), ("lane", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE email_threads ADD COLUMN {col} {ctype}")
                except Exception:
                    conn.rollback()
            # Also ensure unmatched_inbox_emails table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS unmatched_inbox_emails (
                    id              SERIAL PRIMARY KEY,
                    gmail_message_id TEXT UNIQUE,
                    gmail_thread_id TEXT,
                    subject         TEXT,
                    sender          TEXT,
                    recipients      TEXT,
                    body_preview    TEXT,
                    has_attachments BOOLEAN DEFAULT FALSE,
                    attachment_names TEXT,
                    sent_at         TIMESTAMP WITH TIME ZONE,
                    indexed_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    review_status   TEXT DEFAULT 'pending',
                    assigned_efj    TEXT,
                    email_type      TEXT,
                    lane            TEXT
                );
            """)
            # Add email_type and lane columns if they don't exist
            for col, ctype in [("email_type", "TEXT"), ("lane", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE unmatched_inbox_emails ADD COLUMN {col} {ctype}")
                except Exception:
                    conn.rollback()
            # Rate quotes table for Rate IQ comparison
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
                CREATE INDEX IF NOT EXISTS idx_rate_quotes_lane
                    ON rate_quotes(lane);
                CREATE INDEX IF NOT EXISTS idx_rate_quotes_efj
                    ON rate_quotes(efj);
            """)
            # Customer reply alerts for 15-min follow-up
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
            # Carrier directory (also created by app.py startup)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS carriers (
                    id              SERIAL PRIMARY KEY,
                    carrier_name    VARCHAR(256) NOT NULL,
                    mc_number       VARCHAR(32),
                    dot_number      VARCHAR(32),
                    contact_email   VARCHAR(256),
                    contact_phone   VARCHAR(64),
                    contact_name    VARCHAR(256),
                    regions         TEXT,
                    ports           TEXT,
                    rail_ramps      TEXT,
                    equipment_types TEXT,
                    notes           TEXT,
                    source          VARCHAR(32) DEFAULT 'manual',
                    created_at      TIMESTAMPTZ DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # Warehouse directory + rates (also created by app.py startup)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS warehouses (
                    id              SERIAL PRIMARY KEY,
                    name            VARCHAR(256) NOT NULL,
                    mc_number       VARCHAR(32),
                    region          VARCHAR(64),
                    address         TEXT,
                    city            VARCHAR(128),
                    state           VARCHAR(4),
                    zip_code        VARCHAR(12),
                    contact_name    VARCHAR(256),
                    contact_email   VARCHAR(256),
                    contact_phone   VARCHAR(64),
                    services        TEXT,
                    notes           TEXT,
                    source          VARCHAR(32) DEFAULT 'manual',
                    created_at      TIMESTAMPTZ DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS warehouse_rates (
                    id              SERIAL PRIMARY KEY,
                    warehouse_id    INTEGER REFERENCES warehouses(id) ON DELETE CASCADE,
                    rate_type       VARCHAR(64) NOT NULL,
                    rate_amount     DECIMAL(10,2),
                    unit            VARCHAR(32),
                    description     TEXT,
                    effective_date  DATE,
                    notes           TEXT,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                );
            """)
        conn.commit()
        log.info("Tables ready")
    except Exception as e:
        conn.rollback()
        log.error("Table creation failed: %s", e)
    finally:
        put_conn(conn)


# ── Gmail Auth ──
def get_gmail_service():
    """Build Gmail API client using saved OAuth token."""
    if not os.path.exists(TOKEN_PATH):
        log.error("No token file at %s — run csl_gmail_auth.py first", TOKEN_PATH)
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if creds.expired and creds.refresh_token:
        log.info("Refreshing expired token...")
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        log.info("Token refreshed")

    if not creds.valid:
        log.error("Token invalid and cannot refresh — re-run csl_gmail_auth.py")
        sys.exit(1)

    http = httplib2.Http(ca_certs="/etc/ssl/certs/ca-certificates.crt")
    authed_http = AuthorizedHttp(creds, http=http)
    service = build("gmail", "v1", http=authed_http)
    log.info("Gmail API connected")
    return service


# ── Reference Cache ──
_reference_cache = {}
_cache_time = 0
CACHE_TTL = 600  # 10 min


def load_reference_cache():
    """Load all known EFJ#/container# references from the database."""
    global _reference_cache, _cache_time
    if time.time() - _cache_time < CACHE_TTL and _reference_cache:
        return

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get all EFJ numbers from load_documents
            cur.execute("SELECT DISTINCT efj FROM load_documents")
            efjs = {row["efj"].upper() for row in cur.fetchall()}

            # Also get from email_threads
            cur.execute("SELECT DISTINCT efj FROM email_threads")
            efjs.update(row["efj"].upper() for row in cur.fetchall())

        _reference_cache = efjs
        _cache_time = time.time()
        log.info("Reference cache loaded: %d EFJ numbers", len(efjs))
    finally:
        put_conn(conn)


# ── Matching ──
def match_email_to_efj(subject, body, attachment_names=None):
    """
    Try to match an email to a load by EFJ#, container#, or BOL#.
    Returns the matched EFJ string or None.
    """
    text = f"{subject or ''} {body or ''} {' '.join(attachment_names or [])}"

    # Primary: EFJ# in text
    efj_matches = EFJ_PATTERN.findall(text)
    for num in efj_matches:
        efj = f"EFJ{num}"
        return efj  # Return first match

    # Secondary: container# lookup
    container_matches = CONTAINER_PATTERN.findall(text.upper())
    if container_matches:
        # Try to find container in sheet data via DB
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for container in container_matches:
                    # Search load_documents for this container in original_name
                    # or search the shipments cache
                    cur.execute(
                        "SELECT efj FROM email_threads WHERE body_preview ILIKE %s LIMIT 1",
                        (f"%{container}%",),
                    )
                    row = cur.fetchone()
                    if row:
                        return row["efj"]
        finally:
            put_conn(conn)

    return None


def classify_doc_type(filename, sender="", subject="", body=""):
    """Classify document type from filename, sender, subject, and body context."""
    # Tag override: if subject has an explicit tag, use it
    tag_match = TAG_PATTERN.search(subject)
    if tag_match:
        tag_key = tag_match.group(1).lower()
        mapped = TAG_TO_DOC_TYPE.get(tag_key)
        if mapped and mapped != "other":
            return mapped

    # Carrier invoice: sender is a carrier pay service
    if CARRIER_PAY_SENDERS.search(sender) or CARRIER_PAY_SENDERS.search(subject):
        if re.search(r"invoice|inv\b|receipt|payment|remit", filename, re.IGNORECASE):
            return "carrier_invoice"
        return "carrier_invoice"

    # Rate/quote document: determine carrier vs customer
    if re.search(r"rate.?con|rate.?confirm|quote", filename, re.IGNORECASE):
        # Step 1: Sender analysis
        if KNOWN_CARRIER_SENDERS.search(sender):
            return "carrier_rate"
        if KNOWN_CUSTOMER_SENDERS.search(sender):
            return "customer_rate"
        # Step 2: Content analysis (subject + body)
        text = f"{subject} {body}"
        if CARRIER_RATE_LANGUAGE.search(text):
            return "carrier_rate"
        if CUSTOMER_QUOTE_LANGUAGE.search(text):
            return "customer_rate"
        # Step 3: Can't determine — unclassified for manual review
        return "unclassified"

    for pattern, doc_type in DOC_CLASSIFIERS:
        if pattern.search(filename):
            return doc_type
    return "other"


def classify_email_type(sender, subject, body):
    """
    Classify the email itself (independent of attachments) as a carrier/customer
    quote based on sender signature, lane patterns, MC#, and content.
    Returns ('carrier_rate', lane_str) or ('customer_rate', lane_str) or (None, None).
    """
    # Tag override: explicit tags in subject line take priority
    tag_match = TAG_PATTERN.search(subject)
    if tag_match:
        tag_key = tag_match.group(1).lower()
        mapped = TAG_TO_EMAIL_TYPE.get(tag_key)
        if mapped:
            # Still extract lane if present
            lane_match = LANE_PATTERN.search(subject) or LANE_PATTERN.search(body or "")
            lane = None
            if lane_match:
                lane = f"{lane_match.group(1).strip()} → {lane_match.group(2).strip()}"
                if lane_match.group(3):
                    lane += f" ({lane_match.group(3)} mi)"
            return mapped, lane

    if CSL_TEAM_SENDERS.search(sender):
        return None, None  # outgoing — skip

    text = f"{subject} {body}"

    # Extract lane if present
    lane_match = LANE_PATTERN.search(subject) or LANE_PATTERN.search(body or "")
    lane = None
    if lane_match:
        origin_city = lane_match.group(1).strip()
        dest_city = lane_match.group(2).strip()
        miles = lane_match.group(3)
        lane = f"{origin_city} → {dest_city}"
        if miles:
            lane += f" ({miles} mi)"

    # Carrier detection: MC#, transport in sender, lane+miles, rate language
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


def extract_rate_from_email(subject, body, sender, lane, email_type):
    """
    Extract dollar rate and move type from carrier email for Rate IQ scoring.
    Returns dict with rate_amount, rate_unit, move_type, origin, dest, miles or None.
    """
    if email_type != "carrier_rate":
        return None

    text = f"{subject} {body}"
    result = {}

    # Extract dollar amount (e.g., "$1,850", "$2.50/mi", "$1850.00")
    rate_match = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
    if rate_match:
        try:
            result["rate_amount"] = float(rate_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Detect rate unit
    if re.search(r"/\s*mi|per\s+mile|rpm|cpm", text, re.IGNORECASE):
        result["rate_unit"] = "per_mile"
    else:
        result["rate_unit"] = "flat"

    # Detect move type
    if re.search(r"(20|40)\s*(?:ft|foot|'|hc|gp|st)|drayage|chassis|port|rail\s+ramp", text, re.IGNORECASE):
        result["move_type"] = "dray"
    elif re.search(r"ltl|less.than.truck|pallet|cwt", text, re.IGNORECASE):
        result["move_type"] = "ltl"
    else:
        result["move_type"] = "ftl"

    # Parse lane components
    lane_match = LANE_PATTERN.search(subject) or LANE_PATTERN.search(body or "")
    if lane_match:
        result["origin"] = lane_match.group(1).strip()
        result["destination"] = lane_match.group(2).strip()
        if lane_match.group(3):
            try:
                result["miles"] = int(lane_match.group(3))
            except ValueError:
                pass

    # Extract carrier name from sender
    sender_name = sender.split("<")[0].strip().strip('"') if "<" in sender else sender
    result["carrier_name"] = sender_name
    result["carrier_email"] = sender.split("<")[-1].replace(">", "").strip() if "<" in sender else sender

    return result if "rate_amount" in result or lane else result if result else None


def save_rate_quote(email_thread_id, efj, lane, rate_data, sent_at):
    """Save extracted rate quote to rate_quotes table."""
    if not rate_data:
        return
    conn = get_conn()
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
        log.info("  Rate quote saved: %s %s → %s",
                 rate_data.get("carrier_name", "?"),
                 f"${rate_data['rate_amount']}" if rate_data.get("rate_amount") else "no $",
                 lane or "unknown lane")
    except Exception as e:
        conn.rollback()
        log.error("  rate_quotes insert failed: %s", e)
    finally:
        put_conn(conn)


def auto_index_carrier_from_email(sender, subject, body):
    """Auto-index carrier info from a [CARRIER INFO] tagged email into carriers table."""
    text = f"{subject} {body}"
    sender_name = sender.split("<")[0].strip().strip('"') if "<" in sender else sender
    sender_email = sender.split("<")[-1].replace(">", "").strip() if "<" in sender else sender

    mc_match = re.search(r"MC[#\s:-]?\s*(\d{4,7})", text)
    mc_number = mc_match.group(1) if mc_match else None
    dot_match = re.search(r"DOT[#\s:-]?\s*(\d{4,8})", text)
    dot_number = dot_match.group(1) if dot_match else None
    phone_match = re.search(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text)
    phone = phone_match.group(0) if phone_match else None

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO carriers (carrier_name, mc_number, dot_number, contact_email, contact_phone, source)
                VALUES (%s, %s, %s, %s, %s, 'email')
                ON CONFLICT DO NOTHING
            """, (sender_name, mc_number, dot_number, sender_email, phone))
        conn.commit()
        log.info("  Auto-indexed carrier: %s (MC# %s)", sender_name, mc_number or "n/a")
    except Exception as e:
        conn.rollback()
        log.error("  Carrier auto-index failed: %s", e)
    finally:
        put_conn(conn)


def extract_warehouse_rate_from_email(sender, subject, body):
    """Extract warehouse rate info from a [WAREHOUSE RATE] tagged email."""
    text = f"{subject} {body}"
    sender_name = sender.split("<")[0].strip().strip('"') if "<" in sender else sender
    sender_email = sender.split("<")[-1].replace(">", "").strip() if "<" in sender else sender

    mc_match = re.search(r"MC[#\s:-]?\s*(\d{4,7})", text)
    mc_number = mc_match.group(1) if mc_match else None

    # Extract rates: "$XX/pallet", "$XX per day", "$XX.XX/case"
    rate_entries = []
    for m in re.finditer(r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*/?\s*(per\s+)?(pallet|case|day|month|hour|cwt|lb|container|load|unit|sqft)s?", text, re.IGNORECASE):
        try:
            amount = float(m.group(1).replace(",", ""))
            unit = m.group(3).lower()
            rate_entries.append({"rate_amount": amount, "unit": f"per {unit}"})
        except ValueError:
            pass

    # Also look for "Storage $XX", "Labeling $XX", etc.
    for m in re.finditer(r"(storage|labeling|handling|receiving|loading|unloading|wms|palletiz\w+|repack\w*|inspection|drayage)\s*[:\-]?\s*\$\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE):
        try:
            amount = float(m.group(2).replace(",", ""))
            rate_type = m.group(1).strip().title()
            rate_entries.append({"rate_type": rate_type, "rate_amount": amount, "unit": "flat"})
        except ValueError:
            pass

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Upsert warehouse
            cur.execute("""
                INSERT INTO warehouses (name, mc_number, contact_email, source)
                VALUES (%s, %s, %s, 'email')
                ON CONFLICT DO NOTHING RETURNING id
            """, (sender_name, mc_number, sender_email))
            row = cur.fetchone()
            if row:
                wh_id = row["id"]
            else:
                cur.execute("SELECT id FROM warehouses WHERE name = %s LIMIT 1", (sender_name,))
                wh_row = cur.fetchone()
                wh_id = wh_row["id"] if wh_row else None

            if wh_id and rate_entries:
                for re_entry in rate_entries:
                    cur.execute("""
                        INSERT INTO warehouse_rates (warehouse_id, rate_type, rate_amount, unit, description)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (wh_id, re_entry.get("rate_type", "General"), re_entry["rate_amount"],
                          re_entry.get("unit", "flat"), None))
        conn.commit()
        log.info("  Warehouse rate indexed: %s (%d rates)", sender_name, len(rate_entries))
    except Exception as e:
        conn.rollback()
        log.error("  Warehouse rate insert failed: %s", e)
    finally:
        put_conn(conn)


def _send_alert_email(to_email, subject, body_html):
    """Send an alert email via SMTP. Fails silently if SMTP not configured."""
    if not SMTP_USER or not SMTP_PASSWORD:
        log.warning("SMTP not configured — skipping alert email")
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


def _get_rep_email_for_efj(efj):
    """Look up the rep email for an EFJ by checking email thread senders."""
    if not efj:
        return REP_EMAILS.get("John F", EMAIL_CC)  # default to John
    # Check known customer sender domains to infer account → rep
    conn = get_conn()
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
        put_conn(conn)
    return REP_EMAILS.get("John F", EMAIL_CC)


def check_unreplied_customer_emails():
    """
    Check for customer quote emails that haven't received a reply within 15 minutes.
    Inserts into customer_reply_alerts table for the frontend to display.
    Also sends an email alert to the assigned rep.
    """
    conn = get_conn()
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
                log.info("UNREPLIED ALERT: %s [%s] from %s — no reply for 15+ min",
                         email["efj"], email["subject"][:50], email["sender"][:40])

                # Send email alert to assigned rep
                rep_email = _get_rep_email_for_efj(email["efj"])
                lane_info = f" | Lane: {email['lane']}" if email.get("lane") else ""
                _send_alert_email(
                    rep_email,
                    f"CSL Alert: No reply to customer quote — {email['efj'] or 'No EFJ'}{lane_info}",
                    f"""<div style="font-family:Arial,sans-serif;max-width:600px">
<h3 style="color:#F59E0B;margin:0 0 12px 0">Customer Quote — No Reply for 15+ Minutes</h3>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:6px 12px;font-weight:bold;color:#555">EFJ</td><td style="padding:6px 12px">{email['efj'] or 'Not matched'}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#555">From</td><td style="padding:6px 12px">{email['sender']}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#555">Subject</td><td style="padding:6px 12px">{email['subject']}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#555">Lane</td><td style="padding:6px 12px">{email.get('lane') or 'N/A'}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#555">Received</td><td style="padding:6px 12px">{email['sent_at']}</td></tr>
</table>
<p style="color:#888;font-size:12px;margin-top:16px">This customer has been waiting 15+ minutes for a response. Please reply ASAP.</p>
<p style="margin-top:12px"><a href="https://cslogixdispatch.com/app" style="color:#3B82F6">Open Dashboard</a></p>
</div>""",
                )

        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error("Unreplied check failed: %s", e)
    finally:
        put_conn(conn)


# ── Email Processing ──
def is_processed(gmail_msg_id):
    """Check if we already processed this Gmail message."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM email_threads WHERE gmail_message_id = %s",
                (gmail_msg_id,),
            )
            if cur.fetchone():
                return True
            cur.execute(
                "SELECT 1 FROM unmatched_inbox_emails WHERE gmail_message_id = %s",
                (gmail_msg_id,),
            )
            return cur.fetchone() is not None
    finally:
        put_conn(conn)


def get_header(headers, name):
    """Extract a header value from Gmail API headers list."""
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def get_body_preview(payload, max_len=500):
    """Extract plain text body from Gmail message payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        data = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        return data[:max_len]

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            data = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            return data[:max_len]
        # Recurse into multipart
        if part.get("parts"):
            result = get_body_preview(part, max_len)
            if result:
                return result

    return ""


def collect_attachments(payload):
    """Recursively collect attachment metadata from payload."""
    attachments = []
    if payload.get("filename") and payload.get("body", {}).get("attachmentId"):
        attachments.append({
            "filename": payload["filename"],
            "attachment_id": payload["body"]["attachmentId"],
            "mime_type": payload.get("mimeType", ""),
            "size": payload.get("body", {}).get("size", 0),
        })
    for part in payload.get("parts", []):
        attachments.extend(collect_attachments(part))
    return attachments


def download_attachment(service, msg_id, attachment_id):
    """Download attachment data from Gmail API."""
    result = service.users().messages().attachments().get(
        userId="me", messageId=msg_id, id=attachment_id
    ).execute()
    data = result.get("data", "")
    return base64.urlsafe_b64decode(data)


def save_attachment(efj, filename, data):
    """Save attachment to uploads directory. Returns the safe filename."""
    upload_dir = os.path.join(UPLOAD_DIR, efj)
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as f:
        f.write(data)

    os.chmod(file_path, 0o644)
    return safe_name


def process_message(service, msg_id):
    """Process a single Gmail message — match, extract attachments, index."""
    if is_processed(msg_id):
        return

    # Fetch full message
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()

    headers = msg.get("payload", {}).get("headers", [])
    subject = get_header(headers, "Subject")
    sender = get_header(headers, "From")
    to_addr = get_header(headers, "To")
    cc_addr = get_header(headers, "Cc")
    date_str = get_header(headers, "Date")
    rfc_message_id = get_header(headers, "Message-ID")
    gmail_thread_id = msg.get("threadId", "")

    recipients = ", ".join(filter(None, [to_addr, cc_addr]))

    # Handle forwarded emails: strip FW: prefix, extract original sender from body
    original_sender = None
    if FW_PREFIX.search(subject or ""):
        subject = FW_PREFIX.sub("", subject).strip()
        body_text = get_body_preview(msg.get("payload", {}))
        orig_match = ORIGINAL_FROM.search(body_text or "")
        if orig_match:
            original_sender = orig_match.group(1).strip()

    # Parse date
    sent_at = None
    if date_str:
        try:
            sent_at = parsedate_to_datetime(date_str)
        except Exception:
            sent_at = datetime.now(timezone.utc)

    # Get body preview
    body_preview = get_body_preview(msg.get("payload", {}))

    # Collect attachments
    attachments = collect_attachments(msg.get("payload", {}))
    attachment_names = [a["filename"] for a in attachments]
    has_attachments = len(attachments) > 0

    # Filter to allowed file types
    valid_attachments = [
        a for a in attachments
        if Path(a["filename"]).suffix.lower() in ALLOWED_EXTENSIONS
    ]

    # Match to EFJ
    efj = match_email_to_efj(subject, body_preview, attachment_names)

    if efj:
        log.info("MATCHED: %s → %s [%s]", msg_id[:12], efj, subject[:60])

        # Download and save attachments
        saved_docs = []
        for att in valid_attachments:
            try:
                data = download_attachment(service, msg_id, att["attachment_id"])
                safe_name = save_attachment(efj, att["filename"], data)
                doc_type = classify_doc_type(att["filename"], sender=sender, subject=subject, body=body_preview)

                # Insert into load_documents (same table as manual uploads)
                conn = get_conn()
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute(
                            "INSERT INTO load_documents (efj, doc_type, filename, original_name, size_bytes, uploaded_by) "
                            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                            (efj, doc_type, safe_name, att["filename"], len(data), "inbox_scanner"),
                        )
                        doc_id = cur.fetchone()["id"]
                    conn.commit()
                    saved_docs.append(att["filename"])
                    log.info("  Saved: %s → %s (%s)", att["filename"], doc_type, efj)
                except Exception as e:
                    conn.rollback()
                    log.error("  DB error saving doc: %s", e)
                finally:
                    put_conn(conn)
            except Exception as e:
                log.error("  Download failed for %s: %s", att["filename"], e)

        # Classify the email itself (carrier/customer quote, lane detection)
        email_type, lane = classify_email_type(sender, subject, body_preview)
        if email_type:
            log.info("  Email type: %s | Lane: %s", email_type, lane or "none")

        # AI classification (enhanced type, priority, summary)
        ai_result = classifier.ai_classify_email(
            sender, subject, body_preview,
            ", ".join(attachment_names) if attachment_names else "")
        ai_priority = ai_result.get("priority")
        ai_summary_text = ai_result.get("summary")
        ai_suggested_rep = ai_result.get("suggested_rep")
        final_email_type = email_type or ai_result.get("type")
        if ai_priority:
            log.info("  AI: type=%s priority=%d summary=%s",
                     ai_result.get("type", "?"), ai_priority, ai_summary_text or "?")

        # Insert into email_threads
        email_thread_db_id = None
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO email_threads
                       (efj, gmail_thread_id, gmail_message_id, message_id,
                        subject, sender, recipients, body_preview,
                        has_attachments, attachment_names, sent_at,
                        email_type, lane, priority, ai_summary, suggested_rep)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING
                       RETURNING id""",
                    (efj, gmail_thread_id, msg_id, rfc_message_id,
                     subject, sender, recipients, body_preview[:500],
                     has_attachments, ", ".join(attachment_names), sent_at,
                     final_email_type, lane, ai_priority, ai_summary_text, ai_suggested_rep),
                )
                row = cur.fetchone()
                if row:
                    email_thread_db_id = row["id"]
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error("  email_threads insert failed: %s", e)
        finally:
            put_conn(conn)

        # Extract and save rate quote for carrier emails (Rate IQ)
        if email_type == "carrier_rate" and email_thread_db_id:
            rate_data = extract_rate_from_email(subject, body_preview, sender, lane, email_type)
            if rate_data:
                save_rate_quote(email_thread_db_id, efj, lane, rate_data, sent_at)

        # Tag-based: auto-index carrier info
        if email_type == "carrier_info":
            effective_sender = original_sender or sender
            auto_index_carrier_from_email(effective_sender, subject, body_preview)

        # Tag-based: extract warehouse rates
        if email_type == "warehouse_rate":
            effective_sender = original_sender or sender
            extract_warehouse_rate_from_email(effective_sender, subject, body_preview)

    else:
        # Classify the email even when unmatched to an EFJ
        email_type, lane = classify_email_type(sender, subject, body_preview)
        log.info("UNMATCHED: %s [%s] from %s | type=%s lane=%s",
                 msg_id[:12], subject[:60], sender[:40],
                 email_type or "unknown", lane or "none")

        # AI classification (enhanced type, priority, summary)
        ai_result = classifier.ai_classify_email(
            sender, subject, body_preview,
            ", ".join(attachment_names) if attachment_names else "")
        ai_priority = ai_result.get("priority")
        ai_summary_text = ai_result.get("summary")
        ai_suggested_rep = ai_result.get("suggested_rep")
        final_email_type = email_type or ai_result.get("type")
        if ai_priority:
            log.info("  AI: type=%s priority=%d rep=%s",
                     ai_result.get("type", "?"), ai_priority, ai_suggested_rep or "?")

        # Store in unmatched table
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO unmatched_inbox_emails
                       (gmail_message_id, gmail_thread_id, subject, sender,
                        recipients, body_preview, has_attachments,
                        attachment_names, sent_at, email_type, lane,
                        priority, ai_summary, suggested_rep)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING""",
                    (msg_id, gmail_thread_id, subject, sender,
                     recipients, body_preview[:500], has_attachments,
                     ", ".join(attachment_names), sent_at,
                     final_email_type, lane, ai_priority, ai_summary_text, ai_suggested_rep),
                )
                row = cur.fetchone()
                if row:
                    email_thread_db_id = row["id"] if isinstance(row, dict) else row[0]
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error("  unmatched insert failed: %s", e)
        finally:
            put_conn(conn)

        # Tag-based actions work even for unmatched emails
        effective_sender = original_sender or sender
        if email_type == "carrier_info":
            auto_index_carrier_from_email(effective_sender, subject, body_preview)
        if email_type == "warehouse_rate":
            extract_warehouse_rate_from_email(effective_sender, subject, body_preview)


def scan_inbox(service):
    """Scan for unread emails and process them."""
    log.info("Scanning inbox...")

    try:
        result = service.users().messages().list(
            userId="me",
            q="is:unread",
            maxResults=MAX_MESSAGES_PER_SCAN,
        ).execute()
    except Exception as e:
        log.error("Gmail API list failed: %s", e)
        return 0

    messages = result.get("messages", [])
    if not messages:
        log.info("No unread messages")
        return 0

    log.info("Found %d unread messages", len(messages))
    processed = 0

    for msg_meta in messages:
        msg_id = msg_meta["id"]
        try:
            process_message(service, msg_id)
            processed += 1

            # Mark as read
            try:
                service.users().messages().modify(
                    userId="me",
                    id=msg_id,
                    body={"removeLabelIds": ["UNREAD"]},
                ).execute()
            except Exception as e:
                log.warning("Could not mark %s as read: %s", msg_id[:12], e)

        except Exception as e:
            log.error("Error processing %s: %s", msg_id[:12], e)

    log.info("Processed %d/%d messages", processed, len(messages))
    return processed


# ── Main Loop ──
def run_loop():
    """Main scanner loop."""
    service = get_gmail_service()
    failures = 0

    while True:
        try:
            load_reference_cache()
            scan_inbox(service)
            check_unreplied_customer_emails()
            failures = 0
        except Exception as e:
            failures += 1
            log.error("Scan error (attempt %d): %s", failures, e)
            if failures >= 3:
                log.info("Re-authenticating after %d failures...", failures)
                try:
                    service = get_gmail_service()
                    failures = 0
                except Exception as auth_err:
                    log.error("Re-auth failed: %s", auth_err)

        log.info("Sleeping %ds until next scan...", SCAN_INTERVAL)
        time.sleep(SCAN_INTERVAL)


def main():
    log.info("CSL Inbox Scanner starting")
    log.info("Token: %s", TOKEN_PATH)
    log.info("Scan interval: %ds", SCAN_INTERVAL)

    init_pool()
    ensure_tables()
    run_loop()


if __name__ == "__main__":
    main()
