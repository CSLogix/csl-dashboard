# CSL Document Tracker

Automated document tracking system for CSL Logistics (Evans Delivery / EFJ Operations). Monitors forwarded emails from Outlook shared inboxes, identifies BOL and POD attachments, matches them to loads using reference numbers synced from Google Sheets, and serves a web dashboard for the team.

## Architecture

```
Outlook Shared Inboxes (3)
    → Outlook Forwarding Rules →
        Dedicated Gmail Account
            → Python Bot (Gmail API)
                → Classifies attachments (BOL or POD)
                → Matches to load via reference lookup table
                → Stores files on VPS filesystem
                → Writes to PostgreSQL
                    → FastAPI Dashboard
                        → Team sees status per doc + hyperlinks to view
```

## Setup

### 1. Install PostgreSQL

```bash
sudo apt install postgresql postgresql-contrib
```

### 2. Create Database

```bash
sudo -u postgres psql -f setup_db.sql
```

If the `\gexec` command fails (older psql versions), manually create the database first:

```bash
sudo -u postgres createuser csl_admin -P   # enter password when prompted
sudo -u postgres createdb csl_doc_tracker -O csl_admin
sudo -u postgres psql -d csl_doc_tracker -f setup_db.sql
```

### 3. Create Document Storage Directory

```bash
sudo mkdir -p /opt/csl-docs/files
sudo chown $USER /opt/csl-docs/files
```

### 4. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 5. Set Up Google Cloud Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use existing)
3. Enable **Gmail API** and **Google Sheets API**
4. Create OAuth 2.0 credentials for a Desktop Application
5. Download the credentials JSON and save as `credentials.json` in this directory
6. For Google Sheets access, use the existing service account at `/root/csl-credentials.json`

### 6. Configure Environment

```bash
cp .env.example .env
# Edit .env with your actual values
```

### 7. First-Time Gmail OAuth

Run the Gmail monitor once interactively to complete the OAuth flow:

```bash
python3 gmail_monitor.py
```

This will open a browser window to authorize Gmail access. After authorization, a `token.json` file will be saved for future use.

### 8. Set Up Outlook Forwarding

Configure forwarding rules on all three Outlook shared inboxes:
- **EFJ-Operations** → forward to your Gmail account
- **Boviet** → forward to your Gmail account
- **Tolead** → forward to your Gmail account

### 9. Configure Sheet Column Mapping

Edit `config.py` and update the `SHEET_COLUMN_MAPPING` dictionary to match your actual Google Sheet column headers:

```python
SHEET_COLUMN_MAPPING = {
    "EFJ #": "efj",
    "Container#": "container",
    "BOL / Booking#": "bol",
    "PO#": "po",
    "Customer Ref": "company_ref",
}
```

### 10. Start Services

```bash
./start.sh
```

This starts three background processes:
- **sheets_sync.py** — syncs load references from Google Sheets every 5 minutes
- **gmail_monitor.py** — scans Gmail for new emails every 2 minutes
- **app.py** — FastAPI dashboard on port 8080

### Stop Services

```bash
./stop.sh
```

## Dashboard

Access the dashboard at `http://<server-ip>:8080`

Features:
- View all active loads with BOL/POD status
- Click document links to view PDFs in browser
- Filter by account (EFJ-Operations, Boviet, Tolead)
- Review and manually match unmatched emails
- Auto-refreshes every 60 seconds
- Dark theme, mobile-friendly

## Project Structure

```
csl-doc-tracker/
├── config.py                 # All configuration loaded from .env
├── database.py               # PostgreSQL connection pool and query functions
├── gmail_monitor.py          # Gmail API email scanning and attachment downloading
├── document_classifier.py    # BOL vs POD detection logic
├── load_matcher.py           # Reference lookup table and matching logic
├── sheets_sync.py            # Google Sheets → syncs load references into database
├── app.py                    # FastAPI dashboard and document serving
├── setup_db.sql              # Database initialization script
├── requirements.txt          # Python dependencies
├── .env.example              # Template for environment variables
├── start.sh                  # Launch all services
├── stop.sh                   # Stop all services
└── README.md                 # This file
```

## How Load Matching Works

The system matches incoming emails to loads using a lookup table of all known reference numbers:

1. **sheets_sync.py** reads the Google Sheet every 5 minutes and builds a mapping of reference numbers (EFJ#, container#, BOL#, PO#, etc.) to load IDs in the database.
2. **load_matcher.py** maintains an in-memory lookup table for fast matching.
3. When an email arrives, the subject line is checked against all known references.
4. Attachment filenames are also checked as a fallback.
5. If no match is found, the email goes to the "Unmatched" queue for manual review.

## Troubleshooting

### Gmail token expired
Delete `token.json` and run `python3 gmail_monitor.py` interactively to re-authorize.

### Database connection errors
Check that PostgreSQL is running: `sudo systemctl status postgresql`

### Google Sheets 429 quota errors
The sync interval can be increased in `.env` via `SHEET_SYNC_INTERVAL_MINUTES`.

### Logs
Check the log files in the project directory:
- `csl_doc_tracker.log` — main application log
- `sheets_sync.log` — sheets sync output
- `gmail_monitor.log` — email monitor output
- `dashboard.log` — web server output
