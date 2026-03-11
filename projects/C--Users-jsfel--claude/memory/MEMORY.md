# CSL Bot — Project Memory

## Overview
CSL Bot automates logistics for Evans Delivery / EFJ Operations across Dray Import, Dray Export, and FTL shipments. **Postgres migration Phase 1-4 complete** — `shipments` table + v2 API endpoints + frontend switched + **all 3 bots dual-write to PG + Master Google Sheet**. Tolead+Boviet still on sheets (synced via cron). React dashboard at `cslogixdispatch.com/app`. **Sheet fallback toggle** deployed in AnalyticsView.

## Topic Files
- [dashboard-details.md](dashboard-details.md) — component map, alert system, status flow, server architecture
- [rateiq.md](rateiq.md) — Dray IQ, FTL IQ, OOG IQ, Scorecard, Directory
- [inbox-command-center.md](inbox-command-center.md) — thread grouping, reply detection, classification
- [macropoint-integration.md](macropoint-integration.md) — webhook flow, tracking events, GPS inference, timeline
- [patches-applied.md](patches-applied.md) — full list (65 patches)
- [tolead-hub-fix.md](tolead-hub-fix.md) — ORD/JFK/LAX/DFW column fixes
- [unbilled-orders.md](unbilled-orders.md) — schema, state machines, archive gate, tech debt

## Git — Mar 11, 2026
- **Latest `cc55669`** (Mar 11): Public tracker portal + date normalizer + LFD fix + Share Link button
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

### Monitoring
- `cron_log_parser.py` + `health_check.py` + dashboard "Scheduled Jobs" cron cards

## Recent Bot Changes (Deployed)

### Sync Guard + PG→Sheet Write-back — Mar 11, 2026
- **`patch_sync_guard.py`** applied to `csl_sheet_sync.py`:
  - Added `TOLEAD_BOVIET_SYNCABLE_FIELDS` constant (excludes customer_rate, carrier_pay, notes, equipment_type)
  - `_upsert_shipment` INSERT + ON CONFLICT now stamp `sheet_synced_at = NOW()`
  - `_merge_master_shipment` gets `syncable_fields=None` param (defaults to `MASTER_SYNCABLE_FIELDS`)
  - `sync_tolead` + `sync_boviet` existing-row paths now call `_merge_master_shipment(syncable_fields=TOLEAD_BOVIET_SYNCABLE_FIELDS)` — no longer blindly overwrites PG with sheet data
  - PG trigger `trg_shipments_updated_at` created — BEFORE UPDATE auto-stamps `updated_at`
  - Sheet→PG sync cron bumped from `*/10` to `*/3` (6AM-8PM)
- **`patch_writeback.py`** applied: Added `_a1()` + `_batch_writeback()` helpers; `sync_tolead` LAX + all `sync_boviet` tabs now write PG dashboard edits back to sheet when `updated_at > sheet_synced_at` (status/pickup_date/delivery_date fields only). ORD/JFK/DFW excluded (client-shared).

### Boviet Invoice Writer — Mar 11, 2026
- **`/root/csl-bot/boviet_invoice_writer.py`** (new script): Fills Piedra Invoice tab from Macropoint stop times
  - Scrapes MP stop1/stop2 arrived+departed timestamps → writes G/I (whse) + L/N (site) in HH:MM 24-hr
  - Calculates detention (J/O): `max(0, (departure - appt) - 3.0 hrs)` at $50/hr, rounded 2dp
  - Only writes to empty cells — never overwrites existing data
  - **PM heuristic**: bare `H:MM` with hour 1–6 treated as PM (trucking appts are never 1-6 AM)
  - Imports `scrape_macropoint` from `daily_summary.py`; gets MP URLs from col AA hyperlinks via Sheets API v4
  - **Cron**: `0 */2 6-20 * * 1-5` → `/tmp/boviet_invoice.log`
  - **First run**: 81 cells written across 24 rows; 4 rows pending (no MP data yet)
  - **Notable**: J66=7.37 whse detention hrs (EFJ107313) = $368 billable

### Margin Guard — Mar 11, 2026
- **`calcMarginPct(customerRate, carrierPay)`** helper added to DispatchDashboard.jsx
- **DispatchView `<tr>`**: Red bg `rgba(239,68,68,0.10)` when margin < 10% and both rates entered
- **RepDashboardView Dray + FTL `<tr>`**: Same treatment; takes priority over terminal status bg

### Date Normalizer + LFD Fix — Mar 10, 2026
- **`/root/csl-bot/date_normalizer.py`**: `clean_date(raw) -> str | None` — normalizes all date formats to `MM-DD` or `MM-DD HH:MM` (military time)
- **Handles**: Excel serial numbers (46101→03-20), `M/D/YYYY HH:MM:SS`, `MM/DD/YY`, `YYYY-MM-DD`, `DD-Mon`, AM/PM, midnight stripping (00:00 → date only)
- **Gate approach**: `csl_pg_writer.py` normalizes `eta/lfd/pickup_date/delivery_date/return_date` in `pg_update_shipment()` before every write — all callers benefit automatically
- **Sheet sync**: `csl_sheet_sync.py` normalizes dates in `_upsert_shipment()`, `_upsert_master_shipment()`, and `_merge_master_shipment()`
- **LFD/pickup fix**: `csl_bot.py` line ~1422 changed from `if lfd: pickup = lfd` (destructive overwrite) to `if lfd and not pickup: pickup = lfd` (fallback only). LFD now preserved as distinct field
- **LFD in PG write**: Bot main loop now passes `lfd=` to `pg_update_shipment()` (was missing — LFD column was empty for most records)
- **Backfill**: 114 shipments, 177 date fields cleaned (Excel serials, format soup, midnight times)
- **Patches**: `date_normalizer.py` (new), `patch_date_normalizer.py`, `backfill_clean_dates.py`
- **Sheet sync already mapped LFD** (col J → `lfd` in PG) but only worked for accounts where reps entered data manually

### Terminal Normalizer — Mar 10, 2026
- **`/root/csl-bot/terminal_normalizer.py`**: `normalize_origin(raw) -> str` — maps messy terminal strings to canonical "Name, STATE" format
- **Rules**: APM NJ/CA, LBCT, WBCT, TTI, Yusen, Total Terminals, Maher, NYCT, SFCT, BNSF/CP/NS rail, NOLA, plus regex "City STATE" → "City, STATE" formatting
- **Integrated into `csl_bot.py`**: normalizes `row["origin"]` in dray import loop; writes changed origins back to PG + sheet; 36 active shipments normalized on first run
- **NOLA filter** updated to catch both `"new orleans"` and `"napoleon"` keywords
- **Patches**: `terminal_normalizer.py` (new file), `patch_terminal_normalizer.py`

## Recent Dashboard Changes (Deployed)

### Financials + Margin Guard — Mar 11, 2026
- **`carrier_pay NUMERIC(10,2)`** added to `shipments` table; `customer_rate` cast from TEXT → NUMERIC(10,2)
- **Financials section** in both LoadSlideOver instances (DispatchView ~4494, RepDashboardView ~5858): CX Rate + RC Pay inputs with live margin % badge (green ≥10%, orange <10%, red <0%)
- **`carrierPay`** added to `mapShipment()` and `META_TO_PG` — saves to PG on blur via existing `handleMetadataUpdate`
- **`carrier_pay` in ALLOWED** fields for v2 PATCH endpoint
- **Lane-stats query** updated: `AVG(NULLIF(...)::numeric)` → `AVG(customer_rate)` (column is now native NUMERIC)
- **Margin Guard deployed**: `calcMarginPct()` helper + red row bg `rgba(239,68,68,0.10)` in DispatchView, Rep Dray, Rep FTL tables when margin < 10% and both rates entered

### pg_dump Backup Cron — Mar 11, 2026
- **DB**: `csl_doc_tracker` (not `csl_bot`) on PG 17
- **Cron**: `0 3 * * * sudo -u postgres pg_dump csl_doc_tracker | gzip > /root/backups/csl_$(date +\%Y\%m\%d).sql.gz`
- **Cleanup**: `30 3 * * * find /root/backups -name "*.sql.gz" -mtime +14 -delete`
- **Backup dir**: `/root/backups/` — verified 4.5MB on first run

### Auto-Token on Load Creation — Mar 11, 2026
- **`csl_pg_writer.py`**: After INSERT, checks `xmax=0` (true insert vs conflict update) → auto-inserts row into `public_tracking_tokens` with `ON CONFLICT DO NOTHING`
- **Backfill**: 177 active shipments all have tokens now
- Existing manual Share Link tokens untouched

### Reply Button + Email Routing — Mar 11, 2026
- **`↩ Reply` button** in InboxView thread slide-over header — extracts sender email via regex, opens `mailto:` with `Re:` subject + `cc=efj-operations@evansdelivery.com`
- **`Reply-To` header** on all outbound delivery emails via `_get_reply_to(account)`:
  - `tolead` → `tolead-efj@evansdelivery.com`
  - `boviet` → `boviet-efj@evansdelivery.com`
  - default → `efj-operations@evansdelivery.com` (= `DISPATCH_EMAIL`)
- **`_REPLY_TO_MAP` dict** + `_get_reply_to()` function defined at top of `app.py` after `DISPATCH_EMAIL`

### Top Lanes Heatmap — Mar 11, 2026
- **`GET /api/lane-stats`**: Top 20 corridors by load count, city/state split via `SPLIT_PART`, `AVG(customer_rate)` (NULL until rates entered). Inserted before `/api/customer-reply-alerts`
- **Rate IQ "Top Lanes" tab**: Load count bars (teal #1, blue top-3, gray rest), Avg Rate column ready for data. `laneStats` state fetched alongside existing Rate IQ calls

### Public Customer Tracking Portal — Mar 11, 2026
- **`public_tracking_tokens` table**: UUID PK, `efj` FK → shipments, `show_driver` bool, 60-day `expires_at`
- **`GET /track/{token}`**: Standalone Jinja2 page (no auth, no React bundle). Templates at `/root/csl-bot/csl-doc-tracker/templates/public_track.html`. Tailwind CDN, mobile-first, <50KB.
- **`POST /api/shipments/{efj}/generate-token`**: Returns existing active token or creates new UUID. Returns `{token, url}`. Copies URL to clipboard via React.
- **Auth bypass**: `/track` in `PUBLIC_PATHS` + `startswith("/track")` in `AuthMiddleware` middleware check.
- **SQL**: LATERAL join on `tracking_events` for last GPS ping; `driver_contacts` joined on `efj`. No `accounts` table exists — `show_driver` lives on token row, not account.
- **Share Link button**: Purple 🔗 in LoadSlideOver quick-action strip (line ~4155). `copiedLink`/`linkGenerating` state. `handleShareLink()` defined before `requestAiSummary`.
- **Expired token**: Returns 404 inline HTML "Link Expired" page.
- **Jinja2Templates**: Added `from fastapi.templating import Jinja2Templates` + `templates = Jinja2Templates(directory=...)` after `app = FastAPI(...)`.

### Date Normalizer + LFD Fix — Mar 11, 2026
- **`date_normalizer.py`**: `clean_date(raw) -> str` — normalizes all date fields to MM-DD / MM-DD HH:MM format
- **Integrated** into `pg_update_shipment()`, `_upsert_shipment()`, `_upsert_master_shipment()`, `_merge_master_shipment()` pre-comparison
- **LFD fix** (`csl_bot.py`): LFD now only used as pickup fallback when no actual gate-out event exists; existing LFD preserved through `pg_update_shipment`

### Magic Parse Modal + Quick Parse API — Mar 10, 2026
- **`POST /api/quick-parse`** live on VPS (Claude Sonnet 4.6): extracts `efj_number`, `rate`, `container_number`, `carrier`, `confidence` from freeform text. Returns 422 if extraction fails. Patch: `patch_quick_parse.py`
- **No `@require_auth` decorator** — auth handled entirely by `AuthMiddleware` middleware class (all `/api/` routes auto-protected). Do NOT use `@require_auth` on new endpoints.
- **Magic Parse button** in top nav bar (purple sparkle, always visible). Opens modal: textarea → "Extract Fields" → 2×2 color-coded result grid (teal=EFJ, green=rate, blue=container, orange=carrier) + HIGH/MEDIUM/LOW confidence badge + "Open EFJ# →" jump button
- **State added to DispatchDashboard**: `showParseModal`, `parseText`, `isParsing`, `parseResult`, `parseError`. ESC closes modal (wired into existing keyboard handler dep array).
- Build 706KB (`index-H-OOiG7c.js`), deployed Mar 10 19:30 → VPS confirmed active

### Terminal Ground Truth Panel — Mar 10, 2026
- **Both LoadSlideOver instances** (DispatchView ~line 4275, RepDashboardView ~line 5563) upgraded from minimal "Terminal Status" badge to full Ground Truth card
- **Red card** (`rgba(239,68,68,0.08)`) when `t.hasHolds` is true; **blue card** (`rgba(56,189,248,0.08)`) when clear
- Displays raw notes string in JetBrains Mono + vessel line; only renders when `parseTerminalNotes()` returns truthy (requires `Avail:XX | ...` format from NOLA scraper)
- Commit `11d51c2` in dashboard repo; deployed via SCP to `/root/csl-bot/csl-doc-tracker/static/dist/`

### Quote Extractor v2 + 30-Day Warning — Mar 10, 2026
- **quote_extractor.py upgraded**: Basic Haiku → Sonnet 4.6 with Universal Hub Normalization (40+ terminals, 7 FIRMS codes, city centroids), LoadMatch screenshot intelligence (BASE/FSC/TOTAL, market floor/avg/ceiling), carrier email logic
- **30-day aged data warning**: Rate Intel panel shows ⚠ on individual quotes >30 days old + global "Market data may be aged" banner when all data stale
- Both server Python + frontend JS built & deployed
- See [rateiq.md](rateiq.md) for full details

### Delivered Flow / Archive Routing Overhaul — Mar 10, 2026
- **Bug fixed**: EFJ107405 (MD Metal) was routing to Completed Eli — missing rep mapping + silent fallback
- **`csl_sheet_writer.py`**: `sheet_archive_row()` now aborts with WARNING if rep=None (no longer falls to Eli)
- **`csl_bot.py`**: MD Metal added to `ACCOUNT_REPS`; replaced hardcoded dict with `_get_rep_for_account(sh, name)` + TTL-cached `_load_account_reps_from_sheet()` (20-min TTL, force-refresh on cache miss, case-insensitive)
- **Archive is atomic**: Rep lookup happens BEFORE `pg_archive_shipment()` — if rep not found, BOTH PG + sheet skip (no ghost records)
- **`app.py`**: Removed `billed_closed` auto-archive from old status endpoint. Added billing gate to v2 endpoint: if `billed_closed` with active unbilled order → 409 "Cannot close: Active billing record found."
- **Billing gate rule**: Archive ONLY fires via `_archive_shipment_on_close()` (unbilled order closed) OR `billed_closed` with no unbilled record. Bot "Returned to Port" path also atomic.
- **Patch files**: `fix_efj107405_recovery.py`, `patch_archive_routing_fix.py`, `fix_log_calls.py`
- **Schema doc**: `memory/unbilled-orders.md` — full data dictionary

### Tolead MP URL + Ghost Cleanup + Daily Summary Fix — Mar 10, 2026
- **Tolead MP URLs now populate**: `_get_sheet_hyperlinks()` added to both `csl_sheet_sync.py` and `app.py` Tolead readers — extracts Macropoint visibility URLs from EFJ column hyperlinks
- **Ghost record cleanup**: Fixed `sync_tolead()` ghost cleanup (was `conn.cursor()` NameError → proper `db.get_conn()`), now migrates `tracking_events` FK + `container_url` before DELETE
- **`_upsert_shipment` ON CONFLICT**: Now includes `container_url` in UPDATE clause (was missing — MP URLs were lost on re-upsert)
- **Driver/Trailer fix**: `cols["driver"]` in all 4 Tolead hubs actually maps to TRAILER columns — now writes to `driver_contacts.trailer_number` instead of `shipments.driver`
- **One-off cleanup**: Migrated DFW1260308010→EFJ107432 (3 tracking events + container_url), 4 additional ghosts, cleared 47 driver fields with trailer data, migrated 5 tracking cache entries
- **Frontend**: `driver: null` → `driver: s.driver || null` in `mapShipment()`, notes textarea `onBlur` now calls `handleMetadataUpdate()` (was only logging), `fmtDateDisplay()` formats dates as M/D HH:MM military time in slide-over
- **Daily summary fixed**: Was crashing since ~Mar 2 with `ImportError: cannot import name 'scrape_macropoint' from 'ftl_monitor'` (function removed from ftl_monitor, daily_summary has its own copy now). Added `_is_this_week()` date filter — only scrapes loads picking up/delivering this week
- **Patches**: `patch_tolead_sync_fix.py`, `fix_app_tolead_container_url.py`, `fix_ghost_and_driver.py`, `patch_daily_summary_datefilter.py`

### Mar 9, 2026 (condensed)
- **7 new dray statuses** + STATUS_MAP fixes. SSL/Vessel + Container + BOL editable in slide-over. Edit persistence fix (`synced:false` preserved across polls). Polling 60s→90s.
- **MP Status Classifier**: `_classify_mp_display_status()` server-side. `TrackingBadge` rewritten. Schedule alert banners. See [macropoint-integration.md](macropoint-integration.md)
- **Column header filter dropdowns**: DispatchView + RepDashboardView (date presets, stacked filters). Helper fns: `applyColFilters()`, `buildColFilterOptions()` etc.
- **Tracking Events + GPS proximity**: `tracking_events` PG table, 0.5mi arrival / 2.0mi departure inference. Fixed ET timestamp + cache fallback bugs.
- **Unbilled reconciliation**: LEFT JOIN + auto-archive on close. `db.get_cursor()` is context manager → `with db.get_cursor() as cursor:` (RealDictCursor)
- **Inbox overhaul**: Reply detection (sender-pattern), smart classification (P2–P5), InboxView table rewrite, live alert polling, daily digest. See [inbox-command-center.md](inbox-command-center.md)
- **Rate IQ overhaul**: Lane groups accordion, UNION search, Quote→Rate IQ feedback, AI extraction (Claude Haiku→Sonnet 4.6). See [rateiq.md](rateiq.md)

### Mar 5-8, 2026 (condensed)
- Macropoint sync fix (5 bugs), webhook, GPS tracking. Sheet dual-write + fallback toggle. Tolead dedup + date fixes. AddForm snake_case. Rep Dashboard. Live Alerts, Cron Cards.

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
- **Inbox polish**: ✅ Reply button done. Thread detail assign/correction UI still unbuilt
- **Margin Guard**: ✅ DONE — deployed Mar 11
- **Weekly profit report**: Unblocked once reps start entering rates consistently

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
