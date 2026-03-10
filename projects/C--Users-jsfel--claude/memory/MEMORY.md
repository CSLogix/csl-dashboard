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

## Git — Mar 10, 2026
- **Baseline `7c93e8b`** (Mar 9): Clean baseline capturing all production code
- **Latest `884790e`** (Mar 10): Server patches (49c09d9) + frontend fixes (3c44b59) merged
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
- **Sheet→PG Sync**: every 10 min, 6AM-8PM (Tolead+Boviet only)

### Monitoring
- `cron_log_parser.py` + `health_check.py` + dashboard "Scheduled Jobs" cron cards

## Recent Bot Changes (Deployed)

### Terminal Normalizer — Mar 10, 2026
- **`/root/csl-bot/terminal_normalizer.py`**: `normalize_origin(raw) -> str` — maps messy terminal strings to canonical "Name, STATE" format
- **Rules**: APM NJ/CA, LBCT, WBCT, TTI, Yusen, Total Terminals, Maher, NYCT, SFCT, BNSF/CP/NS rail, NOLA, plus regex "City STATE" → "City, STATE" formatting
- **Integrated into `csl_bot.py`**: normalizes `row["origin"]` in dray import loop; writes changed origins back to PG + sheet; 36 active shipments normalized on first run
- **NOLA filter** updated to catch both `"new orleans"` and `"napoleon"` keywords
- **Patches**: `terminal_normalizer.py` (new file), `patch_terminal_normalizer.py`

## Recent Dashboard Changes (Deployed)

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

### Tolead MP URL + Ghost Cleanup + Daily Summary Fix — Mar 10, 2026
- **Tolead MP URLs now populate**: `_get_sheet_hyperlinks()` added to both `csl_sheet_sync.py` and `app.py` Tolead readers — extracts Macropoint visibility URLs from EFJ column hyperlinks
- **Ghost record cleanup**: Fixed `sync_tolead()` ghost cleanup (was `conn.cursor()` NameError → proper `db.get_conn()`), now migrates `tracking_events` FK + `container_url` before DELETE
- **`_upsert_shipment` ON CONFLICT**: Now includes `container_url` in UPDATE clause (was missing — MP URLs were lost on re-upsert)
- **Driver/Trailer fix**: `cols["driver"]` in all 4 Tolead hubs actually maps to TRAILER columns — now writes to `driver_contacts.trailer_number` instead of `shipments.driver`
- **One-off cleanup**: Migrated DFW1260308010→EFJ107432 (3 tracking events + container_url), 4 additional ghosts, cleared 47 driver fields with trailer data, migrated 5 tracking cache entries
- **Frontend**: `driver: null` → `driver: s.driver || null` in `mapShipment()`, notes textarea `onBlur` now calls `handleMetadataUpdate()` (was only logging), `fmtDateDisplay()` formats dates as M/D HH:MM military time in slide-over
- **Daily summary fixed**: Was crashing since ~Mar 2 with `ImportError: cannot import name 'scrape_macropoint' from 'ftl_monitor'` (function removed from ftl_monitor, daily_summary has its own copy now). Added `_is_this_week()` date filter — only scrapes loads picking up/delivering this week
- **Patches**: `patch_tolead_sync_fix.py`, `fix_app_tolead_container_url.py`, `fix_ghost_and_driver.py`, `patch_daily_summary_datefilter.py`

### Tester Bug Fixes & New Statuses — Mar 9, 2026
- **7 new dray statuses**: On Hold (`on_hold`), Returned to Port (`returned_to_port`), Released (`released`), At Yard (`at_yard`), Rail (`rail`), Transload (`transload`), On Site Loading (`on_site_loading`)
- STATUS_MAP changes: `"hold"→on_hold` (was pending), `"returned to port"→returned_to_port` (was empty_return), `"discharged"→released` (was at_port)
- **SSL/Vessel field** added to LoadSlideOver for dray loads (editable, maps to PG `vessel` column)
- **Container/Load# and BOL/Booking** added as editable fields in slide-over
- **Edit persistence fix**: `fetchData` now merges with local state — shipments with `synced: false` are preserved across poll cycles (was fully replacing, wiping mid-edit values)
- **Polling reduced** from 60s → 90s to reduce sync churn
- **FIELD_TO_PG** expanded: `ssl→"vessel"`, `container→"container"`
- **SLIDE_FIELD_MAP** expanded: `ssl`, `container`, `bol`
- **MD Metal** account tab already existed in Master Tracker sheet

### MP Status Classifier — Mar 9, 2026
- Server-side `_classify_mp_display_status()` function computes user-friendly status from raw MP status + schedule alert + GPS staleness
- Webhook handler now stores `schedule_alert`, `schedule_alert_code`, `distance_to_stop`, `eta_to_stop` in tracking cache
- All 3 API endpoints enriched: `/api/v2/shipments` (mp_display_status/mp_display_detail), `/api/macropoint/{efj}` (mpDisplayStatus/mpDisplayDetail/scheduleAlert/distanceToStop), `/api/shipments/tracking-summary`
- Frontend `TrackingBadge` rewritten with classified statuses: On Time (green), Behind Schedule (red), In Transit (blue), At Pickup (amber), At Delivery (purple), Awaiting Update (orange), No Signal (red), Assigned (gray), Delivered (green)
- Hover tooltip shows detail (e.g. "4.2h ahead", "GPS stale")
- Column filter, sort, search, CSV export all use `mpDisplayStatus`
- Schedule alert banners in MacropointModal and LoadSlideOver
- See [macropoint-integration.md](macropoint-integration.md)

### Column Header Filter Dropdowns — Mar 9, 2026
- Excel/Google Sheets style column filtering added to DispatchView and RepDashboardView tables
- **DispatchView**: Account, Status, MP Status, Pickup, Origin, Destination, Delivery columns filterable via dropdown; uses `position: absolute`
- **RepDashboardView Ops/Master tables**: Account, Carrier, PU, DEL, Status filterable
- **RepDashboardView FTL table**: Account, Status, MP Status, Pickup, Origin, Destination, Delivery filterable; uses `position: fixed` to escape `overflow:hidden` clipping
- Date columns use presets: Today, Tomorrow, This Week, Past Due
- Active filter indicated by green icon; column filters stack with existing filter bar
- Helper functions at top of file: `isDateThisWeek()`, `COL_FILTER_KEY_MAP`, `DATE_FILTER_PRESETS`, `matchesDatePreset()`, `applyColFilters()`, `buildColFilterOptions()`

### Tracking Events Fix — Mar 9, 2026
- Fixed 3 bugs preventing GPS-inferred events from reaching dashboard: "ET" timestamp rejected by PG, cache fallback short-circuited, `fmtTs()` NaN on "ET" suffix
- `_persist_tracking_event()` now converts ET→offset, `/api/macropoint` merges cache into PG timeline, frontend uses `/\dT\d/` ISO check
- See [macropoint-integration.md](macropoint-integration.md)

### Tracking Events + GPS Proximity Inference — Mar 9, 2026
- `tracking_events` PG table, `_build_timeline_from_pg()`, GPS proximity stop detection (0.5mi arrival / 2.0mi departure)
- Compact Schedule & Tracking table in both slide-overs: 4-col grid (Stop | Sched | Arrived | Departed)
- See [macropoint-integration.md](macropoint-integration.md)

### Macropoint Sync Fix — Mar 8, 2026
- 5 bugs fixed (stop_times, Tracking Completed→Delivered, MP URLs, container_url PG, v2 enrichment)

### Unbilled ↔ Shipments Reconciliation — Mar 9, 2026
- LEFT JOIN unbilled_orders↔shipments, auto-archive on close, bulk-close-delivered
- `db.get_cursor()` is context manager — use `with db.get_cursor() as cursor:`. Returns `RealDictCursor` (dict rows)

### Tolead Fixes + Email Spam + Date Format — Mar 8, 2026
- Email spam fix (skip None-all-around comparisons), MM/DD date format, Tolead dedup, sync overwrite protection

### Sheet Dual-Write + Fallback Toggle — Mar 6, 2026
- `csl_sheet_writer.py` fire-and-forget module. `/api/health` endpoint. DataSourceToggle in AnalyticsView

### Macropoint Webhook — Mar 6, 2026
- Real-time alerts via BackgroundTasks + `csl_ftl_alerts.py`. GET handler (native protocol). See [macropoint-integration.md](macropoint-integration.md)

### Inbox Overhaul: Smart Classification + Table Redesign — Mar 9, 2026
- **Reply detection fixed**: Replaced empty `sent_messages` table with sender-pattern matching (evansdelivery/commonsenselogistics domains). 12/333 threads need reply (was 352/352)
- **Scanner INSERT bug fixed**: `ON CONFLICT DO NOTHING` → `DO UPDATE RETURNING id` (was causing 153 errors/3 days)
- **Smart classification**: CarrierPay NP→payment_escalation (P5), carrier_invoice (P4), carrier_rate_confirmation (P4), POD body-detect (P3), rate_outreach (P2), carrier_rate_response (P4, thread-based)
- **InboxView rewritten**: Compact table (36-40px rows, full width), sorting, column filters, search, 480px slide-over detail panel
- **Live alerts**: rate_response (teal), payment_escalation (red), send_final_charges (amber) — polled via `/api/rate-response-alerts`
- **Rep dashboard pills**: "Needs Reply" (red) + "Rate Responses" (teal) per rep
- **Daily digest**: `csl_inbox_digest.py` at 7 AM ET Mon-Fri — 3 emails: master reps (by account), Boviet (by project), Tolead (by hub) + unbilled orders
- **Immediate email**: payment_escalation only, sent in real-time
- See [inbox-command-center.md](inbox-command-center.md)

### Rate IQ Overhaul — Mar 9, 2026
- **Customer rate detection**: KNOWN_CUSTOMER_SENDERS + CUSTOMER_QUOTE_LANGUAGE massively expanded in both scanner + classifier (maoinc, manitoulin, OOG, dims, unicode×, hazmat, 53ft, inland rate, service combos, IMO)
- **AI rate extraction**: Both `csl_inbox_scanner.py` and `csl_email_classifier.py` now use Claude Haiku for carrier rate extraction (`_ai_extract_rate()` → JSON, regex fallback for missing fields)
- **Lane groups accordion**: Rate Intel panel now shows grouped lanes with floor/avg/ceiling/source badges per lane (EMAIL/IMPORT/QUOTE); accordion expand/collapse; header shows "N lanes, M quotes"
- **search-lane UNION**: Queries `rate_quotes` + `lane_rates` (243 rows) + won `quotes` together; groups by normalized origin/destination; returns `lane_groups[]` + per-group stats + sources breakdown
- **Quote → Rate IQ feedback**: `_index_quote_to_rate_iq()` called on save/update — dray quotes with carrier_total get written to `rate_quotes` with `source_quote_id` FK
- **Save Quote**: Renamed from "Save Draft"; Dray IQ History filter locked to Dray/Dray+Transload/OTR/Transload move types; "Saved" chip replaces "Drafts"
- **Frontend**: QuoteBuilder.jsx updated + built + deployed

### Inbox Command Center — Mar 6, 2026
- Initial InboxView nav tab, thread grouping, classification feedback, email badges. See [inbox-command-center.md](inbox-command-center.md)

### Older (Mar 5-6)
- AddForm camelCase→snake_case fix, status filter dropdowns
- Rep Dashboard (Dray/FTL views, MM/DD dates, carrier info)
- Platform Audit v2: 12/12 DONE
- Design Spec Color Upgrade, Rate IQ, SlideOver Panel enhancements
- Live Alerts, Cron Cards, Email Classification, Add Load, Auto-archive

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
- **Tolead/Boviet full PG migration**: Move off Google Sheets entirely
- **Customer Tracking Portal**: Public-facing read-only load status
- **Inbox polish**: Mailto reply button, thread detail slide-over assign/correction UI

### Rate IQ
- Lane search mode, Phase 2 OOG IQ (real data), Phase 2 FTL IQ (not built)
- Quote extractor v2 deployed (hub normalization + LoadMatch intelligence) — see [rateiq.md](rateiq.md)

### Other
- Tolead/Boviet slide-over fields (driver phone, delivery date, appt_id)
- Phase 3: Boviet Project Cards (not started)
- Phase 5: Mobile App Layout (not started)
- Excel import: `rate_quote_sheet.xlsx` for Directory
- Warehouse extract: `POST /api/warehouses/extract` handler

## Completed Integrations
- **Sentry**: Error tracking + monitoring
- **Tailwind UI**: Component library + utility-first CSS
- **Postgres Migration** (Phases 1-4): `shipments` table, v2 endpoints, bot dual-write, sheet sync
