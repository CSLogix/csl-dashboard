# Memory Index

- [project_dashboard_repo.md](project_dashboard_repo.md) — Dashboard source at Downloads/csl-dashboard-preview (active) + deploy workflow
- [project_driver_contact_sync.md](project_driver_contact_sync.md) — PR #11: bidirectional driver phone/trailer sync (webhook ↔ cache ↔ PG ↔ sheets ↔ API)
- [project_rateiq_bidirectional.md](project_rateiq_bidirectional.md) — PR #13: bidirectional lane grouping + quote preview styling
- [project_no_sheet_sync_service.md](project_no_sheet_sync_service.md) — csl_sheet_sync.py runs inside csl-dashboard, no separate service
- [feedback_classifier_model.md](feedback_classifier_model.md) — Email classifier must use Claude Haiku, not Gemini Flash (45% failure rate)
- [project_port_groupings_datadriven.md](project_port_groupings_datadriven.md) — User wants port/rail groupings to be data-driven (DB + admin UI), awaiting port/rail list
- [project_jsoncargo_quota.md](project_jsoncargo_quota.md) — JsonCargo API quota optimization: cache TTL, BOL caching, business hours gate (2026-03-18)
- [project_google_maps_key_rotation.md](project_google_maps_key_rotation.md) — Distance Matrix API key rotated 2026-03-18, IP+API restricted, CSL Doc Tracker GCP project
- [feedback_coderabbit_docstrings.md](feedback_coderabbit_docstrings.md) — CodeRabbit auto-docstrings break builds: missing comment closers + indentation errors
- [project_dashboard_prs_deployed.md](project_dashboard_prs_deployed.md) — All PRs #1-#23 deployed (2026-03-18), PR #23 = exception handling + atomic writes
- [project_tolead_dualwrite.md](project_tolead_dualwrite.md) — Tolead dual-write is LAX-only; ORD/JFK/DFW skip (separate sheets)
