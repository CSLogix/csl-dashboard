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

# Doc type classification by filename
DOC_CLASSIFIERS = [
    (re.compile(r"bol|bill.of.lading|b/l", re.IGNORECASE), "bol"),
    (re.compile(r"pod|proof.of.delivery|delivery.receipt", re.IGNORECASE), "pod"),
    (re.compile(r"invoice|inv\b", re.IGNORECASE), "invoice"),
    (re.compile(r"rate.?con|rate.?confirm", re.IGNORECASE), "rate"),
    (re.compile(r"screenshot|screen.?shot|snap", re.IGNORECASE), "screenshot"),
]

# Senders that indicate carrier invoices
CARRIER_PAY_SENDERS = re.compile(
    r"carrier.?pay|carrierpay|carrier.?support|freight.?pay|comcheck|triumph|rts|efs|wex",
    re.IGNORECASE,
)

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
                    UNIQUE(gmail_message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_email_threads_efj
                    ON email_threads(efj);
                CREATE INDEX IF NOT EXISTS idx_email_threads_efj_sent
                    ON email_threads(efj, sent_at DESC);
            """)
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
                    assigned_efj    TEXT
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


def classify_doc_type(filename, sender="", subject=""):
    """Classify document type from filename, sender, and subject context."""
    # Carrier invoice: sender is a carrier pay service, or subject says carrier invoice
    if CARRIER_PAY_SENDERS.search(sender) or CARRIER_PAY_SENDERS.search(subject):
        # If the attachment looks like an invoice, it's a carrier invoice
        if re.search(r"invoice|inv\b|receipt|payment|remit", filename, re.IGNORECASE):
            return "carrier_invoice"
        # Even non-invoice-named attachments from carrier pay are likely carrier invoices
        return "carrier_invoice"

    for pattern, doc_type in DOC_CLASSIFIERS:
        if pattern.search(filename):
            return doc_type
    return "other"


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
                doc_type = classify_doc_type(att["filename"], sender=sender, subject=subject)

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

        # Insert into email_threads
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO email_threads
                       (efj, gmail_thread_id, gmail_message_id, message_id,
                        subject, sender, recipients, body_preview,
                        has_attachments, attachment_names, sent_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING""",
                    (efj, gmail_thread_id, msg_id, rfc_message_id,
                     subject, sender, recipients, body_preview[:500],
                     has_attachments, ", ".join(attachment_names), sent_at),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error("  email_threads insert failed: %s", e)
        finally:
            put_conn(conn)

    else:
        log.info("UNMATCHED: %s [%s] from %s", msg_id[:12], subject[:60], sender[:40])

        # Store in unmatched table
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO unmatched_inbox_emails
                       (gmail_message_id, gmail_thread_id, subject, sender,
                        recipients, body_preview, has_attachments,
                        attachment_names, sent_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING""",
                    (msg_id, gmail_thread_id, subject, sender,
                     recipients, body_preview[:500], has_attachments,
                     ", ".join(attachment_names), sent_at),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error("  unmatched insert failed: %s", e)
        finally:
            put_conn(conn)


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
