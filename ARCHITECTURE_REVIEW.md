# CSLogix Bot — Architecture Review (2026-03-12)

## Current State Assessment

### System Overview
- **Infrastructure**: Hostinger VPS, Ubuntu/Linux, no containerization
- **Database**: PostgreSQL (`csl_doc_tracker`) for dashboard; JSON state files for monitors
- **Backend**: Flask (`upload_server.py`, 576 lines) + FastAPI (`csl-doc-tracker/app.py`, 9,794 lines)
- **Background Workers**: 5 independent Python monitors (csl_bot, ftl_monitor, export_monitor, boviet_monitor, tolead_monitor)
- **Frontend**: React 19 + Vite 7 + Tailwind 4 + Zustand, built to static/dist/
- **Process Mgmt**: systemd for monitors, bash PID script for dashboard, cron for csl_bot

### By the Numbers
| Metric | Value |
|--------|-------|
| Main API file (app.py) | 9,794 lines |
| Route handlers in app.py | 128 |
| Patch scripts in patches/ | 142 |
| Monitor scripts | 5 (csl_bot, ftl, export, boviet, tolead) |
| Total Python files | 40+ |
| State files (JSON) | 5 |
| Dashboard components | 6 React files |

---

## Critical Issues (Ranked by Impact)

### 1. Monolithic API — `app.py` at 9,794 Lines

**Problem**: A single FastAPI file contains 128 route handlers covering shipments, emails, documents, quotes, macropoint, dashboard serving, and more. Every patch script that modifies this file risks breaking unrelated endpoints.

**Solution**: Split into FastAPI `APIRouter` modules:
```
csl-doc-tracker/
├── app.py                  # ~50 lines: imports + include_router()
├── routes/
│   ├── shipments.py        # Load CRUD, status updates
│   ├── emails.py           # Inbox, threads, reply, classification
│   ├── documents.py        # Uploads, preview, classification
│   ├── quotes.py           # Quote builder, Rate IQ
│   ├── macropoint.py       # Tracking, screenshots
│   ├── reports.py          # Daily summary, weekly profit
│   └── dashboard.py        # SPA serving, legacy views
├── database.py             # Already separate (good)
├── auth.py                 # Already separate (good)
└── config.py               # Already separate (good)
```

**Effort**: 2-3 hours (mechanical refactor)
**Risk**: Low — FastAPI APIRouter is a drop-in replacement

### 2. ~~Patch Script Accumulation~~ ✅ DONE (2026-03-19)

Removed 10 dead patch/backup scripts: `cmi_patch*.py`, `patch_*.py`, `csl_bot_backup.py`, `mk_export.py`, `safe_cleanup.sh`, `csl-doc-tracker/patch_webhook_gaps.py`. All had been applied and were not imported anywhere.

### 3. ~~No Reverse Proxy~~ ✅ DONE (2026-03-19)

Nginx config added at `nginx/csl-dashboard.conf`. Includes gzip, rate limiting, security headers, SSE support, and proxy rules for dashboard (8080), webhook (5000), and upload server (5001). TLS via certbot after deploy.

### 4. ~~Missing Root-Level Dependency Management~~ ✅ DONE (2026-03-19)

Root `requirements.txt` now covers all dependencies for both dashboard and monitors, including `httplib2` used by `csl_inbox_scanner.py`.

---

## Lower Priority Improvements

### 5. Email Polling (5-minute interval)

**Current**: `csl_inbox_scanner.py` polls Gmail every 300 seconds via `time.sleep()`.
**Ideal**: Google Pub/Sub push notifications for real-time email processing.
**Effort**: 4-6 hours (GCP project setup, watch renewal, webhook endpoint)
**Recommendation**: Only pursue if 5-minute delay is causing business problems.

### 6. Vite Production Build

**Status**: Already solved. `npm run build` outputs to `static/dist/`, and FastAPI serves it.
**Gap**: Ensure dev mode (`npm run dev`) is never used in production.

### 7. ~~Process Management Consolidation~~ ✅ DONE (2026-03-19)

All services now have systemd unit files in `systemd/`. Long-running services (9 .service files) and scheduled jobs (5 .timer files) replace the old mix of cron + bash PID scripts. Deploy with `sudo ./deploy-services.sh`.

---

## Recommended Roadmap

1. **Now**: Split `app.py` into routers (highest ROI, eliminates patch fragility)
2. **This week**: Clean up patches/, add root requirements.txt
3. **Next sprint**: Add nginx reverse proxy with TLS
4. **When needed**: Gmail Pub/Sub, systemd consolidation

---

## Session Log: 2026-03-20

### Auto-Archive Hardening

**Problem**: `billed_closed` loads set via Google Sheet by reps were never archived in PG because only the v2/legacy API endpoints had archive gates. Bot monitors and sheet sync wrote the status via `pg_update_shipment()` which had no archive logic.

**Fix**: Added auto-archive to `pg_update_shipment()` in `csl_pg_writer.py` — when status is set to `billed_closed` or `billed_and_closed`, immediately sets `archived = TRUE`. Also added terminal-status auto-archive to `csl_sheet_sync.py` so Tolead/Boviet loads with completed statuses get archived during sync cycles.

**Empty Return grace period**: Already implemented in `csl_bot.py` — checks `updated_at` age >24h before archiving `Returned to Port` loads. Working as designed; team confusion was about lack of visibility, not a bug.

### Account Name Mapping

**Problem**: Google Sheet tab named "Texas" but frontend `REP_ACCOUNTS` constant expects "Texas International". Loads appeared in PG with `account = "Texas"` and were invisible under Radka's Texas International card. Direct PG `UPDATE` was reverted on every sheet sync/bot cycle.

**Fix**: Added `_ACCOUNT_NAME_MAP` dict to `csl_pg_writer.py` and `ACCOUNT_NAME_MAP` to `shared.py`. Both normalize `"Texas"` → `"Texas International"` at write time, so the translation is durable across all write paths (bot monitors, sheet sync, dashboard API).

### Dashboard Pill Undercounting

**Problem**: RepDashboardView account cards showed `incoming` (at_port/on_vessel/pending), `active` (in_transit/out_for_delivery), `behind`, and `done`. Statuses like `scheduled`, `at_yard`, `at_terminal` fell into none of these buckets, causing MGF to show "2 in, 1 done" when 7 loads existed.

**Fix**: Expanded `incoming` to include `scheduled`, `at_yard`, `at_terminal`. Expanded `active` to include `dispatched`, `departed_pickup`. All loads now map to at least one pill category.

### Stale Vite Build

**Problem**: AddForm already had LTL move type, SSL/Vessel field, and Pickup/Delivery Time inputs in source, but the deployed bundle was stale. Multiple old JS bundles were sitting in `static/dist/assets/` alongside the current one.

**Fix**: Clean deploy — `rm -f assets/*` before copying new build output. Fresh `npm run build` + SCP to server. Always clean old assets before deploying to prevent Cloudflare serving cached stale bundles.
