# React Dispatch Dashboard — Design & Implementation Notes

## File Location
- Source: `C:\Users\jsfel\Downloads\dispatch-command_2.jsx`
- Preview: `C:\Users\jsfel\Downloads\csl-dashboard-preview\src\DispatchDashboard.jsx`

## Status: WIRED TO REAL API (2026-02-27)
All 5 API endpoints connected via Vite proxy → SSH tunnel → VPS:8080

## API Endpoints (all working)
| Endpoint | Status | Returns |
|----------|--------|---------|
| `GET /api/shipments` | 200 | 232 shipments from 3 Google Sheets |
| `GET /api/stats` | 200 | {active:104, on_schedule:60, eta_changed:28, at_risk:44, completed_today:30} |
| `GET /api/bot-status` | 200 | 7 services with systemd timing |
| `GET /api/alerts` | 200 | 10 urgent LFD-today alerts |
| `GET /api/accounts` | 200 | 18 accounts with active/alert counts |

## Backend Patch Applied
- `patch_react_api.py` → added 5 JSON endpoints + CORS middleware
- `/api/` paths made public (no auth required)
- `_generate_alerts(sheet_cache.shipments)` for alerts
- Deployed and running on VPS

## Vite Dev Setup
- `vite.config.js` proxy: `/api` → `http://127.0.0.1:8080` (SSH tunnel)
- SSH tunnel: `ssh -f -N -L 8080:localhost:8080 root@187.77.217.61`
- Dev server: `npx vite --port 5173 --host` in csl-dashboard-preview dir

## Status Normalization (raw Sheet → internal key)
```
"At Yard"/"At Pickup"/"Discharged" → at_port
"Vessel"/"Vessel Arrived" → on_vessel
"In Transit" → in_transit
"Picking Up"/"Assigned"/"Scheduled" → out_for_delivery
"Delivered" → delivered
"Returned to Port" → empty_return
"Unassigned"/"Hold" → pending
```

## Component Architecture
```
DispatchDashboard (main)
├── State: activeView, shipments, accounts, botStatus, alerts, apiStats, accountOverview
├── fetchData() → 5 parallel API calls, refreshes every 60s
├── mapShipment(s) → normalizes backend field names
├── Sidebar (5 nav items with SVG icons)
├── TopBar (CSL logo, clock, Sheets Live)
├── DashboardView (View A — all panels show real data)
│   ├── Map placeholder (SVG)
│   ├── Live Shipment Data (from apiStats)
│   ├── Bot Status (from /api/bot-status, shows real timing)
│   ├── Live Alerts (from /api/alerts, real urgent LFD alerts)
│   ├── Quick Actions
│   ├── Account Overview (from /api/accounts, real load counts)
│   └── Recent Bot Actions (from bot-status timing)
├── DispatchView (View B — real shipment table)
│   ├── Dynamic accounts dropdown (from API)
│   ├── 232 real shipments in table
│   └── All existing features preserved
├── AddForm (dynamic account list)
└── MacropointModal (mock tracking data, opens real URL)
```

## Real Data Confirmed
- 232 shipments across 18 accounts
- Top accounts: Boviet (27), DSV (16), EShipping (12), DHL (8), GW-World (7)
- 10 urgent alerts (LFD-today pickups)
- All 7 bot services operational with real timing

## Next Steps
- Wire MacropointModal to real webhook data (container_url already in shipments)
- Add `POST /api/load/{efj}/status` for status updates from UI
- Build for production: `npm run build` → serve from FastAPI `/static/dist/`
- Mobile bottom tab bar (user design feedback)
