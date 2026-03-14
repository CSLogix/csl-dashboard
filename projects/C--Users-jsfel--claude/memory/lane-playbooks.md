---
name: Lane Playbooks System
description: Lane playbook JSONB storage, CRUD API, AI tools for retrieval/creation, schema v2 with versioning
type: project
---

## Architecture
- **PG table**: `lane_playbooks` — UUID PK, `lane_code` (unique), `account_name`, `status` (active/inactive/draft), `version` (int), `playbook` (JSONB), timestamps
- **Indexes**: account_name, status, GIN on playbook JSONB
- **Route module**: `routes/playbooks.py` mounted at `/api/playbooks/*`
- **AI tools**: 3 tools in `ai_assistant.py` — query PG directly (bypass HTTP auth)

## API Endpoints (all require auth)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/playbooks/` | List all (summary only, no full JSONB) |
| GET | `/api/playbooks/{lane_code}` | Full playbook by lane code |
| POST | `/api/playbooks/` | Create new playbook |
| PUT | `/api/playbooks/{lane_code}` | Update (increments version, appends changelog) |
| DELETE | `/api/playbooks/{lane_code}` | Soft-delete (sets inactive) |
| POST | `/api/playbooks/match` | Fuzzy match by account+origin+destination |

## Schema v2 Key Fields
- `lane` — origin/dest city+state, commodity, weight, hazmat, oversize
- `load_structure` — multi_load flag, total_loads, per-load details (move_type, equipment, facilities)
- `contacts` — role-tagged (Customer Primary/Backup, Shipper, Carrier Dispatch, Warehouse, etc.)
- `facilities` — type, hours, scheduling_method, detention_rules (free_time_hours, demurrage), quirks
- `carriers` — role (Primary/Backup/Spot/Emergency), rate_paid, flag_if_over, loads_covered
- `rates` — customer_rates per load, accessorials with charge-back rules, combined revenue/margin
- `booking_defaults` — lane-level defaults (typical container size, ocean carrier). Per-shipment booking details go to bulk_create_loads.
- `workflow_steps` — ordered steps with notify lists
- `escalation_rules` — handle_autonomously / flag_but_proceed / escalate_to_john
- `changelog` — date, changed_by, summary, source_document
- `version` + `last_updated` — auto-incremented on update
- `seasonal_notes` — peak/slow months, capacity warnings
- `source_documents` — audit trail of what was indexed

## AI Integration
- System prompt instructs Claude to retrieve playbooks when bookings match known lanes
- `get_lane_playbook` — by lane_code (exact) or account+origin+dest (fuzzy ILIKE)
- `save_lane_playbook` — upsert with version increment + changelog. Called when user says "index this" or "learn this lane"
- `list_lane_playbooks` — summary listing with optional account/status filters

## Seeded Data
- **DSV-RICH-WANDO**: Richburg SC → Wando Welch Terminal SC. 2-load structure (FTL flatbed + Dray Export). AIM Trucking primary on Load 2 ($890, never shop). Revenue $2,060, ~31% margin. 9 contacts, 3 facilities, 7 workflow steps.

## System Prompt + Schema (local files)
- `CSL_AskAI_System_Prompt_v2.md` — Full system prompt with core rules, escalation tiers, DSV-RICH-WANDO inline example
- `extract_lane_playbook_schema_v2.json` — JSON Schema for extraction tool
- Both at `C:\Users\jsfel\Downloads\`

## Auto-Match Engine (#106)
- `playbook_lane_code` TEXT column on `shipments` (indexed)
- `_try_playbook_match(efj, account, origin, destination, move_type)` in ai_assistant.py
- Only auto-applies on exactly 1 active playbook match (0 = no match, 2+ = ambiguous)
- Auto-populates: carrier, carrier_pay, customer_rate, equipment_type, bot_notes
- Hooked into: `_exec_bulk_create_loads` (Ask AI) + `POST /api/v2/load/add` (dashboard Add Form)
- `GET /api/playbooks/shipment/{efj}` — check if a shipment has/can match a playbook

## Process Booking (#107)
- `POST /api/inbox/process-booking` in routes/emails.py
- **Step 1**: Sender domain → account lookup (17 domains in `_DOMAIN_ACCOUNT_MAP`)
- **Step 2**: Claude Sonnet AI extraction (structured JSON: account, origin/dest, move_type, equipment, container, booking#, vessel, dates, rates, commodity)
- **Step 3**: Cross-check domain vs AI account (domain wins, logs discrepancy)
- **Step 4**: Confidence scoring — high (all required + 3/4 nice-to-have), medium (missing 1 required), low (2+ missing)
- **Step 5**: Fuzzy playbook match (ILIKE on city names) → full defaults (carrier, rates, contacts, workflow, multi-load, escalation)
- Returns: `extracted_load` + `playbook_defaults` + `playbook_match` + `confidence` + `source` per field (ai/domain/playbook)

## Playbook-Aware Ask AI
- System prompt updated: Claude ALWAYS calls `get_lane_playbook` before `bulk_create_loads`
- If playbook found + origin/dest match → merges carrier, carrier_pay, customer_rate, equipment_type
- If no match → proceeds normally + suggests indexing the lane afterward
- "Process Booking" quick-action chip added to AskAIOverlay

## Frontend
- **PlaybooksView.jsx**: List/detail sub-views, card grid, 2-column detail layout
- **Dispatch badge**: Teal book icon next to EFJ# when `playbookLaneCode` set (desktop + mobile)
- **LoadSlideOver badge**: Clickable teal lane code badge in header
- **InboxView Build Load**: Orange "Build Load" button → Load Confirmation slide-over (editable form with source badges, MISMATCH/MISSING highlighting, "Index as new playbook" checkbox, "Create Load & Dispatch" button)

## What's Next
- More lane seeds as team indexes bookings via Ask AI
- Retrieval optimization: when lane count > 5, remove inline playbook from system prompt, rely solely on tool retrieval
