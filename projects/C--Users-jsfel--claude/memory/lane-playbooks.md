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

## What's Next
- Frontend: Playbook viewer/editor in dashboard (new tab or within Rate IQ)
- More lane seeds as team indexes bookings via Ask AI
- Retrieval optimization: when lane count > 5, remove inline playbook from system prompt, rely solely on tool retrieval
