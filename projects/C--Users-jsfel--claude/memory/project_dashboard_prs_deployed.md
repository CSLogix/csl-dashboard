---
name: Dashboard PR deployment status
description: All PRs #1-#21 merged and deployed — PR #20 CarrierRankCard was last to sync locally (2026-03-18)
type: project
---

All CSLogix/csl-dashboard PRs through #21 are merged and deployed to production.

**PR #20** (CarrierRankCard + lane analytics) was merged on GitHub but not pulled locally until 2026-03-18 — now deployed.

**PR #21** (fix delete load 500 error + move delete button to end of row):
- Backend: added `public_tracking_tokens` to FK cleanup in `DELETE /api/v2/load/{efj}` (routes/v2.py line ~533)
- Frontend: moved delete trash icon from first column to last column in dispatch table
- Already deployed server-side directly; frontend via build+scp

**Why:** Radka reported 500 error deleting loads + accidental clicks on delete button too close to slide-over open button.

**How to apply:** All PRs are now in sync — local main, GitHub main, and production server all match.
