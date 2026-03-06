#!/usr/bin/env python3
"""
Patch: Fix DFW in daily_summary.py

1. Update DFW hub config with phone/trailer/delivery_date columns
2. Fix scan_tolead to use E+J logic for DFW (same as tolead_monitor)
3. Collect DFW "Needs to Cover" loads (E populated, J not scheduled, no MP)
4. Add orange "Needs to Cover" section to DFW daily summary email
5. Set DFW default origin to "Irving, TX"
"""

TARGET = "/root/csl-bot/daily_summary.py"

with open(TARGET, "r") as f:
    src = f.read()


# ── 1. Update DFW hub config ────────────────────────────────────────────────

old_dfw_cfg = '''        "name": "DFW",
        "sheet_id": "1RfGcq25x4qshlBDWDJD-xBJDlJm6fvDM_w2RTHhn9oI",
        "tab": "DFW",
        "col_load_id": 4, "col_date": 5, "col_origin": None,
        "col_dest": 3, "col_status": 11, "col_efj": 10,
    },'''

new_dfw_cfg = '''        "name": "DFW",
        "sheet_id": "1RfGcq25x4qshlBDWDJD-xBJDlJm6fvDM_w2RTHhn9oI",
        "tab": "DFW",
        "col_load_id": 4, "col_date": 5, "col_origin": None,
        "col_dest": 3, "col_status": 11, "col_efj": 10,
        "col_phone": 13, "col_trailer": 12, "col_delivery_date": 2,
        "col_loads_j": 9, "default_origin": "Irving, TX",
    },'''

if old_dfw_cfg in src:
    src = src.replace(old_dfw_cfg, new_dfw_cfg)
    print("  + Updated DFW hub config in daily_summary.py")
else:
    print("  ! Could not find DFW hub config")


# ── 2. Fix scan_tolead to handle DFW E+J logic + collect Needs to Cover ──

old_scan_loop = '''        entries = []
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
            results[hub_name] = {"entries": entries, "tab": tab}'''

new_scan_loop = '''        entries = []
        needs_cover = []  # DFW loads needing coverage
        for i, row in enumerate(rows[1:], start=2):  # skip header
            if len(row) <= col_efj:
                continue
            status = _safe_get(row, hub["col_status"])
            load_id_val = _safe_get(row, hub["col_load_id"])

            # DFW: derive status from E (LINE#) + J (Loads)
            if hub_name == "DFW":
                if not load_id_val:
                    continue
                if status and status in TOLEAD_SKIP_STATUSES:
                    continue
                col_j = _safe_get(row, hub.get("col_loads_j", 9))
                if col_j.lower() not in ("scheduled", "picked"):
                    # E populated + J not scheduled = needs covering
                    dest = _safe_get(row, hub["col_dest"])
                    pickup = _safe_get(row, hub["col_date"])
                    phone = _safe_get(row, hub.get("col_phone", 13))
                    needs_cover.append({
                        "load_id": load_id_val,
                        "efj": _safe_get(row, col_efj),
                        "dest": dest,
                        "pickup": pickup,
                        "phone": phone,
                    })
                    continue
            else:
                if status in TOLEAD_SKIP_STATUSES:
                    continue

            mp_url = links[i - 1] if i - 1 < len(links) else ""
            if not mp_url or "macropoint" not in mp_url.lower():
                continue

            origin = _safe_get(row, hub["col_origin"]) if hub["col_origin"] is not None else ""
            if not origin and hub.get("default_origin"):
                origin = hub["default_origin"]
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

        tracked_count = len(entries)
        ntc_count = len(needs_cover)
        if entries or needs_cover:
            print(f"    [{hub_name}/{tab}] {tracked_count} tracked, {ntc_count} needs cover")
            results[hub_name] = {"entries": entries, "tab": tab, "needs_cover": needs_cover}'''

if old_scan_loop in src:
    src = src.replace(old_scan_loop, new_scan_loop)
    print("  + Fixed scan_tolead — DFW E+J logic + Needs to Cover collection")
else:
    print("  ! Could not find scan_tolead loop")


# ── 3. Add "Needs to Cover" section builder ─────────────────────────────────
# Add an orange section for uncovered loads

ntc_section_fn = '''
_O = "#e65100"  # Orange for Needs to Cover

def _build_needs_cover_section(needs_cover):
    """Build orange 'Needs to Cover' section for DFW daily summary."""
    if not needs_cover:
        return ""
    hdrs = ["LINE #", "EFJ #", "Destination", "Pickup Date", "Driver Phone"]
    hdr_cells = "".join(f'<th {_TH}>{h}</th>' for h in hdrs)
    rows_html = ""
    for i, item in enumerate(needs_cover):
        alt = i % 2 == 1
        bg = ' style="background:#f9f9f9;"' if alt else ""
        efj_display = item["efj"] or "&mdash;"
        phone_display = item["phone"] or "(not assigned)"
        rows_html += (
            f'<tr{bg}>'
            f'<td {_TD}><b>{item["load_id"]}</b></td>'
            f'<td {_TD}>{efj_display}</td>'
            f'<td {_TD}>{item["dest"]}</td>'
            f'<td {_TD}>{item["pickup"]}</td>'
            f'<td {_TD}>{phone_display}</td>'
            f'</tr>'
        )
    return (
        f'<div style="background:{_O};color:white;padding:8px 14px;'
        f'border-radius:6px 6px 0 0;font-size:15px;margin-top:20px;">'
        f"<b>Needs to Cover ({len(needs_cover)})</b></div>"
        f'<table style="border-collapse:collapse;width:100%;border:1px solid #ddd;border-top:none;">'
        f'<tr style="background:{_O};">{hdr_cells}</tr>'
        f'{rows_html}</table>'
    )

'''

# Insert before the _G/_R/_P color constants
anchor = '_G = "#1b5e20"'
if "_build_needs_cover_section" not in src:
    src = src.replace(anchor, ntc_section_fn + anchor)
    print("  + Added _build_needs_cover_section() for DFW")
else:
    print("  ~ _build_needs_cover_section already exists")


# ── 4. Update Tolead email sending to include Needs to Cover section ─────────

old_tolead_send = '''            for hub_name, data in tolead_data.items():
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
                _send_email("tolead-efj@evansdelivery.com", subject, body)'''

new_tolead_send = '''            for hub_name, data in tolead_data.items():
                entries = data["entries"]
                tab = data["tab"]
                needs_cover = data.get("needs_cover", [])
                print(f"\\n    Scraping [{hub_name}/{tab}] ({len(entries)} loads)...")
                summaries, skipped = scrape_and_summarize(browser, entries)
                if skipped:
                    print(f"    [{hub_name}] {skipped} load(s) skipped (scrape failed)")
                if not summaries and not needs_cover:
                    print(f"    [{hub_name}] No actively tracking loads")
                    continue

                all_tolead_summaries.extend(summaries)

                total_active = len(summaries) + len(needs_cover)
                subject = f"{hub_name} Tolead Daily Summary \\u2014 Schedule \\u2014 {total_active} Active"
                body = build_summary_body(f"{hub_name} Tolead Daily Summary", "Schedule", summaries, skipped=skipped)
                # Append Needs to Cover section for DFW
                if needs_cover:
                    ntc_html = _build_needs_cover_section(needs_cover)
                    body = body.replace("</div>\\n", ntc_html + "</div>\\n", 1) if "</div>\\n" in body else body[:-6] + ntc_html + "</div>"
                print(f"    [{hub_name}] {len(summaries)} tracked + {len(needs_cover)} needs cover — sending to tolead-efj")
                _send_email("tolead-efj@evansdelivery.com", subject, body)'''

if old_tolead_send in src:
    src = src.replace(old_tolead_send, new_tolead_send)
    print("  + Updated Tolead email — includes Needs to Cover + 'Schedule' tab name")
else:
    print("  ! Could not find Tolead email sending block")


with open(TARGET, "w") as f:
    f.write(src)

print(f"\n  Patched: {TARGET}")
print("  Done.")
