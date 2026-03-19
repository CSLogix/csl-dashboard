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

### 3. No Reverse Proxy

**Problem**: FastAPI/Uvicorn runs directly on port 8080. No TLS termination, no gzip, no connection buffering.

**Solution**: Add nginx as reverse proxy:
- TLS via Let's Encrypt (certbot)
- Gzip for static assets
- Proxy pass to uvicorn on localhost:8080
- Rate limiting for API endpoints

**Effort**: 30 minutes
**Risk**: Low

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

### 7. Process Management Consolidation

**Current**: Mix of systemd, bash PID scripts, and cron.
**Ideal**: All services managed by systemd with proper unit files.
**Effort**: 1 hour

---

## Recommended Roadmap

1. **Now**: Split `app.py` into routers (highest ROI, eliminates patch fragility)
2. **This week**: Clean up patches/, add root requirements.txt
3. **Next sprint**: Add nginx reverse proxy with TLS
4. **When needed**: Gmail Pub/Sub, systemd consolidation
