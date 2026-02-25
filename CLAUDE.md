# CSL Bot — Project Documentation

## Overview

CSL Bot is an automated logistics operations system for Evans Delivery / EFJ Operations. It monitors freight loads across three move types — **Dray Import**, **Dray Export**, and **FTL (Full Truckload)** — using a shared Google Sheet as the source of truth. The bot scrapes Macropoint for live tracking data, queries the JsonCargo API for container status, writes updates back to the sheet, sends email alerts to account reps, and archives completed loads.

---

## Repository Layout

```
/root/csl-bot/
├── csl_bot.py              # Main Dray Import monitor (Macropoint scraper + sheet updater)
├── export_monitor.py       # Dray Export monitor (JsonCargo API + cutoff alerts)
├── ftl_monitor.py          # FTL monitor (Macropoint scraper, pickup/delivery tracking)
├── ftl_email_alerts.py     # Legacy supplementary email alert module for FTL
├── macropoint_creator.py   # Playwright automation to create new Macropoint shipments
├── upload_server.py        # Flask web UI (port 5001): report uploads, Macropoint creation
├── webhook.py              # Flask webhook receiver (port 5000): logs Macropoint payloads
├── mp_login_save.py        # One-time script: logs into Macropoint and saves session cookies
├── mk_export.py            # Utility: writes/regenerates export_monitor.py from embedded code
│
├── last_check.json         # State: last seen ETA/LFD/Return/Status per import container
├── export_state.json       # State: last seen ERD/Cutoff per export row
├── ftl_sent_alerts.json    # State: FTL alert dedup (keyed by efj|load_num → [statuses sent])
├── ftl_email_alerts.json   # State: legacy FTL email dedup (keyed by load_id_status)
├── mp_cookies.json         # Saved Macropoint browser session cookies
├── webhook_payloads.log    # Raw log of all inbound webhook POSTs
└── csl_bot.log             # Runtime log for csl_bot.py
```

---

## Infrastructure & Credentials

| Resource | Value / Location |
|---|---|
| Google Sheet ID | `19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0` |
| Google credentials | `/root/csl-credentials.json` (service account JSON) |
| Gmail SMTP user | `jfeltzjr@gmail.com` |
| Gmail app password | Hardcoded in each script |
| CC address | `efj-operations@evansdelivery.com` |
| Macropoint URL | `https://visibility.macropoint.com/` |
| Macropoint login | `john.feltz@evansdelivery.com` |
| JsonCargo API key | `wiD6ZZoQLstkmQl4nRsGTYwe93cr_cpHboDTu15VLRQ` |
| JsonCargo base URL | `https://api.jsoncargo.com/api/v1` |
| Webhook basic auth | user: `cslbot` / password in webhook.py |

---

## Google Sheet Structure

### Tab Layout

- **Account tabs** (one per customer): DHL, DSV, MGF, Kripke, Rose, EShipping, IWS, MAO, Boviet, etc.
- **Account Rep tab**: Maps account name → rep name + rep email. Loaded once at startup.
- **Completed Eli**: Archive for loads handled by rep Eli.
- **Completed Radka**: Archive for loads handled by rep Radka.
- **Skipped tabs**: `Sheet 4`, `DTCELNJW`, `Account Rep`, `Completed Eli`, `Completed Radka`

### Column Layout (all tabs)

| Col | Index (0-based) | gspread (1-based) | Field |
|-----|-----------------|-------------------|-------|
| A | 0 | 1 | EFJ # (e.g. `EFJ106996`) |
| B | 1 | 2 | Move Type (`FTL` / `Dray Export` / `Dray Import`) |
| C | 2 | 3 | Container# or Load# — hyperlinked to Macropoint URL |
| D | 3 | 4 | BOL / Booking# / MBL# |
| E | 4 | 5 | SSL / Vessel name |
| F | 5 | 6 | Carrier |
| G | 6 | 7 | Origin |
| H | 7 | 8 | Destination |
| I | 8 | 9 | ETA (imports) / ERD (exports) |
| J | 9 | 10 | LFD (imports) / Cutoff (exports) |
| K | 10 | 11 | Pickup Date |
| L | 11 | 12 | Delivery Date |
| M | 12 | 13 | Status (dropdown) |
| N | 13 | 14 | Driver / Truck |
| O | 14 | 15 | Bot Notes (written by automation) |
| P | 15 | 16 | Return to Port date (imports only) |

---

## Scripts

### `csl_bot.py` — Dray Import Monitor

Polls the sheet for rows where **Col B** contains import move types and **Col M (Status) = "Tracking Waiting for Update"**. Uses **Playwright with playwright-stealth** to scrape the Macropoint tracking URL in Col C.

**What it does per row:**
1. Reads ETA (Col I), LFD (Col J), Return Date (Col P), Status (Col M) from the sheet.
2. Compares against last state in `last_check.json` (keyed by `account:container`).
3. Scrapes Macropoint URL for live status.
4. Writes updated values back to the sheet (ETA, LFD, Return, Status, Notes).
5. Emails the account rep if status changes or dates change.
6. Archives rows to the appropriate Completed tab when load is delivered/complete.

**Key constants:**
- `STATUS_FILTER = "Tracking Waiting for Update"` — only processes rows with this status in Col M
- `LAST_CHECK_FILE` = `last_check.json`

---

### `export_monitor.py` — Dray Export Monitor

Polls every **60 minutes** for rows where **Col B = "Dray Export"**.

**What it does per row:**
1. Detects ERD (Col I) and Cutoff (Col J) date changes vs. previous state in `export_state.json`.
2. Alerts if cutoff is within **48 hours** (`CUTOFF IN Xhr`).
3. Detects rail containers via keyword matching (rail, ramp, intermodal, BNSF, Union Pacific, CSX) and flags for manual check.
4. Uses **JsonCargo API** to:
   - Look up container number from BOL/booking# if Col C is not yet a container number.
   - Track container for gate-in status events.
5. When gate-in is confirmed → copies row to Completed tab, deletes from source tab, sends archive email.
6. Writes notes to Col O with alert reasons and timestamps.

**JsonCargo flow:**
- Detects shipping line from vessel/carrier name (`SSL_LINE_MAP`).
- If Col C is a booking# (not `[A-Z]{4}\d{7}` format): calls `/containers/bol/{booking}/` → gets container#.
- If container# known: calls `/containers/{container}/` → checks events for gate-in keywords.
- Gate-in keywords: `full load on rail for export`, `gate in full`, `full in`, `received for export transfer`, `loaded on vessel`, `vessel departure`.

**Email types sent:**
- `send_export_alert` — ERD/Cutoff date change or approaching cutoff
- `send_container_assigned_email` — when container# is first discovered from BOL lookup
- `send_archive_email` — when gate-in confirmed and row archived

---

### `ftl_monitor.py` — FTL Monitor

Polls every **30 minutes** for rows where **Col B = "FTL"**.

**What it does per row:**
1. Gets Macropoint URL from Col C hyperlink (fetched via Sheets API v4, not display text).
2. Uses headless **Playwright** (no stealth) to load the Macropoint tracking page.
3. Parses page text to extract stop events, planned times, and status.
4. Maps parsed status to a Col M dropdown value.
5. Writes pickup date → Col K, delivery date → Col L, status → Col M, notes → Col O.
6. Never overwrites an already-populated K or L cell.
7. Sends email alert to account rep on first detection of each status (deduped via `ftl_sent_alerts.json`).
8. Archives delivered rows to the rep's Completed tab.

**Macropoint status detection logic** (priority order):
| Detected | Col M Dropdown |
|---|---|
| FraudGuard / phone unresponsive | `Driver Phone Unresponsive` |
| "Tracking Completed Successfully" | `Delivered` |
| Stop 2 Departed | `Departed Delivery` |
| Stop 2 Arrived | `Arrived at Delivery` |
| Stop 1 Departed | `Departed Pickup - En Route` → `In Transit` |
| Stop 1 Arrived | `Driver Arrived at Pickup` → `At Pickup` |
| Now past planned pickup time, no arrival | `Running Late` → `Running Behind` |
| "Tracking behind / behind schedule" text | `Tracking Behind Schedule` → `Running Behind` |
| No events yet | `Tracking Waiting for Update` |
| "Ready to track" / "Tracking Now" | *(ignored — no alert)* |

**PRO alert:** If a row has no EFJ# in Col A, a daily email is sent to the rep with subject "Please Pro Load ASAP" to prompt assigning the internal reference number.

**Special case — Boviet account:** CC to `efj-operations@evansdelivery.com` is skipped for this account.

**Archive routing:**
- Rep name contains "eli" → `Completed Eli`
- Rep name contains "radka" → `Completed Radka`
- Neither → writes a note to Col O, no archive

---

### `macropoint_creator.py` — Macropoint Shipment Creator

Creates a new Macropoint shipment via Playwright browser automation using saved session cookies.

**Flow:**
1. Loads cookies from `mp_cookies.json`.
2. Navigates to Macropoint, checks for session expiry (redirects to auth.gln.com).
3. Fills in: tracking phone (`4437614954`), load/PRO#, tracking duration (5 days), frequency (15 min), method (Driver Cell Phone).
4. Fills pickup stop: name, address, city, state, zip, appointment time.
5. Fills delivery stop: same fields.
6. Saves and returns the resulting tracking URL.
7. Called as a subprocess from `upload_server.py` with JSON args via `sys.argv[1]`.

**Timezone mapping:** State abbreviation → IANA timezone → Macropoint dropdown label (e.g., `CA` → `America/Los_Angeles` → `(UTC-08:00) Pacific Time (US & Canada)`).

---

### `upload_server.py` — Flask Web UI (port 5001)

Provides a browser-accessible interface for operations staff.

**Routes:**

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Show report upload form |
| `/upload` | POST | Parse Excel (.xlsx) or CSV; update Sheet by EFJ# match |
| `/macropoint` | GET/POST | Upload BOL PDF → parse → review → create Macropoint |
| `/mp-login` | GET/POST | Trigger Macropoint 2FA login, enter OTP, save cookies |
| `/upload-pdf-test` | GET/POST | Debug endpoint for testing PDF parsing |

**Report upload (`/upload`):**
- Parses uploaded file, finds rows starting with `EFJ`.
- Extracts: container# (col B), LFD (col C), pickup (col D), MBL# (col M), vessel (col N).
- Searches all non-skipped sheet tabs for matching EFJ# in Col A.
- Writes to **Col C** (container), **Col D** (MBL), **Col E** (vessel), **Col J** (LFD), **Col K** (pickup) — only if the cell is currently empty.

**Macropoint creation (`/macropoint`):**
- Step 1: Upload PDF → `pdfplumber` extracts EFJ#, PRO#, tab name, pickup/delivery addresses + appointments.
- Step 2: Review/edit parsed data in a form.
- Step 3: Submit → runs `macropoint_creator.py` as subprocess → gets tracking URL → writes `=HYPERLINK(url, pro#)` to Col C of matching row.

---

### `webhook.py` — Webhook Receiver (port 5000)

Simple Flask app that accepts POST requests at `/macropoint-webhook`. Requires Basic Auth. Logs every payload to `webhook_payloads.log` with timestamp.

---

### `mp_login_save.py` — Macropoint Session Saver

One-time interactive script. Logs into Macropoint with username/password, handles OTP 2FA, saves session cookies to `mp_cookies.json`.

```bash
python3 mp_login_save.py <OTP>
# or
python3 mp_login_save.py   # prompts for OTP interactively
```

---

### `ftl_email_alerts.py` — Legacy Email Alert Module

An older standalone alert module (not called by ftl_monitor.py's main loop). Can be imported for `check_and_alert_on_status()`. Reads `GMAIL_APP_PASSWORD` from environment. Triggers on statuses: `Driver Phone Unresponsive`, `Tracking - Waiting for Update`, `Tracking Waiting for Update`. Deduplication state in `ftl_email_alerts.json`.

---

### `mk_export.py` — Code Generator Utility

A bootstrap/deployment script that contains the old export_monitor code as an embedded string and writes it to `export_monitor.py`. Used for redeployment only; `export_monitor.py` is now the live version.

---

## State Files

| File | Keying | Purpose |
|---|---|---|
| `last_check.json` | `"account:container"` | Last seen ETA, LFD, Return, Status for import rows |
| `export_state.json` | `"tab:efj:container"` | Last seen ERD and Cutoff for export rows |
| `ftl_sent_alerts.json` | `"efj\|load_num"` → `[statuses]` | Prevents duplicate FTL emails per status |
| `ftl_email_alerts.json` | `"load_id_status"` | Legacy dedup for ftl_email_alerts.py |
| `mp_cookies.json` | N/A | Macropoint browser session cookies |

---

## Poll Intervals

| Script | Interval |
|---|---|
| `csl_bot.py` (imports) | Runs continuously / per-cycle (not a fixed sleep loop — check script for exact timing) |
| `export_monitor.py` | 60 minutes (`POLL_INTERVAL = 3600`) |
| `ftl_monitor.py` | 30 minutes (`POLL_INTERVAL = 30 * 60`) |

---

## Dependencies

```
playwright           # Browser automation (headless Chromium)
playwright_stealth   # Anti-bot detection (used in csl_bot.py only)
gspread              # Google Sheets API client
google-auth          # Google service account credentials
requests             # HTTP calls (JsonCargo API, Sheets API v4 hyperlinks)
flask                # Web server (upload_server.py, webhook.py)
pdfplumber           # PDF text extraction (upload_server.py /macropoint route)
openpyxl             # Excel file parsing (upload_server.py /upload route)
```

---

## Running the Services

```bash
# Import tracking bot
python3 /root/csl-bot/csl_bot.py

# Export monitor
python3 /root/csl-bot/export_monitor.py

# FTL monitor
python3 /root/csl-bot/ftl_monitor.py

# Web UI (report uploads + Macropoint creation)
python3 /root/csl-bot/upload_server.py   # port 5001

# Webhook receiver
python3 /root/csl-bot/webhook.py         # port 5000

# Re-authenticate Macropoint (when session expires)
python3 /root/csl-bot/mp_login_save.py <OTP>
# or via browser: http://<server>:5001/mp-login
```

---

## Common Operations

### Macropoint session expired
Session cookies in `mp_cookies.json` expire periodically. To renew:
1. Visit `http://<server>:5001/mp-login` in a browser, or
2. Run `python3 mp_login_save.py` on the server.

### Upload a CSL report to update the sheet
1. Visit `http://<server>:5001/`
2. Upload the `.xlsx` or `.csv` file from CSL.
3. Bot matches by EFJ# and fills empty cells in C, D, E, J, K.

### Manually create a Macropoint shipment
1. Visit `http://<server>:5001/macropoint`
2. Upload BOL PDF → review parsed data → click Create.

### Debug FTL Macropoint parsing
Set `DEBUG = True` in `ftl_monitor.py` — saves page inner text to `/tmp/mp_debug_<load>.txt` for inspection.

### Google Sheets 429 quota errors
`ftl_monitor.py` includes `_retry_on_quota()` which retries up to 3 times with 60/120/180s backoff. Other scripts will print a WARNING and continue.

---

## Key Accounts (from state files)

Active accounts seen in production: **DHL, DSV, MGF, Kripke, Rose, EShipping, IWS, MAO, Boviet**
