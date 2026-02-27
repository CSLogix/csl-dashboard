"""
Configuration module for CSL Document Tracker.
All settings loaded from .env file with sensible defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Gmail API ---
GMAIL_CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
GMAIL_TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "token.json")
GMAIL_MONITORED_ACCOUNT = os.getenv("GMAIL_MONITORED_ACCOUNT", "csl.doctracker@gmail.com")
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

# --- Google Sheets ---
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_SHEETS_CREDENTIALS_PATH", "/root/csl-credentials.json"
)
SHEET_TAB_NAME = os.getenv("SHEET_TAB_NAME", "Active Loads")
SHEET_SYNC_INTERVAL_MINUTES = int(os.getenv("SHEET_SYNC_INTERVAL_MINUTES", "5"))

# Google Sheet column mapping: header name -> reference type.
# Fill in with actual column headers from your sheet.
# reference_type values: "efj", "container", "po", "bol", "company_ref"
SHEET_COLUMN_MAPPING = {
    "EFJ #": "efj",
    "Container#": "container",
    "BOL / Booking#": "bol",
    # "PO#": "po",
    # "Customer Ref": "company_ref",
}

# Additional columns to pull for load metadata
SHEET_CUSTOMER_REF_COLUMN = os.getenv("SHEET_CUSTOMER_REF_COLUMN", "")
SHEET_CUSTOMER_NAME_COLUMN = os.getenv("SHEET_CUSTOMER_NAME_COLUMN", "")

# Tabs to skip when syncing from the sheet
SHEET_SKIP_TABS = {
    "Sheet 4",
    "DTCELNJW",
    "Account Rep",
    "Completed Eli",
    "Completed Radka",
}

# --- PostgreSQL ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "csl_doc_tracker")
DB_USER = os.getenv("DB_USER", "csl_admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "changeme")

# --- Document Storage ---
DOCUMENT_STORAGE_PATH = Path(os.getenv("DOCUMENT_STORAGE_PATH", "/opt/csl-docs/files"))

# --- Dashboard ---
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

# --- Polling ---
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "120"))

# --- Mailbox origin labels ---
# Map forwarded-from addresses or subject prefixes to account names.
MAILBOX_ORIGIN_MAP = {
    "efj-operations@evansdelivery.com": "EFJ-Operations",
    "boviet@evansdelivery.com": "Boviet",
    "tolead@evansdelivery.com": "Tolead",
}

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "csl_doc_tracker.log")
