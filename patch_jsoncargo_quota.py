#!/usr/bin/env python3
"""
Patch: Reduce JsonCargo API quota usage across csl_bot.py and export_monitor.py.

Changes:
1. Shared cache TTL: 6h -> 12h (both scripts share jsoncargo_cache.json)
2. BOL lookup results cached for 7 days (container# doesn't change)
3. BOL "not found" cached for 4h (avoid retrying every hour)
4. Export monitor: skip API calls outside business hours (6 AM - 10 PM ET)
"""
import shutil
from datetime import datetime

def patch_file(path, replacements):
    with open(path, 'r') as f:
        content = f.read()
    original = content
    for old, new in replacements:
        if old not in content:
            print(f"  WARNING: pattern not found in {path}:")
            print(f"    {repr(old[:80])}...")
            continue
        content = content.replace(old, new)
        print(f"  Patched: {old[:60].strip()}...")
    if content != original:
        backup = path + f'.pre-quota-{datetime.now().strftime("%Y%m%d")}'
        shutil.copy2(path, backup)
        print(f"  Backup: {backup}")
        with open(path, 'w') as f:
            f.write(content)
        print(f"  Written: {path}")
    else:
        print(f"  No changes needed for {path}")

# ── Patch 1: Shared cache TTL 6h -> 12h (csl_bot.py) ──
print("\n=== Patching csl_bot.py ===")
patch_file("/root/csl-bot/csl_bot.py", [
    ('_JSONCARGO_CACHE_TTL = 6 * 3600',
     '_JSONCARGO_CACHE_TTL = 12 * 3600  # 12h to reduce API quota usage'),
])

# ── Patch 2: export_monitor.py — multiple changes ──
print("\n=== Patching export_monitor.py ===")

with open("/root/csl-bot/export_monitor.py", 'r') as f:
    content = f.read()
backup = "/root/csl-bot/export_monitor.py.pre-quota-" + datetime.now().strftime("%Y%m%d")
shutil.copy2("/root/csl-bot/export_monitor.py", backup)
print(f"  Backup: {backup}")

# 2a: Cache TTL 6h -> 12h
content = content.replace(
    '_JSONCARGO_CACHE_TTL = 6 * 3600',
    '_JSONCARGO_CACHE_TTL = 12 * 3600  # 12h to reduce API quota usage'
)
print("  Patched: cache TTL 6h -> 12h")

# 2b: Replace jsoncargo_bol_lookup with cached version
OLD_BOL = (
    'def jsoncargo_bol_lookup(booking_num, ssl_line):\n'
    '    cached = _jc_cache_get(f"bol:{booking_num}")\n'
    '    if cached is not None:\n'
    '        print(f"    BOL lookup: cache hit for {booking_num}")\n'
    '        return cached\n'
    '    try:\n'
    '        url=f"{JSONCARGO_BASE}/containers/bol/{booking_num}/"\n'
    '        resp=requests.get(url,headers={"x-api-key":JSONCARGO_API_KEY},\n'
    '                         params={"shipping_line":ssl_line},timeout=20)\n'
    '        data=resp.json()\n'
    '        if "data" in data:\n'
    '            containers=data["data"].get("associated_container_numbers",[])\n'
    '            if containers:\n'
    '                print(f"    BOL lookup: found containers {containers}")\n'
    '                _jc_cache_set(f"bol:{booking_num}", containers[0])\n'
    '                return containers[0]\n'
    '        print(f"    BOL lookup: {data.get(\'error\',{}).get(\'title\',\'no result\')}")\n'
    '        return None\n'
    '    except Exception as e:\n'
    '        print(f"    BOL lookup error: {e}"); return None'
)

NEW_BOL = (
    '_BOL_CACHE_TTL = 7 * 24 * 3600   # 7 days -- container# never changes for a BOL\n'
    '_BOL_NOTFOUND_TTL = 4 * 3600     # 4h -- retry "not found" less aggressively\n'
    '\n'
    'def _bol_cache_get(booking_num):\n'
    '    """BOL lookups use longer TTL than container tracking."""\n'
    '    cache = _load_jc_cache()\n'
    '    entry = cache.get(f"bol:{booking_num}")\n'
    '    if not entry:\n'
    '        return None, False\n'
    '    age = _time_mod.time() - entry.get("ts", 0)\n'
    '    data = entry.get("data")\n'
    '    if data is None:\n'
    '        # "not found" entry -- use shorter TTL\n'
    '        if age < _BOL_NOTFOUND_TTL:\n'
    '            return None, True  # cached miss\n'
    '        return None, False     # expired miss\n'
    '    if age < _BOL_CACHE_TTL:\n'
    '        return data, True      # cached hit\n'
    '    return None, False         # expired hit\n'
    '\n'
    'def _bol_cache_set(booking_num, data):\n'
    '    """Cache BOL result (or None for not-found)."""\n'
    '    cache = _load_jc_cache()\n'
    '    cache[f"bol:{booking_num}"] = {"ts": _time_mod.time(), "data": data}\n'
    '    cutoff = _time_mod.time() - 8 * 24 * 3600  # prune entries older than 8 days\n'
    '    cache = {k: v for k, v in cache.items() if v.get("ts", 0) > cutoff}\n'
    '    _save_jc_cache(cache)\n'
    '\n'
    'def jsoncargo_bol_lookup(booking_num, ssl_line):\n'
    '    result, cached = _bol_cache_get(booking_num)\n'
    '    if cached:\n'
    '        if result:\n'
    '            print(f"    BOL lookup: cache hit for {booking_num} -> {result}")\n'
    '        else:\n'
    '            print(f"    BOL lookup: cached not-found for {booking_num} (skip)")\n'
    '        return result\n'
    '    try:\n'
    '        url=f"{JSONCARGO_BASE}/containers/bol/{booking_num}/"\n'
    '        resp=requests.get(url,headers={"x-api-key":JSONCARGO_API_KEY},\n'
    '                         params={"shipping_line":ssl_line},timeout=20)\n'
    '        data=resp.json()\n'
    '        if "data" in data:\n'
    '            containers=data["data"].get("associated_container_numbers",[])\n'
    '            if containers:\n'
    '                print(f"    BOL lookup: found containers {containers}")\n'
    '                _bol_cache_set(booking_num, containers[0])\n'
    '                return containers[0]\n'
    '        err_msg = data.get(\'error\',{}).get(\'title\',\'no result\')\n'
    '        print(f"    BOL lookup: {err_msg}")\n'
    '        # Cache the miss so we do not retry every hour\n'
    '        if "rate limit" not in err_msg.lower():\n'
    '            _bol_cache_set(booking_num, None)\n'
    '        return None\n'
    '    except Exception as e:\n'
    '        print(f"    BOL lookup error: {e}"); return None'
)

if OLD_BOL in content:
    content = content.replace(OLD_BOL, NEW_BOL)
    print("  Patched: BOL lookup with 7-day cache + not-found cache")
else:
    print("  WARNING: BOL lookup function not found verbatim -- trying flexible match")
    # Try to find it by the def line
    if 'def jsoncargo_bol_lookup(' in content:
        print("  Function exists but doesn't match exactly. Manual edit needed.")
    else:
        print("  Function not found at all!")

# 2c: Add business hours check
OLD_RUN = (
    'def run_once():\n'
    '    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")\n'
    '    print(f"\\n[{now_str}] Export poll cycle (Postgres mode)...")'
)

NEW_RUN = (
    'def _is_business_hours():\n'
    '    """Check if current time is within API call window (6 AM - 10 PM ET)."""\n'
    '    hour = datetime.now(ZoneInfo("America/New_York")).hour\n'
    '    return 6 <= hour < 22\n'
    '\n'
    'def run_once():\n'
    '    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")\n'
    '    print(f"\\n[{now_str}] Export poll cycle (Postgres mode)...")'
)

if OLD_RUN in content:
    content = content.replace(OLD_RUN, NEW_RUN)
    print("  Patched: added _is_business_hours()")
else:
    print("  WARNING: run_once header not matched")

# 2d: Gate API calls with business hours
OLD_SSL = (
    '            # Resolve SSL line\n'
    '            ssl_line = _resolve_ssl_export(vessel, carrier)\n'
    '            if not ssl_line:\n'
    '                print(f"    SSL line not detected for {vessel}/{carrier} - skipping API")\n'
    '                continue'
)

NEW_SSL = (
    '            # Resolve SSL line\n'
    '            ssl_line = _resolve_ssl_export(vessel, carrier)\n'
    '            if not ssl_line:\n'
    '                print(f"    SSL line not detected for {vessel}/{carrier} - skipping API")\n'
    '                continue\n'
    '\n'
    '            # Skip API calls outside business hours (6 AM - 10 PM ET)\n'
    '            if not _is_business_hours():\n'
    '                print(f"    Outside business hours - skipping API call")\n'
    '                continue'
)

if OLD_SSL in content:
    content = content.replace(OLD_SSL, NEW_SSL)
    print("  Patched: business hours gate on API calls")
else:
    print("  WARNING: SSL check block not matched")

with open("/root/csl-bot/export_monitor.py", 'w') as f:
    f.write(content)
print("  Written: /root/csl-bot/export_monitor.py")

print("\n=== DONE ===")
print("Estimated monthly API call savings:")
print("  BOL lookups: ~1330 -> ~50 (7-day cache + 4h not-found cache)")
print("  Container tracks: ~50% fewer (12h cache vs 6h)")
print("  Night hours: ~33% fewer calls (10 PM - 6 AM skipped)")
print("  Projected total: ~800-1000/month (was ~3900)")
