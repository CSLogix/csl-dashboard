"""
Gmail monitor for CSL Document Tracker.
Scans a Gmail inbox for forwarded emails, downloads attachments,
classifies them, matches them to loads, and stores them.
"""

import base64
import logging
import os
import re
import sys
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config
import database as db
import document_classifier
import load_matcher

log = logging.getLogger(__name__)


def _get_gmail_service():
    """Authenticate and return a Gmail API service object."""
    creds = None
    token_path = config.GMAIL_TOKEN_PATH

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, config.GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                config.GMAIL_CREDENTIALS_PATH, config.GMAIL_SCOPES,
            )
            creds = flow.run_local_server(
                host="0.0.0.0",
                port=8090,
                open_browser=False,
                success_message="Authorization complete! You can close this tab.",
            )
            print("Gmail authorization successful.")
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _detect_mailbox_origin(headers: dict) -> str:
    """
    Determine which Outlook shared inbox the email was forwarded from.
    Checks X-Forwarded-To, X-Original-To, From, and subject prefixes.
    """
    # Check forwarding headers
    for header_name in ("X-Forwarded-To", "X-Original-To", "Reply-To", "From"):
        value = headers.get(header_name, "").lower()
        for addr, label in config.MAILBOX_ORIGIN_MAP.items():
            if addr.lower() in value:
                return label

    # Check subject for prefix clues
    subject = headers.get("Subject", "").lower()
    if "boviet" in subject:
        return "Boviet"
    if "tolead" in subject:
        return "Tolead"

    return "EFJ-Operations"  # default


def _parse_email_date(headers: dict) -> datetime | None:
    """Extract the email date from headers."""
    date_str = headers.get("Date", "")
    if date_str:
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            pass
    return None


def _save_attachment(
    load_number: str, filename: str, data: bytes
) -> str:
    """
    Save an attachment to the filesystem.
    Returns the relative file path from DOCUMENT_STORAGE_PATH.
    Handles duplicates by appending a counter.
    """
    load_dir = config.DOCUMENT_STORAGE_PATH / load_number
    load_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    target = load_dir / filename

    # Handle duplicates
    counter = 1
    while target.exists():
        target = load_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    target.write_bytes(data)
    # Return path relative to storage root for DB storage
    return str(target.relative_to(config.DOCUMENT_STORAGE_PATH))


def _process_message(service, msg_id: str):
    """Process a single Gmail message: download attachments, classify, match, store."""
    # Check dedup
    if db.is_email_processed(msg_id):
        return

    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()

    # Parse headers into a dict
    headers = {}
    for h in msg.get("payload", {}).get("headers", []):
        headers[h["name"]] = h["value"]

    subject = headers.get("Subject", "")
    sender = headers.get("From", "")
    email_date = _parse_email_date(headers)
    mailbox_origin = _detect_mailbox_origin(headers)

    # Collect all attachment parts
    attachments = []
    _collect_attachments(msg.get("payload", {}), attachments)

    # Log the email
    db.log_email(
        message_id=msg_id,
        mailbox_origin=mailbox_origin,
        subject=subject,
        sender=sender,
        received_date=email_date,
        attachments_count=len(attachments),
    )

    if not attachments:
        db.mark_email_processed(msg_id)
        return

    # Filter to relevant file types
    relevant = [
        (part, fname)
        for part, fname in attachments
        if document_classifier.is_relevant_attachment(fname)
    ]

    if not relevant:
        db.mark_email_processed(msg_id)
        return

    # Try to match the email to a load
    load_id = load_matcher.match_subject(subject)

    # If no match from subject, try attachment filenames
    if load_id is None:
        for _, fname in relevant:
            load_id = load_matcher.match_text(fname)
            if load_id is not None:
                break

    if load_id is None:
        # Store as unmatched
        attachment_names = ", ".join(fname for _, fname in relevant)
        db.insert_unmatched_email(
            message_id=msg_id,
            subject=subject,
            sender=sender,
            received_date=email_date,
            attachment_names=attachment_names,
        )
        db.mark_email_processed(msg_id)
        log.info("Unmatched email: subject='%s', attachments=%s", subject, attachment_names)
        return

    # Get load info for file storage
    load = db.get_load_by_id(load_id)
    load_number = load["load_number"]

    # Get email body snippet for classification context
    body_snippet = msg.get("snippet", "")

    for part, filename in relevant:
        # Download attachment data
        att_data = _download_attachment(service, msg_id, part)
        if att_data is None:
            continue

        # Classify
        doc_type = document_classifier.classify(filename, subject, body_snippet)

        if doc_type == "UNCLASSIFIED":
            # Store as BOL by default but flag in notes
            log.warning(
                "Unclassified attachment '%s' for load %s — storing as UNCLASSIFIED",
                filename, load_number,
            )

        # Save file
        rel_path = _save_attachment(load_number, filename, att_data)

        # Only store BOL or POD in documents table
        if doc_type in ("BOL", "POD"):
            db.insert_document(
                load_id=load_id,
                doc_type=doc_type,
                file_path=rel_path,
                file_name=filename,
                email_subject=subject,
                email_from=sender,
                email_date=email_date,
                source_mailbox=mailbox_origin,
            )
            log.info(
                "Stored %s for load %s: %s", doc_type, load_number, filename
            )
        else:
            # Store unclassified docs too, but mark the type
            db.insert_document(
                load_id=load_id,
                doc_type="UNCLASSIFIED",
                file_path=rel_path,
                file_name=filename,
                email_subject=subject,
                email_from=sender,
                email_date=email_date,
                source_mailbox=mailbox_origin,
            )

    db.mark_email_processed(msg_id, matched_load_id=load_id)
    log.info("Processed email for load %s: subject='%s'", load_number, subject)


def _collect_attachments(payload: dict, results: list):
    """Recursively collect (part, filename) tuples from a message payload."""
    filename = payload.get("filename", "")
    body = payload.get("body", {})

    if filename and body.get("attachmentId"):
        results.append((payload, filename))

    for part in payload.get("parts", []):
        _collect_attachments(part, results)


def _download_attachment(service, msg_id: str, part: dict) -> bytes | None:
    """Download attachment bytes from Gmail API."""
    att_id = part.get("body", {}).get("attachmentId")
    if not att_id:
        return None
    try:
        att = service.users().messages().attachments().get(
            userId="me", id=att_id, messageId=msg_id
        ).execute()
        data = att.get("data", "")
        return base64.urlsafe_b64decode(data)
    except Exception:
        log.exception("Failed to download attachment %s from message %s", att_id, msg_id)
        return None


def scan_inbox(service):
    """
    Scan the Gmail inbox for new messages with attachments.
    Uses the Gmail search query to find unread messages with attachments.
    """
    try:
        results = service.users().messages().list(
            userId="me",
            q="has:attachment is:unread",
            maxResults=50,
        ).execute()
    except Exception:
        log.exception("Failed to list Gmail messages")
        return

    messages = results.get("messages", [])
    if not messages:
        log.debug("No new messages with attachments")
        return

    log.info("Found %d messages to process", len(messages))

    for msg_meta in messages:
        msg_id = msg_meta["id"]
        try:
            _process_message(service, msg_id)
            # Mark as read after processing
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
        except Exception:
            log.exception("Error processing message %s", msg_id)


def run_loop():
    """Run the Gmail scan loop."""
    log.info("Gmail monitor starting (interval=%d sec)", config.SCAN_INTERVAL_SECONDS)
    service = _get_gmail_service()

    while True:
        try:
            scan_inbox(service)
        except Exception:
            log.exception("Unhandled error in Gmail scan cycle")
            # Re-authenticate if needed
            try:
                service = _get_gmail_service()
            except Exception:
                log.exception("Failed to re-authenticate Gmail")
        time.sleep(config.SCAN_INTERVAL_SECONDS)


def main():
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_FILE),
        ],
    )
    db.init_pool()
    # Ensure lookup table is populated before first scan
    load_matcher.rebuild_lookup()
    try:
        run_loop()
    except KeyboardInterrupt:
        log.info("Gmail monitor stopped by user")
    finally:
        db.close_pool()


if __name__ == "__main__":
    main()
