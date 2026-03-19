#!/usr/bin/env python3
"""Fix BOL cache to use Postgres-backed functions instead of _load_jc_cache/_save_jc_cache."""

path = "/root/csl-bot/export_monitor.py"
with open(path, "r") as f:
    content = f.read()

OLD = '''_BOL_CACHE_TTL = 7 * 24 * 3600   # 7 days -- container# never changes for a BOL
_BOL_NOTFOUND_TTL = 4 * 3600     # 4h -- retry "not found" less aggressively

def _bol_cache_get(booking_num):
    """BOL lookups use longer TTL than container tracking."""
    cache = _load_jc_cache()
    entry = cache.get(f"bol:{booking_num}")
    if not entry:
        return None, False
    age = _time_mod.time() - entry.get("ts", 0)
    data = entry.get("data")
    if data is None:
        # "not found" entry -- use shorter TTL
        if age < _BOL_NOTFOUND_TTL:
            return None, True  # cached miss
        return None, False     # expired miss
    if age < _BOL_CACHE_TTL:
        return data, True      # cached hit
    return None, False         # expired hit

def _bol_cache_set(booking_num, data):
    """Cache BOL result (or None for not-found)."""
    cache = _load_jc_cache()
    cache[f"bol:{booking_num}"] = {"ts": _time_mod.time(), "data": data}
    cutoff = _time_mod.time() - 8 * 24 * 3600  # prune entries older than 8 days
    cache = {k: v for k, v in cache.items() if v.get("ts", 0) > cutoff}
    _save_jc_cache(cache)'''

NEW = '''_BOL_CACHE_TTL = 7 * 24 * 3600   # 7 days -- container# never changes for a BOL
_BOL_NOTFOUND_TTL = 4 * 3600     # 4h -- retry "not found" less aggressively

def _bol_cache_get(booking_num):
    """BOL lookups use longer TTL than container tracking (Postgres-backed)."""
    # Try long TTL first (found results cached 7 days)
    result = pg_jc_cache_get(f"bol:{booking_num}", _BOL_CACHE_TTL)
    if result is not None:
        if result == "__notfound__":
            # Check if not-found entry is within shorter TTL
            fresh = pg_jc_cache_get(f"bol:{booking_num}", _BOL_NOTFOUND_TTL)
            if fresh is not None:
                return None, True   # cached miss, still fresh
            return None, False      # expired miss
        return result, True         # cached hit
    return None, False              # no cache entry

def _bol_cache_set(booking_num, data):
    """Cache BOL result (or sentinel for not-found) in Postgres."""
    pg_jc_cache_set(f"bol:{booking_num}", data if data else "__notfound__")'''

if OLD in content:
    content = content.replace(OLD, NEW)
    with open(path, "w") as f:
        f.write(content)
    print("Patched: BOL cache now uses Postgres-backed functions")
else:
    print("WARNING: BOL cache block not found verbatim")
    # Debug: check if parts exist
    if "_load_jc_cache" in content:
        print("  _load_jc_cache still referenced")
    if "_bol_cache_get" in content:
        print("  _bol_cache_get exists")
