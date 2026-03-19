---
name: Oxylabs Proxy Status
description: Oxylabs residential proxy DNS failure on 2026-03-19, transient — quota healthy (5.09/13 GB, 39%)
type: project
---

Oxylabs proxy hit DNS resolution failure on 2026-03-19 (bot alert flagged it). Investigated and found:

- **Quota**: 5.09 / 13 GB used (39%) — not a quota issue
- **Account**: Active residential proxy subscription
- **Root cause**: Transient DNS resolution failure on VPS (`Failed to resolve 'http'` in error)
- **Resolution**: Self-resolved — proxy test passed same day, bot dry-run confirmed working

**Why:** The bot alert system correctly flagged this but it was not an Oxylabs-side issue. VPS DNS resolver (`systemd-resolved` at 127.0.0.53) had a brief blip.

**How to apply:** If proxy fails again, first check VPS DNS (`nslookup pr.oxylabs.io`), then Oxylabs dashboard (dashboard.oxylabs.io) for quota/account status. Browser scrapers skip gracefully when proxy is down — API routes unaffected.
