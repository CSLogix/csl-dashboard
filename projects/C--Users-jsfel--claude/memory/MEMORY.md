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

## Git — Mar 14, 2026
- **Latest**: Mar 14 — Frontend monolith split (10K→25 files) + 3 bug fixes
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
- `src/views/` — OverviewView, RepDashboardView, DispatchView, InboxView (has LOCAL inbox constants different from helpers), LoadSlideOver, AnalyticsView (includes DataSourceToggle), BillingView, UnbilledView, HistoryView, MacropointModal, RateIQView (includes HistoryTabContent), BOLGeneratorView, AddForm, UserManagementView
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
- **Tolead origin/dest fix** (#103): `_shorten_address()` in `csl_sheet_sync.py` was broken — regex body got stranded after `_get_sheet_hyperlinks()` was inserted mid-function. Function returned `None` for all non-empty addresses. All Tolead origin/destination synced as `NULL` since hyperlinks patch. Fixed + manual sync backfilled all 25 active Tolead loads (ORD/JFK/LAX/DFW). Nancy Feltz reported.

### Mar 13, 2026 Bot Changes (late night)
- **Status label→key normalization** (#100): `_STATUS_LABEL_TO_KEY` + `_normalize_status()` in v2.py. `_SHEET_STATUS_MAP` + `_normalize_sheet_status()` in sheet sync. Archive check expanded to include "billed & closed". Fixed EFJ107285 reappearing after Billed & Closed. Normalized 370+ PG rows.
- **Ask AI body_text + PDF vision** (#101): `body_text` TEXT column on both email tables. Scanner `get_full_body_text()` extracts full plain text or HTML→text. `read_load_document` tool in ai_assistant.py — PDF→image via pdftoppm + Claude Sonnet vision. COALESCE(body_text, body_preview) in AI queries. body_text in inbox API responses. Remaining: backfill body_text for ~6700 existing emails.

### Mar 13, 2026 Bot Changes (evening)
- **Session security hardening**: Rotated `.session_secret`, fail-closed verify_session_token(), reject tokens without user_id.
- **Forced password change**: `/change-password` routes, login redirect when `password_gen <= 1`.
- **Analytics router fix**: `routes/analytics.py` not mounted after monolith split — added import + include_router.
- **Eli termination**: Deactivated rep. 20 loads reassigned to John F.

### Mar 13, 2026 Bot Changes
- **Auto-Status Email Drafter**: `routes/email_drafts.py` — milestone triggers → HTML email drafts. Ask AI `bulk_create_loads` fix.
- **Multi-user auth**: PG `users` table (bcrypt), 7 users, session tokens carry user_id/role/rep_name.
- **Monolith split**: 9,794-line `app.py` → 15 APIRouter modules in `routes/` + `shared.py`.
- **Async cache warming** (#96) + **Missing endpoints restored** (#97).

### Mar 12, 2026 Bot Changes (night)
- **Scanner 5-Tier Matching**: `match_email_to_efj()` upgraded from 2-tier to 5-tier. Was only matching EFJ pattern + searching `email_threads.body_preview` for containers (broken). Now: (1) EFJ pattern, (2) Tolead hub IDs (`LAX1260312023`) → `shipments.container`, (3) Container# (`MSCU1234567`) → `shipments.container`, (4) Bare 6-digit (`107330`) → `shipments.efj` (subject-only), (5) BOL/Booking → `shipments.bol`. Patch: `patch_scanner_matching.py` (#95). Rescue script matched 123/6702 unmatched emails (59 hub, 58 container, 6 BOL).

### Mar 12, 2026 Bot Changes (late)
- **Inbox 500 fix**: `psycopg2.InterfaceError: cursor already closed` at `app.py:7239` — inbox enrichment query (`SELECT efj, rep, account FROM shipments`) ran after `with db.get_cursor()` block exited. Fixed with new `cur2` + dict key access. Patches: `fix_inbox_cursor.py` + `fix_inbox_cursor2.py`.
- **Doc reclassify backfill**: `backfill_reclassify_other_docs.py` — Sonnet 4.6 vision reclassified 192/284 "other" docs (64 BOL, 55 POD, 34 carrier_rate, 27 screenshot, 8 carrier_invoice, 2 packing_list, 2 customer_rate). 9 loads auto-advanced to `ready_to_close`. 82 correctly stayed "other" (logos, signatures, embedded images).

### Mar 12, 2026 Bot Changes
- **FTL Monitor crash fix**: `archive_ftl_row_pg()` missing `stop_times` kwarg — FTL loads couldn't archive. Added parameter. **CRITICAL fix.**
- **Ghost load prevention**: EFJ prefix guard in `csl_sheet_sync.py` — if Tolead efj column has container# (not `EFJ` prefix), treats as load_id to prevent ghost rows. Cleaned 4 ghosts (LAX1260309008 + 3 ORD).
- **Stale load archive**: Archived 65 Delivered + Billed & Closed loads stuck as active. 10 "Ready to Close" left for billing pipeline.
- **CSL Tracking email subject**: Now includes EFJ# — `CSL Tracking — Account — EFJ107xxx | LoadID — Status`
- **Junk doc cleanup**: Deleted 69 embedded email images (image027.png etc.) misclassified as carrier_invoice. No new ones since Mar 6 (junk filter works).
- **Container Update emails DISABLED**: `send_account_notification()` early-returns with log. Team no longer wants per-account container change emails.
- **CC dedup fix**: `_send_email()` in csl_bot.py deduplicates CC addresses before sending (was sending "EFJ - J Feltz" x3).
- **Payment Alert batching**: Converted per-load instant PAYMENT ALERT emails → single batched digest per rep. `_payment_alert_queue` collects during scan, `_flush_payment_alerts()` sends one table email at end.
- **Sheet sync cron fix**: Was pointing to wrong file (`csl-doc-tracker/csl_sheet_sync.py` 19KB → `/root/csl-bot/csl_sheet_sync.py` 33KB). Prolog, MD Metal, Talatrans now sync.
- **Revenue backfill**: `patch_revenue_backfill.py` — XLS commission report → PG `customer_rate` (596 shipments, $12M total via xlrd)
- **Inbox rep filter**: `patch_inbox_rep_filter.py` — enriches `/api/inbox` threads with `rep` from shipments table JOIN, fixes `rep_filter`
- **Port groups**: `port_groups.py` (new module) — 18 port/rail groups (LA/LB, NY/NJ, Savannah, Chicago Rail, etc.) + `normalize_to_port_group()`
- **Port groups API**: `patch_port_groups.py` — `/api/port-groups`, `/api/rate-history` endpoints, search-lane port group expansion, apply-rate→lane_rates INSERT
- **ACCOUNT_REPS**: Added Prolog, Talatrans, LS Cargo (→Radka), GW-World (→John F) to `csl_bot.py`
- **REV window expansion**: `patch_rev_window.py` — scoreboard loads/revenue queries use `archived = false` instead of 7-day rolling filter + `total_margin` in response
- **Inbox actions**: `patch_inbox_actions.py` — `manual_rep` + `actioned` columns on email_threads, 2 new PATCH endpoints (assign-rep, mark-actioned), needs_reply filters actioned threads
- **Customer rate extraction**: `patch_customer_rate_extraction.py` — `extract_rate_from_email()` now handles `customer_rate` emails, adds `rate_type` field, `rate_quotes.rate_type` column
- **AI Document Classifier**: `patch_ai_doc_classifier.py` — Sonnet 4.6 vision classifies ambiguous attachments (CamScanner PDFs, phone photos, generic filenames) when regex returns "other". 8/8 accuracy in live testing. Fires only on ambiguous docs (~$7.50/mo).
- **Auto-status advancement**: `check_and_advance_billing()` in scanner — after saving docs, checks if POD + carrier_invoice both present. In-transit/at-delivery → Delivered → Ready to Close. Already-delivered → Ready to Close. Hands-free billing pipeline.

### Mar 11, 2026 Bot Changes (condensed)
- **Margin Bridge**: `patch_margin_bridge.py` — customer_rate/carrier_pay serialization, rate-quotes/apply-rate endpoints, auto-reject competing quotes. AI extraction v2 (expanded body window, linehaul/accessorials fields). Rate suggestion banner in LoadSlideOver.
- **Archive Distance Guard**: `patch_archive_distance_guard.py` — block false D1 archive when distance_to_stop > 15mi in ftl_monitor + webhook handler
- **Status Writeback**: v2 status endpoint writes back to Master Sheet for non-shared accounts (was being overwritten by 3-min sync)
- **Unbilled Weekly Digest**: `unbilled_weekly_digest.py` — Outlook-safe HTML email, Monday 7:15 AM, aging buckets + customer breakdown
- **Sync Guard + PG→Sheet Write-back**: sheet_synced_at stamps, cron */3, Tolead LAX + Boviet write-back
- **No-Reply Alert Fix**: Self-email filter, EFJ dedup, 4hr lookback cap, lane fallback
- **Other**: Boviet invoice writer, dray daily report HTML fix, MP alert subject rename ("CSL Tracking"), margin guard + date/terminal normalizers

## Recent Dashboard Changes (Deployed)

### Mar 14, 2026 Dashboard Changes
- **Frontend monolith split**: `DispatchDashboard.jsx` 10,428 → 1,298 lines. 25 files across `helpers/`, `components/`, `views/`. Clean Vite build, deployed.
- **Bug fix: handleApplyRate field corruption**: Was hard-coding `field: "carrier_pay"` — "Apply CX Rate" saved customer rate as carrier pay. Now reads `quote._field` and maps to correct state key (`carrierPay` vs `customerRate`).
- **Bug fix: showSaveToast scope**: Called from root but defined in LoadSlideOver. Now passed as `{ toast }` callback — toasts show correctly on inline field saves.
- **Bug fix: setRateApplied scope**: Called from root but state lived in LoadSlideOver. Now passed as `{ onApplied }` callback — rate suggestion banner hides after applying.
- **Rate IQ dark dropdowns** (#103): Directory Markets/Ports/Tier `<select>` dropdowns now use `#151926` background on `<option>` elements (was OS-default white). All 3 selects fixed.
- **Lane Search transload badge**: Added `can_transload` (🔄, sky blue `#38bdf8`) to `capBadges` in Lane Search carrier table. Was missing — only 6 of 7 capabilities were shown.

### Mar 13, 2026 Dashboard Changes (late night)
- **Smart Inbox Auto-Actions** (#102): Actions column in inbox table with contextual one-click buttons. `getAutoAction(thread)` maps email_type → suggested action. Buttons: "Save [type]" (teal, for doc emails with attachments), "Delivered" (green, delivery confirmations), "Draft" (blue, opens Ask AI with reply context), "Done" (gray, marks actioned). Thread detail panel: "Draft Reply" + "Save Docs" buttons. Backend `POST /api/inbox/{thread_id}/auto-action` — 3 actions: save_attachment (Gmail API download → load_documents + SHA-256 dedup + billing advance check), mark_delivered, mark_actioned. Optimistic UI updates + flash animation.
- **Status key fix**: `handleStatusUpdate` sends `newStatus` (key) not `statusLabel`. STATUS_MAP added `"billed & closed": "billed_closed"`. HistoryView status dropdown same fix. Drag-to-Ask prompt uses `body_text` (1000 chars) instead of `body_preview` (200 chars). AI summary context uses body_text.
- **Status update fix** (#100): efj-based matching (not index). Zustand `setSelectedShipment` updater support. Save toast + sync indicator.
- **csl-export service disabled**: cron-only now.
- **Auto-Status Email Drafter** (#99): Milestone triggers → HTML email drafts. Drafts badge + modal.
- **Directory ↔ Quote Builder** (#98): Carrier suggestions + feedback loop.
- **Billing statuses always visible**: All loads show billing status buttons regardless of current status.
- **Save feedback toast**: Green "✓ saved" / Red "⚠ Failed" per field save.

### Mar 12, 2026 Dashboard Changes (night)
- **Emails expanded by default**: LoadSlideOver `emailsCollapsed` init changed from `true` → `false`. Emails section visible immediately when slide-over opens.

### Mar 12, 2026 Dashboard Changes (latest)
- **Account Health View**: New panel in OverviewView Row 1 right column (next to Rep Scoreboard), replacing old Account Overview bar chart. Backend `GET /api/account-health` (`patch_account_health.py`, patch #94) — 5 SQL queries GROUP BY account: active loads+revenue+margin, unreplied threads, docs needed, neglected loads, rep mapping (DISTINCT ON + ORDER BY updated_at DESC). Grid columns: Account, Loads, Revenue, Friction, Health Score. Health Score = margin_pct - friction_score (friction = unreplied×2 + docs_needed×1.5 + neglected×1). Sort toggle cycles Health→Revenue→Friction. Clickable rows → dispatch filtered by account (Boviet/Tolead → rep dashboard). Fallback to old bar chart if API empty. Margin% column intentionally hidden (owner preference). Grid ratio 1.1fr/0.9fr, content padding 32px. `accountHealth` + `setAccountHealth` in Zustand store, 2-min polling.

### Mar 12, 2026 Dashboard Changes (late)
- **NEEDS REPLY → Load Indexing**: Clicking a thread in the NEEDS REPLY dropdown now opens the load's slide-over with emails auto-expanded + smooth-scrolled into view, AND pulse-highlights the matching row in the dispatch table (3s teal fade-out). `expandEmailsOnOpen` + `highlightedEfj` Zustand state, `handleLoadClick(s, { expandEmails, highlight })` opts pattern, `emailsSectionRef` + `useEffect` scroll, highlight applied across all 5 row render sites (RepDash dray/ops/FTL, DispatchView desktop, mobile cards).
- **DispatchView crash fix**: `filteredShips` → `filtered` in mobile card view (line 6173). Wrong variable name caused error boundary crash on any navigation.
- **Drag email → Ask AI**: Inbox rows are `draggable="true"`. Drag any thread onto the "Ask AI" button in top nav — it glows/scales with "Drop to Summarize" text. On drop, opens AskAIOverlay with pre-filled prompt including full thread context (subject, sender, messages, AI classification). `AskAIOverlay` accepts `initialQuery` + `onConsumeInitialQuery` props, auto-sends on open.
- **AI Summary card**: Thread detail slide-over now shows `ai_summary` in a teal card at the top of the message list (was in data but never rendered).
- **hideActioned filter fix**: Operator precedence bug — `!t.dismissed && t.needs_reply !== false || !t.has_csl_reply` → fixed to `!t.actioned && (t.needs_reply || t.source === "unmatched")`. "Showing New" now correctly filters to actionable threads only.

### Mar 12, 2026 Dashboard Changes
- **Packing List doc type**: Added `packing_list` to DOC_TYPES_ADD, DOC_TYPE_LABELS, both reclassify dropdowns, both upload dropdowns, icon mapping (📦). Frontend + backend.
- **COMMS click fix**: Scoreboard COMMS click → Inbox filtered by rep (was broken — passed rep as search text). Backend enriches threads with `rep` from shipments JOIN, frontend passes `&rep=` param
- **Port group pills**: Lane Search — 12 port buttons (teal) + 6 rail buttons (purple) above search, click sets origin
- **History tab**: Rate IQ "History" tab — lazy-loads from `/api/rate-history`, groups applied rates by port group
- **Directory port filter**: `<select>` dropdown filters carriers by port group membership
- **Inbox rep chip**: Blue "Radka's Inbox ×" chip when filtered, `inboxInitialRep` added to Zustand store
- **MGN column**: Dispatch table margin column with color coding (red <0, orange <10%, green ≥10%) + sortable via `calcMarginPct()`
- **Billing Pipeline removed from Overview**: Was redundant with Billing tab. Margin summary bar also removed.
- **MP URL edit**: LoadSlideOver Quick Action Strip "Edit MP URL" button with inline input + PATCH to `/api/load/{efj}/mp-url`
- **Inbox thread actions**: Rep assignment `<select>` dropdown + "Mark Actioned" button per thread, ACTIONED badge, actioned threads hidden from needs_reply
- **Boviet Project Cards**: RepDashboardView per-project summary cards (Piedra/Hanson) — active/delivered/pending counts, pickups today, carrier count, last delivery
- **Customer Rate Banner**: LoadSlideOver Financials section shows pending customer rate suggestion with Apply/Reject buttons
- **Mobile layout (Phase 5)**: `useIsMobile()` hook (768px breakpoint), bottom nav bar (Home/Inbox/Rates/Billing/More), full-width slide-overs, card view for dispatch table, horizontal scroll stat cards with snap, CSS media queries
- **Scoreboard tooltips**: Updated from "7d rolling" to "Active loads" / "Active revenue" + margin tooltip
- **Smart Billing Queue**: `getBillingReadiness()` pure function checks POD + carrier_invoice per load via docSummary. Green "Close Ready" stat card + filter. Docs column (INV✓/✗ POD✓/✗). Smart status button (green "Close ✓" when docs complete, advances to correct blocking stage when not). "Close All Ready (N)" bulk close button with 100ms stagger. Close Ready card added to stat row.

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
- **Deferred**: WIN RATE (only 83 rate_quotes, 1 accepted — too sparse), carrier assignment speed + on-time delivery (needs delivered_at TIMESTAMPTZ migration)
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
- **API auth**: `csl_session` cookie (HMAC-signed, password_gen checked, fail-closed) OR `X-Dev-Key` + IP allowlist. Forced pw change on first login (`password_gen <= 1` → `/change-password`)
- **Vite dev**: proxy `/api/*` → production server with dev key header
- **Zustand store**: `setShipments` supports function updaters
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

### Large Items
- **Tolead/Boviet full PG migration**: Resolved as non-issue — data originates from client sheets. Sync guard + write-back deployed instead (see above). ORD/JFK/DFW remain client-shared (no write-back).
- **Customer Tracking Portal**: ✅ DONE
- **Inbox polish**: ✅ DONE — Reply button, density, rep filter, assign-rep dropdown, mark-actioned, drag-to-AI summary, AI summary card in thread detail, hideActioned filter fix all deployed
- **Margin Guard**: ✅ DONE — deployed Mar 11. **Margin Bridge** deployed Mar 11. **MGN column** + margin summary bar deployed Mar 12
- **Rep Scoreboard**: ✅ DONE — v2 deployed Mar 12. REV window expanded to all active loads (not 7d). Deferred: WIN RATE (sparse data), delivered_at TIMESTAMPTZ migration
- **Account Health View**: ✅ DONE — deployed Mar 12. `GET /api/account-health` (5 SQL queries GROUP BY account). Health Score = margin_pct - friction_score. Grid in OverviewView next to Rep Scoreboard, clickable rows → dispatch/rep dashboard

- **Auto-Status Email Drafter**: ✅ DONE — deployed Mar 13. 5 milestone triggers, HTML templates, draft badge + modal + toast in frontend, SMTP send
- **Carrier Auto-Quote Request**: PLANNED — when new load added, AI picks top 3 carriers from Directory and auto-drafts rate request emails. Not started.
- **Container Update emails**: ✅ RESOLVED — `send_account_notification()` early-return IS working (confirmed by `[SUPPRESSED]` logs in cron runs). Emails user saw on Mar 12 ~10:53 PM were from OLD `csl-import` systemd service (long-running process, hadn't reloaded code). Service stopped Mar 13 9:38 AM + disabled. Cron-only now.

### Rate IQ
- ✅ Carrier Directory + Lane Search: DONE — inline editing deployed Mar 11
- ✅ **Directory ↔ Quote Builder**: DONE — deployed Mar 13. Suggest endpoint + feedback loop + suggestion panel in QuoteBuilder
- Phase 2 OOG IQ (real data), Phase 2 FTL IQ (not built)
- Quote extractor v2 deployed (hub normalization + LoadMatch intelligence) — see [rateiq.md](rateiq.md)

### Other
- Tolead/Boviet slide-over fields (driver phone, delivery date, appt_id)
- Phase 3: Boviet Project Cards — ✅ DONE (deployed Mar 12, per-project summary in RepDashboardView)
- Phase 5: Mobile App Layout — ✅ DONE (deployed Mar 12, bottom nav + card views + full-width panels)
- Warehouse extract: `POST /api/warehouses/extract` handler
- Customer rate extraction pipeline deployed (scanner handles customer_rate emails → rate_quotes with rate_type)
- **Billing Flow**: ✅ DONE — Smart auto-advance (doc-aware), AI doc classifier (Sonnet vision), auto-status advancement (POD+invoice→delivered→ready_to_close), bulk close, Close Ready filter. Full hands-free pipeline until final close click.

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
- **DB**: 844 shipments (231→~166 active after archive), 904→835 docs (192 reclassified from "other"), 2,344 emails, 92 rate quotes, 307 unbilled
- **Status distribution after cleanup**: 27 distinct statuses → normalized to standard set (Title Case)
- **Ghost prevention**: EFJ prefix guard deployed in sheet sync. Tolead container numbers no longer create ghost EFJ rows.

## Documents Created
- **CSLogix Workflow Guide** (`Desktop/CSLogix_Work_flow_v2.pptx`): 8-slide dark-theme PPTX for Janice (JC), billing coordinator. Added Column Filters tip bar to slide 5 (Dispatch View) + split slide 7 (Inbox) bottom row into Unbilled Orders / Live Alerts 2×2 grid. XML-edited via unpack/pack workflow.

## Completed Integrations
- **Sentry**: Error tracking + monitoring
- **Tailwind UI**: Component library + utility-first CSS
- **Postgres Migration** (Phases 1-4): `shipments` table, v2 endpoints, bot dual-write, sheet sync
