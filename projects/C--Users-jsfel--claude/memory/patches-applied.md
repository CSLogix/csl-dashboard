# Patches Applied This Sprint

| Patch | What |
|-------|------|
| `patch_add_load.py` | POST /api/load/add — routes to Master/Tolead/Boviet sheets |
| `patch_fix_driver_insert.py` | Fix driver_contacts INSERT to use actual schema columns |
| `patch_fix_cache_invalidate.py` | Fix `sheet_cache._last = 0` (was wrong attribute) |
| `patch_lane_search.py` | GET /api/rate-iq/search-lane — fuzzy lane+carrier search |
| `patch_notes_log.py` | `load_notes` table + GET/POST `/api/load/{efj}/notes` |
| `patch_ai_email_triage.py` | AI email classification via Claude Haiku + priority/type/summary columns |
| `patch_carrier_scorecard.py` | GET /api/carriers/scorecard — aggregated delivery metrics |
| `patch_replace_jsoncargo.py` | Multi-provider tracking: SeaRates primary + JSONCargo fallback |
| `patch_postgres_migration.py` | `shipments` table + import all active sheet data into Postgres |
| `patch_v2_endpoints.py` | `/api/v2/*` endpoints reading/writing from Postgres |
| `csl_sheet_sync.py` | Two-way sync: Tolead+Boviet sheets ↔ Postgres |
| `csl_pg_writer.py` | Shared PG writer module for bot dual-write (UPSERT + archive) |
| `patch_bot_pg_import.py` | Dray Import PG dual-write + archive |
| `patch_bot_pg_ftl.py` | FTL PG dual-write + archive |
| `patch_bot_pg_export.py` | Dray Export PG dual-write + archive |
| `patch_import_pg.py` | Dray Import full PG migration (drop sheets entirely) |
| `patch_export_pg.py` | Dray Export full PG migration (drop sheets entirely) |
| `patch_ftl_pg_migrate.py` | FTL full PG migration (drop sheets + Playwright scraping) |
| `patch_inbox_command_center_db.py` | `sent_messages` table + feedback columns on email tables |
| `patch_sent_mail_scanner.py` | Sent mail tracking in `csl_inbox_scanner.py` |
| `patch_inbox_api.py` | `/api/inbox` + feedback + reply-alerts endpoints |
| `patch_v2_email_stats.py` | Email count/priority enrichment in `/api/v2/shipments` |
| `patch_attachment_filter.py` | Junk attachment filter (signatures, icons, pixels, <15KB) |
| `patch_macropoint_pg.py` | Nginx webhook access + upload_server PG write + cache cleanup |
| `patch_driver_fallback.py` | Driver API PG fallback from shipments table |
| `fix_all_cursor_indent.py` | Fix 19 damaged `with db.get_cursor()` blocks from global sed |
| `fix_driver_dictcursor.py` | Fix RealDictCursor tuple→dict indexing |
| `patch_webhook_get.py` | GET handler for Macropoint native protocol (query params) |
| `patch_webhook_event_codes.py` | Macropoint event code mapping (X1/X2/X6/AG/AF) |
| `patch_webhook_container_match.py` | Container→EFJ PG lookup for Tolead order IDs |
| `patch_macropoint_api_pg.py` | `/api/macropoint/{efj}` PG fallback + lastLocation GPS |
| `patch_ftl_alerts_module.py` | Shared email+dedup module `csl_ftl_alerts.py` + refactor ftl_monitor.py |
| `patch_webhook_realtime_alerts.py` | Webhook BackgroundTasks for real-time email alerts |
| `patch_health_endpoint.py` | `/api/health` — PG, sheets, services, cron, disk checks |
| `csl_sheet_writer.py` | Shared sheet dual-write module (fire-and-forget) |
| `patch_dual_write_import.py` | Dray Import sheet dual-write (sheet_update_import + sheet_archive_row) |
| `patch_dual_write_export_v2.py` | Dray Export sheet dual-write (sheet_update_export + sheet_archive_row) |
| `patch_dual_write_ftl_v2.py` | FTL sheet dual-write (sheet_update_ftl + sheet_archive_row) |
| `fix_health_endpoint.py` | Fix broken `\n` escapes in health endpoint (heredoc issue) |
| `fix_completed_cache.py` | Enrich account from PG, sort newest-first, fix db.get_cursor() context manager |
| `patch_unbilled_reconcile.py` | Unbilled↔Shipments: LEFT JOIN, auto-archive on close, bulk-close-delivered, PG merge into history |
| `patch_macropoint_sync.py` | Fix 5 Macropoint bugs: stop_times (structured eventType), Tracking Completed→Delivered, MP URL from MPOrderID, container_url PG write, v2 mp_status enrichment |
| `backfill_mp_urls.py` | Backfill macropoint_url from webhook_events.log MPOrderIDs (45 cache + 22 PG entries) |
| `fix_timeline_stops.py` | tracking_events PG table + `_build_timeline_from_pg()` + `_persist_tracking_event()` |
| `fix_infer_stop_arrival.py` | GPS proximity inference in schedule alert handler (0.5mi arrival / 2.0mi departure) |
| `backfill_pickup_events.py` | One-time retroactive pickup event backfill from webhook_events.log (60 events) |
| `patch_tracking_events_fix.py` | Fix 3 bugs: ET→offset in `_persist_tracking_event()`, cache→PG timeline merge, log.warning |
| `patch_mp_classifier.py` | `_classify_mp_display_status()` function + webhook schedule alert storage + 3 API endpoints enriched with mpDisplayStatus/mpDisplayDetail |
| `patch_inbox_classification.py` | Scanner classification overhaul: fix INSERT bugs, carrierpay escalation, POD body-detect, rate_outreach, carrier_rate_response thread detection, RC detection, immediate payment alerts, digest queue |
| `patch_inbox_reply_detection.py` | Reply detection fix: sender-pattern matching (replace empty sent_messages), rates tab filter, `/api/rate-response-alerts` endpoint |
| `patch_customer_rate_detection.py` | Expanded KNOWN_CUSTOMER_SENDERS (maoinc, manitoulin, tcr, texas.?int, md.?metal, usha) + CUSTOMER_QUOTE_LANGUAGE (OOG, dims, unicode×, hazmat, 53ft, inland rate, service combos) + AI classifier prompt improvements |
| `patch_scanner_remaining.py` | Fix KNOWN_CUSTOMER_SENDERS + CUSTOMER_QUOTE_LANGUAGE in scanner (exact match with block boundaries) + dimension pattern (optional units before final) |
| `patch_quotes_dray_filter.py` | list_quotes() move_types param + GET /api/quotes move_types filter + POST/PUT /api/quotes → _index_quote_to_rate_iq() + _index_quote_to_rate_iq helper + source_quote_id/status columns in rate_quotes |
| `patch_lane_grouping.py` | search-lane UNION ALL (rate_quotes+lane_rates+won_quotes) + lane_groups accordion response with floor/avg/ceiling/sources per normalized lane |
| `patch_ai_rate_extraction.py` | AI rate extraction for csl_email_classifier.py: extract_rate_from_email → _ai_extract_rate (Claude Haiku) + regex fallback |
| `patch_scanner_extract_fix.py` | AI rate extraction for csl_inbox_scanner.py: same AI+fallback pattern (boundary-detection replace, not exact-match) |
| `patch_tolead_sync_fix.py` | csl_sheet_sync.py: Add `_get_sheet_hyperlinks()`, fix `sync_tolead()` ghost cleanup (NameError→proper db context + FK migration), trailer→driver_contacts, container_url in upsert ON CONFLICT |
| `fix_app_tolead_container_url.py` | app.py: Tolead legacy reader MP URL extraction from hyperlinks + clear driver field |
| `fix_ghost_and_driver.py` | One-off: Migrate DFW1260308010→EFJ107432 (tracking_events + container_url), clean 4 additional ghosts, clear 47 trailer-data driver fields |
| `patch_daily_summary_datefilter.py` | daily_summary.py: `_is_this_week()` date filter — only scrape loads picking up/delivering this week |
| `date_normalizer.py` | Shared date normalizer: `clean_date()` → MM-DD / MM-DD HH:MM. Handles Excel serials, all date formats, midnight stripping |
| `patch_date_normalizer.py` | Gate normalization in csl_pg_writer + LFD/pickup separation in csl_bot + sheet sync normalization |
| `backfill_clean_dates.py` | One-time PG backfill: 114 shipments, 177 fields normalized (Excel serials, format soup, midnight) |
| `patch_sync_guard.py` | csl_sheet_sync.py: TOLEAD_BOVIET_SYNCABLE_FIELDS + sheet_synced_at stamp + syncable_fields param + Tolead/Boviet use _merge not _upsert + PG trigger trg_shipments_updated_at + cron bumped */10→*/3 |
| `patch_writeback.py` | csl_sheet_sync.py: _a1() + _batch_writeback() helpers + Tolead LAX + all Boviet tabs write PG edits back to sheet when updated_at > sheet_synced_at |
| `boviet_invoice_writer.py` | New script: Fills Boviet Piedra Invoice tab — MP stop times→G/I/L/N + detention calc→J/O. PM heuristic for bare time strings. Cron: every 2 hrs 6AM-8PM Mon-Fri |
| `patch_status_writeback.py` | app.py: Add BackgroundTasks + _write_fields_to_master_sheet() to v2 status endpoint for non-shared accounts (fixes status revert bug) |
| `patch_daily_report_html.py` | dray_daily_summary.py: Fix Outlook email HTML — rgba→solid borders, div→table wrapper, cellpadding/cellspacing, font-family |
| `patch_ai_tools_v2.py` | ai_assistant.py: 12 new Ask AI tools (Tier 2-4), MAX_TOOL_ITERATIONS 4→5, MAX_RESPONSE_TOKENS 1024→2048, _clean_efj() helper |
| `patch_margin_bridge.py` | app.py: customer_rate/carrier_pay serialization + rate-quotes/apply-rate endpoints + auto-reject competing quotes |
| `patch_ai_extraction_v2.py` | csl_inbox_scanner.py: Expanded body window, improved prompts, linehaul/accessorials/confidence fields |
| `patch_noreply_fix.py` | csl_inbox_scanner.py: Fix unreplied email alerts — self-filter, EFJ dedup, 4hr cap, lane fallback |
| `patch_alert_subject.py` | csl_ftl_alerts.py: "FTL Alert"→"CSL Tracking" email subject rename |
| `patch_archive_distance_guard.py` | ftl_monitor.py + app.py: Block false D1 archive when distance_to_stop > 15mi |
| `patch_rep_scoreboard.py` | app.py: GET /api/rep-scoreboard — unreplied threads, avg response time, stale quotes, neglected loads |
| `patch_rep_scoreboard_v2.py` | app.py: Added loads_7d, revenue_7d, docs_needed to scoreboard + migration batch guard |
| `fix_scoreboard_db.py` | app.py: Fix DB access pattern (get_db→database._pool) in rep-scoreboard endpoint |
| `patch_revenue_backfill.py` | One-time XLS→PG backfill of customer_rate from commission report (596 shipments, $12M) |
| `patch_inbox_rep_filter.py` | app.py: Enrich /api/inbox threads with rep from shipments JOIN, fix rep_filter |
| `patch_port_groups.py` | app.py: /api/port-groups + /api/rate-history + search-lane port group expansion + apply-rate→lane_rates |
| `port_groups.py` | New module: 18 port/rail group dictionary + normalize_to_port_group() + reverse lookup |
| `patch_rev_window.py` | app.py: Expand REV scoreboard to all active loads (remove 7d filter) + total_margin in response |
| `patch_inbox_actions.py` | app.py: manual_rep + actioned columns on email_threads + PATCH assign-rep + mark-actioned endpoints |
| `patch_customer_rate_extraction.py` | csl_inbox_scanner.py: extract_rate_from_email handles customer_rate + rate_type field + rate_quotes column |
