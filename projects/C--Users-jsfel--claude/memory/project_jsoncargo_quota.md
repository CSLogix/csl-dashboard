---
name: JsonCargo API quota optimization
description: JsonCargo Navigator plan (2500 calls/mo) was being exhausted — optimized caching and added business hours gate
type: project
---

JsonCargo API quota was hitting monthly limit (~3900 calls vs 2500 allowed). Rate limit error: "API Key exceeds rate limit (type=MONTHLY)".

**Root cause:** Export monitor runs 24/7 every 60 min, making ~1830 API calls in 18 days. BOL lookups (1330) were the biggest offender — retrying every cycle even for "not found" results.

**Optimizations deployed 2026-03-18:**
- Cache TTL: 6h → 12h (shared jsoncargo_cache.json used by both csl_bot.py and export_monitor.py)
- BOL lookup cache: 7-day TTL (container# never changes for a BOL)
- BOL "not found": cached for 4h (was retried every hour)
- Business hours gate: export monitor skips API calls outside 6 AM - 10 PM ET
- Projected monthly usage: ~800-1000 (down from ~3900)

**Why:** Navigator plan costs 299 EUR/mo with 2500 calls. Quota resets on billing date (April 16, 2026). Until then, API returns 429 — csl_bot.py falls back to browser scraping, export_monitor BOL/container tracking non-functional.

**How to apply:** If API usage creeps up again, check `journalctl -u csl-export | grep -c "jsoncargo\|JsonCargo"` for call counts. Cache file: `/root/csl-bot/jsoncargo_cache.json`. Backups: `*.pre-quota-20260318`.
