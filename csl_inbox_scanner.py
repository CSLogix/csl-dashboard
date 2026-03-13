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
_payment_alert_queue = []  # Batched payment escalation alerts

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


# ── Junk attachment filter (signature icons, tracking pixels, social logos) ──

JUNK_FILENAME_PATTERNS = re.compile(
    r"^image\d*\.(png|jpg|jpeg|gif)$"           # Outlook signature images: image.png, image001.png
    r"|^Outlook-\w+\.(png|jpg|jpeg)$"            # Outlook-generated: Outlook-abc123.png
    r"|^(icon|logo|banner|spacer|pixel|beacon)"  # Generic junk prefixes
    r"|facebook|linkedin|twitter|instagram|youtube|tiktok"  # Social media icons
    r"|(^|\.)(gif)$"                             # Almost all .gif attachments are tracking pixels
    r"|^outlook_\w+\.(png|jpg)"                  # Outlook-generated images (lowercase)
    r"|^~\$"                                      # Office temp files
    r"|_logo\.(png|jpg|jpeg)$"                    # Company logos: otr_logo.png
    r"|^(sig|signature|header|footer|divider|separator)\d*\.(png|jpg|jpeg)$"
    r"|^cid[_-]"                                   # Content-ID referenced images
    r"|^(brand|badge|seal|cert|certified)\.(png|jpg|jpeg)$"
    , re.IGNORECASE
)

JUNK_MAX_SIZE_BYTES = 50_000  # 50KB — real docs (rate cons, PODs) are larger — real docs are larger

def is_junk_attachment(filename, size_bytes=None):
    """Return True if attachment looks like a signature icon or tracking pixel."""
    if not filename:
        return True
    # Known junk filename patterns
    if JUNK_FILENAME_PATTERNS.search(filename):
        return True
    # Tiny image files are almost always icons/signatures
    if size_bytes is not None and size_bytes < JUNK_MAX_SIZE_BYTES:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in ("png", "jpg", "jpeg", "gif", "bmp", "ico"):
            return True
    return False

# EFJ# pattern: "EFJ" optionally followed by space/dash, then 5-6 digits
EFJ_PATTERN = re.compile(r"EFJ[\s\-]?(\d{5,6})", re.IGNORECASE)
# Container# pattern: 4 uppercase letters + 7 digits
CONTAINER_PATTERN = re.compile(r"\b([A-Z]{4}\d{7})\b")
# BOL/Booking pattern
BOL_PATTERN = re.compile(r"\b(\d{9,12})\b")
# Tolead hub ID pattern: LAX/ORD/JFK/DFW + 7-13 digits
HUB_ID_PATTERN = re.compile(r"\b((?:LAX|ORD|JFK|DFW)\d{7,13})\b", re.IGNORECASE)
# Prefix-less EFJ: standalone 6-digit number starting with 10 (e.g. 107330)
BARE_EFJ_PATTERN = re.compile(r"\b(10\d{4})\b")

# Doc type classification by filename (rate handled in classify_doc_type)
DOC_CLASSIFIERS = [
    (re.compile(r"bol|bill.of.lading|b/l", re.IGNORECASE), "bol"),
    (re.compile(r"pod|proof.of.delivery|delivery.receipt", re.IGNORECASE), "pod"),
    (re.compile(r"invoice|inv\b", re.IGNORECASE), "invoice"),
    (re.compile(r"screenshot|screen.?shot|snap", re.IGNORECASE), "screenshot"),
    (re.compile(r"pack(?:ing)?[_\s-]?list", re.IGNORECASE), "packing_list"),
]

# Senders that indicate carrier invoices
CARRIER_PAY_SENDERS = re.compile(
    r"carrier.?pay|carrierpay|carrier.?support|freight.?pay|comcheck|triumph|rts|efs|wex",
    re.IGNORECASE,
)

# ── POD body-text detection (95% accuracy when carrier + attachment + body keyword) ──
POD_BODY_PATTERNS = re.compile(
    r"(?:pfa\s+pod|pod\s+attached|please\s+(?:see|find)\s+attached"
    r"|attached.*pod|pod.*attached|proof\s+of\s+delivery)",
    re.IGNORECASE,
)

# ── Carrier Rate Confirmation detection ──
RC_PATTERNS = re.compile(
    r"rate\s*con(?:firmation)?|r/?c\s+attached|updated\s+r/?c|final\s+r/?c"
    r"|signed\s+r/?c|executed\s+rate",
    re.IGNORECASE,
)

# ── Enhanced customer quote patterns ──
CUSTOMER_QUOTE_PATTERNS = re.compile(
    # RFQ / rate request language
    r"(?:rfq|rate\s*request|need\s*rates?|quote\s*request|pricing\s*request)"
    r"|(?:rate.*(?:from|to|origin|dest))"
    # Container quantities: 3x40HC, 3×40HC, 1x20'STD etc.
    r"|(?:\d+\s*[x\xd7]\s*(?:20|40|45|53)\s*(?:'\s*)?(?:hq|hc|gp|st|std|ot|fr|rf|IMO)?)"
    r"|(?:ramp\s*[-\u2013]\s*\d+[x\xd7])"
    # Volume / quantity indicators
    r"|(?:vol(?:ume)?\s*[:=]?\s*\d+\s*(?:container|cntr|ctn|unit|piece|pallet|truck))"
    r"|(?:\d+\s+containers?\b)"
    # Service combination requests (strong customer signal)
    r"|(?:dray(?:age)?\s*(?:and|\+|,|&)\s*(?:cross.?dock|delivery|trucking|warehouse|transload))"
    r"|(?:(?:cross.?dock|transload|stripping)\s*(?:and|\+|,|&)\s*(?:delivery|trucking))"
    # Delivery to zip code pattern
    r"|(?:(?:deliver|delivery|ship|trucking)\s+(?:to|from)\s+[A-Z][a-z]+.*\b\d{5}\b)"
    # Commodity descriptions (indicate quote request context)
    r"|(?:commodity\s*:.+(?:quote|rate|dray|truck))"
    r"|(?:(?:quote|rate|dray|truck).+commodity\s*:)"
    # Incoterm references (FCA, FOB, CIF etc. signal trade/shipping quote)
    r"|(?:incoterm\s*:\s*(?:FCA|FOB|CIF|EXW|DDP|DAP|CPT|CIP))"
    # Crate/pallet dimension patterns: 500cm x 240cm x 270cm
    r"|(?:\d+\s*(?:cm|mm|in|ft|'|"")?\s*[x\xd7*]\s*\d+\s*(?:cm|mm|in|ft|'|"")?\s*[x\xd7*]\s*\d+\s*(?:cm|mm|in|ft|'|""))"
    # Weight with gross/net qualifier
    r"|(?:(?:gross|net)\s+weight\s+\d+\s*(?:kg|lbs|kgs|lb|tons?))"
    r"|(?:\d{3,6}\s*(?:kg|kgs|lbs|lb)\s+(?:each|per|total|gross))",
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
    r"dsv\.com|dhl\.com|kripke|allround|cadi|iwsgroup|maoinc|maogroup|eshipping"
    r"|mgfusa|rose.?int|boviet|tolead|mamata|sutton|tanera|meiko|kishco"
    r"|sei.?acq|cnl|manitoulin|tcr|texas.?int|md.?metal|usha"
    r"|prologshipping|mdmetalrecycling|bovietsolarusa",
    re.IGNORECASE,
)

# Known carrier/trucking company patterns
KNOWN_CARRIER_SENDERS = re.compile(
    r"xpo\.com|jbhunt|schneider|knight.?trans|werner\.com|heartland"
    r"|usxpress|saia\.com|estes|odfl\.com|landstar|echo\.com|coyote"
    r"|ch\.?robinson|ryder\.com|penske|averitt|roadrunner"
    r"|railtransfer.com|@.*(?:trucking|transport|freight|drayage|cartage|dispatch|hauling|logistics|transfer|carriers|express|lines).com",
    re.IGNORECASE,
)

# Customer drayage quote request language
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

# RFQ attachment filename patterns
RFQ_ATTACHMENT_NAMES = re.compile(
    r"rfq|rate.?quote|quote.?request|rate.?request|lane.?rate|rate.?sheet|"
    r"drayage.?rate|freight.?quote|bid.?request|pricing.?request",
    re.IGNORECASE,
)

# Strong quote-intent signals (content-first, catches unknown senders)
STRONG_QUOTE_INTENT = re.compile(
    # Direct rate asks
    r"please\s+provide\s+(your\s+)?(current\s+)?rate"
    r"|please\s+quote\s+(?:pickup|delivery|drayage|the\s+below|this)"
    r"|(?:hi|hello)\s+carrier"                    # addressed to Evans as carrier
    r"|drayage\s+request"                          # subject/body keyword
    r"|requesting\s+(a\s+)?(?:rate|quote|pricing)"
    r"|(?:rate|quote)\s+for\s+(?:the\s+)?below\s+route"
    r"|new\s+(?:lane|request|rfq|opportunity).*(?:rate|quote|dray)"
    # Lane in subject (City ST to City ST or ZIP-based)
    r"|\b(?:pick\s*up|pu|p/?u)\s+from\s+.{5,40}\s+(?:and\s+)?deliver"
    r"|\d{5}\s+to\s+(?:[A-Z][a-z]+\s+)?[A-Z]{2}\s+\d{5}"  # ZIP to ZIP
    # Full address signals (pickup/delivery with street address)
    r"|(?:pick\s*up|ship\s*to|deliver\s*to)\s*:\s*\d+\s+[A-Z]"
    r"|loading\s+dock\s+hours"
    r"|commodity\s*:\s*\S"                       # "Commodity: GDSM..."
    r"|(?:40|20|45|53)\s*'?\s*(?:hq|hc|gp|st|ot|fr|rf)\b",  # container type
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

# US state abbreviations for lane validation
_US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
}

# Lane pattern: "City, ST to City, ST" with optional miles (case-sensitive for state codes)
LANE_PATTERN = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,?\s*[A-Z]{2})\s*(?:to|→|->|-)\s*"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,?\s*[A-Z]{2})"
    r"(?:.*?(\d{2,4})\s*mi)?",
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

# PTD reference pattern (DSV / Apple bids: PTD//XXXXXXXXXX-XX or PTD-XXXXX)
PTD_PATTERN = re.compile(r'PTD[\-/]{1,2}(\d{5,}(?:[\-/]\w+)*)', re.IGNORECASE)


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
            # Outbound quote columns (Evans → customer quotes)
            for col_def in [
                ("quote_direction",  "TEXT DEFAULT 'inbound'"),
                ("customer_name",    "TEXT"),
                ("linehaul",         "DECIMAL(10,2)"),
                ("chassis_per_day",  "DECIMAL(10,2)"),
                ("accessorials",     "JSONB"),
                ("total_estimate",   "DECIMAL(10,2)"),
            ]:
                try:
                    cur.execute(f"ALTER TABLE rate_quotes ADD COLUMN IF NOT EXISTS {col_def[0]} {col_def[1]}")
                except Exception:
                    conn.rollback()
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
    Try to match an email to a load by EFJ#, hub ID, container#, bare number, or BOL#.
    Returns the matched EFJ string or None.
    """
    text = f"{subject or ''} {body or ''} {' '.join(attachment_names or [])}"

    # 1. Primary: EFJ# in text (e.g. EFJ107484)
    efj_matches = EFJ_PATTERN.findall(text)
    for num in efj_matches:
        return f"EFJ{num}"

    # 2. Tolead hub IDs: LAX1260312023, ORD1260301008, etc. → shipments.container
    hub_matches = HUB_ID_PATTERN.findall(text)
    if hub_matches:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for hub_id in hub_matches:
                    cur.execute(
                        "SELECT efj FROM shipments WHERE container = %s LIMIT 1",
                        (hub_id.upper(),),
                    )
                    row = cur.fetchone()
                    if row:
                        log.info("Hub ID %s → %s", hub_id, row["efj"])
                        return row["efj"]
        finally:
            put_conn(conn)

    # 3. Container# (MSCU1234567) → shipments.container
    container_matches = CONTAINER_PATTERN.findall(text.upper())
    if container_matches:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for container in container_matches:
                    cur.execute(
                        "SELECT efj FROM shipments WHERE container = %s LIMIT 1",
                        (container,),
                    )
                    row = cur.fetchone()
                    if row:
                        log.info("Container %s → %s", container, row["efj"])
                        return row["efj"]
        finally:
            put_conn(conn)

    # 4. Bare 6-digit EFJ (107330) — only from subject line to reduce false positives
    bare_matches = BARE_EFJ_PATTERN.findall(subject or "")
    if bare_matches:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for num in bare_matches:
                    # Check both with and without EFJ prefix
                    cur.execute(
                        "SELECT efj FROM shipments WHERE efj = %s OR efj = %s LIMIT 1",
                        (f"EFJ{num}", num),
                    )
                    row = cur.fetchone()
                    if row:
                        log.info("Bare number %s → %s", num, row["efj"])
                        return row["efj"]
        finally:
            put_conn(conn)

    # 5. BOL/Booking number → shipments.bol
    bol_matches = BOL_PATTERN.findall(text)
    if bol_matches:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for bol in bol_matches:
                    cur.execute(
                        "SELECT efj FROM shipments WHERE bol = %s LIMIT 1",
                        (bol,),
                    )
                    row = cur.fetchone()
                    if row:
                        log.info("BOL %s → %s", bol, row["efj"])
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

    # POD body-text fallback: if body mentions POD + has attachments
    if body and POD_BODY_PATTERNS.search(body[:500]):
        if not CSL_TEAM_SENDERS.search(sender):
            return "pod"

    for pattern, doc_type in DOC_CLASSIFIERS:
        if pattern.search(filename):
            return doc_type
    return "other"


# ═══════════════════════════════════════════════════════════════
# AI DOCUMENT CLASSIFIER — Sonnet vision for ambiguous attachments
# ═══════════════════════════════════════════════════════════════

_AI_CLASSIFY_VALID_TYPES = {"pod", "carrier_invoice", "bol", "carrier_rate", "customer_rate", "packing_list", "screenshot", "other"}
_AI_CLASSIFY_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".tif", ".bmp"}

def ai_classify_document(file_data, filename, sender="", subject="", efj=""):
    """
    Use Claude Sonnet 4.6 vision to classify a document that regex couldn't identify.
    Returns a doc_type string. Falls back to "other" on any error.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _AI_CLASSIFY_EXTENSIONS:
        return "other"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        encoded = base64.standard_b64encode(file_data).decode("utf-8")

        # Determine media type
        if ext == ".pdf":
            media_type = "application/pdf"
            content_block = {"type": "document", "source": {"type": "base64", "media_type": media_type, "data": encoded}}
        elif ext in (".jpg", ".jpeg"):
            media_type = "image/jpeg"
            content_block = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}
        elif ext == ".png":
            media_type = "image/png"
            content_block = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}
        elif ext == ".gif":
            media_type = "image/gif"
            content_block = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}
        elif ext == ".webp":
            media_type = "image/webp"
            content_block = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}
        elif ext in (".tiff", ".tif"):
            # Anthropic doesn't support TIFF natively — skip
            return "other"
        elif ext == ".bmp":
            return "other"
        else:
            return "other"

        # Limit file size to 5MB for API
        if len(file_data) > 5 * 1024 * 1024:
            log.info("  AI classify: skipping %s (>5MB)", filename)
            return "other"

        prompt = f"""Classify this logistics document into exactly ONE of these types:

- pod (Proof of Delivery — signed delivery receipt, delivery confirmation, receiver signature)
- carrier_invoice (carrier's freight bill/invoice for payment)
- bol (Bill of Lading — shipping document, pickup receipt)
- carrier_rate (rate confirmation, rate agreement from a carrier)
- customer_rate (rate quote or pricing sent TO a customer)
- packing_list (itemized list of goods being shipped)
- screenshot (screenshot of a tracking page or system)
- other (none of the above, or unreadable)

Context: This was emailed to a freight brokerage (Evans Delivery).
Filename: {filename}
Sender: {sender}
Subject: {subject}
Load: {efj}

Reply with ONLY the doc_type, nothing else. Example: pod"""

        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=20,
            messages=[{"role": "user", "content": [content_block, {"type": "text", "text": prompt}]}],
        )

        result = resp.content[0].text.strip().lower().replace(" ", "_")
        # Map common variations
        if result in ("carrier_invoice", "invoice", "freight_invoice", "freight_bill"):
            result = "carrier_invoice"
        elif result in ("pod", "proof_of_delivery", "delivery_receipt"):
            result = "pod"
        elif result in ("bol", "bill_of_lading"):
            result = "bol"
        elif result in ("rate_confirmation", "rate_con", "carrier_rate"):
            result = "carrier_rate"

        if result in _AI_CLASSIFY_VALID_TYPES:
            log.info("  AI classify: %s -> %s (was other)", filename, result)
            return result
        else:
            log.warning("  AI classify: unexpected result '%s' for %s, defaulting to other", result, filename)
            return "other"

    except Exception as e:
        log.error("  AI classify error for %s: %s", filename, e)
        return "other"


# ═══════════════════════════════════════════════════════════════
# AUTO-STATUS ADVANCEMENT — POD + Invoice → Delivered → Ready to Close
# ═══════════════════════════════════════════════════════════════

_ADVANCE_STATUSES = {
    "in_transit", "out_for_delivery", "at_delivery",
    "in transit", "out for delivery", "at delivery",
}
_DELIVERED_STATUSES = {"delivered", "completed", "need_pod", "need pod"}
_TERMINAL_STATUSES = {"billed_closed", "billed & closed", "empty_return", "empty_returned", "cancelled", "ready_to_close", "ready to close"}

def check_and_advance_billing(efj, conn_func, put_conn_func):
    """
    After docs are saved for a load, check if POD + carrier_invoice are present.
    If both exist and load is in a qualifying status, auto-advance.
    """
    conn = conn_func()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check what docs exist for this load
            cur.execute(
                "SELECT doc_type, COUNT(*) as cnt FROM load_documents WHERE efj = %s GROUP BY doc_type",
                (efj,),
            )
            doc_counts = {row["doc_type"]: row["cnt"] for row in cur.fetchall()}

            has_pod = doc_counts.get("pod", 0) > 0
            has_invoice = doc_counts.get("carrier_invoice", 0) > 0

            if not (has_pod and has_invoice):
                return  # Not ready yet

            # Get current shipment status
            cur.execute("SELECT status FROM shipments WHERE efj = %s", (efj,))
            row = cur.fetchone()
            if not row:
                return

            current_status = (row["status"] or "").strip().lower()

            if current_status in _TERMINAL_STATUSES:
                return  # Already past billing

            if current_status in _ADVANCE_STATUSES:
                # In transit/at delivery → mark delivered, then ready to close
                cur.execute(
                    "UPDATE shipments SET status = 'delivered', updated_at = NOW() WHERE efj = %s",
                    (efj,),
                )
                log.info("  Auto-advance: %s status %s -> delivered (POD + invoice present)", efj, current_status)
                conn.commit()

                # Brief pause then advance to ready_to_close
                cur.execute(
                    "UPDATE shipments SET status = 'ready_to_close', updated_at = NOW() WHERE efj = %s AND LOWER(status) = 'delivered'",
                    (efj,),
                )
                log.info("  Auto-advance: %s delivered -> ready_to_close", efj)
                conn.commit()

            elif current_status in _DELIVERED_STATUSES:
                # Already delivered → advance to ready_to_close
                cur.execute(
                    "UPDATE shipments SET status = 'ready_to_close', updated_at = NOW() WHERE efj = %s",
                    (efj,),
                )
                log.info("  Auto-advance: %s %s -> ready_to_close (POD + invoice present)", efj, current_status)
                conn.commit()

            else:
                # Status is something else (pending, at_port, on_vessel, etc.)
                # Don't auto-advance — the load hasn't been picked up yet
                log.info("  Auto-advance: skipping %s (status=%s, not qualifying)", efj, current_status)

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        log.error("  Auto-advance error for %s: %s", efj, e)
    finally:
        put_conn_func(conn)


_SIG_STRIP = re.compile(
    r'(?:^|\n)\s*(?:-{3,}|\*{3,}|_{3,}|Insurance Notice|Best regards?|Sincerely|'
    r'Regards,|Thanks,|Thank you|Sent from|CONFIDENTIAL|DISCLAIMER|'
    r'This email|The information).*',
    re.IGNORECASE | re.DOTALL,
)

def _extract_lane(subject, body):
    """Helper to extract lane from subject/body. Returns lane string or None.
    Strips email signatures and disclaimers before parsing to avoid false matches."""
    # Strip signature/disclaimer content — only parse first 400 chars of body
    clean_body = _SIG_STRIP.sub("", body or "")[:400] if body else ""
    for text in [subject or "", clean_body]:
        lane_match = LANE_PATTERN.search(text)
        if not lane_match:
            continue
        origin_city = lane_match.group(1).strip()
        dest_city = lane_match.group(2).strip()
        # Validate state codes are real US states
        origin_st = origin_city[-2:].upper()
        dest_st = dest_city[-2:].upper()
        if origin_st not in _US_STATES or dest_st not in _US_STATES:
            continue
        miles = lane_match.group(3)
        lane = f"{origin_city} → {dest_city}"
        if miles:
            lane += f" ({miles} mi)"
        return lane
    return None


def classify_email_type(sender, subject, body, has_attachments=False, attachment_names=None):
    """
    Classify the email itself based on sender, subject, body content.
    Returns (email_type, lane_str) tuple.

    Classification priority:
    1. Tag override (explicit [CARRIER RATE] etc.)
    2. CarrierPay escalation (before CSL team skip)
    3. POD body-text detection (carrier + attachment + POD keywords)
    4. Carrier rate confirmation (RC patterns)
    5. CSL team outbound → rate_outreach or skip
    6. Carrier signal scoring → carrier_rate
    7. Known customer sender → customer_rate
    8. Customer quote language → customer_rate
    9. Enhanced customer patterns → customer_rate
    """
    sender_lower = (sender or "").lower()
    subject_safe = subject or ""
    body_safe = body or ""
    body_lower = body_safe[:500].lower()
    text = f"{subject_safe} {body_safe}"

    # 1. Tag override: explicit tags in subject line take priority
    tag_match = TAG_PATTERN.search(subject_safe)
    if tag_match:
        tag_key = tag_match.group(1).lower()
        mapped = TAG_TO_EMAIL_TYPE.get(tag_key)
        if mapped:
            return mapped, _extract_lane(subject_safe, body_safe)

    # 2. CarrierPay escalation — BEFORE CSL team skip
    if CARRIER_PAY_SENDERS.search(sender_lower):
        lane = _extract_lane(subject_safe, body_safe)
        if re.search(r'\bNP\b', text):
            return 'payment_escalation', lane
        return 'carrier_invoice', lane

    # 3. POD body-text detection (carrier + attachment + keywords, 95% accurate)
    if has_attachments and POD_BODY_PATTERNS.search(body_lower):
        if not CSL_TEAM_SENDERS.search(sender_lower):
            return 'pod', _extract_lane(subject_safe, body_safe)

    # 4. Carrier rate confirmation (RC patterns, from non-CSL sender)
    if not CSL_TEAM_SENDERS.search(sender_lower):
        if RC_PATTERNS.search(text):
            return 'carrier_rate_confirmation', _extract_lane(subject_safe, body_safe)

    # 5. CSL team outbound — detect rate_outreach or skip
    if CSL_TEAM_SENDERS.search(sender_lower):
        subject_lower = (subject_safe).lower()
        rate_signals = bool(re.search(
            r'rate|rfq|quote|pricing|need\s+truck|available.*capacity',
            subject_lower))
        lane = _extract_lane(subject_safe, body_safe)
        lane_signal = lane is not None
        container_signal = bool(re.search(
            r'\d+\s*x\s*(20|40|45)\s*(hq|hc|gp|st|ot|fr|rf)?',
            subject_lower + ' ' + body_lower))
        if rate_signals or (lane_signal and container_signal):
            return 'rate_outreach', lane
        return None, None  # Non-rate CSL team email — skip

    # Extract lane for remaining checks
    lane = _extract_lane(subject_safe, body_safe)

    # 6. Carrier detection: MC#, transport in sender, lane+miles, rate language
    carrier_signals = 0
    if KNOWN_CARRIER_SENDERS.search(sender_lower):
        carrier_signals += 2
    if re.search(r"MC[#\s-]?\d{4,7}", text):
        carrier_signals += 2
    if re.search(r"transport|trucking|freight|hauling", sender_lower):
        carrier_signals += 1
    if LANE_PATTERN.search(subject_safe):
        carrier_signals += 1
    if CARRIER_RATE_LANGUAGE.search(text):
        carrier_signals += 1
    if carrier_signals >= 2:
        return "carrier_rate", lane

    # 7-8. Customer detection (existing patterns)
    if KNOWN_CUSTOMER_SENDERS.search(sender_lower):
        # Don't fire customer_rate if this is clearly an operational/POD acknowledgment
        _body_lower_full = (body_safe or "").lower()
        _is_operational = bool(re.search(
            r"well noted|noted with thanks|share the pod|send.*pod|"
            r"pod.*once available|please.*keep.*posted|duly noted|"
            r"acknowledged|thank you for the update|received with thanks",
            _body_lower_full,
        ))
        if _is_operational:
            return "tracking", lane
        return "customer_rate", lane
    if CUSTOMER_QUOTE_LANGUAGE.search(text):
        return "customer_rate", lane

    # 9. Enhanced customer patterns (RFQ, container quantities, ramp references)
    if CUSTOMER_QUOTE_PATTERNS.search(text):
        return "customer_rate", lane

    # 9.5 Strong quote intent — content-first catch for unknown senders
    # Lane in subject + any rate/quote signal = high confidence quote request
    subject_has_lane = bool(LANE_PATTERN.search(subject_safe))
    strong_intent = STRONG_QUOTE_INTENT.search(text)
    if strong_intent:
        # Exclude if clearly operational/acknowledgment
        _body_lower_full = (body_safe or "").lower()
        _is_operational = bool(re.search(
            r"well noted|noted with thanks|share the pod|send.*pod|"
            r"pod.*once available|please.*keep.*posted|duly noted|"
            r"acknowledged|thank you for the update|received with thanks",
            _body_lower_full,
        ))
        if not _is_operational:
            return "customer_rate", _extract_lane(subject_safe, body_safe)

    if subject_has_lane and re.search(r"rate|quote|dray|rfq|pricing", text, re.I):
        return "customer_rate", _extract_lane(subject_safe, body_safe)

    # 9.6 Thin-body RFQ: "please quote the attached" + attachment with RFQ filename
    if has_attachments:
        _thin_quote = bool(re.search(
            r"please\s+(quote|rate|price)\s+(?:the\s+)?attached"
            r"|see\s+attached.*(?:rfq|rate|quote|lane)"
            r"|(?:rate|quote|rfq).*see\s+attached"
            r"|attached.*(?:rate\s+request|rfq|quote\s+request)"
            r"|rates?\s+attached|quote\s+attached",
            text, re.IGNORECASE,
        ))
        _rfq_filename = any(
            RFQ_ATTACHMENT_NAMES.search(name)
            for name in (attachment_names or [])
        )
        if _thin_quote or _rfq_filename:
            return "customer_rate", _extract_lane(subject_safe, body_safe)

    return None, None
def extract_outbound_quote(subject, body, recipient, lane):
    """
    Extract Evans' own outbound customer rate quote using AI.
    Handles the Evans Network rate table format (linehaul+fuel, chassis, accessorials).
    Returns dict or None.
    """
    import anthropic as _ant
    client = _ant.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    prompt = f"""Extract the rate quote from this Evans outbound email.
Subject: {subject}
Recipient: {recipient}
Lane: {lane or 'unknown'}

Email body:
{body[:2000]}

Return JSON only with these fields (use null if not found):
{{
  "origin": "city, ST",
  "destination": "city, ST",
  "move_type": "dray|ftl|transload|crossdock",
  "linehaul": <number or null>,
  "chassis_per_day": <number or null>,
  "total_estimate": <number or null>,
  "accessorials": {{
    "detention": <number or null>,
    "prepull": <number or null>,
    "pier_pass": <string or null>,
    "dry_run": <number or null>,
    "chassis_split": <number or null>,
    "storage_per_night": <number or null>,
    "other": []
  }},
  "customer_name": "company name or null",
  "notes": "brief note about FSC or special conditions"
}}"""
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        import json, re as _re
        m = _re.search(r'\{.*\}', text, _re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        log.error("  outbound quote extraction failed: %s", e)
    return None


def save_outbound_quote(email_thread_id, efj, lane, recipient, quote_data, sent_at):
    """Save Evans outbound customer rate quote to rate_quotes table."""
    if not quote_data:
        return
    import json
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO rate_quotes
                    (email_thread_id, efj, lane, origin, destination,
                     move_type, customer_name, carrier_email,
                     rate_amount, total_estimate,
                     linehaul, chassis_per_day, accessorials,
                     quote_direction, quote_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'outbound',%s)
                ON CONFLICT DO NOTHING
            """, (
                email_thread_id, efj, lane,
                quote_data.get("origin"), quote_data.get("destination"),
                quote_data.get("move_type", "dray"),
                quote_data.get("customer_name"),
                recipient,
                quote_data.get("total_estimate"),   # rate_amount = total
                quote_data.get("total_estimate"),
                quote_data.get("linehaul"),
                quote_data.get("chassis_per_day"),
                json.dumps(quote_data.get("accessorials") or {}),
                sent_at,
            ))
        conn.commit()
        log.info("  Outbound quote saved: %s → %s @ $%s",
                 lane or "?", quote_data.get("customer_name", recipient[:30]),
                 quote_data.get("total_estimate") or "?")
    except Exception as e:
        conn.rollback()
        log.error("  outbound quote save failed: %s", e)
    finally:
        put_conn(conn)


def extract_rate_from_email(subject, body, sender, lane, email_type):
    """
    Extract rate data from carrier email using AI (Haiku) with regex fallback.
    Returns dict with rate_amount, rate_unit, move_type, origin, dest, miles.
    """
    if email_type not in ("carrier_rate", "customer_rate"):
        return None

    text = f"{subject} {body[:2500]}"
    sender_name = sender.split("<")[0].strip().strip('"') if "<" in sender else sender
    carrier_email = sender.split("<")[-1].replace(">", "").strip() if "<" in sender else sender

    # AI extraction first
    result = _ai_extract_rate(subject, body[:2500], sender_name)

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
    result["rate_type"] = "customer" if email_type == "customer_rate" else "carrier"
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
    prompt = f"""Extract the freight rate from this carrier email. Return ONLY valid JSON.

FROM: {sender_name}
SUBJECT: {subject}
BODY:
{body}

RULES:
- Look for dollar amounts ($X,XXX or $X,XXX.XX) near keywords like "rate", "all-in", "total", "we can do", "our price", "quoted at", "linehaul", "flat rate"
- IGNORE insurance amounts, liability limits, cargo values, bond amounts, and per-diem chassis charges unless they are the primary rate
- If you see a per-mile rate (e.g. "$2.35/mile") with mileage, compute rate_amount = per_mile_rate * miles and set rate_unit=per_mile
- If you see linehaul + FSC or accessorials separately, sum them for rate_amount and also populate linehaul/accessorials fields
- If multiple dollar amounts exist, prefer the "all-in" or "total" amount. If no total, use the linehaul amount
- If the email is a rate confirmation (not a new quote), extract the confirmed rate
- move_type=dray if email mentions port, chassis, drayage, container, pier, terminal
- If no clear freight rate is found, set rate_amount to null — do NOT guess

Return this JSON:
{{
  "rate_amount": <all-in dollar amount as number, or null>,
  "rate_unit": "<flat or per_mile>",
  "move_type": "<dray or ftl or ltl>",
  "origin": "<origin city/state or null>",
  "destination": "<destination city/state or null>",
  "miles": <integer or null>,
  "carrier_name": "<company name from email signature or null>",
  "linehaul": <linehaul amount if separate from total, or null>,
  "accessorials": <accessorials/FSC total if mentioned, or null>,
  "confidence": "<high or medium or low>"
}}"""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=300,
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
        for f in ("rate_unit", "move_type", "origin", "destination", "carrier_name", "confidence"):
            if data.get(f):
                out[f] = str(data[f]).strip()
        if data.get("miles"):
            try:
                out["miles"] = int(data["miles"])
            except (TypeError, ValueError):
                pass
        for nf in ("linehaul", "accessorials"):
            if data.get(nf) is not None:
                try:
                    out[nf] = float(data[nf])
                except (TypeError, ValueError):
                    pass
        return out
    except Exception as e:
        log.debug("AI rate extraction failed: %s", e)
        return {}

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


def _flush_payment_alerts():
    """Send a single batched email for all queued payment alerts."""
    global _payment_alert_queue
    if not _payment_alert_queue:
        return
    alerts = _payment_alert_queue[:]
    _payment_alert_queue = []
    
    # Group by rep
    from collections import defaultdict
    by_rep = defaultdict(list)
    for a in alerts:
        rep_email = _get_rep_email_for_efj(a["efj"])
        by_rep[rep_email].append(a)
    
    for rep_email, items in by_rep.items():
        efj_list = ", ".join(a["efj"] for a in items)
        rows = ""
        for a in items:
            rows += (f'<tr>'
                     f'<td style="padding:4px 8px;border-bottom:1px solid #eee;"><b>{a["efj"]}</b></td>'
                     f'<td style="padding:4px 8px;border-bottom:1px solid #eee;">{a["sender"][:40]}</td>'
                     f'<td style="padding:4px 8px;border-bottom:1px solid #eee;">{a["summary"][:80]}</td>'
                     f'</tr>')
        body = (f'<div style="font-family:Arial,sans-serif;max-width:700px;">'
                f'<div style="background:#c62828;color:white;padding:10px 14px;border-radius:6px 6px 0 0;">'
                f'<b>⚠ Payment Alerts ({len(items)})</b></div>'
                f'<table style="border-collapse:collapse;width:100%;border:1px solid #ddd;border-top:none;">'
                f'<tr style="background:#c62828;color:white;">'
                f'<th style="padding:4px 8px;text-align:left;">EFJ</th>'
                f'<th style="padding:4px 8px;text-align:left;">From</th>'
                f'<th style="padding:4px 8px;text-align:left;">Summary</th></tr>'
                f'{rows}</table></div>')
        subject = f"⚠ PAYMENT ALERTS: {len(items)} loads — {efj_list[:80]}"
        _send_alert_email(rep_email, subject, body)
        log.info("Sent batched payment digest to %s (%d alerts)", rep_email, len(items))


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

    Dedup: by email_thread_id AND by (efj, sender_domain) to prevent
    multiple alerts when same customer sends multiple threads about same EFJ.
    Filters out self-sent emails (bot alert emails classified as customer_rate).
    """
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT et.id, et.efj, et.sender, et.subject, et.lane, et.sent_at
                FROM email_threads et
                WHERE et.email_type = 'customer_rate'
                  AND et.sent_at < NOW() - INTERVAL '15 minutes'
                  AND et.sent_at > NOW() - INTERVAL '4 hours'
                  -- Exclude self-sent (bot alert emails)
                  AND et.sender NOT ILIKE '%%jfeltzjr%%'
                  AND et.sender NOT ILIKE '%%commonsenselogistics%%'
                  AND et.sender NOT ILIKE '%%evansdelivery%%'
                  AND et.subject NOT ILIKE '%%CSL Alert%%'
                  -- No reply from our team in same thread
                  AND NOT EXISTS (
                    SELECT 1 FROM email_threads reply
                    WHERE reply.gmail_thread_id = et.gmail_thread_id
                      AND (reply.sender ILIKE '%%commonsenselogistics%%'
                           OR reply.sender ILIKE '%%evansdelivery%%')
                      AND reply.sent_at > et.sent_at
                  )
                  -- Not a rate outreach thread
                  AND NOT EXISTS (
                    SELECT 1 FROM email_threads outreach
                    WHERE outreach.gmail_thread_id = et.gmail_thread_id
                      AND outreach.email_type = 'rate_outreach'
                  )
                  -- Dedup: not already alerted for this email_thread_id
                  AND NOT EXISTS (
                    SELECT 1 FROM customer_reply_alerts cra
                    WHERE cra.email_thread_id = et.id
                  )
                  -- Dedup: not already alerted for same EFJ in last 2 hours
                  AND NOT EXISTS (
                    SELECT 1 FROM customer_reply_alerts cra2
                    WHERE cra2.efj = et.efj
                      AND cra2.efj IS NOT NULL
                      AND cra2.alerted_at > NOW() - INTERVAL '2 hours'
                  )
                ORDER BY et.sent_at ASC
                LIMIT 5
            """)
            unreplied = cur.fetchall()

            for email in unreplied:
                cur.execute("""
                    INSERT INTO customer_reply_alerts (email_thread_id, efj, sender, subject)
                    VALUES (%s, %s, %s, %s)
                """, (email["id"], email["efj"], email["sender"], email["subject"]))
                log.info("UNREPLIED ALERT: %s [%s] from %s — no reply for 15+ min",
                         email["efj"], email["subject"][:50], email["sender"][:40])

                # Try to get lane from shipments table if email lane is bad
                lane = email.get("lane") or ""
                if not lane or len(lane) > 60 or any(w in lane.lower() for w in
                        ["don't", "dont", "want", "proceed", "please", "need", "can you"]):
                    # Lane looks like body text, try PG shipments table
                    try:
                        cur.execute(
                            "SELECT origin, destination FROM shipments WHERE efj = %s LIMIT 1",
                            (email["efj"],)
                        )
                        row = cur.fetchone()
                        if row and row.get("origin") and row.get("destination"):
                            lane = f"{row['origin']} → {row['destination']}"
                        else:
                            lane = ""
                    except Exception:
                        lane = ""

                # Send email alert to assigned rep
                rep_email = _get_rep_email_for_efj(email["efj"])
                _raw_sender = email.get("sender", "")
                _cust_name = _raw_sender.split("<")[0].strip().strip('"') if "<" in _raw_sender else _raw_sender.split("@")[0]
                _subject_parts = [p for p in [_cust_name[:30] if _cust_name else None,
                                               lane[:40] if lane else None] if p]
                _alert_subject = "CSL Alert: No reply — " + " | ".join(_subject_parts) if _subject_parts else f"CSL Alert: No reply to customer quote — {email['efj'] or 'No EFJ'}"
                _send_alert_email(
                    rep_email,
                    _alert_subject,
                    f"""<div style="font-family:Arial,sans-serif;max-width:600px">
<h3 style="color:#F59E0B;margin:0 0 12px 0">Customer Quote — No Reply for 15+ Minutes</h3>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:6px 12px;font-weight:bold;color:#555">EFJ</td><td style="padding:6px 12px">{email['efj'] or 'Not matched'}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#555">From</td><td style="padding:6px 12px">{email['sender']}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#555">Subject</td><td style="padding:6px 12px">{email['subject']}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#555">Lane</td><td style="padding:6px 12px">{lane or 'N/A'}</td></tr>
<tr><td style="padding:6px 12px;font-weight:bold;color:#555">Received</td><td style="padding:6px 12px">{email['sent_at']}</td></tr>
</table>
<p style="color:#888;font-size:12px;margin-top:16px">This customer has been waiting 15+ minutes for a response. Please reply ASAP.</p>
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
        # Check Content-Disposition / Content-ID for inline detection
        disposition = ""
        has_content_id = False
        for h in payload.get("headers", []):
            hname = h.get("name", "").lower()
            if hname == "content-disposition":
                disposition = h.get("value", "").lower()
            elif hname == "content-id":
                has_content_id = True
        is_inline = "inline" in disposition or (has_content_id and "attachment" not in disposition)
        attachments.append({
            "filename": payload["filename"],
            "attachment_id": payload["body"]["attachmentId"],
            "mime_type": payload.get("mimeType", ""),
            "size": payload.get("body", {}).get("size", 0),
            "is_inline": is_inline,
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
        and not is_junk_attachment(a["filename"], a.get("size"))
        and not (a.get("is_inline") and Path(a["filename"]).suffix.lower() in (".png", ".jpg", ".jpeg", ".gif"))
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

                # AI vision fallback for ambiguous docs
                if doc_type in ("other", "unclassified"):
                    ai_type = ai_classify_document(data, att["filename"], sender=sender, subject=subject, efj=efj)
                    if ai_type != "other":
                        doc_type = ai_type

                # Compute file hash for dedup
                import hashlib as _hl
                file_hash = _hl.sha256(data).hexdigest()

                # Insert into load_documents (same table as manual uploads)
                conn = get_conn()
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        # Check for duplicate by hash
                        cur.execute(
                            "SELECT 1 FROM load_documents WHERE efj=%s AND file_hash=%s",
                            (efj, file_hash),
                        )
                        if cur.fetchone():
                            log.info("  Skipping duplicate document: %s for %s", att["filename"], efj)
                            conn.commit()
                            continue

                        cur.execute(
                            "INSERT INTO load_documents (efj, doc_type, filename, original_name, size_bytes, uploaded_by, file_hash) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                            (efj, doc_type, safe_name, att["filename"], len(data), "inbox_scanner", file_hash),
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

        # Auto-advance billing if POD + carrier_invoice now present
        if saved_docs and efj:
            try:
                check_and_advance_billing(efj, get_conn, put_conn)
            except Exception as _adv_err:
                log.error("  Billing advance check failed for %s: %s", efj, _adv_err)

        # Classify the email itself (carrier/customer quote, lane detection)
        email_type, lane = classify_email_type(sender, subject, body_preview, has_attachments, attachment_names=attachment_names)
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
                       ON CONFLICT (gmail_message_id) DO UPDATE
                         SET gmail_message_id = EXCLUDED.gmail_message_id
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

        # ── Carrier rate response detection (thread-based) ──
        if final_email_type in (None, 'carrier_rate', 'general', 'customer_rate') and gmail_thread_id:
            try:
                conn2 = get_conn()
                with conn2.cursor() as cur2:
                    cur2.execute(
                        "SELECT 1 FROM email_threads WHERE gmail_thread_id = %s AND email_type = 'rate_outreach' LIMIT 1",
                        (gmail_thread_id,),
                    )
                    if cur2.fetchone():
                        final_email_type = 'carrier_rate_response'
                        ai_priority = max(ai_priority or 0, 4)
                        log.info("  ↑ Upgraded to carrier_rate_response (reply to rate_outreach thread)")
                        if email_thread_db_id:
                            with conn2.cursor() as cur3:
                                cur3.execute(
                                    "UPDATE email_threads SET email_type = %s, priority = %s WHERE id = %s",
                                    (final_email_type, ai_priority, email_thread_db_id),
                                )
                            conn2.commit()
                put_conn(conn2)
            except Exception as e:
                log.error("  Rate response detection failed: %s", e)

        # ── Queue payment alerts for batched digest (not per-load) ──
        if final_email_type == 'payment_escalation' and email_thread_db_id:
            _payment_alert_queue.append({
                "efj": efj, "sender": sender, "subject": subject,
                "summary": ai_summary_text or "CarrierPay flagged non-payment",
            })

        # ── Digest queue insert for actionable types ──
        _DIGEST_TYPES = {'carrier_rate_response', 'carrier_invoice',
                         'carrier_rate_confirmation', 'pod'}
        if final_email_type in _DIGEST_TYPES and email_thread_db_id:
            try:
                conn3 = get_conn()
                with conn3.cursor() as cur4:
                    cur4.execute(
                        """INSERT INTO inbox_digest_queue
                           (efj, email_type, sender, subject, summary, rep)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON CONFLICT DO NOTHING""",
                        (efj, final_email_type, sender, subject[:200],
                         ai_summary_text or '', ai_suggested_rep or ''),
                    )
                conn3.commit()
                put_conn(conn3)
            except Exception as e:
                log.error("  Digest queue insert failed: %s", e)

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
        email_type, lane = classify_email_type(sender, subject, body_preview, has_attachments, attachment_names=attachment_names)
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
                       ON CONFLICT (gmail_message_id) DO UPDATE
                         SET gmail_message_id = EXCLUDED.gmail_message_id
                       RETURNING id""",
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


        # ── PTD# contextual inheritance (DSV/Apple forwarded bids) ──────────
        if final_email_type in (None, 'unknown') and body_preview:
            ptd_match = PTD_PATTERN.search(body_preview)
            if not ptd_match:
                ptd_match = PTD_PATTERN.search(subject or "")
            if ptd_match:
                ptd_ref = ptd_match.group(0)
                try:
                    conn_ptd = get_conn()
                    with conn_ptd.cursor(cursor_factory=RealDictCursor) as cur_ptd:
                        cur_ptd.execute(
                            """SELECT email_type, efj, lane, account
                               FROM email_threads
                               WHERE subject ILIKE %s
                                  OR body_preview ILIKE %s
                               ORDER BY sent_at DESC LIMIT 1""",
                            (f"%{ptd_ref}%", f"%{ptd_ref}%"),
                        )
                        parent = cur_ptd.fetchone()
                    if parent and parent.get("email_type"):
                        inherited_type = parent["email_type"]
                        inherited_efj  = parent.get("efj")
                        inherited_lane = parent.get("lane") or lane
                        final_email_type = inherited_type
                        log.info("  PTD# match: %s → inherited type=%s efj=%s",
                                 ptd_ref, inherited_type, inherited_efj or "none")
                        if email_thread_db_id:
                            conn_upd = get_conn()
                            with conn_upd.cursor() as cur_upd:
                                cur_upd.execute(
                                    "UPDATE unmatched_inbox_emails SET email_type=%s, lane=%s WHERE id=%s",
                                    (inherited_type, inherited_lane, email_thread_db_id),
                                )
                            conn_upd.commit()
                            put_conn(conn_upd)
                    else:
                        # PTD# found but no parent — still mark as customer_rate (DSV bid)
                        final_email_type = 'customer_rate'
                        log.info("  PTD# found (%s) but no parent thread — tagging customer_rate", ptd_ref)
                        if email_thread_db_id:
                            conn_upd = get_conn()
                            with conn_upd.cursor() as cur_upd:
                                cur_upd.execute(
                                    "UPDATE unmatched_inbox_emails SET email_type='customer_rate' WHERE id=%s",
                                    (email_thread_db_id,),
                                )
                            conn_upd.commit()
                            put_conn(conn_upd)
                    put_conn(conn_ptd)
                except Exception as e_ptd:
                    log.error("  PTD# lookup failed: %s", e_ptd)

        # ── Carrier rate response detection for unmatched (thread-based) ──
        if final_email_type in (None, 'carrier_rate', 'general', 'customer_rate') and gmail_thread_id:
            try:
                conn_r = get_conn()
                with conn_r.cursor() as cur_r:
                    cur_r.execute(
                        "SELECT 1 FROM email_threads WHERE gmail_thread_id = %s AND email_type = 'rate_outreach' LIMIT 1",
                        (gmail_thread_id,),
                    )
                    if cur_r.fetchone():
                        final_email_type = 'carrier_rate_response'
                        ai_priority = max(ai_priority or 0, 4)
                        log.info("  ↑ Upgraded unmatched to carrier_rate_response")
                        if email_thread_db_id:
                            with conn_r.cursor() as cur_u:
                                cur_u.execute(
                                    "UPDATE unmatched_inbox_emails SET email_type = %s, priority = %s WHERE id = %s",
                                    (final_email_type, ai_priority, email_thread_db_id),
                                )
                            conn_r.commit()
                put_conn(conn_r)
            except Exception as e:
                log.error("  Unmatched rate response detection failed: %s", e)

        # ── Digest queue insert for actionable unmatched types ──
        _DIGEST_TYPES_U = {'carrier_rate_response', 'carrier_invoice',
                           'carrier_rate_confirmation', 'pod'}
        if final_email_type in _DIGEST_TYPES_U and email_thread_db_id:
            try:
                conn_d = get_conn()
                with conn_d.cursor() as cur_d:
                    cur_d.execute(
                        """INSERT INTO inbox_digest_queue
                           (efj, email_type, sender, subject, summary, rep)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON CONFLICT DO NOTHING""",
                        (None, final_email_type, sender, subject[:200],
                         ai_summary_text or '', ai_suggested_rep or ''),
                    )
                conn_d.commit()
                put_conn(conn_d)
            except Exception as e:
                log.error("  Unmatched digest queue insert failed: %s", e)

        # Tag-based actions work even for unmatched emails
        effective_sender = original_sender or sender
        if email_type == "carrier_info":
            auto_index_carrier_from_email(effective_sender, subject, body_preview)
        if email_type == "warehouse_rate":
            extract_warehouse_rate_from_email(effective_sender, subject, body_preview)



# ── Sent Mail Scanner (for reply detection) ──────────────────────────

def scan_sent_messages(service):
    """Scan sent folder for outbound messages to track CSL replies."""
    log.info("Scanning sent messages for reply tracking...")

    try:
        # Get sent messages from last 24 hours
        import datetime as dt
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).strftime("%Y/%m/%d")
        result = service.users().messages().list(
            userId="me",
            q=f"in:sent after:{since}",
            maxResults=100,
        ).execute()
    except Exception as e:
        log.error("Gmail API sent list failed: %s", e)
        return 0

    messages = result.get("messages", [])
    if not messages:
        log.info("No recent sent messages")
        return 0

    stored = 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for msg_meta in messages:
                msg_id = msg_meta["id"]
                try:
                    # Check if already indexed
                    cur.execute(
                        "SELECT 1 FROM sent_messages WHERE gmail_message_id = %s",
                        (msg_id,)
                    )
                    if cur.fetchone():
                        continue

                    # Fetch message metadata
                    msg = service.users().messages().get(
                        userId="me", id=msg_id, format="metadata",
                        metadataHeaders=["To", "Subject", "Date"],
                    ).execute()

                    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                    thread_id = msg.get("threadId", "")
                    recipient = headers.get("To", "")
                    subject = headers.get("Subject", "")

                    # For rate_outreach subjects, fetch full body for quote extraction
                    _rate_signals = bool(__import__('re').search(
                        r'rate|rfq|quote|pricing|dray|lane', (subject or '').lower()))
                    if _rate_signals:
                        try:
                            full_msg = service.users().messages().get(
                                userId="me", id=msg_id, format="full").execute()
                            _body = get_body_preview(full_msg.get("payload", {}))
                            _lane = _extract_lane(subject or "", _body or "")
                            _efj = match_email_to_efj(subject or "", _body or "", [])
                            _qdata = extract_outbound_quote(subject, _body or "", recipient, _lane)
                            if _qdata and _qdata.get("total_estimate"):
                                save_outbound_quote(None, _efj, _lane, recipient, _qdata, None)
                        except Exception as _e:
                            log.warning("  Outbound quote extraction failed for %s: %s", msg_id[:12], _e)

                    # Parse date
                    sent_at = None
                    date_str = headers.get("Date", "")
                    if date_str:
                        try:
                            from email.utils import parsedate_to_datetime
                            sent_at = parsedate_to_datetime(date_str)
                        except Exception:
                            pass

                    cur.execute(
                        """INSERT INTO sent_messages
                           (gmail_message_id, gmail_thread_id, recipient, subject, sent_at)
                           VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT (gmail_message_id) DO NOTHING""",
                        (msg_id, thread_id, recipient[:500] if recipient else None,
                         subject[:500] if subject else None, sent_at),
                    )
                    stored += 1

                except Exception as e:
                    log.warning("Error indexing sent message %s: %s", msg_id[:12], e)

        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error("sent_messages batch insert failed: %s", e)
    finally:
        put_conn(conn)

    if stored:
        log.info("Indexed %d new sent messages", stored)
    return stored


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

    _flush_payment_alerts()
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
            scan_sent_messages(service)
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
