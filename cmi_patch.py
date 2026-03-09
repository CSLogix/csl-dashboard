"""Patch ftl_monitor.py and tolead_monitor.py — add CAN'T MAKE IT detection."""
import re

# ═══════════════════════════════════════════════════════════════════════════
# PATCH ftl_monitor.py
# ═══════════════════════════════════════════════════════════════════════════
path = "/root/csl-bot/ftl_monitor.py"
with open(path) as f:
    code = f.read()
with open(path + ".pre-cmi", "w") as f:
    f.write(code)

# 1) Add cant_make_it detection after stop2_planned_start line
code = code.replace(
    '    stop2_planned_start = _find_planned_start(stop2_text)             if stop2_text else None\n\n    # Extract Macropoint Load ID',
    """    stop2_planned_start = _find_planned_start(stop2_text)             if stop2_text else None

    # Detect "CAN'T MAKE IT" in stop sections
    _cmi_stops = []
    if stop1_text and re.search(r"CAN['\u2019]?T\\s+MAKE\\s+IT", stop1_text, re.I):
        _cmi_stops.append("Stop 1 (Pickup)")
    if stop2_text and re.search(r"CAN['\u2019]?T\\s+MAKE\\s+IT", stop2_text, re.I):
        _cmi_stops.append("Stop 2 (Delivery)")
    cant_make_it = " & ".join(_cmi_stops) if _cmi_stops else None

    # Extract Macropoint Load ID""",
)

# 2) Add cant_make_it to every return in _parse_macropoint
#    Every return ends with ", mp_load_id" — append ", cant_make_it"
#    But only inside _parse_macropoint (before the scrape_macropoint function)
marker_start = "def _parse_macropoint("
marker_end = "\n# ── Playwright scraper"
start_i = code.index(marker_start)
end_i = code.index(marker_end)
func_body = code[start_i:end_i]
func_body = func_body.replace(", mp_load_id\n", ", mp_load_id, cant_make_it\n")
code = code[:start_i] + func_body + code[end_i:]

# 3) Update scrape_macropoint error returns from 6-None to 7-None
code = code.replace(
    "        return None, None, None, None, None, None\n    finally:",
    "        return None, None, None, None, None, None, None\n    finally:",
)
# Second error return
code = code.replace(
    "        return None, None, None, None, None, None\n\n    if DEBUG:",
    "        return None, None, None, None, None, None, None\n\n    if DEBUG:",
)

# 4) Update unpacking in run_once
code = code.replace(
    "                status, stop1_date, stop2_date, stop1_planned, stop2_planned, mp_load_id = (\n                    scrape_macropoint(browser, row[\"url\"])\n                )",
    "                status, stop1_date, stop2_date, stop1_planned, stop2_planned, mp_load_id, cant_make_it = (\n                    scrape_macropoint(browser, row[\"url\"])\n                )",
)

# 5) Add CAN'T MAKE IT alert block after the normal alert block
code = code.replace(
    '                    mark_sent(sent, key, status)\n\n                # Queue for archiving after all rows processed',
    """                    mark_sent(sent, key, status)

                # ── CAN'T MAKE IT alert ──────────────────────────────────
                if cant_make_it:
                    cmi_status = f"Can't Make It - {cant_make_it}"
                    if not already_sent(sent, key, cmi_status):
                        print(f"    CAN'T MAKE IT detected: {cant_make_it}")
                        send_ftl_email(row["efj"], row["load_num"], cmi_status, tab_name, account_lookup, mp_load_id=mp_load_id)
                        mark_sent(sent, key, cmi_status)

                # Queue for archiving after all rows processed""",
)

with open(path, "w") as f:
    f.write(code)
print(f"Patched {path}")

# ═══════════════════════════════════════════════════════════════════════════
# PATCH tolead_monitor.py
# ═══════════════════════════════════════════════════════════════════════════
path2 = "/root/csl-bot/tolead_monitor.py"
with open(path2) as f:
    code2 = f.read()
with open(path2 + ".pre-cmi", "w") as f:
    f.write(code2)

# 1) Update unpacking in run_once
code2 = code2.replace(
    "                mp_status, stop1_arrived, stop2_departed, _, _, mp_load_id = scrape_macropoint(browser, mp_url)",
    "                mp_status, stop1_arrived, stop2_departed, _, _, mp_load_id, cant_make_it = scrape_macropoint(browser, mp_url)",
)

# 2) Add CAN'T MAKE IT alert after the normal alert block
code2 = code2.replace(
    "                mark_sent(sent, alert_key, mp_status)\n                changes += 1\n\n        finally:",
    """                mark_sent(sent, alert_key, mp_status)
                changes += 1

                # ── CAN'T MAKE IT alert ──────────────────────────────────
                if cant_make_it:
                    cmi_status = f"Can't Make It - {cant_make_it}"
                    if not already_sent(sent, alert_key, cmi_status):
                        print(f"    CAN'T MAKE IT detected: {cant_make_it}")
                        send_tolead_alert(ord_num, efj, cmi_status, dest, pickup_date, mp_load_id)
                        mark_sent(sent, alert_key, cmi_status)
                        changes += 1

        finally:""",
)

# 3) Also handle cant_make_it when mp_status is None (load could have no main status but still show CAN'T MAKE IT)
code2 = code2.replace(
    """                if not mp_status:
                    print("    No status detected")
                    continue""",
    """                if not mp_status and not cant_make_it:
                    print("    No status detected")
                    continue""",
)

# 4) Update dry-run print to show cant_make_it
code2 = code2.replace(
    '                        print(f"    Result: status={result[0]}, stop1={result[1]}, stop2={result[2]}, mp_load={result[5]}")',
    '                        print(f"    Result: status={result[0]}, stop1={result[1]}, stop2={result[2]}, mp_load={result[5]}, cmi={result[6]}")',
)

with open(path2, "w") as f:
    f.write(code2)
print(f"Patched {path2}")
print("Done.")
