---
name: Driver contact sync (PR #11)
description: PR #11 merged — bidirectional driver phone/trailer/carrierEmail sync between webhook cache, PG driver_contacts, Google Sheets, and tracking-summary API
type: project
---

PR #11 (claude/fix-macropoint-webhook-SaPWJ) merged 2026-03-17. Adds:

- **shipments.py**: tracking-summary endpoint enriched with driverPhone, trailer, carrierEmail from PG driver_contacts (bulk load, dual-keyed by raw EFJ and stripped EFJ)
- **webhooks.py**: cache entry creation seeds driver_phone/trailer from driver_contacts; after writing container_url, upserts phone/trailer back to driver_contacts
- **csl_sheet_sync.py**: bulk-fetches driver_contacts per hub (no N+1), writes PG phone/trailer back to Tolead sheets, updates tracking cache atomically, retry with backoff on sheet writes

**Why:** Driver phone and trailer weren't flowing from webhook events to the loadboard dashboard. This closes the loop: webhook → cache → PG → sheet → tracking-summary API.

**How to apply:** When touching driver contact data flow, these three files form the sync chain. The tracking cache file is `/root/csl-bot/ftl_tracking_cache.json`.
