# MacroPoint Webhook Data Flow Details

## Protocol
MacroPoint sends **GET requests** with query parameters (native protocol), not POST JSON.
- Location pings: `DataSource=Ping`, `Latitude`, `Longitude`, `City`, `State`
- Schedule alerts: `ScheduleAlertText`, `ScheduleAlertCode` (1=ahead, 3=can't make it, 4=behind)
- Trip events: `Event` field (X1=arrived, X2=departed, X6=delivered, AF=tracking started, AG=unresponsive)
- Load identifier: `ID` param (e.g. `TT-P-0310-EV-1`, `LAX1260308015-1`, `TRHU8234452`)

## Cache Lookup Chain
`ID` from webhook -> search cache by `efj`, `load_num`, `mp_load_id`, or key -> match found -> update entry
Example: `TT-P-0310-EV-1` matches cache key `107423` where `load_num=TT-P-0310-EV-1`

## patch_webhook_gaps.py (2026-03-10) — 7 Patch Sites

### Gap A: behindSchedule missed schedule_alert text
- Location: `api_tracking_summary()` (~line 3071)
- Problem: Only checked `stop_times` ETAs for "BEHIND", never read `schedule_alert` field
- Fix: Added check for `schedule_alert` text containing "BEHIND" or "PAST APPOINTMENT"
- Verified: EFJ107354 was `false`, now correctly `true` (141.5 hrs behind)

### Gap B: cant_make_it never set from ScheduleAlertCode=3
- Location: Schedule alert storage block in GET handler (~line 8926)
- Problem: Stored `schedule_alert_code` but never set `cant_make_it` flag
- Fix: Set `cant_make_it=True` when code=3, clear when code=1/2 (driver recovered)

### Gap C: Suffixed load refs don't match cache (4 sites)
- Problem: `LAX1260308015-1` doesn't match `load_num=LAX1260308015`
- Fix: Added `rsplit("-", 1)[0]` fallback in all 4 lookup locations:
  1. Ping handler cache lookup
  2. Schedule alert proximity detector (`_sc_cache`)
  3. Schedule alert storage (`_sa_cache`)
  4. `_update_tracking_cache_webhook()` (before PG fallback)

### Gap D: Empty status on active loads
- Location: Ping handler, after `last_location` update
- Problem: Loads receiving pings had `status=""`, showed blank on dashboard
- Fix: Auto-set `status="Tracking Started"` when ping arrives for empty-status load

## Log Files
- Raw POST payloads: `/root/csl-bot/webhook_payloads.log` (mostly test data)
- Structured events: `/root/csl-bot/webhook_events.log` (active, all GET events)
- App logs: `journalctl -u csl-dashboard -f`

## Key Code Locations in app.py
- `_read_tracking_cache()`: line ~187
- `_classify_mp_display_status()`: line ~370
- `api_tracking_summary()`: line ~3061
- `_persist_tracking_event()`: line ~8141
- `_webhook_pg_write()`: line ~8335
- `_update_tracking_cache_webhook()`: line ~8442
- GET handler `macropoint_webhook_get()`: line ~8642
