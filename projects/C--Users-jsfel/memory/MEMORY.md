# CSL Bot Memory

## MacroPoint Webhook Architecture
- Standalone `csl-webhook` (port 5003) is **dead/disabled** since March 5 2026
- Webhook is now integrated into `csl-dashboard` FastAPI app (port 8080) via `patch_webhook_migrate.py`
- MacroPoint uses **GET native protocol** (query params), NOT POST JSON — see [webhook-details.md](webhook-details.md)
- Cache file: `/root/csl-bot/ftl_tracking_cache.json` — keyed by numeric EFJ (e.g. `107423`)
- Tracking-summary endpoint: `/api/shipments/tracking-summary` reads cache directly

## Rate IQ — Quote Builder
- Fully deployed: `quote_extractor.py` + `quote_routes.py` on server, registered in `app.py`
- Frontend: `QuoteBuilder.jsx` in `DispatchDashboard.jsx` — drag/drop + clipboard paste + text input
- Endpoints: `POST /api/quotes/extract`, `GET /api/quotes/distance`, CRUD at `/api/quotes/*`
- Model: `claude-sonnet-4-6` (upgraded from Haiku on 2026-03-10)
- `ANTHROPIC_API_KEY` lives in systemd service file (`/etc/systemd/system/csl-dashboard.service`) — NOT just `.env`
- Old CSL-Rate IQ key (`sk-ant-api03-4nb...8gAA`) was revoked — replaced with new key on 2026-03-10
- `quote_extractor.py` has `TERMINAL_HUBS` + `FIRMS_CODES` dicts + `normalize_hub()` for universal port/rail hub matching
- LA/LB cluster: any of LAX, LBCT, APM Terminals, Port of LA, TraPac, SSA Marine → "LA/LB Ports"
- LoadMatch screenshots: BASE + FSC% = TOTAL; market_floor/average/ceiling/data_points extracted as separate fields
- Backup at `/root/csl-bot/csl-doc-tracker/quote_extractor.py.bak`
- Rate Intel accordion shows "No rate history" until quotes are saved — self-populates from `lane_rates` table over time

## Phase 3 — Port Terminal Scraping

### Ports America API (twpapi.pachesapeake.com) — CONFIRMED WORKING
- **Endpoint**: `GET https://twpapi.pachesapeake.com/api/track/GetContainers`
- **Params**: `siteId=NAP_NO`, `key=CNUM1,CNUM2,...` (comma-separated, up to 10), `pickupDate=MM/DD/YYYY`
- **Auth**: None required — fully public
- **No Playwright needed** — pure `requests.get()`
- Discovered via playwright-stealth intercept of `https://www.portsamerica.com/our-locations/new-orleans-la?terminal=napoleon-container-terminal`
  - Cargo type selector uses Mantine combobox button (`id=mantine-xa7fd895r`, value="Select Cargo Type")
  - Must select cargo type BEFORE the "Enter Numbers" input enables
  - Cargo type options: "Container Availability by Container", "Container Availability by BoL", "Booking Inquiry", "EDO Inquiry", "EIR RePrint by Container"

### siteId values
- `NAP_NO` — Napoleon Container Terminal, New Orleans ✅ working
- `PNCT_NJ` — PNCT Newark ✅ responds (returns [] if container not there)
- `SGT_BAL` — Seagirt Baltimore ✅ responds
- `WBCT_LA` — timeout on pachesapeake, uses separate backend

### Key API Response Fields
- `Available`: 1=Ready, 2=Not Ready, 0=Not Found
- `Location` / `State`: "Vessel", "On Ship", "In Yard", "Available"
- `CustomReleaseStatus`: "RELEASED" or "HOLD"
- `CarrierReleaseStatus`: "RELEASED" or "HOLD"
- `UsdaStatus`: null or hold string
- `YardReleaseStatus`: null or "HOLD"
- `MiscHoldStatus` / `MiscHoldTypes`: "2H", "TMF", etc.
- `TmfStatus`: null or hold string
- `BeginDeliveryDate`: when container available for pickup → **Col K**
- `LastFreeDate`: LFD (port free days)
- `DemurrageEndDate` / `DemurrageAmount`: demurrage info
- `VesselName` / `VoyageNumber`: vessel info

### Module: `/root/csl-bot/terminal_nola.py`
- `check_nola_containers(container_numbers)` → `{cnum: {ready, location, holds, bot_notes, pickup_date, ...}}`
- `check_pnct_containers()` / `check_seagirt_containers()` — same pattern, different siteId
- Bot Notes format: `"Avail:NO | Loc:Vessel | Carrier:HOLD|Misc:2H | Vessel:OOCL BREMERHAVEN 14W"`
- **Write targets**: Bot Notes → Col N; Pickup Date (when ready) → Col K

### Column Mapping (confirmed by user)
- Availability (Ready for Delivery + Location) → Col K (Pickup Date) and/or Col N prefix
- Holds (Customs, Freight, Other) → Col N (Bot Notes)
- Do NOT write to a new Col R — user confirmed K and N

### terminal_creds.json
- `/root/csl-bot/terminal_creds.json` (600 perms) — 26 terminals with login credentials
- Napoleon NOLA public form requires no login — creds not needed for this terminal

## Security Remediation — IN PROGRESS (paused 2026-03-10)
Steps completed: none yet
Next step: **Step 1** — fix local SSH key permissions
Full plan (in order, all systems stay running):
1. Fix local SSH key perms: `icacls "C:\Users\jsfel\.ssh\id_ed25519" /inheritance:r /grant:r "%USERNAME%:R"`
2. Move GCP JSON keys out of `Downloads/` and `OneDrive/Desktop/...` (2 files + JSON Key.txt)
3. Rotate SMTP password for `jfeltzjr@gmail.com` → Gmail App Passwords page → user edits `/root/csl-bot/csl-doc-tracker/.env` directly → restart csl-dashboard
4. Rotate Postgres `csl_admin` password → user edits `.env` → restart csl-dashboard
5. Rotate Anthropic API key → update systemd service file + `.env` → restart csl-dashboard
6. (Optional) Rewrite server git history to purge committed secrets (BFG)
**Rule: never paste secrets into chat — always edit .env directly via SSH**

## Phase 3 — Frontend Terminal Badge (2026-03-10)
- `parseTerminalNotes(notes)` — pure function, detects `Avail:` prefix, extracts avail/loc/carrier/cbp/usda/misc holds
- `TerminalBadge` component — 3 states: green `READY` badge, red hold-code badges (2H/TMF/FRT/CBP/USDA), grey loc fallback
- Row tinting: green `rgba(34,197,94,0.06)` when READY, red `rgba(239,68,68,0.05)` when holds present
- Patched in both **RepDashboard ops table** and **DispatchView** — Notes cell + `<tr>` background
- Plain notes (no `Avail:` prefix) fall through to existing inline-edit text — no regression
- Bot notes column is **Col O** in Master Tracker (CLAUDE.md says O=Bot Notes, N=Driver/Truck)
- State test: set Col O to `Avail:YES | Loc:In Yard | Carrier:RELEASED | Misc:None` → row goes green after cache expires

## Patches Applied (recent)
- `patch_webhook_gaps.py` (2026-03-10) — Fixed 4 data flow gaps between MacroPoint webhook and React dashboard. See [webhook-details.md](webhook-details.md)
- `quote_extractor.py` rewrite (2026-03-10) — Sonnet upgrade, hub normalization, LoadMatch prompt
- `terminal_nola.py` deployed (2026-03-10) — PA terminal API scraper, no auth, pure requests
- `TerminalBadge` + `parseTerminalNotes` (2026-03-10) — Frontend parser for Col O bot notes, visual hold badges + row tinting

## Server Auth Notes
- Dev key in systemd: `CSL_DEV_KEY=114d9df820d6c9c8aff380208a555b5e5d163e76a213518f`
- Dev IPs restricted: `CSL_DEV_IPS=108.191.130.19,108.191.130.159`
- Localhost curl to API requires session cookie or dev key + IP match — dev key won't work from server itself without IP allowlist update
- `.env` file is at `/root/csl-bot/csl-doc-tracker/.env` (not `/root/csl-bot/.env`)

## React Dashboard Startup
- 10+ API calls on mount via `Promise.allSettled` (lines 849-856 in DispatchDashboard.jsx)
- 90-second poll interval (`setInterval(fetchData, 90000)`)
- 10-second fallback timeout forces `loaded=true` even if APIs haven't responded
- Source dir: `C:\Users\jsfel\Downloads\csl-dashboard-preview\dashboard\` (note extra `dashboard\` subdir)
