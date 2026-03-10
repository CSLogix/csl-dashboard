# Inbox Command Center — Detailed Notes

## Overview
Top-level dashboard view for email triage. Compact table-based inbox with sender-pattern reply detection, smart classification (carrierpay escalation, carrier rate response, POD auto-detect, RC detection), live alerts, rep email pills, and daily digest emails. Major overhaul deployed Mar 9, 2026.

## Architecture

### Email Sources
- **Inbound**: `john.feltz@commonsenselogistics.com` via Gmail OAuth scanner (polls every 5 min)
- **Reply detection**: Sender-pattern matching in `email_threads` — checks for `evansdelivery.com` or `commonsenselogistics.com` senders
- **Evans auto-forward**: Evans inboxes forward to CSL Gmail. Reps set Outlook CC rule to `john.feltz@commonsenselogistics.com`

### Reply Detection Flow (Fixed Mar 9, 2026)
1. Inbound email lands in CSL Gmail → scanner classifies + stores in `email_threads`
2. `/api/inbox` groups by `gmail_thread_id`, tags messages from CSL domains as `direction: "sent"`
3. Reply detection: if any CSL-domain message timestamp > latest external message → `has_csl_reply = true`
4. **NOTE**: `sent_messages` table is DEPRECATED (always empty, receive-only Gmail account). Reply detection now uses sender-pattern matching in `email_threads`.

### Classification Logic (`csl_inbox_scanner.py` — `classify_email_type()`)
9-step priority classification (first match wins):
1. **Tag override**: Subject contains `[CARRIER RATE]`, `[CUSTOMER RATE]`, `[POD]`, `[INVOICE]` → direct classification
2. **CarrierPay escalation**: `carrierpay@evansdelivery.com` — "NP" pattern → `payment_escalation` (priority 5), else `carrier_invoice` (priority 4)
3. **POD body-text**: Non-CSL sender + attachment + body matches `POD_BODY_PATTERNS` → `pod` (priority 3)
4. **Carrier rate confirmation**: `RC_PATTERNS` match → `carrier_rate_confirmation` (priority 4)
5. **CSL team outbound**: CSL sender + rate signals → `rate_outreach` (priority 2), else skip
6. **Carrier signal scoring**: Known carrier domains, MC#, trucking keywords → `carrier_rate`
7-8. **Customer patterns**: Known customer domains or quote language → `customer_rate`
9. **Enhanced customer**: `CUSTOMER_QUOTE_PATTERNS` (RFQ, container sizes, ramp patterns) → `customer_rate`

**Thread-based carrier response**: After DB insert, checks if `gmail_thread_id` has prior `rate_outreach` → reclassifies as `carrier_rate_response` (priority 4)

### Key Regex Constants (in csl_inbox_scanner.py after line ~148)
- `POD_BODY_PATTERNS`: "pfa pod", "pod attached", "please see attached", "proof of delivery"
- `RC_PATTERNS`: "rate confirmation", "r/c attached", "updated rc", "signed rc"
- `CUSTOMER_QUOTE_PATTERNS`: "rfq", "rate request", container sizes "1x40HQ", ramp patterns

### Junk Attachment Filter
- Skips Outlook signature images (`image001.png` through `image999.png`)
- Skips social media icons (facebook, linkedin, twitter, instagram, youtube)
- Skips tracking pixels (all `.gif` files, `pixel.*`, `beacon.*`, `spacer.*`)
- Skips any image under 15KB (real docs are always larger)
- Function: `is_junk_attachment(filename, size_bytes)` in `csl_inbox_scanner.py`

## Email Types

| Type | When | Priority | Alert? |
|------|------|----------|--------|
| `payment_escalation` | CarrierPay + "NP" pattern | 5 (CRITICAL) | Immediate email to rep |
| `carrier_invoice` | CarrierPay without NP | 4 (HIGH) | Daily digest + "Send Final Charges" alert |
| `carrier_rate_confirmation` | Carrier RC/rate con | 4 (HIGH) | Daily digest + "Send Final Charges" alert |
| `carrier_rate_response` | Carrier reply on rate_outreach thread | 4 (HIGH) | Live alert + daily digest |
| `pod` (body-detected) | Carrier + attachment + body keywords | 3 (NORMAL) | Daily digest |
| `rate_outreach` | CSL team outbound + rate signals | 2 (LOW) | No |
| `customer_rate` | Inbound + RFQ/container patterns | 4 (HIGH) | No |
| `carrier_rate` | Inbound carrier rate | 3 (NORMAL) | No |

## Email Notifications

### Immediate (payment_escalation only)
- Sent in real-time from `process_message()` when `payment_escalation` classified
- From `jfeltzjr@gmail.com`, to assigned rep, CC `efj-operations@evansdelivery.com`
- Dedup via `inbox_alert_sent.json` (same atomic write pattern as `ftl_sent_alerts.json`)

### Daily Digest (`csl_inbox_digest.py --once`, 7:00 AM ET Mon-Fri)
3 separate emails:
1. **Master Reps** (Eli, Radka, John F, Janice): per-rep email grouped by account, CC `efj-operations@evansdelivery.com`
2. **Boviet**: to `boviet-efj@evansdelivery.com`, broken down by project (Piedra/Hanson)
3. **Tolead**: to `tolead-efj@evansdelivery.com`, broken down by hub (ORD/JFK/LAX/DFW)

All digests include unbilled orders section from `unbilled_orders` table.

Queue table: `inbox_digest_queue` (id, efj, email_type, sender, subject, summary, rep, created_at, sent)

## Database Tables

### `inbox_digest_queue` (created Mar 9, 2026)
```sql
id SERIAL PRIMARY KEY,
efj TEXT,
email_type TEXT NOT NULL,
sender TEXT, subject TEXT, summary TEXT, rep TEXT,
created_at TIMESTAMPTZ DEFAULT NOW(),
sent BOOLEAN DEFAULT FALSE
```
Index: `idx_digest_queue_unsent ON inbox_digest_queue (sent, created_at) WHERE sent = FALSE`

### `sent_messages` (DEPRECATED — always empty)
Still exists but unused. Reply detection now uses sender-pattern matching.

### Added columns
- `email_threads.classification_feedback` TEXT — "correct" or "incorrect"
- `email_threads.corrected_type` TEXT — corrected email_type if feedback is "incorrect"
- `unmatched_inbox_emails.classification_feedback` TEXT
- `unmatched_inbox_emails.corrected_type` TEXT

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/inbox` | Thread-grouped emails with sender-pattern reply detection. Params: `?days=`, `?tab=all\|needs_reply\|unmatched\|rates`, `?type=`, `?priority_min=`, `?rep=`, `?limit=` |
| POST | `/api/inbox/{id}/feedback` | Classification feedback. Body: `{ feedback: "correct"\|"incorrect", corrected_type: "detention" }` |
| GET | `/api/inbox/reply-alerts` | Unreplied customer quote thread alerts |
| GET | `/api/rate-response-alerts` | Recent carrier_rate_response + payment_escalation + carrier_invoice + carrier_rate_confirmation from last 24h |

## Frontend

### InboxView Component (rewritten Mar 9, 2026 — compact table layout)
- **Layout**: Full-width table with 36-40px rows (replaced card layout with max-width 960px)
- **Columns**: Priority (dot), Status (NEEDS REPLY/REPLIED badges), Type (colored badge), Subject (flex), EFJ, Sender, Msgs, Updated
- **Tabs**: All, Needs Reply (count), Unmatched (count), Rates
- **Sorting**: Click any column header to sort (asc/desc toggle)
- **Column filters**: Dropdown filters on Type, EFJ, Sender, Status columns
- **Search**: Subject, sender, EFJ, lane search
- **Thread detail**: 480px right slide-over panel (replaces inline expand) with chronological messages, action bar
- **Polling**: 90s interval + manual Refresh button

### EMAIL_TYPE_COLORS (in DispatchDashboard.jsx)
```
payment_escalation: red (#EF4444)
carrier_rate_response: teal (#00D4AA)
rate_outreach: blue (#3B82F6)
carrier_invoice: orange (#F97316)
carrier_rate_confirmation: purple (#A855F7)
warehouse_rate: cyan (#06B6D4)
```

### Live Alert Types (added Mar 9, 2026)
- `rate_response`: icon ★, teal (#00D4AA) — carrier responded to rate request
- `payment_escalation`: icon ⚠, red (#EF4444) — carrierpay NP alert
- `send_final_charges`: icon $, amber (#F59E0B) — invoice/RC received, bill customer

Fetched via `/api/rate-response-alerts` in polling loop with diff detection.

### Rep Dashboard Email Pills (added Mar 9, 2026)
- **Needs Reply** (red) — count of inbox threads needing reply for this rep's accounts
- **Rate Responses** (teal) — count of carrier_rate_response threads

### Dispatch Table Email Badges
- Small `✉N` badge next to EFJ in dispatch table rows
- Gray for normal priority, orange for priority >= 4

## Backend Patches Applied
| Patch | What |
|-------|------|
| `patch_inbox_command_center_db.py` | DB migration: `sent_messages` table + feedback columns |
| `patch_sent_mail_scanner.py` | Sent mail tracking in `csl_inbox_scanner.py` |
| `patch_inbox_api.py` | `/api/inbox` + `/api/inbox/{id}/feedback` + `/api/inbox/reply-alerts` |
| `patch_v2_email_stats.py` | Email count/priority enrichment in `/api/v2/shipments` |
| `patch_attachment_filter.py` | Junk attachment filter (signature icons, tracking pixels, <15KB images) |
| `patch_inbox_classification.py` | Classification overhaul: carrierpay, POD body-detect, rate_outreach, carrier_rate_response, RC detection |
| `patch_inbox_reply_detection.py` | Reply detection fix: sender-pattern matching, rates tab filter, `/api/rate-response-alerts` |

## Remaining Work
- **Mailto reply button**: "Reply" button on inbox threads opening Outlook with To/Subject/CC pre-filled
- **Thread detail slide-over polish**: Assign to load, classification correction UI
