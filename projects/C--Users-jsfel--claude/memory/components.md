# CSL Bot — Component Architecture

## System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Google Sheet                             │
│  (19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0)           │
│                                                              │
│  Account Tabs: DHL, DSV, MGF, Kripke, Rose, EShipping, ...  │
│  Archive Tabs: Completed Eli, Completed Radka                │
│  Config Tab:   Account Rep (name → email mapping)            │
└──────┬──────────────┬──────────────┬─────────────────────────┘
       │              │              │
       ▼              ▼              ▼
┌──────────┐  ┌──────────────┐  ┌──────────┐
│ csl_bot  │  │export_monitor│  │ftl_monitor│
│ (Import) │  │  (Export)    │  │  (FTL)    │
└────┬─────┘  └──────┬───────┘  └─────┬────┘
     │               │                │
     ▼               ▼                ▼
┌──────────┐  ┌──────────────┐  ┌──────────┐
│Macropoint│  │ JsonCargo    │  │Macropoint│
│ Scraper  │  │ API          │  │ Scraper  │
│(stealth) │  │              │  │(plain)   │
└────┬─────┘  └──────┬───────┘  └─────┬────┘
     │               │                │
     └───────┬───────┴────────┬───────┘
             ▼                ▼
      ┌────────────┐  ┌─────────────┐
      │ Gmail SMTP │  │ JSON State  │
      │ Alerts     │  │ Files       │
      └────────────┘  └─────────────┘

┌─────────────────────────────────────────┐
│        upload_server.py (port 5001)      │
│  /         → Report upload (xlsx/csv)    │
│  /macropoint → BOL PDF → create shipment │
│  /mp-login   → Re-auth Macropoint 2FA   │
└──────────────────┬──────────────────────┘
                   │
                   ▼
         ┌──────────────────┐
         │macropoint_creator│
         │ (Playwright)     │
         └──────────────────┘

┌─────────────────────────────────────────┐
│        webhook.py (port 5000)            │
│  /macropoint-webhook → logs payloads     │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│   csl-doc-tracker/ (PR #1, unmerged)     │
│  app.py          → FastAPI dashboard     │
│  gmail_monitor   → Polls Gmail for docs  │
│  document_classifier → BOL/POD detection │
│  load_matcher    → EFJ# matching         │
│  sheets_sync     → Sheet status writeback│
│  database.py     → PostgreSQL backend    │
└─────────────────────────────────────────┘
```

---

## Component Details

### Monitor Components (always running)

| Component | File | Trigger | Data Source | Output |
|---|---|---|---|---|
| Dray Import Monitor | `csl_bot.py` | Continuous poll | Macropoint (Playwright + stealth) | Sheet update, email alert, archive |
| Dray Export Monitor | `export_monitor.py` | Every 60 min | JsonCargo API | Sheet update, email alert, archive |
| FTL Monitor | `ftl_monitor.py` | Every 30 min | Macropoint (Playwright) | Sheet update, email alert, archive |

### Web Components (always running)

| Component | File | Port | Purpose |
|---|---|---|---|
| Upload Server | `upload_server.py` | 5001 | Report uploads, Macropoint creation, session renewal |
| Webhook Receiver | `webhook.py` | 5000 | Logs inbound Macropoint webhook payloads |

### Utility Components (run on demand)

| Component | File | Purpose |
|---|---|---|
| Macropoint Creator | `macropoint_creator.py` | Automates new shipment creation in Macropoint UI |
| Session Saver | `mp_login_save.py` | Logs into Macropoint, saves cookies for automation |
| Code Generator | `mk_export.py` | Regenerates export_monitor.py from embedded source |

### Planned Components (unmerged branches)

| Component | Branch | Purpose |
|---|---|---|
| LFD Alert | `claude/add-claude-documentation-xhgMM` | Warns when Last Free Day approaches without pickup |
| Doc Tracker | `claude/csl-doc-tracker-hrZQh` | Full document tracking system (Gmail → classify → match → dashboard) |
| Daily Summary | `claude/ftl-daily-summary-pxJpv` | Morning digest email of all active FTL loads |

---

## Data Flow Per Move Type

### Dray Import Flow
```
Sheet row (Status = "Tracking Waiting for Update")
  → Read Col C hyperlink (Macropoint URL)
  → Playwright + stealth scrapes tracking page
  → Extract: ETA, LFD, Return Date, Status
  → Compare vs last_check.json
  → If changed: update sheet (Cols I, J, K, L, M, O, P)
  → If changed: email account rep
  → If delivered: archive to Completed tab
```

### Dray Export Flow
```
Sheet row (Move Type = "Dray Export")
  → Read ERD (Col I) + Cutoff (Col J)
  → Compare vs export_state.json
  → If cutoff < 48hrs: alert
  → If rail keywords detected: flag for manual check
  → JsonCargo API: BOL → Container# lookup
  → JsonCargo API: Container → gate-in event check
  → If gate-in confirmed: archive + email
```

### FTL Flow
```
Sheet row (Move Type = "FTL")
  → Sheets API v4: get real hyperlink from Col C
  → Playwright loads Macropoint tracking page
  → Parse stop events + planned times
  → Map to status dropdown value (priority order)
  → Write: pickup (K), delivery (L), status (M), notes (O)
  → Email rep on first detection of each status
  → If delivered: archive to rep's Completed tab
  → If no EFJ#: send "Please Pro Load" reminder
```

---

## State Management

All state is file-based JSON — no database for the core monitors.

| File | Key Format | Values | Used By |
|---|---|---|---|
| `last_check.json` | `"account:container"` | `{eta, lfd, return, status}` | csl_bot.py |
| `export_state.json` | `"tab:efj:container"` | `{erd, cutoff}` | export_monitor.py |
| `ftl_sent_alerts.json` | `"efj\|load_num"` | `[list of sent statuses]` | ftl_monitor.py |
| `ftl_email_alerts.json` | `"load_id_status"` | `true` | ftl_email_alerts.py (legacy) |
| `mp_cookies.json` | browser cookies | session auth | macropoint_creator.py |

---

## Email Alert Matrix

| Monitor | Alert Type | Trigger | Recipient |
|---|---|---|---|
| Import | Status/Date Change | ETA, LFD, Return, or Status differs from last_check | Account rep + CC ops |
| Import | LFD Approaching (branch) | LFD within threshold, no pickup | Account rep + CC ops |
| Export | Date Change | ERD or Cutoff changed | Account rep + CC ops |
| Export | Cutoff Warning | Cutoff < 48 hours | Account rep + CC ops |
| Export | Container Assigned | BOL lookup returned container# | Account rep + CC ops |
| Export | Archive | Gate-in confirmed | Account rep + CC ops |
| FTL | Status Change | First detection of each status | Account rep + CC ops (except Boviet) |
| FTL | Pro Load Reminder | Missing EFJ# in Col A | Account rep |
| FTL | Daily Summary (branch) | Once per morning | Account rep + CC ops |

---

## External Service Dependencies

| Service | Protocol | Auth | Used For |
|---|---|---|---|
| Google Sheets | gspread + API v4 | Service account JSON | Read/write load data |
| Macropoint | Playwright (browser) | Session cookies | Scrape tracking status |
| JsonCargo | REST API | API key header | Container/BOL lookup, event tracking |
| Gmail SMTP | SMTP/TLS port 587 | App password | Send alert emails |
| Gmail API (doc tracker) | OAuth2 | OAuth token | Poll for document attachments |
| PostgreSQL (doc tracker) | TCP | Local connection | Store document metadata |
