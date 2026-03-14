# Rate IQ — Detailed Notes

## Architecture
- **RateIQView** in DispatchDashboard.jsx: Wrapper with 4 sub-tabs — **Dray IQ** | **FTL IQ** | **OOG IQ** | **Scorecard**
- Tab state: `useState("dray")` — keys: `dray`, `ftl`, `oog`, `scorecard`
- **QuoteBuilder.jsx** (`src/QuoteBuilder.jsx`, ~1100 lines): Renders inside "Dray IQ" tab
- **OOGQuoteBuilder.jsx** (`src/OOGQuoteBuilder.jsx`, ~550 lines): Renders inside "OOG IQ" tab
- **FTL IQ**: Placeholder "coming soon" — no component yet
- **Scorecard**: Expandable carrier cards with lane drill-down (Lanes tab merged in)
- **Dray IQ** and **OOG IQ** tabs use `maxWidth: "none"` (full width); Scorecard uses `maxWidth: 1200`
- QuoteBuilder has internal sub-tabs: "Quote Builder" (form) and "History" (saved quotes list)

## QuoteBuilder.jsx Components
| Component | Purpose |
|-----------|---------|
| `QuotePreview` | Live PDF-style preview with logo, route, line items, totals |
| `HistoryTab` | Saved quotes list with search/filter/sort/pagination |
| `QuoteBuilder` (default export) | Main form: extract, manual entry, save, copy to clipboard |

## Key Features
- **AI Extract**: Upload image/PDF/text/.msg → POST `/api/quotes/extract` → Claude Vision parses rate data
- **Copy to Email**: html2canvas renders preview → PNG → clipboard (fallback: auto-download PNG)
- **Save**: POST/PUT `/api/quotes` → auto-switches to History tab after 600ms
- **Clipboard Paste**: `navigator.clipboard.read()` for images, `readText()` fallback for text
- **File Types**: `.png,.jpg,.jpeg,.gif,.webp,.pdf,.msg,.txt,.csv,.xlsx,.xls`

## Directory (Carriers Table)
- 11 columns: CARRIER NAME, MC#, V-CODE, EMAIL, PHONE, PICKUP, DESTINATION, DATE QUOTED, REGIONS, EQUIPMENT, delete
- All columns use `InlineCell` for inline editing
- Add Carrier form: 12 fields in 4-column grid
- Search + region filter + Import Excel + Upload buttons
- Backend: `carriers` table in PostgreSQL with CRUD at `/api/carriers`, `/api/carriers/{id}`

## Carrier DB Columns
`id`, `name`, `mc_number`, `v_code`, `email`, `phone`, `pickup_area`, `destination_area`, `date_quoted`, `regions`, `equipment`, `can_dray`, `hazmat`, `overweight`, `transload`, `created_at`, `updated_at`

## Backend Extract Endpoint (`/api/quotes/extract`)
- Accepts: FormData with `file` (image/PDF/msg) or `text` field
- Images: base64 → Claude Vision
- PDFs: PyMuPDF text extraction → Claude text, or page-to-image → Claude Vision
- **.msg files**: `extract-msg` library (v0.55) parses subject, sender, date, body, attachments. Embedded images sent to Claude Vision. Embedded PDFs text-extracted. Fallback: brute-force ASCII block extraction
- .htm/.html: Strip tags → Claude text extraction
- Returns: JSON with origin, destination, carrier, rate fields

## Image Cache Busting
- `/rateiq-bot.png?v=2` and `/astrobot.png?v=2` in frontend source
- Server has explicit FileResponse routes for these + auth middleware bypass for image extensions

## OOG IQ (OOGQuoteBuilder.jsx)
Oversize/Out-of-Gauge freight quote calculator. Replaces third-party "Oversize Rates" tool ($3/query).

### Layout
Two-column: left (inputs/builder), right (market analysis + bell curve + alerts + quote preview)

### Lookup Tables (placeholder values, user to provide real data)
- `FEDERAL_THRESHOLDS` — Width 8'6", Height 13'6", Length 48'/53'/75', Weight 80K lbs
- `STATE_PERMITS` — All 48 contiguous states + DC, single-trip permit costs
- `ESCORT_REQUIREMENTS` — Per-state width/height thresholds triggering escort
- `DIM_PENALTY_TIERS` — Tiered $/mile by oversize amount (moderate/significant/extreme/superload)
- `EQUIPMENT_OPTIONS` — Flatbed, Step Deck, RGN/Lowboy, Double Drop, Perimeter, Multi-Axle
- `TARP_OPTIONS` — Standard ($150), Heavy ($350), Custom ($600)
- `FSC_CONFIG` — Base rate $0.58/mile
- `SURVEY_RATES` — Basic $350, Bridge $750, Full $1200

### Auto-Calculation (useMemo hooks)
1. `classifyOversize()` — Compares L/W/H/weight vs FEDERAL_THRESHOLDS → colored badges (OVERWIDTH red, OVERHEIGHT orange, OVERLENGTH yellow, OVERWEIGHT purple, SUPERLOAD red pulse)
2. `calcDimPenalties()` — Tier lookup × miles for each oversize dimension
3. `calcPermitCosts()` — Sum STATE_PERMITS for each traversed state
4. `calcEscortCosts()` — Check ESCORT_REQUIREMENTS per state, $/mile with minimums
5. FSC = baseRate × miles
6. Survey = $350 if any state requires escort
7. **Market Rate** = Trip Rate + Dim Penalties + Permits + Escort + FSC + Survey + Tarp

### Override Toggle Pattern
Each auto-calculated cost field: `{ on: boolean, val: string }` state
- **AUTO** (green chip) — computed from lookup tables
- **MANUAL** (orange chip) — user types custom value

### Other Features
- States traversed tag-chip input (Enter/comma to add, X to remove)
- Bell curve SVG (pure inline, no library) — Low (0.85×), Average, High (1.30×) markers
- Alerts panel: auto-generated warnings (permits, escort, survey, superload)
- Copy-to-email: HTML `<table>` via ClipboardItem `text/html` blob

## Quote Status Workflow
- Statuses: `draft` (yellow ✏), `sent` (blue ✉), `accepted`/Won (green ✓), `lost` (red ✗), `expired` (gray ⏳)
- `PATCH /api/quotes/{id}/status` — quick status update without reloading full quote
- Won/Lost buttons shown on draft/sent quotes in History tab
- `margin_type` column: `pct` (% markup) or `flat` ($ flat) — persisted in DB

## History Tab (HistoryTab component)
- **Lane-first display**: Primary title is "Origin → Destination" (from `q.pod` + `q.final_delivery`); falls back to CSL-Q-### if no route
- **Secondary row**: CSL-Q-### (monospace) · Customer · Carrier
- **Action row**: Relative time + Won/Lost buttons + estimated total
- Filter chips: All | Drafts | Sent | Won | Lost | Expired
- Sort: Newest | Oldest | Highest $ | Lowest $ | Customer
- Pagination: 25 per page

## Scorecard Tab
- Data from `/api/rate-iq` — `data.scorecard` (carrier stats) + `data.lanes` (lane-grouped quotes)
- Expandable carrier cards: click row → shows lane drill-down for that carrier
- Cross-reference: `data.lanes.filter(l => l.carrier_quotes?.some(q => q.carrier === c.carrier))`
- Per-lane quotes show rate, date, status badge, accept/reject buttons, cheapest indicator
- Win% badges: green (≥50%), yellow (≥25%), red (>0%), gray (0)
- State: `expandedCarrier` (replaces old `expandedLane`)

## Flexible Margin (Mar 5, 2026)
- `marginType` state: `"pct"` (% Markup) or `"flat"` ($ Flat)
- Dropdown selector next to margin input in QuoteBuilder
- QuotePreview recalculates sell price based on type:
  - `pct`: `carrierRate * (1 + margin/100)`
  - `flat`: `carrierRate + flatAmount` (per linehaul item)
- Persisted in DB via `margin_type` column on `quotes` table

## Rate Intelligence Panel (updated Mar 9, 2026)
- States: `rateIntel`, `rateIntelLoading`, `rateIntelOpen`, `rateIntelGroups` (Set of expanded group indices)
- Auto-searches when `route.pod` OR `route.finalDelivery` has value (1.5s debounce)
- Calls `GET /api/rate-iq/search-lane?origin=X&destination=Y`
- Collapsible panel between margin row and accessorials section
- **Lane groups accordion**: Each lane group row (▶ expandable) shows lane name, quote count, source badges (E/I/Q), floor–ceiling range. Expanded: carrier rows with EMAIL/IMPORT/QUOTE tags, click to autofill
- Header: "Rate Intel — N lanes, M quotes" when lane_groups present
- Global stats bar: floor/avg/ceiling/carriers + source breakdown pills (EMAIL/IMPORT/QUOTE)
- Falls back to flat `matches[]` list if no lane_groups (backwards compat)
- First group auto-expanded on search

## Lane Search Backend (updated Mar 9, 2026)
- `GET /api/rate-iq/search-lane` — UNION ALL of 3 sources:
  - `rate_quotes` (carrier emails, AI-extracted) — source: "email"
  - `lane_rates` (Excel import, 243 rows) — source: "import"
  - `quotes` (won QuoteBuilder entries, status='accepted') — source: "quote"
- Groups by normalized (origin_lower, destination_lower)
- Returns: `{ lane_groups: [{lane, floor, avg, ceiling, carriers, count, sources, quotes[]}], matches[], carriers[], stats }`
- `stats` includes `sources: {email, import, quote}` breakdown and `total_lanes`

## AI Rate Extraction (Mar 9, 2026)
- Both `csl_inbox_scanner.py` and `csl_email_classifier.py` now use Claude Haiku for carrier rate extraction
- `extract_rate_from_email()` → calls `_ai_extract_rate()` first, regex fallback for missing fields
- `_ai_extract_rate()`: uses `claude-haiku-4-5-20251001`, returns JSON with rate_amount, rate_unit, move_type, origin, destination, miles, carrier_name
- Existing 16 rate_quotes have null rates (pre-AI era); new emails will populate correctly

## Quote Extractor v2 — Master Logistics Update (Mar 10, 2026)
Upgraded `quote_extractor.py` from basic Haiku extraction to Sonnet 4.6 with full intermodal intelligence.

### Universal Hub Normalization
- **`TERMINAL_HUBS`** dict: 40+ entries covering LA/LB (12 terminals), NY/NJ (6), Savannah (3), Houston (3), BNSF rail (7), UP rail (5), NS rail (4), CSX rail (3), city centroids (4)
- **`FIRMS_CODES`** dict: Y183 (APM), W158 (LBCT), Y790 (TraPac), E472 (Everport), Y256 (SSA), E204 (PNCT), E023 (Port Newark)
- **`normalize_hub(text)`**: FIRMS code priority → exact match → longest substring match → None
- **`post_process_extraction(result)`**: Applied after every Claude extraction — normalizes origin/destination, injects `origin_address`/`destination_address`
- Default LA/LB → 700 Pier A Plaza, Long Beach, CA 90802; default Chicago → 436 W 25th Pl, Chicago, IL 60616

### LoadMatch Screenshot Intelligence
- Prompt instructs: BASE/FSC/TOTAL column parsing; TOTAL = BASE × (1 + FSC%) as authoritative rate
- New output fields: `market_floor`, `market_average`, `market_ceiling`, `data_points`
- Multi-terminal rows in LA/LB cluster → one linehaul_item per terminal type
- Accessorials extracted from notes column: chassis, pre-pull, pier pass, storage, hazmat

### Carrier Email Logic
- Carrier name from From/Signature, linehaul + FSC + accessorial extraction
- Scrap material detection → auto-add scrap_premium accessorial ($150)

### 30-Day Aged Data Warning (QuoteBuilder.jsx)
- Individual Rate Intel quote rows: yellow ⚠ icon when `q.date` > 30 days old
- Global stats bar: "⚠ Market data may be aged" banner when newest data across all lane groups > 30 days
- Applied to both lane-group accordion view and flat-list fallback

## Quote → Rate IQ Feedback (Mar 9, 2026)
- `_index_quote_to_rate_iq(row)` helper in app.py: indexes saved dray quotes to `rate_quotes`
- Triggers on POST /api/quotes (create) and PUT /api/quotes/{id} (update)
- Only indexes Dray/Dray+Transload/OTR/Transload with valid carrier_total + origin + dest
- `source_quote_id` FK column in `rate_quotes` links back to `quotes.id`
- `status` column added to `rate_quotes` (default 'received', set 'quoted' for won quotes)

## Directory ↔ Quote Builder Integration (Mar 13, 2026)

### Backend (`routes/directory.py`)
- `GET /api/directory/suggest?port_code=X&caps=Y&destination=Z` — ranked carrier suggestions
  - Two-tier port matching: exact `ports` ILIKE match (tier 1) > fuzzy `pickup_area`/`regions` ILIKE (tier 2)
  - Capability filtering: `caps` param maps to `can_hazmat`, `can_dray`, `can_overweight`, etc.
  - LEFT JOIN `lane_rates` per carrier for rate_min/rate_max/rate_range/lane_match
  - Ranking: lane_match (yes first) → port_match (exact first) → tier_rank → carrier_name
  - Response: `{ carriers: [{ carrier_id, name, capabilities, last_quoted, rate_range, lane_match, lane_rate, contact, tier_rank, port_match }], total }`
- `POST /api/directory/feedback` — quote save → directory update
  - Primary lookup by `carrier_id` (int PK), fallback to `carrier_name` ILIKE
  - Found: UPDATE `date_quoted`, INSERT `lane_rates` row (source="quote")
  - Not found: INSERT new carrier with `needs_review=true`, return `action: "added_for_review"`
- DB migration: `ALTER TABLE carriers ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT false`

### Frontend (`QuoteBuilder.jsx`)
- State: `suggestedCarriers`, `suggestionsLoading`, `selectedCarrier`, `suggestionsExpanded`, `suggestionsSearched`
- `detectedCaps` useMemo: auto-detects `dray`/`transload`/`overweight` from shipment type + accessorials
- Auto-fetch: 300ms debounce on `route.pod` (3+ chars), preserves existing `carrierName`
- Suggestion panel: shimmer skeleton loading, carrier rows with capability badges (exact CAP_OPTIONS colors), lane match green dot, highlighted row for current carrier (teal left border), collapsed/selected state with "Change" link
- Feedback on save: `POST /api/directory/feedback` with `carrier_id` (from selectedCarrier) or null (manual entry)
- Badge colors: HAZ `#f87171`, OWT `#FBBF24`, Reefer `#60a5fa`, Bonded `#a78bfa`, OOG `#fb923c`, WHS `#34d399`, Transload `#38bdf8` (no badge for `can_dray`)

## Dray IQ Layout (QuoteBuilder)
- Quote Builder: `maxWidth: 1100, margin: "0 auto"`, flex with gap 40px
- Builder panel: width 480, minWidth 420
- Preview panel: width 560, flexShrink 0
- Directory: `maxWidth: "none"` (full width for wide table)

## Rate IQ UX Redesign (Mar 14, 2026) — Built, Not Yet Deployed
- **Autocomplete search**: Origin + Destination inputs with dropdown suggestions from `rateLaneSummaries`. Shows lane count + avg rate per location. `useMemo` client-side filtering.
- **Recent searches**: Saved to `localStorage` ("rateiq_recent"), shown as blue pills when inputs empty. Max 5.
- **Quick Quote on LaneCard**: Hover-revealed gradient button → jumps to quote view with lane pre-selected.
- **Enhanced Carrier Cell** (CarrierRateTable): 3-line info hub — Line 1: name + capability icons + age. Line 2: MC# + copy button (clipboard). Line 3: dispatch email as mailto link.
- **Email RC button**: Hover-revealed on carrier rows. Opens `mailto:` with pre-filled rate confirmation details (origin, dest, rate, equipment).
- **LaneCard volume tags**: High Volume (teal, ≥20), Active (blue, ≥5), Low Volume (muted). Trend arrows with %.

## Gmail Rate Backfill (Mar 14, 2026)
- **Script**: `/root/csl-bot/backfill_rate_history.py` (local: `C:\Users\jsfel\csl-patches\backfill_rate_history.py`)
- **Vision model**: `claude-sonnet-4-20250514` (NOT `claude-sonnet-4-6-*` — that 404s)
- **Gmail run result**: 159 threads → 17 rates extracted (6 DRAY, 10 FTL, 1 TRANSLOAD). 10.7% rate.
- **Classification**: 3-pass — container regex (DRAY anchor) → transload keywords → keyword scoring (threshold ≥2)
- **DRAY keywords**: chassis, container, pier, vessel, terminal, port, ssl, steamship, demurrage, per diem, free time, pierpass, clean truck, ramp, intermodal, rail, drayage, csx, bnsf, norfolk southern, union pacific, linehaul, prepull, 20', 40', 40hc, 40 hc, 20gp, 40gp, 20st, oog, open top, flat rack, 20ft, 40ft
- **Post-extraction reclassification**: Checks AI-returned fields for dray signals (container#, chassis, prepull, ramp/intermodal in origin/dest, equipment patterns). Working — caught "Tampa FL PORT" as DRAY.
- **Attachment filtering**: SKIP_PATTERNS regex filters image001.png, Outlook-*.png, CamScanner BOL/POD. Size threshold >5000 bytes. PDFs prioritized by size desc.
- **Dual insert**: `rate_quotes` + `lane_rates` tables, both with `source='gmail_backfill'`
- **Confidence decay**: `max(0.3, 1.0 - (age_months * 0.06))`
- **State file**: `backfill_rate_state.json` for resumable processing
- **Folder mode**: `--folder /path/` for Outlook PDF dump import

## Outlook .msg Extraction (Mar 14, 2026)
- **322 .msg files** exported to `C:\Users\jsfel\OneDrive\Desktop\Rate Exports\`
- **Extraction script**: `/root/csl-bot/extract_msg_attachments.py` — uses `extract-msg` library
- **Pipeline**: .msg → extract attachments (PDFs/images) + body text → `/root/csl-bot/rate-imports/` → `backfill_rate_history.py --folder`
- **Server dirs**: `/root/csl-bot/rate-msg-dump/` (raw .msg), `/root/csl-bot/rate-imports/` (extracted attachments)
- **Status**: Upload in progress (handled in separate chat)
