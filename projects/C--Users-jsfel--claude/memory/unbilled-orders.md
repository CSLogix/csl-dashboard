# Unbilled Orders: Schema & Data Flow

## Architectural Overview

The system tracks unbilled freight through two distinct tables that must be reconciled to prevent loads from disappearing between delivery and invoicing:

| Table | Role | Primary Key | Data Entry |
|-------|------|-------------|------------|
| `shipments` | Operations master — synced with Google Sheets | `efj` | csl_bot cron + manual |
| `unbilled_orders` | Finance tracker — uploaded via Excel batches | `id` (serial) | `/api/unbilled/upload` |

**Join:** `REPLACE(u.order_num, ' ', '') = s.efj` *(brittle — see tech debt below)*

---

## Table Schemas

### `shipments` (billing-relevant columns)

| Column | Type | Notes |
|--------|------|-------|
| `efj` | TEXT PK | Load identifier |
| `status` | TEXT | Operational + billing status (see states below) |
| `account` | TEXT NOT NULL | Customer account name |
| `rep` | TEXT | Account rep name |
| `archived` | BOOLEAN DEFAULT FALSE | Set to TRUE only when billing closes |
| `archived_at` | TIMESTAMPTZ | When archived |
| `updated_at` | TIMESTAMPTZ | Last update |

**Missing (tech debt):** `invoice_number`, `invoice_amount`, `billed_at`, `payment_date`

### `unbilled_orders`

| Column | Type | Notes |
|--------|------|-------|
| `id` | SERIAL PK | — |
| `order_num` | TEXT NOT NULL | Matched to EFJ via REPLACE(spaces) |
| `container` | TEXT | Container/load reference |
| `bill_to` | TEXT | Bill-to customer name |
| `tractor` | TEXT | Tractor number |
| `entered` | DATE | Order entry date |
| `appt_date` | DATE | Appointment date |
| `dliv_dt` | DATE | Scheduled delivery |
| `act_dt` | DATE | Actual delivery |
| `age_days` | INT DEFAULT 0 | Days since entry — **calculated at upload only, never refreshed** |
| `dismissed` | BOOLEAN DEFAULT FALSE | Hidden from active view |
| `dismissed_at` | TIMESTAMPTZ | When dismissed |
| `dismissed_reason` | TEXT | `manual` \| `closed` \| `reconciled` \| `auto_delivered` |
| `billing_status` | TEXT DEFAULT 'ready_to_bill' | Current finance state |
| `upload_batch` | TEXT | Batch ID (timestamp) from upload |
| `created_at` | TIMESTAMPTZ | Record creation |

---

## Billing State Machines

### `shipments.status` — 7 Billing States (user-set via dashboard)

```
ready_to_close → missing_invoice → ppwk_needed → waiting_confirmation
                                                         ↓
                                               waiting_cx_approval → cx_approved → billed_closed
```

### `unbilled_orders.billing_status` — 4-State Finance Flow

```
ready_to_bill → billed_cx → driver_paid → closed
    (yellow)     (blue)      (orange)     (green, auto-dismisses)
```

**On `closed`:** `_archive_shipment_on_close(efj)` fires → `shipments.archived = TRUE` + `sheet_archive_row()`

---

## Archive Gate (as of Mar 10, 2026)

A load is archived from the active sheet **ONLY** when one of these fires:

| Trigger | Source | Condition |
|---------|--------|-----------|
| Unbilled order closed | `POST /api/unbilled/{id}/status` | `billing_status = 'closed'` |
| Billed & Closed with no unbilled record | `POST /api/v2/load/{efj}/status` | `billed_closed` status + no active `unbilled_orders` row |
| Bot detects Returned to Port | `csl_bot.py` archive loop | Rep must be mapped; if not, **both** PG + sheet archive skip (load stays fully visible) |

**Deliberately removed:** Auto-archive on `billed_closed` status change (old behavior — caused visibility black hole).

---

## Visibility Criteria: "Delivered but Unbilled"

A load is in the dangerous gap (delivered, not yet billed) if:

```sql
SELECT s.efj, s.account, s.rep, s.delivery_date, u.billing_status, u.age_days
FROM shipments s
JOIN unbilled_orders u ON REPLACE(u.order_num, ' ', '') = s.efj
WHERE s.status IN ('delivered', 'completed', 'empty returned')
  AND s.archived = FALSE
  AND u.dismissed = FALSE
  AND u.billing_status != 'closed'
```

---

## Rep Routing (Archive Destination)

Archive routing uses `_get_rep_for_account(sh, account_name)` in `csl_bot.py`:
1. Checks TTL-cached Account Rep sheet data (refreshes every 20 min)
2. On cache miss: forces live re-read before giving up
3. Falls back to hardcoded `ACCOUNT_REPS` dict
4. All lookups are case-insensitive + strip-normalized

**Completed tab destinations:**
- Radka → "Completed Radka"
- Eli → "Completed Eli"
- John F → "Completed John F"
- None found → **archive skipped entirely**, load stays active (logged as WARNING)

---

## API Endpoints

| Method | Endpoint | Action |
|--------|----------|--------|
| GET | `/api/unbilled` | All active (non-dismissed) orders + shipment enrichment |
| GET | `/api/unbilled/stats` | Count, avg_age, by_customer, delivered_count |
| POST | `/api/unbilled/upload` | Upload .xls/.xlsx batch (UPSERT, preserves billing_status) |
| POST | `/api/unbilled/{id}/status` | Advance billing_status; closes + archives on `closed` |
| POST | `/api/unbilled/{id}/dismiss` | Manual dismiss (reason: `manual`) |
| POST | `/api/unbilled/bulk-close-delivered` | Close all orders whose shipment is delivered |

---

## Tech Debt

1. **Brittle EFJ join:** `REPLACE(u.order_num, ' ', '') = s.efj` — will silently miss matches with other spacing/formatting differences. Should add a `shipment_efj` FK column to `unbilled_orders` populated at upload time.
2. **`age_days` static:** Calculated at upload, never updated. Queries should use `CURRENT_DATE - u.entered` instead.
3. **No invoice tracking:** `invoice_number`, `invoice_amount`, `billed_at`, `payment_date` not stored anywhere. All actual billing data lives in external invoicing software.
4. **Two disconnected status systems:** `shipments.status` (7 billing states) and `unbilled_orders.billing_status` (4 states) don't link to each other — reconciliation is manual.
