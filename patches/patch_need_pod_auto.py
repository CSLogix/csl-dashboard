#!/usr/bin/env python3
"""
patch_need_pod_auto.py
Patches ftl_monitor.py to auto-transition loads to "Need POD" status
when Macropoint tracking shows "Tracking Completed Successfully".

Also stores mp_status (Macropoint tracking status like "Tracking Now",
"Driver Phone Unresponsive", etc.) in the tracking cache for dashboard use.

Run: python3 /tmp/patch_need_pod_auto.py
"""
import re

FILE = "/root/csl-bot/ftl_monitor.py"

with open(FILE) as f:
    code = f.read()

changes = 0

# ══════════════════════════════════════════════════════════════════════════
# 1) Store mp_status in tracking cache (the raw Macropoint Load Status)
# ══════════════════════════════════════════════════════════════════════════
# The tracking cache write happens in update_tracking_cache() or save_tracking_cache()
# We need to make sure mp_status is written alongside status, mp_load_id, etc.

if '"mp_status"' in code:
    print("mp_status already in code — skipping cache field addition")
else:
    # Find where tracking cache entries are built. Look for the pattern that
    # sets "status" in the cache entry dict
    # Common pattern: cache[key] = { "efj": ..., "status": status, ... }
    # or entry["status"] = status

    # Try to find the update_tracking_cache function or wherever cache entries are built
    if "def update_tracking_cache" in code:
        # Add mp_status parameter to the function signature
        old_sig_pattern = r'def update_tracking_cache\((.*?)\):'
        match = re.search(old_sig_pattern, code, re.DOTALL)
        if match:
            old_sig = match.group(0)
            params = match.group(1)
            if "mp_status" not in params:
                new_params = params.rstrip() + ", mp_status=None"
                new_sig = f"def update_tracking_cache({new_params}):"
                code = code.replace(old_sig, new_sig, 1)

                # Also add mp_status to the cache entry dict
                # Look for the cache entry assignment
                if '"macropoint_url"' in code:
                    # Add mp_status after macropoint_url in the dict
                    code = code.replace(
                        '"macropoint_url": url,',
                        '"macropoint_url": url,\n        "mp_status": mp_status or "",',
                        1
                    )
                elif '"last_scraped"' in code:
                    code = code.replace(
                        '"last_scraped":',
                        '"mp_status": mp_status or "",\n        "last_scraped":',
                        1
                    )
                changes += 1
                print("Added mp_status to update_tracking_cache")
        else:
            print("WARNING: Could not parse update_tracking_cache signature")
    else:
        # Fallback: try to add mp_status to wherever the cache dict is built
        print("WARNING: update_tracking_cache not found — mp_status not added to cache")

# ══════════════════════════════════════════════════════════════════════════
# 2) Capture Macropoint Load Status text during scraping
# ══════════════════════════════════════════════════════════════════════════
# The scraper reads the load detail page. We need to find where it extracts
# status and also capture the "Load Status" text (Tracking Now, etc.)
# This varies by implementation — look for patterns like:
#   - page.locator("...Load Status...")
#   - "tracking_status" or "load_status" variable

if "mp_load_status" in code or "mp_status_text" in code:
    print("MP Load Status capture already exists — skipping")
else:
    # Look for where status is extracted from the Macropoint page
    # Common pattern: status = page.locator(...).text_content()
    # Try to find the scraping section and inject mp_status capture

    # Look for pattern where update_tracking_cache is called
    update_call_pattern = r'update_tracking_cache\([^)]+\)'
    matches = list(re.finditer(update_call_pattern, code))

    if matches:
        for m in matches:
            old_call = m.group(0)
            if "mp_status" not in old_call:
                # Add mp_status parameter to the call
                new_call = old_call.rstrip(")")
                new_call += ", mp_status=mp_load_status)"
                code = code.replace(old_call, new_call, 1)

        # Now add mp_load_status variable extraction before the first call
        # Look for where cant_make_it is determined (it's near the status scrape)
        if "cant_make_it" in code and "mp_load_status" not in code:
            # Add mp_load_status extraction near cant_make_it
            cant_make_anchor = re.search(r'cant_make_it\s*=', code)
            if cant_make_anchor:
                insert_pos = cant_make_anchor.start()
                # Find the start of the line
                line_start = code.rfind('\n', 0, insert_pos) + 1
                indent = ' ' * (insert_pos - line_start)
                mp_status_code = f'''{indent}# Extract Macropoint Load Status text (Tracking Now, Unresponsive, etc.)
{indent}mp_load_status = ""
{indent}try:
{indent}    ls_el = page.locator('[data-testid="load-status"], .load-status-text, h3:has-text("Load Status") + span, h3:has-text("Load Status") + div').first
{indent}    if ls_el.count() > 0:
{indent}        mp_load_status = (ls_el.text_content() or "").strip()
{indent}except Exception:
{indent}    pass
'''
                code = code[:line_start] + mp_status_code + code[line_start:]
                changes += 1
                print("Added Macropoint Load Status capture")
    else:
        print("WARNING: No update_tracking_cache calls found")

# ══════════════════════════════════════════════════════════════════════════
# 3) Auto-transition: Tracking Completed → Need POD
# ══════════════════════════════════════════════════════════════════════════
if "Need POD" in code:
    print("Need POD auto-transition already exists — skipping")
else:
    # Find where status updates are written to the Google Sheet
    # Pattern: ws.update_cell(row_number, STATUS_COL, ...)
    # Or where delivered status is detected

    # Look for the section where alerts are sent after status change detection
    # We want to add a check after status is determined

    # Try to find where the sheet status write happens
    # Usually near: "Delivered" status handling or at the end of the per-load loop

    # Find the alert sending logic (send_email or similar)
    alert_pattern = re.search(r'(if\s+.*"[Dd]elivered".*:)', code)

    if alert_pattern:
        insert_pos = alert_pattern.start()
        line_start = code.rfind('\n', 0, insert_pos) + 1
        indent = ' ' * (insert_pos - line_start)

        need_pod_code = f'''
{indent}# Auto-transition: Tracking Completed → Need POD
{indent}if mp_load_status and "tracking completed" in mp_load_status.lower():
{indent}    current_status = (row_data.get("status") or "").strip().lower() if isinstance(row_data, dict) else ""
{indent}    if current_status not in ("need pod", "pod received", "pod rc'd", "driver paid"):
{indent}        try:
{indent}            ws.update_cell(row_number, STATUS_COL + 1, "Need POD")
{indent}            log.info("Auto-status: %s -> Need POD (tracking completed)", efj)
{indent}        except Exception as e:
{indent}            log.warning("Failed to auto-status %s to Need POD: %s", efj, e)

'''
        code = code[:line_start] + need_pod_code + code[line_start:]
        changes += 1
        print("Added Need POD auto-transition logic")
    else:
        # Alternative: add at the end of the per-load processing loop
        # Look for where tracking cache is saved/updated
        save_pattern = re.search(r'save_tracking_cache\(', code)
        if save_pattern:
            insert_pos = save_pattern.start()
            line_start = code.rfind('\n', 0, insert_pos) + 1
            indent = ' ' * (insert_pos - line_start)

            need_pod_code = f'''
{indent}# Auto-transition: Tracking Completed → Need POD
{indent}if mp_load_status and "tracking completed" in mp_load_status.lower():
{indent}    sheet_status = (status or "").strip().lower()
{indent}    if sheet_status not in ("need pod", "pod received", "pod rc'd", "driver paid"):
{indent}        try:
{indent}            ws.update_cell(row_idx, 13, "Need POD")
{indent}            log.info("Auto-status: %s -> Need POD (tracking completed)", efj)
{indent}        except Exception as e:
{indent}            log.warning("Failed to auto-status %s to Need POD: %s", efj, e)

'''
            code = code[:line_start] + need_pod_code + code[line_start:]
            changes += 1
            print("Added Need POD auto-transition logic (near save_tracking_cache)")
        else:
            print("WARNING: Could not find suitable insertion point for Need POD logic")
            print("         You may need to manually add this to ftl_monitor.py")

# ══════════════════════════════════════════════════════════════════════════
# Write
# ══════════════════════════════════════════════════════════════════════════
with open(FILE, "w") as f:
    f.write(code)

print(f"\n{'=' * 60}")
print(f"Applied {changes} changes to ftl_monitor.py")
print("Restart service: systemctl restart csl-ftl")
