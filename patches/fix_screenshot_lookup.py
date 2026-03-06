#!/usr/bin/env python3
"""
Patch: Fix screenshot API endpoint to handle key mismatches.

When the tracking cache is keyed by container number (CSNU8670992) but the
dashboard requests by EFJ number (EFJ107093), this patch adds a fallback
that checks the tracking cache for a reverse mapping.
"""
import re

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

OLD = '''@app.get("/api/macropoint/{efj}/screenshot")
async def get_macropoint_screenshot(efj: str):
    """Serve a cached Macropoint tracking screenshot."""
    screenshot_path = f"/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.png"
    if not os.path.exists(screenshot_path):
        return JSONResponse(status_code=404, content={"error": "no screenshot"})
    import json as _json
    meta_path = f"/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.json"
    headers = {"Cache-Control": "max-age=300"}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = _json.load(f)
        headers["X-Captured-At"] = meta.get("captured_at", "")
    return FileResponse(screenshot_path, media_type="image/png", headers=headers)'''

NEW = '''@app.get("/api/macropoint/{efj}/screenshot")
async def get_macropoint_screenshot(efj: str):
    """Serve a cached Macropoint tracking screenshot.

    Tries direct filename match first, then checks the tracking cache for
    reverse mapping (e.g. EFJ107093 → CSNU8670992 or vice versa).
    """
    import json as _json
    _mp_dir = "/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots"
    _cache_file = "/root/csl-bot/ftl_tracking_cache.json"

    # Try direct match first
    screenshot_path = os.path.join(_mp_dir, f"{efj}.png")

    # Fallback: reverse lookup in tracking cache
    if not os.path.exists(screenshot_path):
        alt_key = None
        try:
            with open(_cache_file) as f:
                _tc = _json.load(f)
            # Check if any cache entry's load_num matches the requested efj
            for k, v in _tc.items():
                if v.get("load_num") == efj or k == efj:
                    alt_key = k if k != efj else v.get("load_num")
                    break
            # Also try bare number match: EFJ107230 → key "107230"
            if not alt_key and efj.startswith("EFJ") and efj[3:].isdigit():
                bare = efj[3:]
                if bare in _tc:
                    alt_key = bare
        except Exception:
            pass
        if alt_key:
            alt_path = os.path.join(_mp_dir, f"{alt_key}.png")
            if os.path.exists(alt_path):
                screenshot_path = alt_path

    if not os.path.exists(screenshot_path):
        return JSONResponse(status_code=404, content={"error": "no screenshot"})

    meta_path = screenshot_path.replace(".png", ".json")
    headers = {"Cache-Control": "max-age=300"}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = _json.load(f)
        headers["X-Captured-At"] = meta.get("captured_at", "")
    return FileResponse(screenshot_path, media_type="image/png", headers=headers)'''

with open(APP_PY) as f:
    code = f.read()

if OLD not in code:
    print("ERROR: Could not find old screenshot endpoint code")
    print("Searching for partial match...")
    if '@app.get("/api/macropoint/{efj}/screenshot")' in code:
        print("  Found the route decorator — code may have changed slightly")
    else:
        print("  Route not found at all!")
    exit(1)

code = code.replace(OLD, NEW)

with open(APP_PY, "w") as f:
    f.write(code)

print("Patched screenshot endpoint with reverse-lookup fallback")
