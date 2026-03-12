# CSL Bot — Project Memory

## Overview
CSL Bot automates logistics for Evans Delivery / EFJ Operations across Dray Import, Dray Export, and FTL shipments. **Postgres migration Phase 1-4 complete** — `shipments` table + v2 API endpoints + frontend switched + **all 3 bots dual-write to PG + Master Google Sheet**. Tolead+Boviet still on sheets (synced via cron). React dashboard at `cslogixdispatch.com/app`. **Sheet fallback toggle** deployed in AnalyticsView.

## Topic Files
- [dashboard-details.md](dashboard-details.md) — component map, alert system, status flow, server architecture
- [rateiq.md](rateiq.md) — Dray IQ, FTL IQ, OOG IQ, Scorecard, Directory
- [inbox-command-center.md](inbox-command-center.md) — thread grouping, reply detection, classification
- [macropoint-integration.md](macropoint-integration.md) — webhook flow, tracking events, GPS inference, timeline
- [patches-applied.md](patches-applied.md) — full list (88 patches)
- [tolead-hub-fix.md](tolead-hub-fix.md) — ORD/JFK/LAX/DFW column fixes
- [unbilled-orders.md](unbilled-orders.md) — schema, state machines, archive gate, tech debt
- [ai-tools-roadmap.md](ai-tools-roadmap.md) — Ask AI tool expansion plan: 11 deployed + 14 to build

## Git — Mar 12, 2026
- **Latest**: Mar 12 — Mobile layout + margin column + inbox actions + Boviet cards + MP URL edit
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

### Mar 12, 2026 Bot Changes
- **Sheet sync cron fix**: Was pointing to wrong file (`csl-doc-tracker/csl_sheet_sync.py` 19KB → `/root/csl-bot/csl_sheet_sync.py` 33KB). Prolog, MD Metal, Talatrans now sync.
- **Revenue backfill**: `patch_revenue_backfill.py` — XLS commission report → PG `customer_rate` (596 shipments, $12M total via xlrd)
- **Inbox rep filter**: `patch_inbox_rep_filter.py` — enriches `/api/inbox` threads with `rep` from shipments table JOIN, fixes `rep_filter`
- **Port groups**: `port_groups.py` (new module) — 18 port/rail groups (LA/LB, NY/NJ, Savannah, Chicago Rail, etc.) + `normalize_to_port_group()`
- **Port groups API**: `patch_port_groups.py` — `/api/port-groups`, `/api/rate-history` endpoints, search-lane port group expansion, apply-rate→lane_rates INSERT
- **ACCOUNT_REPS**: Added Prolog, Talatrans, LS Cargo (→Radka), GW-World (→John F) to `csl_bot.py`
- **REV window expansion**: `patch_rev_window.py` — scoreboard loads/revenue queries use `archived = false` instead of 7-day rolling filter + `total_margin` in response
- **Inbox actions**: `patch_inbox_actions.py` — `manual_rep` + `actioned` columns on email_threads, 2 new PATCH endpoints (assign-rep, mark-actioned), needs_reply filters actioned threads
- **Customer rate extraction**: `patch_customer_rate_extraction.py` — `extract_rate_from_email()` now handles `customer_rate` emails, adds `rate_type` field, `rate_quotes.rate_type` column

### Mar 11, 2026 Bot Changes (condensed)
- **Margin Bridge**: `patch_margin_bridge.py` — customer_rate/carrier_pay serialization, rate-quotes/apply-rate endpoints, auto-reject competing quotes. AI extraction v2 (expanded body window, linehaul/accessorials fields). Rate suggestion banner in LoadSlideOver.
- **Archive Distance Guard**: `patch_archive_distance_guard.py` — block false D1 archive when distance_to_stop > 15mi in ftl_monitor + webhook handler
- **Status Writeback**: v2 status endpoint writes back to Master Sheet for non-shared accounts (was being overwritten by 3-min sync)
- **Unbilled Weekly Digest**: `unbilled_weekly_digest.py` — Outlook-safe HTML email, Monday 7:15 AM, aging buckets + customer breakdown
- **Sync Guard + PG→Sheet Write-back**: sheet_synced_at stamps, cron */3, Tolead LAX + Boviet write-back
- **No-Reply Alert Fix**: Self-email filter, EFJ dedup, 4hr lookback cap, lane fallback
- **Other**: Boviet invoice writer, dray daily report HTML fix, MP alert subject rename ("CSL Tracking"), margin guard + date/terminal normalizers

## Recent Dashboard Changes (Deployed)

### Mar 12, 2026 Dashboard Changes
- **COMMS click fix**: Scoreboard COMMS click → Inbox filtered by rep (was broken — passed rep as search text). Backend enriches threads with `rep` from shipments JOIN, frontend passes `&rep=` param
- **Port group pills**: Lane Search — 12 port buttons (teal) + 6 rail buttons (purple) above search, click sets origin
- **History tab**: Rate IQ "History" tab — lazy-loads from `/api/rate-history`, groups applied rates by port group
- **Directory port filter**: `<select>` dropdown filters carriers by port group membership
- **Inbox rep chip**: Blue "Radka's Inbox ×" chip when filtered, `inboxInitialRep` added to Zustand store
- **MGN column**: Dispatch table margin column with color coding (red <0, orange <10%, green ≥10%) + sortable via `calcMarginPct()`
- **Margin summary bar**: Billing Pipeline section shows total rev/cost/margin/avg margin % across all priced active loads
- **MP URL edit**: LoadSlideOver Quick Action Strip "Edit MP URL" button with inline input + PATCH to `/api/load/{efj}/mp-url`
- **Inbox thread actions**: Rep assignment `<select>` dropdown + "Mark Actioned" button per thread, ACTIONED badge, actioned threads hidden from needs_reply
- **Boviet Project Cards**: RepDashboardView per-project summary cards (Piedra/Hanson) — active/delivered/pending counts, pickups today, carrier count, last delivery
- **Customer Rate Banner**: LoadSlideOver Financials section shows pending customer rate suggestion with Apply/Reject buttons
- **Mobile layout (Phase 5)**: `useIsMobile()` hook (768px breakpoint), bottom nav bar (Home/Inbox/Rates/Billing/More), full-width slide-overs, card view for dispatch table, horizontal scroll stat cards with snap, CSS media queries
- **Scoreboard tooltips**: Updated from "7d rolling" to "Active loads" / "Active revenue" + margin tooltip

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
- **Data gaps**: REV shows "--" until customer_rate populates via rate extraction pipeline. LOADS/REV now use `archived = false` (removed 7d rolling + migration batch guard). `total_margin` added to response

### Mar 11, 2026 Dashboard Changes (condensed)
- **Carrier Intelligence Suite**: Directory tab (cards + inline editing + capability pills), Lane Search (grouped results, inline rate editing, carrier enhancements), schema expansion (12 new columns), Sheet imports (35 carrier tabs, 40 rate tabs), doc dedup (SHA-256), MP→billing bridge, Loadboard rename, BOL systemd
- **Ask AI Command Palette**: `ai_assistant.py` — Claude Sonnet 4.6, 23 tools across 4 tiers, `POST /api/ask-ai`, `AskAIOverlay` component (Ctrl+K), quick-action chips, markdown rendering
- **Overview**: + New Load button, Billing Pipeline section (stage cards with counts), STATUS_MAP underscore fix
- **Team Feedback Fixes**: Dispatch nav removed (accessible via stat cards), Yesterday filter + stat card, ← Overview back button, layout reorder (Team above Actions), Boviet STATUS_MAP, inbox density reduction
- **Financials + Margin Guard**: `carrier_pay` column, Financials section in LoadSlideOvers, `calcMarginPct()`, red row bg <10%
- **pg_dump + Tracking + Reply**: Daily backup, auto-token, Reply button in Inbox, Top Lanes tab, Public tracking portal (`/track/{token}`)

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
- **Inbox polish**: ✅ DONE — Reply button, density, rep filter, assign-rep dropdown, mark-actioned button all deployed
- **Margin Guard**: ✅ DONE — deployed Mar 11. **Margin Bridge** deployed Mar 11. **MGN column** + margin summary bar deployed Mar 12
- **Rep Scoreboard**: ✅ DONE — v2 deployed Mar 12. REV window expanded to all active loads (not 7d). Deferred: WIN RATE (sparse data), Account Health view (next build), delivered_at TIMESTAMPTZ migration
- **Account Health View**: NOT STARTED — same scoreboard data grouped by account instead of rep. Needed for strategic review (margin-to-friction ratio per customer)

### Rate IQ
- ✅ Carrier Directory + Lane Search: DONE — inline editing deployed Mar 11
- Phase 2 OOG IQ (real data), Phase 2 FTL IQ (not built)
- Quote extractor v2 deployed (hub normalization + LoadMatch intelligence) — see [rateiq.md](rateiq.md)

### Other
- Tolead/Boviet slide-over fields (driver phone, delivery date, appt_id)
- Phase 3: Boviet Project Cards — ✅ DONE (deployed Mar 12, per-project summary in RepDashboardView)
- Phase 5: Mobile App Layout — ✅ DONE (deployed Mar 12, bottom nav + card views + full-width panels)
- Warehouse extract: `POST /api/warehouses/extract` handler
- Customer rate extraction pipeline deployed (scanner handles customer_rate emails → rate_quotes with rate_type)

## Documents Created
- **CSLogix Workflow Guide** (`Desktop/CSLogix_Work_flow_v2.pptx`): 8-slide dark-theme PPTX for Janice (JC), billing coordinator. Added Column Filters tip bar to slide 5 (Dispatch View) + split slide 7 (Inbox) bottom row into Unbilled Orders / Live Alerts 2×2 grid. XML-edited via unpack/pack workflow.

## Completed Integrations
- **Sentry**: Error tracking + monitoring
- **Tailwind UI**: Component library + utility-first CSS
- **Postgres Migration** (Phases 1-4): `shipments` table, v2 endpoints, bot dual-write, sheet sync
