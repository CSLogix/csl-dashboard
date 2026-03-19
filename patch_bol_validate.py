#!/usr/bin/env python3
"""Fix: validate that BOL lookup returns actual container numbers, not error strings."""
import re

path = "/root/csl-bot/export_monitor.py"
with open(path, "r") as f:
    content = f.read()

OLD = '''            if containers:
                print(f"    BOL lookup: found containers {containers}")
                _bol_cache_set(booking_num, containers[0])
                return containers[0]'''

NEW = '''            if containers:
                # Filter out error strings like "Containers not yet assigned"
                real = [c for c in containers if re.match(r'^[A-Z]{4}\d{7}$', c.strip())]
                if real:
                    print(f"    BOL lookup: found containers {real}")
                    _bol_cache_set(booking_num, real[0])
                    return real[0]
                else:
                    print(f"    BOL lookup: no valid container# in response: {containers}")
                    _bol_cache_set(booking_num, None)
                    return None'''

if OLD in content:
    content = content.replace(OLD, NEW)
    with open(path, "w") as f:
        f.write(content)
    print("Patched: BOL lookup now validates container format")

    # Also clear the bad cache entry
    import subprocess
    subprocess.run(["python3", "-c", """
from csl_pg_writer import pg_jc_cache_set
# Overwrite the bad entry with not-found sentinel
pg_jc_cache_set("bol:267202035", "__notfound__")
print("Cleared bad cache entry for bol:267202035")
"""], cwd="/root/csl-bot")
else:
    print("WARNING: pattern not found")
