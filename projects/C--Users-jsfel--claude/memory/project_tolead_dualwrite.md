---
name: Tolead dual-write policy
description: FTL monitor dual-writes to Master Sheet only for Tolead LAX — ORD/JFK/DFW skip dual-write (separate sheets)
type: project
---

Tolead dual-write to Master Google Sheet is LAX-only. ORD, JFK, and DFW each have their own separate sheets and do NOT dual-write.

**Why:** Tolead ORD/JFK/DFW are tracked in their own Google Sheets (not tabs in Master). Writing to Master would create phantom rows. LAX is the exception — it does dual-write.

**How to apply:** In `ftl_monitor.py`, the dual-write guard checks `hub` field from PG:
- `_skip_dualwrite = (tab_name.lower() == "tolead" and (hub).upper() != "LAX")`
- Applied at both the update path (line ~497) and archive path (line ~329)
- `hub` column added to the FTL SELECT query
- Boviet dual-writes normally (has its own sheet but also writes to Master)

Changed 2026-03-18.
