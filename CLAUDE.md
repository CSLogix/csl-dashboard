# CSL Bot — Project Documentation

## Overview

CSL Bot is an automated logistics operations system for Evans Delivery / EFJ Operations. It monitors freight loads across three move types — **Dray Import**, **Dray Export**, and **FTL (Full Truckload)** — using a shared Google Sheet as the source of truth. The bot scrapes carrier tracking websites, queries the JsonCargo API for container status, writes updates back to the sheet, sends email alerts to account reps, and archives completed loads.

---

## Repository Layout

```
/root/csl-bot/
├── csl_bot.py              # Main Dray Import monitor (carrier scraper + sheet updater)
├── export_monitor.py       # Dray Export monitor (JsonCargo API + cutoff alerts)
├── ftl_monitor.py          # FTL monitor (Macropoint scraper, pickup/delivery tracking)
├── ftl_email_alerts.py     # Legacy supplementary email alert module for FTL
├── macropoint_creator.py   # Playwright automation to create new Macropoint shipments
├── upload_server.py        # Flask web UI (port 5001): report uploads, Macropoint creation
├── webhook.py              # Flask webhook receiver (port 5000): logs Macropoint payloads
├── mp_login_save.py        # One-time script: logs into Macropoint and saves session cookies
├── mk_export.py            # Utility: writes/regenerates export_monitor.py from embedded code
│
├── .env                    # All credentials (SMTP, API keys, proxy, etc.) — gitignored
├── last_check.json         # State: last seen ETA/LFD/Return/Status per import container
├── export_state.json       # State: last seen ERD/Cutoff per export row
├── ftl_sent_alerts.json    # State: FTL alert dedup (keyed by efj|load_num → [statuses sent])
├── ftl_email_alerts.json   # State: legacy FTL email dedup (keyed by load_id_status)
├── mp_cookies.json         # Saved Macropoint browser session cookies
├── webhook_payloads.log    # Raw log of all inbound webhook POSTs
├── csl_bot.log             # Runtime log for csl_bot.py
└── csl_bot.py.pre-optimization  # Backup of csl_bot.py before Stage 1-3 changes
```

---

## Infrastructure & Credentials

All secrets are centralized in `/root/csl-bot/.env` (gitignored). Scripts load via `python-dotenv`.

| Resource | Env Variable |
|---|---|
| Google Sheet ID | `SHEET_ID` |
| Google credentials | `GOOGLE_CREDENTIALS_FILE` → `/root/csl-credentials.json` |
| Gmail SMTP | `SMTP_USER`, `SMTP_PASSWORD` |
| CC address | `EMAIL_CC` |
| Macropoint login | `MACROPOINT_USER`, `MACROPOINT_PASSWORD` |
| Macropoint tracking phone | `MACROPOINT_TRACKING_PHONE` |
| Webhook basic auth | `WEBHOOK_AUTH_USERNAME`, `WEBHOOK_AUTH_PASSWORD` |
| JsonCargo API | `JSONCARGO_API_KEY` (base URL: `https://api.jsoncargo.com/api/v1`) |
| Oxylabs proxy | `PROXY_SERVER`, `PROXY_USERNAME`, `PROXY_PASSWORD` |
| Upload server auth | `UPLOAD_SERVER_USERNAME`, `UPLOAD_SERVER_PASSWORD` |
| Upload server allowed IPs | `UPLOAD_SERVER_ALLOWED_IPS` |

---

## Google Sheet Structure

### Tab Layout

- **Account tabs** (one per customer): Allround, Cadi, Boviet, DHL, DSV, EShipping, IWS, Kripke, MAO, MGF, Rose, USHA
- **Account Rep tab**: Maps account name → rep name + rep email. Loaded once at startup.
- **Completed Eli**: Archive for loads handled by rep Eli.
- **Completed Radka**: Archive for loads handled by rep Radka.
- **Skipped tabs**: `Sheet 4`, `DTCELNJW`, `Account Rep`, `Completed Eli`, `Completed Radka`

### Column Layout (all tabs)

| Col | Index (0-based) | gspread (1-based) | Field |
|-----|-----------------|-------------------|-------|
| A | 0 | 1 | EFJ # (e.g. `EFJ106996`) |
| B | 1 | 2 | Move Type (`FTL` / `Dray Export` / `Dray Import`) |
| C | 2 | 3 | Container# or Load# — hyperlinked to carrier/Macropoint URL |
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

Runs twice daily via cron (7:30 AM and 1:30 PM ET, Mon-Fri). Processes all account tabs for rows where **Col B** contains import move types. Uses Playwright with stealth for browser scraping, and JsonCargo API for Maersk/HMM containers.

**Architecture (after Stage 1-3 optimization):**

```
main()
 ├── Proxy health check (httpbin.org, 15s timeout)
 ├── For each account tab:
 │   ├── Read sheet data + hyperlinks (with sheets_retry)
 │   ├── For each Dray Import row:
 │   │   ├── dray_import_workflow() routes by carrier URL:
 │   │   │   ├── maersk.com → JsonCargo API (ssl_line=MAERSK)
 │   │   │   │   └── If "Prefix not found" → browser fallback (if proxy OK)
 │   │   │   ├── hmm21.com  → JsonCargo API (ssl_line=HMM)
 │   │   │   │   └── If "Prefix not found" → browser fallback (if proxy OK)
 │   │   │   ├── shipmentlink.com → run_shipmentlink() [browser]
 │   │   │   ├── hapag-lloyd.com  → run_hapag_lloyd()  [browser]
 │   │   │   ├── one-line.com     → run_one_line()     [browser]
 │   │   │   └── other            → run_dray_import()  [generic browser]
 │   │   └── Collect pending sheet updates
 │   └── Batch write all updates for tab (single API call)
 └── Summary
```

**Key features:**
- **Stealth**: `playwright_stealth.Stealth().apply_stealth_sync(page)` applied to all browser scrapers
- **Bot detection**: `detect_bot_block(page)` checks for Cloudflare ("Just a moment", "Attention Required") and Akamai ("Access Denied") challenges after every `page.goto()`
- **Resource blocking**: Images, fonts, CSS, and analytics domains are blocked via `page.route()` to speed up page loads
- **Proxy health check**: Tests proxy via httpbin.org before starting; skips all browser scrapers if proxy is down (API routes still run)
- **Circuit breaker**: Skips a carrier domain after 3 consecutive browser scraper failures (resets per run). Does NOT apply to API routes or proxy-down skips.
- **Google Sheets retry**: All Sheets API calls wrapped with `sheets_retry()` — exponential backoff on 429 quota errors (up to 5 retries)
- **Batched writes**: Collects all cell updates during tab processing, writes once per tab instead of per-row
- **Container trim**: `container_num.strip()` before API calls to handle trailing whitespace in sheet data

**CLI flags:**
```bash
python3 csl_bot.py                    # Full run (all tabs, writes to sheet)
python3 csl_bot.py --dry-run          # Scrape but skip sheet writes/emails
python3 csl_bot.py --tab DHL          # Process only the DHL tab
python3 csl_bot.py --tab DHL --dry-run  # Test DHL tab without writes
```

**JsonCargo API integration:**
- Reuses the same API key as `export_monitor.py` (`JSONCARGO_API_KEY` from `.env`)
- Detects shipping line from vessel/carrier text via `_SSL_LINE_MAP`
- Returns `_fallback` status for unrecognized container prefixes (SELU, BMOU, etc.) → falls back to browser scraper
- Container events parsed for status keywords: "empty return" → Returned to Port, "gate out" → Released, "discharged" → Discharged, etc.

**What it does per row:**
1. Reads container, BOL, URL, vessel, carrier from sheet (URLs from hyperlinks API)
2. Routes to appropriate scraper or API based on carrier URL domain
3. Extracts ETA, Pickup date, Return date, Status
4. Compares against last state in `last_check.json`
5. Writes updated values back to sheet (batched per tab)
6. Emails account rep on changes (if not --dry-run)
7. Archives delivered rows to Completed tab

**Key constants:**
- `STATUS_FILTER = "Tracking Waiting for Update"` — only processes rows with this status in Col M
- `LAST_CHECK_FILE = last_check.json`

---

### `export_monitor.py` — Dray Export Monitor

Polls every **60 minutes** for rows where **Col B = "Dray Export"**.

**What it does per row:**
1. Detects ERD (Col I) and Cutoff (Col J) date changes vs. previous state in `export_state.json`.
2. Alerts if cutoff is within **48 hours** (`CUTOFF IN Xhr`). Alert deduped via `cutoff_alerted` flag in state — only fires once per cutoff date. Resets if the cutoff date itself changes.
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
3. Fills in: tracking phone (from `MACROPOINT_TRACKING_PHONE`), load/PRO#, tracking duration (5 days), frequency (15 min), method (Driver Cell Phone).
4. Fills pickup stop: name, address, city, state, zip, appointment time.
5. Fills delivery stop: same fields.
6. Saves and returns the resulting tracking URL.
7. Called as a subprocess from `upload_server.py` with JSON args via `sys.argv[1]`.

**Timezone mapping:** State abbreviation → IANA timezone → Macropoint dropdown label (e.g., `CA` → `America/Los_Angeles` → `(UTC-08:00) Pacific Time (US & Canada)`).

---

### `upload_server.py` — Flask Web UI (port 5001)

Provides a browser-accessible interface for operations staff. **Protected by Basic Auth + IP whitelist.**

**Auth:** Username/password from `UPLOAD_SERVER_USERNAME`/`UPLOAD_SERVER_PASSWORD` env vars. IP whitelist from `UPLOAD_SERVER_ALLOWED_IPS` (comma-separated). Uses bcrypt for password verification.

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

## State Files

| File | Keying | Purpose |
|---|---|---|
| `last_check.json` | `"account:container"` | Last seen ETA, LFD, Return, Status for import rows |
| `export_state.json` | `"tab:efj:container"` | Last seen ERD, Cutoff, and `cutoff_alerted` flag per export row |
| `ftl_sent_alerts.json` | `"efj\|load_num"` → `[statuses]` | Prevents duplicate FTL emails per status |
| `ftl_email_alerts.json` | `"load_id_status"` | Legacy dedup for ftl_email_alerts.py |
| `mp_cookies.json` | N/A | Macropoint browser session cookies |

---

## Services & Scheduling

### systemd services (long-running)

| Service | Script | Port | Restart |
|---|---|---|---|
| `csl-ftl.service` | `ftl_monitor.py` | — | `Restart=always, RestartSec=10` |
| `csl-export.service` | `export_monitor.py` | — | `Restart=always, RestartSec=10` |
| `csl-webhook.service` | `webhook.py` | 5000 | `Restart=always, RestartSec=10` |
| `csl-upload.service` | `upload_server.py` | 5001 | `Restart=always, RestartSec=10` |
| `csl-bot.service` | `csl_bot.py` | — | `Restart=on-failure, RestartSec=300, StartLimitBurst=3` (disabled — runs via cron) |

**Disabled duplicate services:** `ftl-monitor.service`, `webhook.service`

### Cron schedule

```crontab
30 7 * * 1-5  cd /root/csl-bot && python3 csl_bot.py >> /tmp/csl_bot_cron.log 2>&1
30 13 * * 1-5 cd /root/csl-bot && python3 csl_bot.py >> /tmp/csl_bot_cron.log 2>&1
```

### Service management

```bash
systemctl status csl-ftl csl-export csl-webhook csl-upload
systemctl restart csl-ftl       # Restart FTL monitor
journalctl -u csl-export -f     # Tail export monitor logs
```

---

## Dependencies

```
playwright           # Browser automation (headless Chromium)
playwright_stealth   # Anti-bot detection (Stealth class, apply_stealth_sync)
gspread              # Google Sheets API client
google-auth          # Google service account credentials
requests             # HTTP calls (JsonCargo API, Sheets API v4 hyperlinks)
flask                # Web server (upload_server.py, webhook.py)
pdfplumber           # PDF text extraction (upload_server.py /macropoint route)
openpyxl             # Excel file parsing (upload_server.py /upload route)
python-dotenv        # Load .env credentials
bcrypt               # Password hashing (upload_server.py auth)
```

---

## Common Operations

### Test dray import bot
```bash
python3 csl_bot.py --tab DHL --dry-run    # Test one tab, no writes
python3 csl_bot.py --dry-run               # Test all tabs, no writes
```

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
- `csl_bot.py`: All Sheets calls wrapped in `sheets_retry()` — exponential backoff, up to 5 retries
- `ftl_monitor.py`: Uses `_retry_on_quota()` — retries up to 3 times with 60/120/180s backoff
- Other scripts: Print WARNING and continue

### Oxylabs proxy quota exhausted
When the proxy traffic limit is reached, `csl_bot.py` detects this via the startup health check and skips all browser-based scrapers. API routes (Maersk, HMM via JsonCargo) continue to work. Check Oxylabs dashboard for quota reset timing.

---

## Key Accounts (from state files)

Active accounts: **Allround, Cadi, Boviet, DHL, DSV, EShipping, IWS, Kripke, MAO, MGF, Rose, USHA**

---

## Change Log

### 2026-02-25 — Stages 1-3 Optimization

**csl_bot.py:**
- Applied `playwright_stealth.Stealth().apply_stealth_sync(page)` to all 4 browser scrapers (was imported but never called)
- Added `detect_bot_block(page)` — checks page title for Cloudflare/Akamai challenges after every navigation
- Added `block_resources(page)` — blocks images, fonts, CSS, analytics via `page.route()`
- Added `sheets_retry()` wrapper with exponential backoff for all Google Sheets API calls (gspread + raw requests)
- Added `CircuitBreaker` class — skips carrier domain after 3 consecutive browser scraper failures (excludes API routes)
- Routed maersk.com through JsonCargo API (was 0% success via browser — Maersk React SPA always timed out)
- Routed hmm21.com through JsonCargo API (was 100% blocked by Akamai)
- Added browser fallback for unrecognized container prefixes returned by JsonCargo ("Prefix not found")
- Added proxy health check at startup — skips browser scrapers when proxy is down
- Batched Google Sheets writes per tab (reduced API calls from ~96 to ~12)
- Added `--tab` and `--dry-run` CLI flags
- Added `.strip()` to container numbers before API calls
- Backup saved at `csl_bot.py.pre-optimization`

**export_monitor.py:**
- Fixed duplicate cutoff alert emails — added `cutoff_alerted` flag to state dict, resets when cutoff date changes

**macropoint_creator.py:**
- Fixed signature mismatch: removed unused `otp` parameter from `__main__` call

**upload_server.py:**
- Added Basic Auth (bcrypt) + IP whitelist via `@app.before_request`

**All scripts:**
- Moved all hardcoded credentials to `/root/csl-bot/.env`, loaded via `python-dotenv`

**Infrastructure:**
- Fixed systemd `csl-bot.service`: `Restart=on-failure, RestartSec=300, StartLimitBurst=3` (prevents infinite restart loops)
- Disabled duplicate services: `ftl-monitor.service`, `webhook.service`
- SSH key-based auth configured for deployment
