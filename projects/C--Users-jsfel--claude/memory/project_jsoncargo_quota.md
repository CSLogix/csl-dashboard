---
name: JsonCargo API quota and flat response migration
description: JsonCargo Navigator plan (2500 calls/mo) optimized + API response parsing updated from events[] to flat fields
type: project
---

JsonCargo API quota was hitting monthly limit (~3900 calls vs 2500 allowed). Rate limit error: "API Key exceeds rate limit (type=MONTHLY)".

**Root cause:** Export monitor was running 24/7 every 60 min, making ~1830 API calls in 18 days. BOL lookups (1330) were the biggest offender — retrying every cycle even for "not found" results.

**Optimizations deployed 2026-03-18:**
- Cache TTL: 6h → 12h (Postgres-backed jsoncargo_cache table, shared by both scripts)
- BOL lookup cache: 7-day TTL (container# never changes for a BOL)
- BOL "not found": cached for 4h with `__notfound__` sentinel (was retried every hour)
- BOL validation: filters out non-container strings (e.g. "Containers not yet assigned")
- Both import and export scanners only scrape 2x/day (7 AM + 1:30 PM ET, weekdays)
- Projected monthly usage: ~1,200 calls (well under 2,500 limit)

**API response format change (also 2026-03-18):**
- JsonCargo API no longer returns `data.events[]` or `data.moves[]` arrays
- All responses are flat: `container_status`, `eta_final_destination`, `timestamp_of_last_location`, etc.
- Updated both `csl_bot.py` and `export_monitor.py` to parse flat fields as primary path
- Status keywords (discharged, vessel departure, gate out, etc.) matched against `container_status` string
- Dates extracted from `eta_final_destination`, `eta_next_destination`, `timestamp_of_last_location`

**Why:** Navigator plan costs 299 EUR/mo with 2500 calls. At 2x/day weekdays-only with caching, usage stays at ~1,200/mo.

**How to apply:** If API usage creeps up, check `journalctl -u csl-export | grep -c "jsoncargo\|JsonCargo"` for call counts. Cache is Postgres-backed (`jsoncargo_cache` table). Backups: `*.pre-quota-20260318`, `*.pre-flat-20260318`.
