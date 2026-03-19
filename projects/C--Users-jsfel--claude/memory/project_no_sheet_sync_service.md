---
name: No separate csl-sync service
description: csl_sheet_sync.py runs inside csl-dashboard service, not as a standalone systemd unit
type: project
---

There is no `csl-sync.service`. The sheet sync (`csl_sheet_sync.py`) runs as part of the `csl-dashboard` service. Restarting `csl-dashboard` picks up changes to both `app.py` routes and `csl_sheet_sync.py`.

**How to apply:** After deploying csl_sheet_sync.py changes, restart `csl-dashboard` (not a nonexistent sync service).
