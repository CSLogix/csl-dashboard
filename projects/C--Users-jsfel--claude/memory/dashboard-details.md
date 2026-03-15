# Dashboard Details

## Component File Map (split Mar 14, 2026)
No longer a monolith. Root `DispatchDashboard.jsx` (1,298 lines) contains state, handlers, layout.

| File | Lines | Purpose |
|------|-------|---------|
| `src/DispatchDashboard.jsx` | 1,298 | Root — state, API fetching, handlers, nav, layout |
| `src/store.js` | 118 | Zustand store (askAI state lifted here) |
| `src/styles.js` | 67 | GLOBAL_STYLES CSS constant |
| `src/helpers/api.js` | 8 | apiFetch wrapper + API_BASE |
| `src/helpers/constants.js` | 325 | STATUS_MAP, NAV_ITEMS, REP_ACCOUNTS, equipment, move-type helpers |
| `src/helpers/utils.js` | 367 | normalizeStatus, mapShipment, filters, date helpers, useIsMobile |
| `src/components/AskAIOverlay.jsx` | 294 | Ctrl+K AI assistant overlay |
| `src/components/CommandPalette.jsx` | 93 | Ctrl+F shipment search |
| `src/components/ClockDisplay.jsx` | 18 | Live clock + sync status |
| `src/components/DocIndicators.jsx` | 14 | Document type icons |
| `src/components/TerminalBadge.jsx` | 25 | Terminal status badge |
| `src/components/TrackingBadge.jsx` | 59 | FTL tracking badge |
| `src/components/MyActions.jsx` | ~350 | Merged Today's Actions + Live Alerts, rep-scoped, accordion groups |
| `src/views/OverviewView.jsx` | ~400 | Homepage: KPIs, Rep Overview, Accounts (dark theme, gradient accents) |
| `src/views/RepDashboardView.jsx` | 1,027 | Rep dashboard: Dray/FTL toggle, inline editing |
| `src/views/DispatchView.jsx` | 673 | Dispatch table: filters, search, sorting |
| `src/views/InboxView.jsx` | 796 | Inbox Command Center (has LOCAL inbox constants) |
| `src/views/LoadSlideOver.jsx` | 1,171 | Right panel: tracking, docs, driver, emails |
| `src/views/AnalyticsView.jsx` | 254 | Bot status, sync log (includes DataSourceToggle) |
| `src/views/BillingView.jsx` | 251 | Billing queue + sub-tab to UnbilledView |
| `src/views/UnbilledView.jsx` | 360 | Unbilled: Excel upload, aged table |
| `src/views/RateIQView.jsx` | 713 | Rate IQ + HistoryTabContent |
| `src/views/BOLGeneratorView.jsx` | 500 | BOL generator |
| `src/views/HistoryView.jsx` | 177 | Archived/completed loads |
| `src/views/MacropointModal.jsx` | 270 | Macropoint map, progress |
| `src/views/AddForm.jsx` | 334 | New load form |
| `src/views/UserManagementView.jsx` | 152 | Admin user management |

## Alert System Architecture
- **Snapshot alerts** (useMemo): `delivered_needs_billing`, `tracking_behind`, `pod_received`, `needs_driver` — recomputed each render from shipment data
- **Event alerts** (useState): `status_change`, `doc_indexed` — pushed by fetchData change detection and handleStatusUpdate
- **Dismissed alerts**: localStorage key `csl_dismissed_alerts`, pruned to 500 max
- **Snapshot IDs**: deterministic `${type}-${efj}` so dismiss persists across refreshes
- **Event IDs**: `${type}-${s.id}-${status}-${Date.now()}` for uniqueness

## Status Flow
1. Normal statuses: unassigned → assigned → picking_up → in_transit → on_site → delivered
2. After delivered: auto-transition to `ready_to_close` (1.5s delay)
3. Billing statuses: ready_to_close → missing_invoice / billed_closed / ppwk_needed / waiting_confirm / cx_approval / cx_approved
4. `billed_closed` → load removed from active view (2s delay), backend bot archives to Completed sheet tab

## Server-Side Architecture
- **Dashboard app**: `/root/csl-bot/csl-doc-tracker/app.py` (FastAPI, port 8080)
- **Static files**: `/root/csl-bot/csl-doc-tracker/static/dist/` (JS/CSS in `assets/` subfolder)
- **DB**: PostgreSQL — `unbilled_orders`, `load_documents`, `email_threads`, `unmatched_inbox_emails`, `quotes`, `carriers`, `rate_quotes`, `driver_contacts`, `customer_reply_alerts`, `load_notes`
- **Services**: csl-dashboard (8080), csl-import, csl-ftl, csl-export, csl-boviet, csl-tolead, csl-inbox, csl-webhook (5003), csl-upload (5001), bol-webapp (5002)

## Key API Endpoints Added (Mar 5, 2026)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/account-health` | Account health metrics: loads, revenue, friction, health score per account (2-min poll) |
| POST | `/api/load/add` | Add new load → routes to Master/Tolead/Boviet sheet |
| GET | `/api/rate-iq/search-lane` | Fuzzy lane search for rate intelligence |

## AddForm Details
- EFJ PRO # field at top (monospace, uppercase, required)
- EFJ + Container # in 2-column row
- Submits to `POST /api/load/add` (real API, not local state)
- `submitting` + `error` states for UX feedback
- Validation: EFJ required, carrier/origin/destination required

## Dispatch Table
- **Billing column removed** (Mar 5 evening) — billing workflow managed via status dropdown only
- Auto-archive: `billed_closed` triggers backend copy to "Completed {rep}" tab + delete from active
- Columns: Account, Status, EFJ#, Container/Load#, MP Status (conditional on FTL), Pickup, Origin, Destination, Delivery, Truck, Trailer#, Driver Phone, Carrier Email, Rate, Notes
- All columns from Pickup onward are inline-editable (click cell → input)
- **Column header filter dropdowns**: Account, Status, MP Status, Pickup, Origin, Destination, Delivery columns have Excel-style filter dropdowns (`position: absolute`). Date columns use presets (Today, Tomorrow, This Week, Past Due). Active filters show green icon and stack with the filter bar

## RepDashboardView — Dray/FTL Toggle
- **`repViewMode`** state: "dray" (default) | "ftl"
- **Back button**: `←` arrow navigates to OverviewView (was "← Command Center")
- **Dray View**: Filters `displayShips` to `moveType !== "FTL"`, shows account cards + compact table with inline date editing
- **FTL View**: Filters to `moveType === "FTL"`, renders full dispatch-style table via `renderFTLTable()` with all inline-editable columns (status, dates, truck, trailer, phone, email, rate, notes)
- **Props**: Receives `handleFieldUpdate`, `handleMetadataUpdate`, `handleDriverFieldUpdate` from parent
- **`TRUCK_TYPES`**: Module-level constant `["", "53' Solo", "53' Team", "Flat Bed", "26' Box"]`
- Applies to all reps: master (Eli, Radka, John F, Janice), Boviet, Tolead
- **Column header filter dropdowns**: Ops/Master tables filter Account, Carrier, PU, DEL, Status; FTL table filters Account, Status, MP Status, Pickup, Origin, Destination, Delivery. Uses `position: fixed` dropdowns to escape `overflow:hidden` clipping. Date columns use presets (Today, Tomorrow, This Week, Past Due)

## driver_contacts Table Schema
`efj` (PK), `driver_name`, `driver_phone`, `driver_email`, `notes`, `created_at`, `updated_at`
- Note: Does NOT have `trailer`, `carrier_email`, or `macropoint_url` columns
- Trailer/MP URL stored in `notes` field as "Trailer: X | MP: Y"

## sheet_cache Internals
- Cache TTL attribute: `sheet_cache._last` (NOT `last_refresh`)
- Set `sheet_cache._last = 0` to force refresh on next API call
