---
name: Git workflow — commit everything, no SCP patches
description: All server and dashboard changes must be committed to git before walking away. No more SCP-only patches. Deploy helpers on server (csl-deploy, csl-commit).
type: feedback
---

Every code change must be committed to git — never leave patches as uncommitted working tree changes.
**Why:** Months of SCP patches on the server were never committed. Any git pull/checkout wiped them, causing the same patches to be re-applied repeatedly.
**How to apply:**
- Dashboard (frontend): Edit locally → build → SCP dist → commit + push to GitHub
- Bot (server Python): Edit → test → immediately `csl-commit` on server (or commit locally + `csl-deploy` on server)
- Server has `csl-deploy` (git pull + restart) and `csl-commit` (stage + commit + push) bash functions in ~/.bashrc
- `.gitignore` on server excludes: `rate-msg-dump/`, `backfill_rate_history.py`, `extract_msg_attachments.py`, `csl-doc-tracker/fix_tolead_dfw.py`
- Never leave a session with uncommitted changes on the server
