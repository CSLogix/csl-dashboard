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
- [feedback_git_workflow.md](feedback_git_workflow.md) — Git workflow: commit everything, no SCP patches, deploy helpers

## Git — Mar 16, 2026
- **Latest**: Mar 16 — Full git sync: 15 modified + 6 new server files committed, dashboard bulk/delete/repview committed
- **Repos**: `CSLogix/CSLogix_Bot` (private, `master`) | `CSLogix/csl-dashboard` (private, `main`)
- **VPS, GitHub, Local** all in sync as of Mar 16
- **`.gitignore`**: Excludes `*.bak*`, `*.pre-*`, `*.json` (except package.json), `dist/`, `uploads/`, credentials, `rate-msg-dump/`, one-time scripts
- **State files** (`ftl_sent_alerts.json`, `last_check.json`, `export_state.json`) are runtime dedup/state — gitignored, live on VPS only
- **Server deploy helpers**: `csl-deploy` (pull + restart) and `csl-commit` (stage + commit + push) in `~/.bashrc`
- **Workflow**: Edit locally → commit → push → `csl-deploy` on server. Or hotfix on server → `csl-commit` immediately.

## Memory Repo — Mar 10, 2026
- **Repo**: `CSLogix/csl-claude-memory` (private) — `git@github.com:CSLogix/csl-claude-memory.git`
- **Local**: `C:\Users\jsfel\.claude` — SSH remote set, tracking `origin/master`
- **SSH key**: `~/.ssh/id_ed25519` added to GitHub (`CSLogix` account)

## Dashboard Component Map (split Mar 14, 2026)
**No longer a monolith.** `DispatchDashboard.jsx` is 1,298 lines (root state + handlers + layout). Components organized into:
- `src/helpers/` — `api.js`, `constants.js`, `utils.js`, `index.js` (barrel)
- `src/components/` — AskAIOverlay, ClockDisplay, CommandPalette, DocIndicators, TerminalBadge, TrackingBadge
- `src/views/` — OverviewView, RepDashboardView, DispatchView, InboxView, LoadSlideOver, AnalyticsView, BillingView, UnbilledView, HistoryView, MacropointModal, RateIQView, PlaybooksView, BOLGeneratorView, AddForm, UserManagementView
- `src/styles.js` — GLOBAL_STYLES CSS constant
- `src/store.js` — Zustand store

**Callback pattern**: `handleFieldUpdate`/`handleMetadataUpdate` accept `{ toast }` callback. `handleApplyRate` accepts `{ onApplied }` callback.

## Services Architecture (as of Mar 2026)

### Systemd Services (always running)
`csl-dashboard` (8080), `csl-boviet`, `csl-tolead`, `csl-inbox`, `csl-upload` (5001), `bol-webapp` (5002)
Note: `csl-ftl`, `csl-export`, `csl-webhook` all DISABLED (migrated to cron / app.py).

### Cron Jobs
- **Dray Import/Export** (`--once`): 7:30 AM & 1:30 PM Mon-Fri
- **FTL Monitor** (`--once`): every 30 min, 6AM-8PM Mon-Fri
- **Sheet→PG Sync**: every 3 min, 6AM-8PM (Tolead+Boviet+Master)
- **Daily Summary**: 7:00 AM daily | **Health Check**: every 15 min, 6AM-7PM
- **Macropoint Screenshots**: every 30 min, 7AM-7PM Mon-Fri
- **Vessel Schedules**: 6:00 AM & 12:00 PM Mon-Fri
- **Boviet Invoice Writer**: every 2 hrs, 6AM-8PM Mon-Fri
- **Unbilled Weekly Digest**: Monday 7:15 AM ET

## Recent Changes (Mar 12-16, 2026)

### Server (Bot/API) — All committed Mar 16
- Auth rewrite (password_gen, forced change-password), playbooks CRUD router, analytics router, email_drafts router
- AI tools: bulk_create_loads, read_load_document, playbook-aware prompts (+720 lines)
- Webhook processing: complete rewrite (~2100 lines refactored)
- Emails: body_text in inbox, RC rate extraction via AI vision
- v2: status normalization (label→key), playbook_lane_code, coverage status
- Directory: carrier suggest endpoint, miles/zip/MC join for quote builder
- 5-tier inbox matching, DFW destination lookup, scanner improvements
- Multi-user auth (7 users, bcrypt), monolith split (9,794→15 routers + shared.py)
- Status normalization (370+ PG rows), session hardening (fail-closed)

### Dashboard — All committed Mar 16
- Overview redesign: MyActions merge, dark theme, gradient accents, rep avatars
- Bulk create mode in AddForm, hub selector for Boviet/Tolead
- Delete load button + confirmation modal in LoadSlideOver
- RepDashboardView: "All" tab default, date picker filters, auto-FTL view
- Dispatch column picker, 11px font floor, LoadSlideOver action consolidation
- Rate IQ miles/zip/MC/email, Lane Playbooks frontend, Process Booking flow
- Smart Inbox Auto-Actions, Load Confirmation slide-over, MP real-time sync
- **Inline editing**: ALL dispatch cells editable (Account, EFJ, Container, Origin, Destination + existing fields). Tab/Shift+Tab/Enter/Escape spreadsheet navigation. Bidirectional sync between loadboard and slide-over

### Earlier (Mar 5-11) — condensed
See topic files. Key: Carrier Intelligence Suite, Ask AI (23 tools), Financials+Margin Guard, Mobile layout, Rep Scoreboard, Account Health, Sheet dual-write, Tolead dedup, Live Alerts.

## Key Technical Patterns
- **API auth**: `csl_session` cookie (HMAC-signed, fail-closed) OR `X-Dev-Key` + IP allowlist
- **Vite dev**: proxy `/api/*` → production server with dev key header
- **Zustand store**: `setShipments` and `setTrackingSummary` support function updaters
- **PG dual-write**: `csl_pg_writer.py` (UPSERT/archive) + `csl_sheet_writer.py` (fire-and-forget sheets)
- **Data source fallback**: Zustand `dataSource` ("postgres"|"sheets"). Yellow "SHEETS MODE" badge when active
- **Batched sheet writes**: ~12 API calls vs ~96. `_retry_on_quota()` retries 429s with backoff

## SeaRates APIs
- **Container Tracking**: INTEGRATED via `_searates_container_track()`
- **Ship Schedules v2**: NOT YET INTEGRATED. Spec saved → [searates-schedules-api.md](searates-schedules-api.md)

## Tool Preferences
- **Always use Vite preview tools** for verification. Preview server: port 5173
- **Never use Claude in Chrome MCP** for dashboard verification
- **SSH escaping**: Never use bash heredocs for binary-sensitive ops. SCP Python scripts instead

## Deploy Checklist
1. `cd dashboard && npx vite build` in `C:\Users\jsfel\Downloads\csl-dashboard-preview\dashboard\`
2. `scp dashboard/dist/index.html root@187.77.217.61:/root/csl-bot/csl-doc-tracker/static/dist/`
3. `scp dashboard/dist/assets/* root@187.77.217.61:/root/csl-bot/csl-doc-tracker/static/dist/assets/`
4. `ssh root@187.77.217.61 "systemctl restart csl-dashboard"` (or just `csl-deploy` if already pushed to git)
5. Hard refresh (`Ctrl+Shift+R`) to bypass Cloudflare cache

## Remaining Work
- **Carrier Auto-Quote Request**: PLANNED — AI picks top 3 carriers, auto-drafts rate request emails
- Rate IQ Phase 2: OOG IQ (real data), FTL IQ (not built)
- Tolead/Boviet slide-over fields (driver phone, delivery date, appt_id)

## Health Check Baseline — Mar 12, 2026
- **Server**: 6% disk (184G free), 2.3G/15G RAM, load 0.44
- **DB**: 844 shipments, 835 docs, 2,344 emails, ~483 rate quotes, 307 unbilled
