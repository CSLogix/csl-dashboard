#!/usr/bin/env python3
"""Fix: Use ftl_tracking_cache macropoint_url as fallback when container_url is empty.

Two changes:
1. Remove the early 404 guard that rejects loads without container_url — instead check
   both container_url AND tracking cache macropoint_url before 404ing.
2. macropointUrl response field already patched to fall back to cached URL.
"""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP) as f:
    code = f.read()

# Fix 1: Replace the early 404 guard to also check tracking cache
old_guard = '''    if not shipment.get("container_url"):
        raise HTTPException(404, f"No Macropoint tracking for {efj}")'''

new_guard = '''    # Also check tracking cache for macropoint_url (FTL loads may not have sheet hyperlinks)
    _tracking_cache = _read_tracking_cache()
    _cached_url = _tracking_cache.get(efj, {}).get("macropoint_url", "")
    if not shipment.get("container_url") and not _cached_url:
        raise HTTPException(404, f"No Macropoint tracking for {efj}")'''

if old_guard not in code:
    if "_cached_url" in code.split("api_macropoint")[1].split("def ")[0]:
        print("SKIP: Guard already patched")
    else:
        print("ERROR: Could not find guard string to patch")
else:
    code = code.replace(old_guard, new_guard, 1)
    print("PATCHED: Guard now checks tracking cache URL too")

# Fix 2: Make macropointUrl fall back to cached.get("macropoint_url")
# (may already be applied from previous patch)
old_url = '''"macropointUrl": shipment.get("container_url", ""),'''
new_url = '''"macropointUrl": shipment.get("container_url", "") or cached.get("macropoint_url", ""),'''

if old_url in code:
    code = code.replace(old_url, new_url, 1)
    print("PATCHED: macropointUrl falls back to tracking cache URL")
elif 'cached.get("macropoint_url"' in code:
    print("SKIP: macropointUrl fallback already present")

with open(APP, "w") as f:
    f.write(code)

print("Done. Restart csl-dashboard to apply.")
