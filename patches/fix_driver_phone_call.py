#!/usr/bin/env python3
"""Add the missing scrape_driver_phone() call before update_tracking_cache."""

FILE = "/root/csl-bot/ftl_monitor.py"

with open(FILE) as f:
    code = f.read()

# The update_tracking_cache call has driver_phone=driver_phone, but we need
# to define driver_phone before it. Insert the scrape block before update_tracking_cache.

anchor = '''                update_tracking_cache(
                    row["efj"], row["load_num"], status,
                    mp_load_id, cant_make_it, stop_times,
                    row["url"], tracking_cache,
                    driver_phone=driver_phone,
                )'''

if "driver_phone = scrape_driver_phone(" in code:
    print("scrape_driver_phone call already present — skipping")
elif anchor in code:
    replacement = '''                # Try to get driver's tracking phone from authenticated MP portal
                driver_phone = None
                if mp_load_id and mp_cookies:
                    driver_phone = scrape_driver_phone(
                        browser, mp_load_id, row["load_num"], mp_cookies
                    )

                update_tracking_cache(
                    row["efj"], row["load_num"], status,
                    mp_load_id, cant_make_it, stop_times,
                    row["url"], tracking_cache,
                    driver_phone=driver_phone,
                )'''
    code = code.replace(anchor, replacement)
    with open(FILE, "w") as f:
        f.write(code)
    print("Added scrape_driver_phone call before update_tracking_cache")
else:
    print("ERROR: Cannot find update_tracking_cache call anchor")

# Verify syntax
import py_compile
try:
    py_compile.compile(FILE, doraise=True)
    print("✅ Syntax OK")
except py_compile.PyCompileError as e:
    print(f"❌ Syntax error: {e}")
