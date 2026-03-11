# CSL Bot — Project Memory

## Overview
CSL Bot automates logistics for Evans Delivery / EFJ Operations across Dray Import, Dray Export, and FTL shipments. **Postgres migration Phase 1-4 complete** — `shipments` table + v2 API endpoints + frontend switched + **all 3 bots dual-write to PG + Master Google Sheet**. Tolead+Boviet still on sheets (synced via cron). React dashboard at `cslogixdispatch.com/app`. **Sheet fallback toggle** deployed in AnalyticsView.

## Topic Files
- [dashboard-details.md](dashboard-details.md) — component map, alert system, status flow, server architecture
- [rateiq.md](rateiq.md) — Dray IQ, FTL IQ, OOG IQ, Scorecard, Directory
- [inbox-command-center.md](inbox-command-center.md) — thread grouping, reply detection, classification
- [macropoint-integration.md](macropoint-integration.md) — webhook flow, tracking events, GPS inference, timeline
- [patches-applied.md](patches-applied.md) — full list (67 patches)
- [tolead-hub-fix.md](tolead-hub-fix.md) — ORD/JFK/LAX/DFW column fixes
- [unbilled-orders.md](unbilled-orders.md) — schema, state machines, archive gate, tech debt

## Git — Mar 11, 2026
- **Latest `ee1488a`** (Mar 11): Margin bridge + unbilled digest + team feedback fixes
- **Repo**: `CSLogix/CSLogix_Bot` (private), single `master` branch
- **VPS, GitHub, Local** all in sync
- **`.gitignore`**: Excludes `*.bak*`, `*.pre-*`, `*.json` (except package.json), `dist/`, `uploads/`, credentials
- **State files** (`ftl_sent_alerts.json`, `last_check.json`, `export_state.json`) are runtime dedup/state — gitignored, live on VPS only

## Memory Repo — Mar 10, 2026
- **Repo**: `CSLogix/csl-claude-memory` (private) — `git@github.com:CSLogix/csl-claude-memory.git`
- **Local**: `C:\Users\jsfel\.claude` — SSH remote set, tracking `origin/master`
- **SSH key**: `~/.ssh/id_ed25519` added to GitHub (`CSLogix` account)

## Dashboard Component Map (DispatchDashboard.jsx)
Single-file React SPA (~7100 lines). Key components: `DispatchDashboard` (root), `OverviewView`, `RepDashboardView`, `DispatchView`, `InboxView`, `LoadSlideOver`, `AnalyticsView`, `UnbilledView`, `HistoryView`, `AddForm`.

## Services Architecture (as of Mar 2026)

### Systemd Services (always running)
`csl-dashboard` (8080), `csl-boviet`, `csl-tolead`, `csl-inbox`, `csl-upload` (5001), `bol-webapp` (5002)
Note: `csl-ftl` DISABLED (migrated to cron). `csl-webhook` DISABLED (migrated into app.py).

### Cron Jobs
- **Dray Import/Export** (`--once`): 7:30 AM & 1:30 PM Mon-Fri — PG + Sheet dual-write
- **FTL Monitor** (`--once`): every 30 min, 6AM-8PM Mon-Fri — PG + Sheet + webhook cache
- **Daily Summary**: 7:00 AM daily
- **Health Check**: every 15 min, 6AM-7PM
- **Macropoint Screenshots**: every 30 min, 7AM-7PM Mon-Fri
- **Vessel Schedules**: 6:00 AM & 12:00 PM Mon-Fri
- **Sheet→PG Sync**: every **3** min, 6AM-8PM (Tolead+Boviet+Master) — bumped from 10
- **Boviet Invoice Writer**: every 2 hrs on even hours, 6AM-8PM Mon-Fri → `/tmp/boviet_invoice.log`
- **Unbilled Weekly Digest**: Monday 7:15 AM ET → Janice + efj-operations CC → `/var/log/csl-unbilled-digest.log`

### Monitoring
- `cron_log_parser.py` + `health_check.py` + dashboard "Scheduled Jobs" cron cards

## Recent Bot Changes (Deployed)

### Status Writeback Fix (All Accounts) — Mar 11, 2026
- **`patch_status_writeback.py`** applied to `app.py`: v2 status endpoint (`POST /api/v2/load/{efj}/status`) now writes back to Master Sheet for non-shared accounts via `BackgroundTasks` + `_write_fields_to_master_sheet()`. Previously only Tolead/Boviet (shared accounts) got sheet writeback — Master accounts (DSV, Allround, etc.) had their dashboard status edits overwritten by the 3-min sheet→PG sync.
- **Root cause**: Status endpoint wrote to PG only; sheet kept old value; sync read sheet → overwrote PG

### Margin Bridge — Carrier Pay Auto-Extraction Pipeline — Mar 11, 2026
- **Problem**: `_shipment_row_to_dict()` omitted `customer_rate`/`carrier_pay` from API response → frontend always got undefined → 0/805 shipments had financial data despite columns existing in PG. Rate extraction pipeline (Haiku AI → `rate_quotes` table) was fully disconnected from `shipments.carrier_pay`.
- **`patch_margin_bridge.py`** applied to `app.py`:
  - Added `customer_rate`/`carrier_pay` to `_shipment_row_to_dict()` serialization
  - New `GET /api/load/{efj}/rate-quotes` endpoint (pending/accepted quotes)
  - New `POST /api/load/{efj}/apply-rate` endpoint (one-click confirm → writes to `shipments.carrier_pay` + rejects competing quotes)
  - Wired `PATCH /api/rate-iq/{id}` accept → auto-reject competing quotes for same EFJ
  - Wired `PATCH /api/inbox/{id}/quote-action` won → auto-accept linked `rate_quotes` row
- **`patch_ai_extraction_v2.py`** applied to `csl_inbox_scanner.py`:
  - Body window expanded 1200→2500 chars, regex fallback 1500→2500
  - Improved prompt with carrier-specific patterns (ignore insurance/bond, handle per-mile, sum linehaul+FSC)
  - Added `linehaul`, `accessorials`, `confidence` fields to extraction output
  - Max tokens 200→300
- **Frontend**: Rate suggestion banner in both LoadSlideOver Financials sections (main + rep). Shows carrier name + amount with "✓ Apply" button. Auto-hides when carrier_pay already populated.
- **Pipeline**: Email classified → AI extracts rate → `rate_quotes` INSERT → banner appears in slide-over → rep clicks Apply → `shipments.carrier_pay` updated → Margin Guard activates

### Unbilled Weekly Digest — Mar 11, 2026
- `unbilled_weekly_digest.py`: Outlook-safe HTML email to Janice (billing) with summary cards (total/avg age/new/cleared), aging buckets (0-7/8-14/15-30/30+), ⚠ approaching-30-day warning table, and customer breakdown with color-coded bucket counts
- Cron: Monday 7:15 AM ET → `Janice.Cortes@evansdelivery.com` (cc: efj-operations)
- 307 orders across 29 customers on first run. DSV has 11 orders approaching 30-day threshold

### Dray Daily Report Email Fix — Mar 11, 2026
- **`patch_daily_report_html.py`** applied to `dray_daily_summary.py`: Fixed Outlook-incompatible HTML — rgba→solid borders, div→table wrapper, added cellpadding/cellspacing/table-layout:fixed, font-family on all cells

### Sync Guard + PG→Sheet Write-back — Mar 11, 2026
- `patch_sync_guard.py` + `patch_writeback.py`: TOLEAD_BOVIET_SYNCABLE_FIELDS, sheet_synced_at stamps, PG trigger, cron */3, Tolead LAX + Boviet tabs write PG edits back to sheet

### Boviet Invoice Writer — Mar 11, 2026
- `boviet_invoice_writer.py`: Fills Piedra Invoice tab from MP stop times. Cron: every 2 hrs 6AM-8PM Mon-Fri

### No-Reply Alert Fix — Mar 11, 2026
- **`patch_noreply_fix.py`** applied to `csl_inbox_scanner.py`: Fixed `check_unreplied_customer_emails()` and re-enabled in `run_loop`
  - **Removed "Open Dashboard" link** — IT was blocking emails with external links
  - **Self-email filter** — bot's own alert emails (`jfeltzjr`, `CSL Alert` subject) excluded from triggering new alerts (was causing 10x spam loop)
  - **EFJ-level dedup** — same EFJ can only fire once per 2 hours (prevents multiple threads from same customer triggering separate alerts)
  - **4hr lookback cap** — won't alert on ancient emails
  - **Lane fix** — if `email_threads.lane` contains body text garbage (e.g. "dont want → proceed if he"), falls back to `shipments.origin → destination` from PG
- **DB table**: `customer_reply_alerts` (email_thread_id, efj, sender, subject, alerted_at, dismissed)

### Macropoint Alert Subject Rename — Mar 11, 2026
- **`patch_alert_subject.py`** applied to `csl_ftl_alerts.py`: Renamed email subject "FTL Alert" → "CSL Tracking" and body header "FTL Status Update" → "Tracking Update" — generic across all move types (dray, FTL, etc.)
- **Macropoint webhook delay analysis**: Arrived/Delivered events come 60-80 min late from Macropoint's side. Departed events are near-instant. Our server processes + emails within 1-2 seconds of webhook receipt.

### Margin Guard + Date Normalizer + Terminal Normalizer — Mar 10-11, 2026
- `calcMarginPct()` + red row bg when margin < 10%. `date_normalizer.py` gate in pg_update_shipment(). `terminal_normalizer.py` in csl_bot.py dray import loop. LFD/pickup fix (fallback only)

## Recent Dashboard Changes (Deployed)

### Team Feedback Session Fixes — Mar 11, 2026
- **Dispatch nav removed**: Removed from `NAV_ITEMS` sidebar. DispatchView still accessible via Overview stat card clicks (Active, Today, Yesterday, etc.)
- **Yesterday filter**: `isDateYesterday()` helper + filter clause in `filtered` useMemo + purple "YESTERDAY" stat card on Overview + "Yesterday's Activity" chip label
- **Back button**: `← Overview` button in DispatchView header, resets all filters on click
- **Overview layout reorder**: Team + Account Overview grid now renders ABOVE Today's Actions + Live Alerts (swapped the two grid rows)
- **Boviet STATUS_MAP**: Added `"ready to close": "ready_to_close"` and `"completed": "delivered"` mappings
- **Inbox density**: Default fetch reduced 7→3 days, actioned threads hidden by default, toggle buttons for both settings
- **Status save fix**: See "Status Writeback Fix" in Bot Changes above

### Financials + Margin Guard — Mar 11, 2026
- `carrier_pay NUMERIC(10,2)` added; Financials section in both LoadSlideOvers; `calcMarginPct()` + red row bg when margin < 10%

### pg_dump Backup + Auto-Token + Reply Button + Top Lanes + Public Tracking — Mar 11, 2026
- **pg_dump**: Daily backup at 3AM, 14-day retention, `/root/backups/`
- **Auto-token**: `csl_pg_writer.py` auto-inserts `public_tracking_tokens` on new load creation
- **Reply button**: `↩ Reply` in InboxView + `Reply-To` header on outbound emails via `_get_reply_to(account)`
- **Top Lanes**: `GET /api/lane-stats` + Rate IQ "Top Lanes" tab
- **Public tracking**: `GET /track/{token}` standalone Jinja2 page, `POST /api/shipments/{efj}/generate-token`, Share Link button in LoadSlideOver

### Mar 10, 2026 (condensed)
- Magic Parse modal + `POST /api/quick-parse` (Claude Sonnet 4.6). Terminal Ground Truth panel (red/blue cards). Quote Extractor v2 (hub normalization + LoadMatch). Archive routing fix (atomic rep lookup). Tolead MP URL + ghost cleanup. Daily summary `_is_this_week()` date filter. Date normalizer gate in pg_update_shipment(). See topic files for details.

### Mar 5-9, 2026 (condensed)
- 7 new dray statuses, MP classifier, column header filters, tracking events + GPS proximity, unbilled reconciliation, inbox overhaul, Rate IQ overhaul, Macropoint sync fix (5 bugs), webhook, sheet dual-write + fallback toggle, Tolead dedup, Rep Dashboard, Live Alerts, Cron Cards.

## Key Technical Patterns
- **State dedup**: JSON files (`ftl_sent_alerts.json`) prevent duplicate bot alerts. Thread-safe `fcntl.flock()`
- **Quota handling**: `_retry_on_quota()` retries 429s with backoff
- **Batched sheet writes**: ~12 API calls vs ~96
- **API auth**: `csl_session` cookie OR `X-Dev-Key` + IP allowlist
- **Vite dev**: proxy `/api/*` → production server with dev key header
- **Zustand store**: `setShipments` supports function updaters
- **Multi-provider tracking**: SeaRates → JSONCargo → Playwright. Cache `jsoncargo_cache.json` 6hr TTL
- **PG dual-write**: `csl_pg_writer.py` (UPSERT/archive) + `csl_sheet_writer.py` (fire-and-forget sheets)
- **Data source fallback**: Zustand `dataSource` ("postgres"|"sheets"). Yellow "SHEETS MODE" badge when active

## SeaRates APIs
- **Container Tracking** (`tracking.searates.com`): INTEGRATED via `_searates_container_track()`
- **Ship Schedules v2** (`schedules.searates.com/api/v2`): NOT YET INTEGRATED. User has OpenAPI spec

## Tool Preferences
- **Always use Vite preview tools** for verification. Preview server: port 5173
- **Never use Claude in Chrome MCP** for dashboard verification
- **SSH escaping**: Never use bash heredocs for binary-sensitive ops. SCP Python scripts instead

## Deploy Checklist
1. `cd dashboard && npx vite build` in `C:\Users\jsfel\Downloads\csl-dashboard-preview\dashboard\`
2. `scp dashboard/dist/index.html root@187.77.217.61:/root/csl-bot/csl-doc-tracker/static/dist/`
3. `scp dashboard/dist/assets/* root@187.77.217.61:/root/csl-bot/csl-doc-tracker/static/dist/assets/`
4. `ssh root@187.77.217.61 "systemctl restart csl-dashboard"`
5. Hard refresh (`Ctrl+Shift+R`) to bypass Cloudflare cache

## Remaining Work

### Large Items
- **Tolead/Boviet full PG migration**: Resolved as non-issue — data originates from client sheets. Sync guard + write-back deployed instead (see above). ORD/JFK/DFW remain client-shared (no write-back).
- **Customer Tracking Portal**: ✅ DONE
- **Inbox polish**: ✅ Reply button + density reduction done. Thread detail assign/correction UI still unbuilt
- **Margin Guard**: ✅ DONE — deployed Mar 11. **Margin Bridge** deployed Mar 11 — auto-extraction pipeline wired, suggestion banner live, one-click apply works
- **Weekly profit report**: Unblocked — `_shipment_row_to_dict` now serializes `customer_rate`/`carrier_pay`. Will return real data as reps use Apply button or enter manually

### Rate IQ
- Lane search mode, Phase 2 OOG IQ (real data), Phase 2 FTL IQ (not built)
- Quote extractor v2 deployed (hub normalization + LoadMatch intelligence) — see [rateiq.md](rateiq.md)

### Other
- Tolead/Boviet slide-over fields (driver phone, delivery date, appt_id)
- Phase 3: Boviet Project Cards (not started)
- Phase 5: Mobile App Layout (not started)
- Excel import: `rate_quote_sheet.xlsx` for Directory
- Warehouse extract: `POST /api/warehouses/extract` handler

## Documents Created
- **CSLogix Workflow Guide** (`Desktop/CSLogix_Work_flow_v2.pptx`): 8-slide dark-theme PPTX for Janice (JC), billing coordinator. Added Column Filters tip bar to slide 5 (Dispatch View) + split slide 7 (Inbox) bottom row into Unbilled Orders / Live Alerts 2×2 grid. XML-edited via unpack/pack workflow.

## Completed Integrations
- **Sentry**: Error tracking + monitoring
- **Tailwind UI**: Component library + utility-first CSS
- **Postgres Migration** (Phases 1-4): `shipments` table, v2 endpoints, bot dual-write, sheet sync
