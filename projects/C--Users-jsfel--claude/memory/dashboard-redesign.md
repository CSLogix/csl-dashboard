# Dashboard Redesign — DEPLOYED (2026-02-27)

All steps below are live and running on the server.

## Rep Dashboard (`/rep/{rep_name}`) — DEPLOYED
- Account cards with stats: Active, On Schedule, At Risk, Unbilled
- Click card → inline expand shows load table
- Invoiced `<select>` dropdown per load row (PostgreSQL, `POST /api/load/{efj}/invoiced`)
- Invoiced rows green-tinted, persists across refreshes
- Responsive grid: `minmax(240px)` for <=6 accounts, `minmax(180px)` for 7+
- Detail slide-out panel on EFJ# click with Macropoint link

## SheetCache Multi-Sheet Reading — DEPLOYED
Dashboard reads 3 sheets every 5 min via `_do_refresh()`:
1. **Master Tracker** (`19MB5...`) — 12 account tabs, cols A-P
2. **Boviet** (`1OP-Z...`) — 6 sub-account tabs (DTE, Sundance, Renewable Energy, Radiance Solar, Piedra, Hanson)
3. **Tolead** (`1-zl7...`) — "Schedule" tab, only loads with non-empty status in col J

### Boviet TAB_CONFIGS
```
DTE Fresh/Stock:  efj=0, load_id=1, status=5
Sundance:         efj=0, load_id=1, status=6
Renewable Energy: efj=0, load_id=1, status=5
Radiance Solar:   efj=0, load_id=1, status=5
Piedra:           efj=0, load_id=2, status=7
Hanson:           efj=0, load_id=1, status=6
SKIP: POCs, Boviet Master
```

### Known Issue — TO FIX NEXT SESSION
Boviet loads all get `account="Boviet"` — tab name (project) NOT stored in shipment dict.
**Fix**: Add `"project": tab_name` to each Boviet shipment in `_do_refresh()`, then modify `rep_dashboard()` to group by `project` when `rep_name=="Boviet"` showing summary bar + 6 project cards.

### Sidebar Structure (current)
```python
items = [
    ("dashboard", "/", "Dashboard"),
    ("shipments", "/shipments", "Shipments"),
    ("unmatched", "/unmatched", "Unmatched Emails"),
    ("docs", "#", "Documents"),  # <-- NON-FUNCTIONAL, replace with Unbilled
]
# Bottom: Settings gear icon
```
**Next**: Replace `("docs", "#", "Documents")` with `("unbilled", "/unbilled", "Unbilled Orders")`

## Macropoint Hyperlinks — DEPLOYED
- `_get_sheet_hyperlinks(creds, sheet_id, tab_name)` helper fetches via Sheets API v4
- Boviet: hyperlinks from EFJ col (col A)
- Tolead: hyperlinks from col P
- Stored as `container_url` in each shipment dict
- Detail panel shows clickable "Track Shipment" Macropoint link

## Document Tracker (`/shipments`) — DEPLOYED
- Columns: EFJ#, Container/Load ID, Account, BOL, POD, Status
- Drag-and-drop POD upload on each row → auto "Ready to Invoice"
- "Ready to Invoice" section (amber) with dismiss button
- API: `/api/load/{efj}/ready-to-invoice`, `/api/load/{efj}/dismiss`

## Live Alerts — DEPLOYED
- Filter tabs: All, Imports, Exports, FTL, Boviet, Tolead
- `data-account` attribute on alert items for filtering

## Team Panel — DEPLOYED
- Boviet (amber, "BV") and Tolead (red, "TL") as own rows
- Clickable → `/rep/Boviet`, `/rep/Tolead`

## Bug Fixes — DEPLOYED
- webhook.py: port 5003 (was 5000, then 5002 also taken by bol-webapp)
- tolead_monitor.py: NoneType guard on status + skip empty statuses

## Database Schema (current)
- `loads` table: id, load_number, customer_ref, customer_name, account, status, invoiced, created_at, updated_at
- `documents`, `load_references`, `document_checklist`, `email_log`, `unmatched_emails`
- Functions: `set_load_invoiced()`, `get_invoiced_map()`, plus all CRUD helpers in database.py
