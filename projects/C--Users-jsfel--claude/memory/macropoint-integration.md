# Macropoint Webhook Integration — Mar 6, 2026

## Architecture
Macropoint → Nginx (`allow all`) → FastAPI app.py → cache update + BackgroundTask → PG write + real-time email alert

### Webhook Flow (Updated Mar 6 — Real-Time Alerts)
1. Macropoint sends GET request with query params to `https://cslogixdispatch.com/macropoint-webhook`
2. Nginx `allow all` bypasses Cloudflare-only restriction for this path
3. `macropoint_webhook_get()` handler processes by `DataSource` / `Event` field
4. Location pings: stored in cache `last_location` (lat/lon/city/state/street/timestamp)
5. Status events: mapped via `_MP_EVENT_MAP`, update cache status
6. **NEW**: `_update_tracking_cache_webhook()` returns `(bool, match_info_dict)` tuple
7. **NEW**: On cache hit, schedules `_webhook_send_alert_background()` via FastAPI `BackgroundTasks`
8. Background task: resolves account from PG → writes PG status via `pg_update_shipment()` → sends email via `send_webhook_alert()`
9. Handler returns 200 immediately — email sends async in ~1-3s
10. FTL monitor cron still runs as safety net (shared dedup via `ftl_sent_alerts.json` prevents duplicates)

### Key Design Change (Mar 6)
Previously webhook did NOT write PG (to preserve FTL monitor's diff detection). Now webhook writes PG AND sends email directly via `csl_ftl_alerts.py` shared module. FTL monitor remains as backup — shared `ftl_sent_alerts.json` dedup file ensures no duplicate emails.

## Macropoint Protocol
- Protocol name: "MacroPoint" (native protocol)
- Method: **GET** with URL query params (NOT POST with JSON)
- Key params: `ID` (load ref), `DataSource` (Ping/StatusChange), `Event` (X1/X2/X3/X6), `Latitude`, `Longitude`, `City`, `State`

### Event Codes
| Code | Meaning | Mapped Status |
|------|---------|---------------|
| AF | Tracking Started | Tracking Started |
| X1 | Arrived at Stop | Context-dependent (origin vs dest) |
| X2 | Departed Stop | Context-dependent |
| X3 | Position Update | (location ping only) |
| X4 | In Transit | Departed Pickup - En Route |
| X6 | Delivered | Delivered |
| AG | Unresponsive | Driver Phone Unresponsive |

### Macropoint Portal Callbacks (5 types configured)
1. Location Updates
2. Order Status Changes
3. Trip Event Updates
4. Trip Sheet Change Notifications
5. Schedule Alerts

## Container→EFJ Matching
Macropoint sends Tolead order IDs (e.g., `ORD1260305010`) but cache keys are EFJ-based. Fallback lookup:
1. Check cache keys directly
2. Check cache `efj`, `load_num`, `mp_load_id` fields
3. PG `container` field: `SELECT efj FROM shipments WHERE container = %s OR container LIKE %s`

## Nginx Config
```nginx
location /macropoint-webhook {
    allow all;
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## Auth
- Username: `CSLogix_Dispatch` (in both `/root/csl-bot/.env` and `csl-doc-tracker/.env`)
- Basic Auth on webhook endpoints

## API Changes
- `/api/macropoint/{efj}`: Falls back to PG `shipments` table when `sheet_cache` misses. Returns `lastLocation` GPS data. No 404 when macropoint_url missing
- `/api/load/{efj}/driver`: Falls back to `shipments` table (driver, driver_phone, container_url) when `driver_contacts` empty

## Frontend Changes
- Removed "Open Macropoint →" link from slide-over (Tracking button in quick actions suffices)
- Added compact progress bar below "Synced" in slide-over header
  - `Origin ——●—— Destination` with colored fill based on step completion
  - GPS city label (e.g., "Irvine, CA") below the progress dot
  - Status + ETA row above the bar

## Upload Server
- `upload_server.py` now writes tracking URLs to PG via `pg_update_shipment(efj, container_url=url)` + updates `ftl_tracking_cache.json`
- No longer writes to Google Sheets

## Files Modified (server)
- `/etc/nginx/sites-enabled/csl-dispatch` — webhook location blocks
- `/root/csl-bot/upload_server.py` — PG write instead of sheets
- `/root/csl-bot/csl-doc-tracker/app.py` — GET webhook handler, driver fallback, macropoint API PG fallback
- `/root/csl-bot/.env` + `csl-doc-tracker/.env` — webhook auth username

## Patches Applied
| Patch | Description |
|-------|-------------|
| `patch_macropoint_pg.py` | Nginx + upload server PG write + cache cleanup |
| `patch_driver_fallback.py` | Driver API PG fallback |
| `fix_all_cursor_indent.py` | Fix 19 damaged `with db.get_cursor()` blocks |
| `fix_driver_dictcursor.py` | Fix RealDictCursor dict access |
| `patch_webhook_get.py` | GET handler for Macropoint native protocol |
| `patch_webhook_event_codes.py` | Event code mapping (X1/X2/X6) |
| `patch_webhook_container_match.py` | Container→EFJ PG lookup |
| `patch_macropoint_api_pg.py` | API PG fallback + lastLocation |
| `patch_macropoint_sync.py` | Fix 5 bugs: structured eventType for stop_times, Tracking Completed→Delivered, MP URL from MPOrderID, container_url PG write, v2 mp_status enrichment |
| `backfill_mp_urls.py` | Backfill macropoint_url from webhook_events.log MPOrderIDs (45 cache + 22 PG entries) |

## MP URL Backfill
- PG migration didn't extract hyperlink URLs from Google Sheet column C
- 20 Boviet FTL loads had `visibility.macropoint.com` URLs in sheet but `container_url` was empty in PG
- Backfilled via `check_sheet_mp_urls.py` — all 20 written to PG
- `csl_sheet_sync.py` `ON CONFLICT DO UPDATE` does NOT include `container_url` — backfilled URLs are safe
- Master Tracker loads (DSV, EShipping, etc.) get MP URLs via upload_server (writes to PG now)
- Tolead loads: NOW have MP URLs — `_get_sheet_hyperlinks()` added to both `csl_sheet_sync.py` and `app.py` (Mar 10, 2026)

## Boviet vs FTL Monitor
- **Boviet monitor** (`csl-boviet` systemd): Reads Boviet Google Sheet, scrapes MP visibility URLs via Playwright, sends emails on status changes. Runs every 20 min. This is the old scraping method — still works
- **FTL monitor** (`ftl_monitor.py` cron): Reads PG, compares with `ftl_tracking_cache.json` (webhook-updated), writes PG on diff, sends emails. Processes ALL FTL loads including Boviet
- Both monitors process Boviet FTL loads — Boviet monitor via sheet+scraping, FTL monitor via PG+cache
- Email alerts for Boviet come from the Boviet monitor (sheet-driven), not from webhooks

## Tracking Events Persistence — Mar 9, 2026

### PG Table: `tracking_events`
- Columns: `id`, `efj`, `event_code`, `stop_type` (Pickup/DropOff), `city`, `state`, `lat`, `lon`, `event_timestamp`, `raw_data`, `created_at`
- Stores all webhook events permanently (X1/X2/X3/X6/D1/AF + inferred GPS events)
- `_persist_tracking_event()` — fire-and-forget INSERT (used by both webhook handler and GPS inference)

### Timeline from PG: `_build_timeline_from_pg(efj)`
- Reads `tracking_events` WHERE efj, ordered by event_timestamp
- `_is_pickup_stop()` matches stop_name/stop_type/city against shipment origin/destination from PG
- Returns chronological timeline array with `type`, `label`, `location`, `timestamp`, `isPickup` fields

### GPS Proximity Inference — `fix_infer_stop_arrival.py`
**Problem**: Macropoint webhooks only push X1/X2 for delivery stops. Pickup arrival/departure detected by Macropoint GPS geofencing internally but never sent as webhook callbacks.

**Solution**: Enhanced schedule alert handler to infer stop arrival/departure from GPS proximity:
- `ARRIVAL_THRESHOLD = 0.5` miles → record arrival (first time only)
- `DEPARTURE_THRESHOLD = 2.0` miles after arrival → record departure (first time only)
- Reads cache to check existing stop_times, only records first arrival and first departure per stop
- Persists to both `ftl_tracking_cache.json` stop_times AND PG `tracking_events` via `_persist_tracking_event()`
- Uses `now` (handler timestamp in ET) instead of `EtaToStop` (which is predicted arrival)
- `_is_pickup_stop()` determines stop type from origin/destination matching

### Schedule Alert Webhook Fields
- `StopType`: "Pickup" or "DropOff"
- `StopName`: Stop description/address
- `DistanceToStopInMiles`: GPS distance to stop (used for proximity inference)
- `EtaToStop`: Predicted arrival time (NOT used — we use actual timestamp)
- Sent every ~15 min per active load

### Backfill Script — `backfill_pickup_events.py`
- One-time script to retroactively process `webhook_events.log`
- Groups events by load_ref + stop_type, detects arrival (<0.5mi) and departure (>2mi)
- Maps load_ref → efj via cache + PG shipments table
- `_fix_ts()` converts `"2026-03-06 13:10:20 ET"` → `"2026-03-06 13:10:20-05:00"` for PG TIMESTAMPTZ
- Inserted 60 inferred events across all loads

### Frontend: Schedule & Tracking Compact Table
- **Both slide-overs** (Dispatch LoadSlideOver + RepDashboard slide-over) have identical compact table
- 4-column grid: `[Stop] [Sched] [Arrived] [Departed]`
- PU row (amber dot) + DEL row (green dot) with truncated location names (18 char max)
- Delivered confirmation row at bottom with teal accent
- `parsedStops` useMemo extracts PU/DEL arrived/departed/delivered from `trackingData.timeline`
- **Military time format** (24h): `3/6 13:10` not `3/6 1:10 pm`
- **M/D format** (no year): regex strips year from scheduled dates like `3/6/2026 9:00` → `3/6 9:00`
- `fmtTs()` handles ISO timestamps, scheduled dates, and YYYY-MM-DD formats

### Known Bug Fixed — "ET" Timestamp + Cache Fallback (Mar 9)
**Problem**: GPS inference correctly detected arrival/departure and saved to `ftl_tracking_cache.json`, but `_persist_tracking_event()` passed timestamps like `"2026-03-09 10:33:18 ET"` — PG rejects "ET" as invalid timezone. Silently swallowed by `log.debug()`. Meanwhile `/api/macropoint/{efj}` only fell back to cache when PG timeline was completely empty — if ANY event (e.g. AF/Tracking Started) persisted, cache stop_times were skipped.

**Frontend**: `fmtTs()` used `v.includes("T")` to detect ISO timestamps, but `"ET"` contains "T" — triggered ISO parse path → `new Date("...ET")` → NaN.

**Fixes**:
1. `_persist_tracking_event()`: Converts "ET" suffix → proper offset (`-04:00`/`-05:00`) via `ZoneInfo("America/New_York")`
2. `/api/macropoint/{efj}`: Merges cache `stop_times` into PG timeline when arrival/departure events missing (not just when empty)
3. Logging bumped from `log.debug()` to `log.warning()`
4. Frontend `fmtTs()`: `/\dT\d/.test(v)` instead of `v.includes("T")` + `isNaN(d)` guard

### Patches
| Patch | Description |
|-------|-------------|
| `fix_timeline_stops.py` | tracking_events table + `_build_timeline_from_pg()` + `_persist_tracking_event()` |
| `fix_infer_stop_arrival.py` | GPS proximity inference in schedule alert handler |
| `backfill_pickup_events.py` | One-time retroactive event backfill from webhook_events.log |
| `patch_tracking_events_fix.py` | Fix ET timestamp persist + cache↔PG merge + log.warning |

## MP Status Classifier — Mar 9, 2026

### Problem
Raw `mp_status` from Macropoint (e.g. "Tracking Started", "INTRANSIT") was not useful to dispatchers. Schedule alert intelligence (`ScheduleAlertText` with "X Hours BEHIND/AHEAD") was received by webhook but NOT stored in tracking cache.

### Server: `_classify_mp_display_status(cache_entry, shipment=None)`
Returns `(display_status, detail)` tuple. Classification hierarchy:
1. No status → "No MP"
2. "unassigned" → "Unassigned"
3. "delivered"/"completed" → "Delivered"
4. "unresponsive" → "No Signal" (detail: "Driver phone unresponsive")
5. Parse `schedule_alert` for hours offset (regex: `(\d+\.?\d*)\s*Hours?\s*(BEHIND|AHEAD)`)
6. GPS staleness check: `last_location.timestamp` age > 2h → stale
7. At stops: "arrived"+"pickup" → "At Pickup", "arrived"+"delivery" → "At Delivery"
8. In transit: behind → "Behind Schedule", ahead → "On Time", GPS stale → "Awaiting Update", else "In Transit"
9. "tracking started": behind → "Behind Schedule", ahead → "On Time", no GPS → "Assigned", stale → "Awaiting Update"
10. Fallback: behind → "Behind Schedule", ahead → "On Time", else raw status

### Webhook Enhancement
Schedule alert handler now stores in `ftl_tracking_cache.json`:
- `schedule_alert` — raw text (e.g. "6.5 Hours BEHIND schedule")
- `schedule_alert_code` — 1=ahead, 4=behind
- `distance_to_stop` — miles to next stop
- `eta_to_stop` — predicted arrival time
- `schedule_stop_type` — "Pickup" or "DropOff"

### API Enrichment
- `/api/v2/shipments`: `mp_display_status`, `mp_display_detail` fields on each shipment
- `/api/macropoint/{efj}`: `mpDisplayStatus`, `mpDisplayDetail`, `scheduleAlert`, `distanceToStop`
- `/api/shipments/tracking-summary`: `mpDisplayStatus`, `mpDisplayDetail` per entry

### Frontend
- `TrackingBadge` component rewritten with color-coded badges and hover tooltips
- Badge colors: On Time→green, Behind Schedule→red, In Transit→blue, At Pickup→amber, At Delivery→purple, Awaiting Update→orange, No Signal→red, Assigned→gray, Delivered→green
- Column filter, sort, search, CSV export all use `mpDisplayStatus`
- Schedule alert banners in MacropointModal and LoadSlideOver
- `mapShipment()` extracts `mpDisplayStatus` and `mpDisplayDetail` from API response

### Patch
| Patch | Description |
|-------|-------------|
| `patch_mp_classifier.py` | Classifier function + webhook storage + 3 API enrichments |

## Analytics Dashboard
- `csl-ftl` removed from `BOT_SERVICES` (was showing "DOWN" on Analytics page)
- FTL monitor tracked in "Scheduled Jobs" cron cards instead (via `cron_log_parser.py`)

## Lessons Learned
- Never use global `sed` on app.py — damaged 19 code blocks. Use targeted Python patch scripts instead
- `db.get_cursor()` returns `RealDictCursor` (dicts) — use column names, not tuple indices
- Macropoint native protocol uses GET, not POST — must handle both methods
- ~~Email alerts depend on cache≠PG diff detection~~ — NOW webhook writes PG + sends email directly via shared module
- PG migration scripts must extract hyperlink URLs from Google Sheet cells, not just display values
- **Webhook eventType must be structured** (`ARRIVED_PICKUP`, not `X1`) — `_update_tracking_cache_webhook` uses string-contains checks (`"ARRIVED" in event_upper`), not code lookups
- **stop_times only populate from trip events** (X1/X2/X6) and GPS proximity inference — not from schedule alerts or pings
- **MPOrderID → visibility URL**: `https://visibility.macropoint.com/shipments?l={MPOrderID}` — auto-populate on every webhook event
- **v2 API enrichment**: PG `shipments` has no `mp_status` column — must enrich from tracking cache at query time via `_find_tracking_entry()`

## Real-Time Alert Module — `/root/csl-bot/csl_ftl_alerts.py`
Shared email + dedup module extracted from `ftl_monitor.py`:
- `ACCOUNT_REPS_PG` dict (24 accounts → rep email)
- `STATUS_TO_DROPDOWN` mapping (webhook status → PG dropdown value)
- Thread-safe dedup: `load_sent_alerts()` / `save_sent_alerts()` with `fcntl.flock()` for concurrent access
- `send_webhook_alert()` — convenience wrapper: loads dedup → checks → sends email → marks sent → saves
- `send_ftl_email()` — HTML email template via SMTP STARTTLS on port 587
- `_send_pod_reminder_ftl()` — POD reminder triggered on Delivered status
- `ftl_monitor.py` imports from this module instead of local copies

### Patches
| Patch | Description |
|-------|-------------|
| `patch_ftl_alerts_module.py` | Creates shared module + refactors ftl_monitor.py imports |
| `patch_webhook_realtime_alerts.py` | Patches app.py webhook handlers with BackgroundTasks |
