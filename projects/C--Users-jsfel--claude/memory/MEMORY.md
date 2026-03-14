# CSL Bot — Project Memory

## Overview
CSL Bot automates logistics for Evans Delivery / EFJ Operations across Dray Import, Dray Export, and FTL shipments. **Postgres migration Phase 1-4 complete** — `shipments` table + v2 API endpoints + frontend switched + **all 3 bots dual-write to PG + Master Google Sheet**. Tolead+Boviet still on sheets (synced via cron). React dashboard at `cslogixdispatch.com/app`. **Sheet fallback toggle** deployed in AnalyticsView.

## Topic Files
- [dashboard-details.md](dashboard-details.md) — component map, alert system, status flow, server architecture
- [rateiq.md](rateiq.md) — Dray IQ, FTL IQ, OOG IQ, Scorecard, Directory
- [inbox-command-center.md](inbox-command-center.md) — thread grouping, reply detection, classification
- [macropoint-integration.md](macropoint-integration.md) — webhook flow, tracking events, GPS inference, timeline
- [patches-applied.md](patches-applied.md) — full list (100+ patches)
- [tolead-hub-fix.md](tolead-hub-fix.md) — ORD/JFK/LAX/DFW column fixes
- [unbilled-orders.md](unbilled-orders.md) — schema, state machines, archive gate, tech debt
- [ai-tools-roadmap.md](ai-tools-roadmap.md) — Ask AI tool expansion plan: 11 deployed + 14 to build
- [lane-playbooks.md](lane-playbooks.md) — Lane playbook system, schema, AI tools, API endpoints
- [feedback_overview_simplicity.md](feedback_overview_simplicity.md) — Keep Overview panels simple (loads+rev only), no Dispatch in nav

## Git — Mar 14, 2026
- **Latest**: Mar 14 — Auto-Match Playbook Engine (#106), Process Booking (#107), Build Load UI
- **Repos**: `CSLogix/CSLogix_Bot` (private, `master`) | `CSLogix/csl-dashboard` (private, `main` at `b688b27`)
- **VPS, GitHub, Local** all in sync
- **`.gitignore`**: Excludes `*.bak*`, `*.pre-*`, `*.json` (except package.json), `dist/`, `uploads/`, credentials
- **State files** (`ftl_sent_alerts.json`, `last_check.json`, `export_state.json`) are runtime dedup/state — gitignored, live on VPS only

## Memory Repo — Mar 10, 2026
- **Repo**: `CSLogix/csl-claude-memory` (private) — `git@github.com:CSLogix/csl-claude-memory.git`
- **Local**: `C:\Users\jsfel\.claude` — SSH remote set, tracking `origin/master`
- **SSH key**: `~/.ssh/id_ed25519` added to GitHub (`CSLogix` account)

## Dashboard Component Map (split Mar 14, 2026)
**No longer a monolith.** `DispatchDashboard.jsx` is 1,298 lines (root state + handlers + layout). Components organized into:
- `src/helpers/` — `api.js`, `constants.js` (STATUS_MAP, NAV_ITEMS, REP_ACCOUNTS, equipment, etc.), `utils.js` (normalizeStatus, mapShipment, parseTerminalNotes, getBillingReadiness, filters, date helpers, useIsMobile), `index.js` (barrel)
- `src/components/` — AskAIOverlay, ClockDisplay, CommandPalette, DocIndicators, TerminalBadge, TrackingBadge
- `src/views/` — OverviewView, RepDashboardView, DispatchView, InboxView (has LOCAL inbox constants different from helpers), LoadSlideOver, AnalyticsView (includes DataSourceToggle), BillingView, UnbilledView, HistoryView, MacropointModal, RateIQView (includes HistoryTabContent), PlaybooksView, BOLGeneratorView, AddForm, UserManagementView
- `src/styles.js` — GLOBAL_STYLES CSS constant
- `src/store.js` — Zustand store (askAIOpen/askAIInitialQuery/askAIInitialFiles lifted from local state)

**Callback pattern**: `handleFieldUpdate`/`handleMetadataUpdate` accept `{ toast }` callback. `handleApplyRate` accepts `{ onApplied }` callback. LoadSlideOver passes `showSaveToast`/`setRateApplied` via these.

## Services Architecture (as of Mar 2026)

### Systemd Services (always running)
`csl-dashboard` (8080), `csl-boviet`, `csl-tolead`, `csl-inbox`, `csl-upload` (5001), `bol-webapp` (5002)
Note: `csl-ftl` DISABLED (migrated to cron). `csl-export` DISABLED (migrated to cron). `csl-webhook` DISABLED (migrated into app.py).

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

### Mar 14, 2026 Bot Changes
- **RC Rate Extraction** (#108): `_extract_rate_from_doc()` in routes/emails.py — when `save_attachment` auto-action saves a `carrier_rate` or `customer_rate` doc, triggers Haiku vision extraction (pdftoppm → PNG → Claude) and inserts `rate_quotes` row with `source='document'`. `doc_id` + `source` columns added to `rate_quotes` table. Suggestion banner appears automatically in LoadSlideOver Financials.
- **Auto-Match Playbook Engine** (#106): `playbook_lane_code` column on shipments (indexed). `_try_playbook_match()` in ai_assistant.py — queries active playbooks by account+origin+destination, auto-populates carrier/rates/equipment on exact single match. Hooked into `_exec_bulk_create_loads` (AI tool) and `POST /api/v2/load/add` (dashboard). `GET /api/playbooks/shipment/{efj}` endpoint. Added to `_shipment_row_to_dict` serializer.
- **Process Booking** (#107): `POST /api/inbox/process-booking` — two-click load creation. Sender domain→account lookup (17 domains). Claude Sonnet AI extraction. Confidence scoring. Fuzzy playbook match with full defaults. Source tracking per field (ai/domain/playbook).
- **Playbook-Aware Ask AI prompt**: System prompt instructs Claude to always call `get_lane_playbook` before `bulk_create_loads` and merge defaults. "Process Booking" chip in AskAIOverlay.
- **Lane Playbooks** (#103): `lane_playbooks` PG table (JSONB + GIN index), `routes/playbooks.py` (6 CRUD endpoints), 3 AI tools, DSV-RICH-WANDO seeded. Schema v2: versioning, changelog, detention_rules, booking_defaults, seasonal_notes.
- **Other**: Tolead origin/dest fix (backfilled 25 loads), DFW destination fix (12 rows), Guest access system (`/guest?code=XXXX`).

### Mar 13, 2026 Bot Changes (condensed)
- **Status normalization** (#100): label→key mapping in v2.py + sheet sync. Fixed archive check for "billed & closed". Normalized 370+ PG rows.
- **Ask AI body_text + PDF vision** (#101): `body_text` TEXT column on email tables. `read_load_document` AI tool (PDF→image via pdftoppm + Sonnet vision).
- **Security**: Session hardening (fail-closed), forced password change, analytics router fix, Eli termination (20 loads reassigned).
- **Auto-Status Email Drafter**, Multi-user auth (7 users, bcrypt), Monolith split (9,794→15 routers + shared.py), Async cache warming (#96), Missing endpoints (#97).

### Mar 12, 2026 Bot Changes (night)
- **Scanner 5-Tier Matching**: `match_email_to_efj()` upgraded from 2-tier to 5-tier. Was only matching EFJ pattern + searching `email_threads.body_preview` for containers (broken). Now: (1) EFJ pattern, (2) Tolead hub IDs (`LAX1260312023`) → `shipments.container`, (3) Container# (`MSCU1234567`) → `shipments.container`, (4) Bare 6-digit (`107330`) → `shipments.efj` (subject-only), (5) BOL/Booking → `shipments.bol`. Patch: `patch_scanner_matching.py` (#95). Rescue script matched 123/6702 unmatched emails (59 hub, 58 container, 6 BOL).

### Mar 12, 2026 Bot Changes (late)
- **Inbox 500 fix**: `psycopg2.InterfaceError: cursor already closed` at `app.py:7239` — inbox enrichment query (`SELECT efj, rep, account FROM shipments`) ran after `with db.get_cursor()` block exited. Fixed with new `cur2` + dict key access. Patches: `fix_inbox_cursor.py` + `fix_inbox_cursor2.py`.
- **Doc reclassify backfill**: `backfill_reclassify_other_docs.py` — Sonnet 4.6 vision reclassified 192/284 "other" docs (64 BOL, 55 POD, 34 carrier_rate, 27 screenshot, 8 carrier_invoice, 2 packing_list, 2 customer_rate). 9 loads auto-advanced to `ready_to_close`. 82 correctly stayed "other" (logos, signatures, embedded images).

### Mar 12, 2026 Bot Changes (condensed)
- **Critical**: FTL archive crash fix (`stop_times` kwarg), ghost load prevention (EFJ prefix guard), stale load archive (65 loads)
- **Email**: Container Update emails DISABLED, CC dedup, Payment Alert batching (digest per rep), CSL Tracking subject includes EFJ#
- **Data**: Revenue backfill ($12M via xlrd), sheet sync cron fix, ACCOUNT_REPS expanded (Prolog/Talatrans/LS Cargo/GW-World)
- **Features**: Port groups module (18 groups) + API, inbox rep filter + actions (assign-rep/mark-actioned), REV window expansion, customer rate extraction, AI doc classifier (Sonnet vision), auto-status advancement (POD+invoice→delivered→ready_to_close)
- **Cleanup**: 69 junk docs deleted, doc reclassify backfill (192/284), inbox 500 fix (cursor closed), scanner 5-tier matching (#95, rescued 123 emails)

### Mar 11, 2026 Bot Changes (condensed)
- Margin Bridge (rate-quotes/apply-rate endpoints), Archive Distance Guard, Status Writeback to Sheet, Unbilled Weekly Digest, Sync Guard + PG→Sheet Write-back, No-Reply Alert Fix, Boviet invoice writer, date/terminal normalizers

## Recent Dashboard Changes (Deployed)

### Mar 14, 2026 Dashboard Changes (late)
- **Dispatch nav removed** (again): Dispatch link removed from `NAV_ITEMS` in constants.js — accessible only via stat cards on Overview. Was accidentally re-added.
- **Overview panels simplified**: "Rep Scoreboard" → "Rep Overview" (loads + rev only, removed COMMS/DOCS/STALE defense columns). "Account Health" → "Accounts" (loads + rev only, removed Friction/HS columns and red/green health score styling). Neutral row styling.
- **Overview grid equalized**: Both rows changed from `6fr 4fr` → `1fr 1fr`. All 4 panels (Rep Overview, Accounts, Today's Actions, Live Alerts) now equal width in clean 2×2 grid.
- **Live Alerts — grouped + urgency sorted**: Alerts with same type+rep collapse into single row ("Tolead: 7 needs driver"). Urgency sort: lfd_today→lfd_tomorrow→needs_driver→tracking_behind→status_change. Group header shows count badge + "next in Xh Ym" soonest pickup countdown. Expand/collapse to see individual alerts. Single alerts show inline "pickup in Xm" countdown.

### Mar 14, 2026 UI Audit (no code changes)
- **Comprehensive UI analysis** done across all views. Key problem areas identified:
  - **Dispatch table**: 15 columns, requires 2000px+ viewport — needs column picker (hide/show)
  - **LoadSlideOver actions**: 8 buttons in 380px wraps badly — reduce to 4 primary + overflow menu
  - **Font sizes**: 9-10px in dispatch table cells — below legibility threshold, bump to 11px min
  - **RateIQ tabs**: 7 tabs crowded in one row — redesign planned (see below)
  - **Filter bar**: 5+ inputs overflow at <1360px — needs floating filter drawer or popover
  - **Button inconsistency**: 3 different styles with no clear hierarchy
  - **Status colors**: 17 distinct colors, several nearly-identical blues
  - **Spacing**: Ad-hoc (3/5/6/7px) — needs 8px grid enforcement
- **Next**: Rate IQ UI redesign (starting in new chat)

### Mar 14, 2026 Dashboard Changes
- **MP Status real-time sync**: LoadSlideOver now pushes fresh `/api/macropoint/{efj}` data back into global `trackingSummary` Zustand store. Dispatch table MP STATUS column updates immediately when slide-over opens (was stale until next poll). `setTrackingSummary` upgraded to support function updaters.
- **30s tracking fast-poll**: Dedicated `setInterval(30000)` polls `/api/shipments/tracking-summary` so webhook-triggered MP updates appear in dispatch table within 30s (was 90s full fetchData cycle).
- **Playbook badge in dispatch**: Book icon next to EFJ# in dispatch table (desktop + mobile) when `playbookLaneCode` is set. Teal lane code badge in LoadSlideOver header.
- **Process Booking / Build Load button**: Orange "Build Load" button in inbox thread detail header. Fires AI extraction + playbook match.
- **Load Confirmation slide-over**: 420px right-side drawer. Green "Active Playbook Applied" or Yellow "New Lane Detected" banner. Editable form with source badges (AI blue, DOMAIN purple, PLAYBOOK teal). MISMATCH/MISSING field highlighting. Multi-load warning, key contacts, playbook instructions. "Index as new playbook" checkbox → Ask AI. "Create Load & Dispatch" button → v2/load/add + rate_quotes history. Low-confidence guard.
- **Playbook-Aware Ask AI**: System prompt updated — Claude always checks `get_lane_playbook` before `bulk_create_loads`, merges defaults. "Process Booking" quick-action chip added to AskAIOverlay.
- **Lane Playbooks frontend** (#104): `PlaybooksView.jsx` — list/detail sub-views, card grid with search + status filter, 2-column detail layout (overview, carriers, rates, facilities, contacts, workflow, escalation, changelog). "Index New Lane" opens Ask AI.
- **Frontend monolith split**: `DispatchDashboard.jsx` 10,428 → 1,298 lines. 25 files across `helpers/`, `components/`, `views/`.
- **Bug fixes**: handleApplyRate field corruption (CX rate→carrier pay), showSaveToast scope, setRateApplied scope.
- **Other**: Rate IQ dark dropdowns, Lane Search transload badge, Account Health sort by loads.

### Mar 13, 2026 Dashboard Changes (late night)
- **Smart Inbox Auto-Actions** (#102): Actions column in inbox table with contextual one-click buttons. `getAutoAction(thread)` maps email_type → suggested action. Buttons: "Save [type]" (teal, for doc emails with attachments), "Delivered" (green, delivery confirmations), "Draft" (blue, opens Ask AI with reply context), "Done" (gray, marks actioned). Thread detail panel: "Draft Reply" + "Save Docs" buttons. Backend `POST /api/inbox/{thread_id}/auto-action` — 3 actions: save_attachment (Gmail API download → load_documents + SHA-256 dedup + billing advance check), mark_delivered, mark_actioned. Optimistic UI updates + flash animation.
- **Status key fix**: `handleStatusUpdate` sends `newStatus` (key) not `statusLabel`. STATUS_MAP added `"billed & closed": "billed_closed"`. HistoryView status dropdown same fix. Drag-to-Ask prompt uses `body_text` (1000 chars) instead of `body_preview` (200 chars). AI summary context uses body_text.
- **Status update fix** (#100): efj-based matching (not index). Zustand `setSelectedShipment` updater support. Save toast + sync indicator.
- **csl-export service disabled**: cron-only now.
- **Auto-Status Email Drafter** (#99): Milestone triggers → HTML email drafts. Drafts badge + modal.
- **Directory ↔ Quote Builder** (#98): Carrier suggestions + feedback loop.
- **Billing statuses always visible**: All loads show billing status buttons regardless of current status.
- **Save feedback toast**: Green "✓ saved" / Red "⚠ Failed" per field save.

### Mar 12, 2026 Dashboard Changes (condensed)
- **Account Health View**: OverviewView grid — Health Score = margin_pct - friction_score, clickable rows → dispatch. `GET /api/account-health` (5 SQL queries)
- **NEEDS REPLY → Load Indexing**: Click thread → slide-over with emails expanded + row pulse-highlight (3s teal fade)
- **Drag email → Ask AI**: Draggable inbox rows, drop on AI button → pre-filled summary prompt
- **Smart Billing Queue**: `getBillingReadiness()`, Close Ready filter, bulk close, doc status columns
- **Rep Scoreboard v2**: 7 SQL queries (offense: loads/rev, defense: comms/docs/stale), clickable cells → filtered views
- **Mobile layout (Phase 5)**: `useIsMobile()` hook, bottom nav, card views, full-width panels
- **Other**: Packing list doc type, COMMS click fix, port group pills, Rate IQ History tab, directory port filter, inbox rep chip, MGN column, MP URL edit, Boviet project cards, customer rate banner, hideActioned fix, emails expanded by default, DispatchView crash fix, AI summary card

### Mar 11, 2026 Dashboard Changes (condensed)
- **Carrier Intelligence Suite**: Directory tab (cards + inline editing + capability pills), Lane Search (grouped results, inline rate editing, carrier enhancements), schema expansion (12 new columns), Sheet imports (35 carrier tabs, 40 rate tabs), doc dedup (SHA-256), MP→billing bridge, Loadboard rename, BOL systemd
- **Ask AI Command Palette**: `ai_assistant.py` — Claude Sonnet 4.6, 23 tools across 4 tiers, `POST /api/ask-ai`, `AskAIOverlay` component (Ctrl+K), quick-action chips, markdown rendering
- **Overview**: + New Load button, Billing Pipeline section (stage cards with counts), STATUS_MAP underscore fix
- **Team Feedback Fixes**: Dispatch nav removed (accessible via stat cards — re-confirmed Mar 14), Yesterday filter + stat card, ← Overview back button, layout reorder (Team above Actions), Boviet STATUS_MAP, inbox density reduction
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
- **API auth**: `csl_session` cookie (HMAC-signed, password_gen checked, fail-closed) OR `X-Dev-Key` + IP allowlist. Forced pw change on first login (`password_gen <= 1` → `/change-password`)
- **Vite dev**: proxy `/api/*` → production server with dev key header
- **Zustand store**: `setShipments` and `setTrackingSummary` support function updaters
- **Multi-provider tracking**: SeaRates → JSONCargo → Playwright. Cache `jsoncargo_cache.json` 6hr TTL
- **PG dual-write**: `csl_pg_writer.py` (UPSERT/archive) + `csl_sheet_writer.py` (fire-and-forget sheets)
- **Data source fallback**: Zustand `dataSource` ("postgres"|"sheets"). Yellow "SHEETS MODE" badge when active

## SeaRates APIs
- **Container Tracking** (`tracking.searates.com`): INTEGRATED via `_searates_container_track()`
- **Ship Schedules v2** (`schedules.searates.com/api/v2`): NOT YET INTEGRATED. Full OpenAPI spec saved → [searates-schedules-api.md](searates-schedules-api.md)

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

### Completed (all deployed)
Tracking Portal, Inbox polish, Margin Guard+Bridge+MGN, Rep Scoreboard v2, Account Health View, Auto-Status Email Drafter, Directory ↔ Quote Builder, Boviet Project Cards, Mobile layout, Billing Flow (auto-advance + bulk close), Container Update emails disabled

### Remaining
- **Rate IQ UI Redesign**: Autocomplete + recent searches + Quick Quote + enhanced carrier cell + Email RC built locally, NOT YET DEPLOYED. See rateiq.md.
- **Rate Backfill COMPLETE**: Gmail (17 rates/159 threads) + Outlook (190 rates/322 .msg files) = 207 new rates. DB total ~355. See rateiq.md.
- **Outlook 35 errors**: NoneType bug in classify_mode — fixable by guarding args. Low priority (most were no-rate emails anyway).
- **Dispatch Column Picker**: Hide/show columns toggle — 15 cols currently overwhelming
- **LoadSlideOver action consolidation**: 4 primary + overflow menu
- **Global font floor**: 11px minimum in all tables (currently 9-10px)
- **Carrier Auto-Quote Request**: PLANNED — AI picks top 3 carriers from Directory, auto-drafts rate request emails. Not started.
- Rate IQ Phase 2: OOG IQ (real data), FTL IQ (not built)
- Tolead/Boviet slide-over fields (driver phone, delivery date, appt_id)
- Warehouse extract: `POST /api/warehouses/extract` handler

### Radka Feedback Items (from Daily Agenda doc, Mar 12)
- ✅ **Inbox "click does nothing"**: FIXED — emails now expanded by default in LoadSlideOver + NEEDS REPLY click indexes to load
- ✅ **"Don't need updates by account"**: FIXED — Container Update emails disabled
- ✅ **"Emails CC'ing me multiple times"**: FIXED — CC dedup + payment alert batching
- **"No links in emails to team"**: Bot sends hyperlinks to tracking sites. Clarify if they want those removed.
- **Rate IQ "not uploading properly"**: Endpoint exists, code looks correct. Need specific error/screenshot.
- **Cadi load to Laredo workflow**: Needs clarification on what to do differently.
- **BOL generator**: Service running (200 OK). Needs end-to-end test.

## Health Check Baseline — Mar 12, 2026
- **Server**: 6% disk (184G free), 2.3G/15G RAM, load 0.44, 8 days uptime
- **DB**: 844 shipments (231→~166 active after archive), 904→835 docs (192 reclassified from "other"), 2,344 emails, ~355 rate quotes (was 92→165 gmail→355 outlook), 307 unbilled
- **Status distribution after cleanup**: 27 distinct statuses → normalized to standard set (Title Case)
- **Ghost prevention**: EFJ prefix guard deployed in sheet sync. Tolead container numbers no longer create ghost EFJ rows.

## Documents Created
- **CSLogix Workflow Guide** (`Desktop/CSLogix_Work_flow_v2.pptx`): 8-slide dark-theme PPTX for Janice (JC), billing coordinator. Added Column Filters tip bar to slide 5 (Dispatch View) + split slide 7 (Inbox) bottom row into Unbilled Orders / Live Alerts 2×2 grid. XML-edited via unpack/pack workflow.

## Completed Integrations
- **Sentry**: Error tracking + monitoring
- **Tailwind UI**: Component library + utility-first CSS
- **Postgres Migration** (Phases 1-4): `shipments` table, v2 endpoints, bot dual-write, sheet sync
