#!/usr/bin/env python3
"""
patch_tolead_daily_summary.py — Update daily_summary.py to support all 4
Tolead hubs (ORD, JFK, LAX, DFW) instead of just ORD.
"""
import re

FILE = "/root/csl-bot/daily_summary.py"

with open(FILE, "r") as f:
    code = f.read()

# ── 1. Replace single Tolead config block with TOLEAD_HUBS list ─────────────
old_tolead_config = '''# Tolead config
TOLEAD_TAB        = "Schedule"
TOLEAD_SKIP_STATUSES = {"Delivered", "Canceled"}
TOLEAD_COL_ORD    = 1
TOLEAD_COL_DATE   = 4
TOLEAD_COL_ORIGIN = 6
TOLEAD_COL_DEST   = 7
TOLEAD_COL_STATUS = 9
TOLEAD_COL_EFJ    = 15'''

new_tolead_config = '''# Tolead config — all 4 hubs
TOLEAD_SKIP_STATUSES = {"Delivered", "Canceled", "Cancelled"}
TOLEAD_HUBS = [
    {
        "name": "ORD",
        "sheet_id": "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac",
        "tab": "Schedule",
        "col_load_id": 1, "col_date": 4, "col_origin": 6,
        "col_dest": 7, "col_status": 9, "col_efj": 15,
    },
    {
        "name": "JFK",
        "sheet_id": "1mfhEsK2zg6GWTqMDTo5VwCgY-QC1tkNPknurHMxtBhs",
        "tab": "Schedule",
        "col_load_id": 0, "col_date": 3, "col_origin": 6,
        "col_dest": 7, "col_status": 9, "col_efj": 14,
    },
    {
        "name": "LAX",
        "sheet_id": "1YLB6z5LdL0kFYTcfq_H5e6acU8-VLf8nN0XfZrJ-bXo",
        "tab": "LAX",
        "col_load_id": 3, "col_date": 4, "col_origin": None,
        "col_dest": 6, "col_status": 8, "col_efj": 0,
    },
    {
        "name": "DFW",
        "sheet_id": "1RfGcq25x4qshlBDWDJD-xBJDlJm6fvDM_w2RTHhn9oI",
        "tab": "DFW",
        "col_load_id": 4, "col_date": 5, "col_origin": None,
        "col_dest": 3, "col_status": 11, "col_efj": 10,
    },
]'''

assert old_tolead_config in code, "Could not find old Tolead config block"
code = code.replace(old_tolead_config, new_tolead_config)

# ── 2. Remove the single TOLEAD_SHEET_ID constant ──────────────────────────
code = code.replace('TOLEAD_SHEET_ID = "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac"\n', '')

# ── 3. Replace scan_tolead function ─────────────────────────────────────────
old_scan = '''def scan_tolead(creds, gc):
    print("\\n  -- Tolead Sheet --")
    try:
        ws = gc.open_by_key(TOLEAD_SHEET_ID).worksheet(TOLEAD_TAB)
        rows = ws.get_all_values()
        links = _get_hyperlinks(creds, TOLEAD_SHEET_ID, TOLEAD_TAB, TOLEAD_COL_EFJ)
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return {}

    entries = []
    for i, row in enumerate(rows[1:], start=2):  # skip header row
        if len(row) <= TOLEAD_COL_EFJ:
            continue
        status = _safe_get(row, TOLEAD_COL_STATUS)
        if status in TOLEAD_SKIP_STATUSES:
            continue
        mp_url = links[i - 1] if i - 1 < len(links) else ""
        if not mp_url or "macropoint" not in mp_url.lower():
            continue
        entries.append({
            "efj": _safe_get(row, TOLEAD_COL_EFJ),
            "load_id": _safe_get(row, TOLEAD_COL_ORD),
            "mp_url": mp_url,
            "pickup": _safe_get(row, TOLEAD_COL_DATE),
            "delivery": "",
            "origin": _safe_get(row, TOLEAD_COL_ORIGIN),
            "dest": _safe_get(row, TOLEAD_COL_DEST),
            "sheet_status": status,
        })

    if entries:
        print(f"    [Schedule] {len(entries)} tracked load(s)")
        return {"Schedule": {"entries": entries}}
    return {}'''

new_scan = '''def scan_tolead(creds, gc):
    """Scan all Tolead hubs (ORD, JFK, LAX, DFW)."""
    print("\\n  -- Tolead Sheets --")
    results = {}
    for hub in TOLEAD_HUBS:
        hub_name = hub["name"]
        sheet_id = hub["sheet_id"]
        tab = hub["tab"]
        col_efj = hub["col_efj"]
        time.sleep(1)
        try:
            ws = gc.open_by_key(sheet_id).worksheet(tab)
            rows = ws.get_all_values()
            links = _get_hyperlinks(creds, sheet_id, tab, col_efj)
        except Exception as exc:
            print(f"    [{hub_name}] ERROR: {exc}")
            continue

        entries = []
        for i, row in enumerate(rows[1:], start=2):  # skip header
            if len(row) <= col_efj:
                continue
            status = _safe_get(row, hub["col_status"])
            if status in TOLEAD_SKIP_STATUSES:
                continue
            mp_url = links[i - 1] if i - 1 < len(links) else ""
            if not mp_url or "macropoint" not in mp_url.lower():
                continue

            origin = _safe_get(row, hub["col_origin"]) if hub["col_origin"] is not None else ""
            entries.append({
                "efj": _safe_get(row, col_efj),
                "load_id": _safe_get(row, hub["col_load_id"]),
                "mp_url": mp_url,
                "pickup": _safe_get(row, hub["col_date"]),
                "delivery": "",
                "origin": origin,
                "dest": _safe_get(row, hub["col_dest"]),
                "sheet_status": status,
                "hub": hub_name,
            })

        if entries:
            print(f"    [{hub_name}/{tab}] {len(entries)} tracked load(s)")
            results[hub_name] = {"entries": entries, "tab": tab}

    return results'''

assert old_scan in code, "Could not find old scan_tolead function"
code = code.replace(old_scan, new_scan)

# ── 4. Replace Tolead section in run() to use hub names ─────────────────────
old_run_tolead = '''            # ── Tolead ───────────────────────────────────────────────
            tolead_data = scan_tolead(creds, gc)
            all_tolead_summaries = []
            for tab_name, data in tolead_data.items():
                entries = data["entries"]
                print(f"\\n    Scraping [{tab_name}] ({len(entries)} loads)...")
                summaries, skipped = scrape_and_summarize(browser, entries)
                if skipped:
                    print(f"    [{tab_name}] {skipped} load(s) skipped (scrape failed)")
                if not summaries:
                    print(f"    [{tab_name}] No actively tracking loads")
                    continue

                all_tolead_summaries.extend(summaries)

                subject = f"ORD Tolead Daily Summary \\u2014 {tab_name} \\u2014 {len(summaries)} Active"
                body = build_summary_body("ORD Tolead Daily Summary", tab_name, summaries, skipped=skipped)
                print(f"    [{tab_name}] {len(summaries)} active — sending to tolead-efj")
                _send_email("tolead-efj@evansdelivery.com", subject, body)

            if all_tolead_summaries:
                sync_state(TOLEAD_STATE_FILE, all_tolead_summaries, key_fmt="tolead")'''

new_run_tolead = '''            # ── Tolead (all hubs) ─────────────────────────────────────
            tolead_data = scan_tolead(creds, gc)
            all_tolead_summaries = []
            for hub_name, data in tolead_data.items():
                entries = data["entries"]
                tab = data["tab"]
                print(f"\\n    Scraping [{hub_name}/{tab}] ({len(entries)} loads)...")
                summaries, skipped = scrape_and_summarize(browser, entries)
                if skipped:
                    print(f"    [{hub_name}] {skipped} load(s) skipped (scrape failed)")
                if not summaries:
                    print(f"    [{hub_name}] No actively tracking loads")
                    continue

                all_tolead_summaries.extend(summaries)

                subject = f"{hub_name} Tolead Daily Summary \\u2014 {tab} \\u2014 {len(summaries)} Active"
                body = build_summary_body(f"{hub_name} Tolead Daily Summary", tab, summaries, skipped=skipped)
                print(f"    [{hub_name}] {len(summaries)} active — sending to tolead-efj")
                _send_email("tolead-efj@evansdelivery.com", subject, body)

            if all_tolead_summaries:
                sync_state(TOLEAD_STATE_FILE, all_tolead_summaries, key_fmt="tolead")'''

assert old_run_tolead in code, "Could not find old Tolead run() block"
code = code.replace(old_run_tolead, new_run_tolead)

# ── Write back ──────────────────────────────────────────────────────────────
with open(FILE, "w") as f:
    f.write(code)

print("Patched daily_summary.py:")
print("  - Added TOLEAD_HUBS with ORD/JFK/LAX/DFW configs")
print("  - scan_tolead() now iterates all 4 hubs")
print("  - Email subjects prefixed with hub name (ORD/JFK/LAX/DFW)")
print("  - LAX/DFW handle col_origin=None correctly")
