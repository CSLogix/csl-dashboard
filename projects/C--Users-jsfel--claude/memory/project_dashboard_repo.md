---
name: Dashboard source repo and deploy workflow
description: CSL Dashboard frontend source location, CI/CD pipeline, and deploy details
type: project
---

Dashboard frontend source is at `C:\Users\jsfel\Downloads\csl-dashboard-preview\dashboard\` (cloned from `CSLogix/csl-dashboard` GitHub repo via SSH).

**Note:** `C:\Users\jsfel\csl-dashboard\` also exists (HTTPS clone) but is stale — stopped at PR #11. The active working copy is `Downloads\csl-dashboard-preview`.

**Frontend deploy: GitHub Actions CI/CD (automated since 2026-03-17)**
- Workflow: `.github/workflows/deploy.yml` — triggers on push/merge to `main`
- Steps: checkout → Node 22 + npm ci → vite build → clean stale assets on VPS → SCP dist/ → restart csl-dashboard
- Secrets: `VPS_HOST`, `VPS_SSH_KEY`, `VPS_SSH_PORT` configured in repo settings
- Uses `appleboy/scp-action` + `appleboy/ssh-action`
- `strip_components: 2` maps `dashboard/dist/*` → VPS `/root/csl-bot/csl-doc-tracker/static/dist/`
- Manual SCP deploy is no longer needed for frontend — just merge to `main`

**Why:** Manual SCP deploys were error-prone (wrong paths, stale hashed bundles, forgetting restart). CI/CD ensures VPS always matches GitHub.

**How to apply:** When deploying dashboard frontend changes, just merge the PR to `main`. No manual build/SCP/restart needed.

**Backend deploy (still manual):** Backend route files live in `csl-doc-tracker/routes/` in the same repo. When PRs touch Python files, SCP those:
```
scp csl-doc-tracker/routes/<file>.py root@187.77.217.61:/root/csl-bot/csl-doc-tracker/routes/
scp csl_sheet_sync.py root@187.77.217.61:/root/csl-bot/csl-doc-tracker/csl_sheet_sync.py
```

**Sync verification:** Compare local vs server with `md5sum` on all changed `.py` files to confirm deploy.

**Current state (2026-03-17):** All PRs through #15 merged on GitHub and fully deployed to server. CI/CD workflow live and tested green.
