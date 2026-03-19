---
name: Dashboard PR deployment status
description: All PRs deployed + Rate IQ RPM fix + CSLogix_Bot PRs #8-#12 merged (2026-03-19)
type: project
---

All CSLogix/csl-dashboard commits through 155bbcd deployed. CSLogix_Bot master at d6ac041. (2026-03-19)

**Rate IQ RPM fix (2026-03-19):**
- Fixed `NULL AS miles` → `lr.miles` in rate_iq.py query (root cause: RPM never showed)
- Forced IPv4 in quotes.py Distance Matrix calls (API key restricted to server's IPv4)
- Backfilled 626 rows with distance data (236 lane_rates + 390 rate_quotes)
- Added miles to lane-rates PUT allowed fields (directory.py)
- Frontend: auto-fetch miles for lanes missing data + LoadMatch carrier rows in QuoteBuilder
- Ghost files committed, CREATE TABLE for tracking_events/public_tracking_tokens added

**CSLogix_Bot PRs merged (2026-03-19):**
- PR #8: Rate intelligence APIs (trends, similar loads, alerts, batch extraction)
- PR #9: Rate IQ tests
- PR #10: Verify sheet data sync
- PR #11: Rate IQ UI enhancements (market rates, rate intake panel, RPM)
- PR #12: PG cache migration + webhook refactor + tests
- Verify-sheet-data-sync branch: atomic email dedup, AG transient flag, jsoncargo tables

**How to apply:** Both repos pushed. Frontend built and deployed. csl-dashboard restarted. Google Maps API key needs IPv6 added to GCP restrictions for future server-side batch calls (workaround: force IPv4 in Python).
