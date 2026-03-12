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
- [ai-tools-roadmap.md](ai-tools-roadmap.md) — Ask AI tool expansion plan: 11 deployed + 14 to build

## Git — Mar 12, 2026
- **Latest**: Mar 12 — Rep Scoreboard v2 + revenue rename
- **Repo**: `CSLogix/CSLogix_Bot` (private), single `master` branch
- **VPS, GitHub, Local** all in sync
- **`.gitignore`**: Excludes `*.bak*`, `*.pre-*`, `*.json` (except package.json), `dist/`, `uploads/`, credentials
- **State files** (`ftl_sent_alerts.json`, `last_check.json`, `export_state.json`) are runtime dedup/state — gitignored, live on VPS only

## Memory Repo — Mar 10, 2026
- **Repo**: `CSLogix/csl-claude-memory` (private) — `git@github.com:CSLogix/csl-claude-memory.git`
- **Local**: `C:\Users\jsfel\.claude` — SSH remote set, tracking `origin/master`
- **SSH key**: `~/.ssh/id_ed25519` added to GitHub (`CSLogix` account)

## Dashboard Component Map (DispatchDashboard.jsx)
Single-file React SPA (~8500 lines). Key components: `DispatchDashboard` (root), `OverviewView`, `RepDashboardView`, `DispatchView`, `InboxView`, `LoadSlideOver`, `AnalyticsView`, `UnbilledView`, `HistoryView`, `AddForm`, `AskAIOverlay`, `RateIQView` (with Directory, Lane Search, Scorecard tabs).

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

### Mar 11, 2026 Bot Changes (condensed)
- **Margin Bridge**: `patch_margin_bridge.py` — customer_rate/carrier_pay serialization, rate-quotes/apply-rate endpoints, auto-reject competing quotes. AI extraction v2 (expanded body window, linehaul/accessorials fields). Rate suggestion banner in LoadSlideOver.
- **Archive Distance Guard**: `patch_archive_distance_guard.py` — block false D1 archive when distance_to_stop > 15mi in ftl_monitor + webhook handler
- **Status Writeback**: v2 status endpoint writes back to Master Sheet for non-shared accounts (was being overwritten by 3-min sync)
- **Unbilled Weekly Digest**: `unbilled_weekly_digest.py` — Outlook-safe HTML email, Monday 7:15 AM, aging buckets + customer breakdown
- **Sync Guard + PG→Sheet Write-back**: sheet_synced_at stamps, cron */3, Tolead LAX + Boviet write-back
- **No-Reply Alert Fix**: Self-email filter, EFJ dedup, 4hr lookback cap, lane fallback
- **Other**: Boviet invoice writer, dray daily report HTML fix, MP alert subject rename ("CSL Tracking"), margin guard + date/terminal normalizers

## Recent Dashboard Changes (Deployed)

### Rep Scoreboard v2 — Mar 12, 2026
- **Backend**: `GET /api/rep-scoreboard` — 7 SQL queries computing per-rep metrics, polls every 2 min
  - **Offense**: `loads_7d` (loads booked, migration-batch excluded), `revenue_7d` (SUM customer_rate, NOT margin — owner's preference to hide cost structure from floor)
  - **Defense**: `unreplied_threads` (last msg is external, 3-day window), `avg_response_min` (7-day rolling, 16hr overnight cap), `docs_needed` (delivered loads missing POD/carrier_invoice), `neglected_loads` (non-terminal, no update >24h), `stale_quotes` (pending >2h)
  - `worst_account` flag per rep (account with most unreplied threads)
- **Frontend**: Replaced old Team panel in OverviewView with grid scoreboard. Blue offense headers (LOADS, REV) | divider | amber defense headers (COMMS, DOCS, STALE)
  - COMMS = merged unreplied count + avg speed in one cell (green ✓ / yellow / red composite)
  - Color thresholds: ≥5 unreplied or ≥3 stale or ≥5 docs → red row highlight
  - **Clickable cells**: COMMS → Inbox filtered by rep, DOCS → Rep Dashboard, STALE → Dispatch filtered by rep
- **DB pattern**: Uses `database._pool.getconn()` directly (not context manager) for multi-query read-only endpoint
- **Deferred**: WIN RATE (only 83 rate_quotes, 1 accepted — too sparse), carrier assignment speed + on-time delivery (needs delivered_at TIMESTAMPTZ migration), Account Health view (same data grouped by account — next build)
- **Data gaps**: REV shows "--" until customer_rate populates via rate extraction pipeline. LOADS had migration batch issue (610 loads on Mar 6) — excluded via `created_at > '2026-03-07'` guard that becomes no-op naturally

### Carrier Intelligence Suite — Mar 11, 2026
- **Carrier Directory tab** in Rate IQ: searchable/filterable carrier cards with capability pills (HAZ, OWT, Reefer, Bonded, OOG, WHS), tier badges, market chips, truck counts. Expanded detail shows contact info, equipment, insurance, service feedback/notes/record/comments
- **Carrier Directory inline editing**: ✏️ pencil toggle per card → capability pills become toggleable (click to on/off), tier rank becomes dropdown, all detail fields become save-on-blur inputs. `PUT /api/carriers/{id}` handles updates
- **Lane Search tab** in Rate IQ: origin/dest search with grouped results by lane. Expanded view shows carrier table with all accessorial columns (dray, FSC, total, chassis, prepull, storage, detention, chassis split, overweight, tolls, hazmat, triaxle, reefer, bond)
- **Lane Search inline editing**: click any rate cell → number input with teal border → save on blur/Enter, Escape cancels. `PUT /api/lane-rates/{id}` endpoint (new) with auto-recalculate total if dray_rate/fsc change
- **Lane Search carrier enhancements**: capability emoji badges (🔥⚖❄🔒📦🏭), tier dot indicators, MC# from carrierCapMap cross-reference, date stamps ("today"/"3d"/"2w"/"3mo" with color aging), "Draft Load →" hover button opens Ask AI
- **Carrier schema expansion**: `can_reefer`, `can_bonded`, `can_oog`, `can_warehousing`, `tier_rank`, `service_feedback`, `service_notes`, `service_record`, `comments`, `markets[]`, `haz_classes[]`, `dnu`, `trucks`, `insurance_info` columns added to `carriers` table
- **Carrier Sheet import**: `import_carrier_sheet.py` (openpyxl) reads 35 tabs from `Carrier Sheet.xlsx`, UPSERT on MC#, merges markets array, maps Yes/No → booleans, tier strings → integers
- **Rate Quote Sheet import**: `import_rate_quotes_sheet.py` reads 40 city-market tabs, imports dray rates + all accessorial columns to `lane_rates` table
- **Document dedup**: SHA-256 `file_hash` column + UNIQUE constraint on `load_documents`, backfill script, inbox scanner + upload endpoint hash-check guard. Expanded junk filename patterns (image.png, Outlook-*.jpg)
- **Macropoint→Billing bridge**: Webhook "Delivered" auto-transitions to `ready_to_close` after 60s delay via BackgroundTask
- **Loadboard rename**: "Dispatch" labels → "Loadboard" in OverviewView stat cards and DispatchView header
- **BOL systemd service**: `/etc/systemd/system/bol-webapp.service` created and enabled

### Ask AI — Command Palette — Mar 11, 2026
- **Backend**: `ai_assistant.py` module — Claude Sonnet 4.6 tool-calling with **23 tools** across 4 tiers. Up to 5 tool iterations, 2048 max response tokens. Backup: `ai_assistant.py.pre-tools-v2`
- **Tier 1** (original): query_lane_history, query_carrier_db, check_efj_status, extract_rate_con, draft_new_load + quote_lookup, carrier_capability_check, available_capacity, eta_delay_check, recent_emails, suggest_carrier
- **Tier 2** "Stop Asking Me": unit_converter, shipment_summary, detention_calculator, accessorial_estimator, billing_checklist
- **Tier 3** "Make Me Look Smart": load_comparison, account_health_report, transit_time_estimator, explain_like_a_customer, what_if_scenario
- **Tier 4** "Outside the Box": daily_briefing, smart_dispatch_suggest
- **Endpoint**: `POST /api/ask-ai` in app.py — accepts `{ question, context }`, returns `{ answer, tool_calls, sources }`
- **Frontend**: `AskAIOverlay` component — center-screen chat overlay (z-index 310), triggered by Ctrl+K or "Ask AI ⌘K" button. Quick-action chips, markdown rendering (tables, bold, lists, headers), tool call purple badges, session history
- **Keyboard shortcuts**: Ctrl+K → Ask AI, Ctrl+F → shipment search CommandPalette
- **Anthropic API key**: stored in `/root/csl-bot/.env` as `ANTHROPIC_API_KEY`, `pip install anthropic --break-system-packages`

### Overview Enhancements — Mar 11, 2026
- **+ New Load button**: Top-right of Overview header, calls `onAddLoad` to open AddForm modal
- **Billing Pipeline section**: Visual pipeline below Today's Actions/Live Alerts. Shows color-coded stage cards (Delivered → Ready to Close → Missing Invoice → PPWK Needed → Waiting) with counts and arrow separators. "View Billing →" link. `billingCounts` useMemo computes from shipments array. Conditional render when `billingCounts.total > 0`
- **STATUS_MAP underscore fix**: Added all PG underscore-format status variants (`ready_to_close`, `missing_invoice`, `billed_closed`, `ppwk_needed`, `in_transit`, `at_port`, `on_vessel`, `returned_to_port`, `empty_return`, etc.) so `normalizeStatus()` maps them correctly instead of falling through to "pending"

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
- **Margin Guard**: ✅ DONE — deployed Mar 11. **Margin Bridge** deployed Mar 11
- **Rep Scoreboard**: ✅ DONE — v2 deployed Mar 12. LOADS/REV/COMMS/DOCS/STALE. Deferred: WIN RATE (sparse data), Account Health view (next build), delivered_at TIMESTAMPTZ migration
- **Account Health View**: NOT STARTED — same scoreboard data grouped by account instead of rep. Needed for strategic review (margin-to-friction ratio per customer)

### Rate IQ
- ✅ Carrier Directory + Lane Search: DONE — inline editing deployed Mar 11
- Phase 2 OOG IQ (real data), Phase 2 FTL IQ (not built)
- Quote extractor v2 deployed (hub normalization + LoadMatch intelligence) — see [rateiq.md](rateiq.md)

### Other
- Tolead/Boviet slide-over fields (driver phone, delivery date, appt_id)
- Phase 3: Boviet Project Cards (not started)
- Phase 5: Mobile App Layout (not started)
- Warehouse extract: `POST /api/warehouses/extract` handler

## Documents Created
- **CSLogix Workflow Guide** (`Desktop/CSLogix_Work_flow_v2.pptx`): 8-slide dark-theme PPTX for Janice (JC), billing coordinator. Added Column Filters tip bar to slide 5 (Dispatch View) + split slide 7 (Inbox) bottom row into Unbilled Orders / Live Alerts 2×2 grid. XML-edited via unpack/pack workflow.

## Completed Integrations
- **Sentry**: Error tracking + monitoring
- **Tailwind UI**: Component library + utility-first CSS
- **Postgres Migration** (Phases 1-4): `shipments` table, v2 endpoints, bot dual-write, sheet sync
