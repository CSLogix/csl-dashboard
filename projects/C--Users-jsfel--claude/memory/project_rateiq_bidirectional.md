---
name: Rate IQ bidirectional lanes and quote preview
description: PR #13 — bidirectional lane grouping + polished quote preview for email screenshots
type: project
---

**PR #13** (merged 2026-03-17): "Support bidirectional lanes and optimize quote preview styling"

Changes:
- **Bidirectional lane grouping:** A→B and B→A merged into single lane card with ↔ arrow. Applied in both frontend (RateIQView groupedLanes) and backend (search-lane API).
- **Quote preview redesign:** Tighter, screenshot-friendly card. CSL brand colors (green/teal gradient), dark theme. Only shows route rows with values. Compact spacing optimized for Outlook paste at 576px.
- **Carrier dedup fix:** Same carrier_name + same total → keep the one with more populated fields.
- **MC# and email placeholders:** Always shown on carrier rate cards.

Files changed: `csl-doc-tracker/routes/rate_iq.py`, `dashboard/src/QuoteBuilder.jsx`, `dashboard/src/views/RateIQView.jsx`
