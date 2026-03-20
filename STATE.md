# STATE.md — CSLogix Sprint State (2026-03-20 07:50 ET)

## 1. Current Architecture

### Frontend
- **Framework**: Vite + React + TypeScript (migrated from JSX monolith)
- **Source**: `C:\Users\jsfel\Downloads\csl-dashboard-preview\dashboard\src\`
- **Build target**: `/root/csl-bot/csl-doc-tracker/static/dist/` on `root@187.77.217.61`
- **Deploy**: `npm run build` → scp `dist/index.html` + `dist/assets/*` → `systemctl restart csl-dashboard`
- **Legacy views retained**: `CustomerPortal.jsx`, `ReportUploadView.jsx` (still JSX, not yet migrated)

### Data Layer — Postgres as Primary
- **Default data source**: `store.ts` → `dataSource: "postgres"`
- **Read path**: `fetchData()` calls `/api/v2/shipments` → Postgres query on `shipments` table
- **Write path**: All mutations route through `/api/v2/load/{efj}/*` endpoints:
  - `POST /api/v2/load/{efj}/status` — status updates
  - `POST /api/v2/load/{efj}/update` — inline field edits (origin, destination, dates, driver, etc.)
  - `POST /api/v2/load/add` — new shipment creation
  - `DELETE /api/v2/load/{efj}` — shipment deletion
- **Sheets fallback**: Toggle in Zustand store; when `dataSource === "sheets"`, reads from `/api/shipments` (Google Sheets via gspread). Yellow banner displayed in UI.
- **v2 endpoints**: Defined in `/root/csl-bot/csl-doc-tracker/routes/v2.py` — includes `/api/v2/shipments`, `/api/v2/stats`, `/api/v2/accounts`, `/api/v2/team`, `/api/rep-scoreboard`

### Dual-Write (Monitors → PG + Sheets)
- `csl_bot.py` (Dray Import), `export_monitor.py` (Dray Export), `ftl_monitor.py` (FTL) all import `csl_pg_writer` and `csl_sheet_writer`
- PG writes are stable and unaffected by load
- **Google Sheets is hitting 429 Quota Exceeded errors** on dual-write (`Read requests per minute per user`). Observed during the 7:30 AM import scanner run. PG writes completed normally for the same rows. This validates the migration direction — Sheets is the bottleneck, PG handles it cleanly.
- Tolead monitor also dual-writes (LAX only; ORD/JFK/DFW on separate sheets)

### Services (all on `root@187.77.217.61`)
| Service | Status | Notes |
|---------|--------|-------|
| csl-dashboard (port 8080) | HEALTHY | FastAPI + React SPA, `TimeoutStopSec=5` patched |
| csl-ftl | HEALTHY | Polls every 30 min |
| csl-export | HEALTHY | Polls every 60 min |
| csl-boviet | HEALTHY | Sleeps weekends |
| csl-tolead | HEALTHY | ORD/JFK/LAX/DFW, polls every 20 min |
| csl-inbox | HEALTHY | Gmail scanner, polls every 5 min |
| csl-upload (port 5001) | HEALTHY | Flask web UI |
| csl-webhook | DISABLED | Retired — webhooks route through csl-dashboard on 8080 |
| csl-import (cron) | HEALTHY | 7:30 AM + 1:30 PM ET, Mon-Fri. Fixed this session. |

### Database
- PostgreSQL on localhost
- ~987 shipments, ~737 tracking events
- Tables: `shipments`, `tracking_events`, `load_documents`, `load_notes`, `email_threads`, `unmatched_inbox_emails`, `unbilled_orders`, `driver_contacts`, `rate_quotes`
- Stale test record `EFJ-TEST999` exists with null `account` — safe to delete

---

## 2. Completed Fixes (Last 2 Hours)

### Session 1 (6:00 AM - 7:15 AM)

1. **csl-webhook retired**: Killed orphaned process on port 5003, `systemctl stop && disable csl-webhook`. All Macropoint webhook traffic confirmed flowing through csl-dashboard on port 8080.

2. **Tolead NoneType crash**: `tolead_monitor.py` line 398 — `scrape_macropoint()` returned `mp_status=None` when `cant_make_it=True`, bypassing the null check. Fix: `mp_status = mp_status or ""` guard.

3. **Macropoint trigger f-string bug**: `routes/macropoint.py` line 51 — `trigger_script = f"""..."""` was evaluating `{cookies_file}` as a Python f-string variable before `.replace()` could substitute it, causing `NameError`. Fix: removed `f` prefix.

4. **Macropoint Session panel restored**: Re-added to `AnalyticsView.tsx` — 3-column bottom grid (Recent Errors, Google Sheets Connections, Macropoint Session). Full OTP flow: trigger → enter code → save cookies.

5. **TypeScript frontend unified**: Merged true TS source from `csl-dashboard` into `CSLogix_Bot` master. Build pipeline: `npm install` → `npm run build` → scp → restart.

### Session 2 (7:25 AM - 7:45 AM)

6. **`playwright_stealth` import crash** (`csl_bot.py` line 14): Package updated on server, renamed `Stealth` class to `stealth_sync()` function. Fix: `from playwright_stealth import stealth_sync` and replaced all 5 call sites (`_stealth.apply_stealth_sync(page)` → `stealth_sync(page)`). Removed dead `_stealth = Stealth()` instantiation.

7. **`sh` UnboundLocalError** (`csl_bot.py` ~line 2422): `run_once()` refactored to "Postgres mode" but archive path still called `_get_rep_for_account(sh, tab_name)`. Variable `sh` was only assigned inside nested try blocks for sheet writes, never at function scope. Fix: added gspread `sh` initialization block at line 2162 (after `new_check = {}`), with `sh = None` fallback on error.

8. **Systemd shutdown hang**: `csl-dashboard.service` was using default 90s `TimeoutStopSec`. Open HTTP/WebSocket connections kept the process alive. Fix: `TimeoutStopSec=5` injected into `[Service]` section, `systemctl daemon-reload` applied.

9. **Zombie dry-run processes**: Two stale `python3 csl_bot.py --dry-run` processes from 2026-03-19 holding headless Chromium instances. Confirmed dead (no longer in process table).

10. **Dependabot vulnerabilities**: `npm audit fix` in `dashboard/` — 4 vulnerabilities (1 critical, 3 high) → 0. `package-lock.json` committed and pushed (`1a3e432` → `main`).

---

## 3. The 'Missing Analytics' Problem

### Current State of AnalyticsView.tsx
`AnalyticsView.tsx` is **exclusively a DevOps/System Health board**. It contains:
- Service health cards (healthy/degraded/crash_loop/down/idle)
- Cron job status (success/partial/failed/overdue)
- Summary metrics: Emails Sent (24h), Crashes (24h), Cycles Run (24h), Services OK
- Recent Errors log (from journalctl parsing)
- Google Sheets connection status
- Macropoint Session panel (OTP flow)

### What's Missing
There are **zero business analytics visualizations** in the entire frontend:
- No revenue charts (trend, by account, by rep)
- No load volume over time
- No delivery performance / on-time rate
- No move type breakdown (Dray Import vs Export vs FTL)
- No average dwell time / LFD compliance
- No charting library installed (`recharts`, `chart.js`, `d3` — none present in `package.json`)

### Where Revenue Data Exists Today
- `OverviewView.tsx` shows revenue as **inline text** in rep cards and account cards (sortable by loads/revenue)
- `UnbilledView.tsx` shows revenue per unbilled order
- `PlaybooksView.tsx` shows `combined_lane_revenue` per playbook
- All are plain numbers in table cells — no time-series, no trends, no charts

### What Needs to Happen
1. Install a charting library (recharts recommended — lightweight, React-native)
2. Build backend endpoints for time-series data (`/api/v2/analytics/revenue`, `/api/v2/analytics/volume`, etc.) querying PG `shipments` table with date grouping
3. Create a `BusinessAnalyticsView.tsx` or repurpose a tab for: revenue trend (30/60/90 day), load volume by week, delivery performance, account breakdown, rep performance comparison

---

## 4. Next Immediate Objectives

### A. Business Analytics Views
Build the revenue/volume/performance charts the team needs. This is the highest-visibility gap — the "Analytics" tab exists but shows ops health, not business health.

### B. CI/CD Pipeline (deploy.yml)
Currently deploying via manual `npm run build` → scp → restart. Need a GitHub Actions workflow that:
- Triggers on push to `main`/`master`
- Runs `npm run build` in `dashboard/`
- SCPs dist to server
- Restarts `csl-dashboard` via SSH
- (Backend deploys already have a partial `deploy.yml` from PR #1 — needs completion)

### C. Monitor PG Under Friday Load
Friday is historically the heaviest day (end-of-week status updates, archive rushes, report uploads). Watch for:
- `shipments` table query latency under concurrent dashboard reads + monitor writes
- Connection pool exhaustion (current: default psycopg2, no pooling layer)
- The 1:30 PM cron run hitting alongside FTL/export/tolead polls

### D. Minor Cleanup (Low Priority)
- gspread `DeprecationWarning`: `worksheet.update()` argument order changed — swap `range_name` and `values` params
- `SyntaxWarning: invalid escape sequence '\d'` in `csl_bot.py` line 1373 — JS regex embedded in Python string, needs raw string prefix
- Delete `EFJ-TEST999` from PG `shipments` table
- Kill or configure the Sheets dual-write retry logic to back off faster on 429s

---

## 5. Key File Locations

| What | Where |
|------|-------|
| Frontend source | `C:\Users\jsfel\Downloads\csl-dashboard-preview\dashboard\src\` |
| Backend app | `/root/csl-bot/csl-doc-tracker/app.py` |
| v2 routes (PG reads/writes) | `/root/csl-bot/csl-doc-tracker/routes/v2.py` |
| Health routes | `/root/csl-bot/csl-doc-tracker/routes/health.py` |
| Import scanner | `/root/csl-bot/csl_bot.py` |
| PG writer | `/root/csl-bot/csl_pg_writer.py` |
| Sheet writer | `/root/csl-bot/csl_sheet_writer.py` |
| Sheet sync | `/root/csl-bot/csl-doc-tracker/csl_sheet_sync.py` |
| Zustand store | `dashboard/src/store.ts` |
| AnalyticsView | `dashboard/src/views/AnalyticsView.tsx` |
| OverviewView | `dashboard/src/views/OverviewView.tsx` |
| systemd service | `/etc/systemd/system/csl-dashboard.service` |
| Import cron log | `/tmp/csl_import.log` |
