---
name: AI Tools Roadmap
description: Ask AI tool inventory — 24 tools deployed across 4 tiers in ai_assistant.py
type: project
---

## Deployed (24 tools in ai_assistant.py)

### Original 5
- `query_lane_history` — lane rate search
- `query_carrier_db` — carrier database search
- `check_efj_status` — shipment lookup
- `extract_rate_con` — regex rate con parser
- `draft_new_load` — structured load draft (no DB insert)

### Tier 1 (deployed Mar 11, 2026)
- `quote_lookup` — historical avg carrier pay + target margin % → suggested customer_rate
- `carrier_capability_check` — DNU check, tier rank, service feedback, 90-day stats
- `available_capacity` — delivered dray imports needing empty return, per diem risk
- `eta_delay_check` — billing readiness: which docs on file, what's missing
- `recent_emails` — pulls carrier contact, generates email template
- `suggest_carrier` — revenue vs carrier pay, avg margin %, top/bottom lanes

### Tier 2 — "Stop Asking Me" (deployed Mar 11, 2026)
- `unit_converter` — metric ↔ imperial: cm/m/kg → ft/in/lbs, CBM → cuft
- `shipment_summary` — one-pager brief: shipment + tracking + docs + emails + margin + carrier
- `detention_calculator` — terminal + arrival time + free time → when detention starts, estimated cost
- `accessorial_estimator` — historical accessorial averages for a lane (chassis, prepull, tolls, overweight)
- `billing_checklist` — pass/fail checklist: POD? Rate con? Carrier invoice? Rates entered?

### Tier 3 — "Make Me Look Smart" (deployed Mar 11, 2026)
- `load_comparison` — side-by-side diff of two loads (rates, carriers, timeline, docs)
- `account_health_report` — account-level: volume trend, avg margin, open issues, aging unbilled
- `transit_time_estimator` — historical delivery times from actual shipment data, avg/min/max transit days
- `explain_like_a_customer` — translates internal jargon (LFD, demurrage, per diem) into plain English
- `what_if_scenario` — "what if Carrier X instead of Y?" — margin calc + compliance + historical comparison

### Tier 4 — "Outside the Box" (deployed Mar 11, 2026)
- `daily_briefing` — morning standup: arriving loads, expiring LFDs, containers to return, missing docs, low-margin alerts
- `smart_dispatch_suggest` — "need carrier for 40HC PNCT→ATL" — combines lane rates + carrier DB + compliance into ranked suggestions
- `read_load_document` — PDF/image vision: downloads doc from uploads dir, converts PDF→image via pdftoppm, sends to Claude Sonnet vision. Can read rate confirmations, BOLs, PODs, invoices. Deployed Mar 13, 2026.

### Not implemented (covered by existing tools)
- `port_schedule_lookup` — functionality covered by existing vessel schedule data in check_efj_status
- `generate_report_card` — functionality covered by account_health_report + daily_briefing

## Architecture
- File: `/root/csl-bot/csl-doc-tracker/ai_assistant.py`
- Backup: `ai_assistant.py.pre-tools-v2`
- Pattern: TOOLS list (definition dict) + `_exec_<name>()` function + TOOL_DISPATCH entry
- Shared helper: `_clean_efj()` for EFJ normalization
- Model: Claude Sonnet 4.6 (`claude-sonnet-4-20250514`)
- MAX_TOOL_ITERATIONS: 5, MAX_RESPONSE_TOKENS: 2048
- All tools query PG directly via `database.get_cursor()`
- Frontend: `AskAIOverlay` component, Ctrl+K trigger, POST `/api/ask-ai`
