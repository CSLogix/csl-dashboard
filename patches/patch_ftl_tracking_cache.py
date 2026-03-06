#!/usr/bin/env python3
"""
patch_ftl_tracking_cache.py
Patches ftl_monitor.py to write a tracking cache JSON after each scrape.
The dashboard reads this file for detailed stop times, ETAs, and alerts.

Run: python3 /tmp/patch_ftl_tracking_cache.py
"""
import re

FILE = "/root/csl-bot/ftl_monitor.py"

with open(FILE) as f:
    code = f.read()

changes = 0

# ── 1) Add TRACKING_CACHE_FILE constant ──────────────────────────────────
if "TRACKING_CACHE_FILE" in code:
    print("[1] TRACKING_CACHE_FILE already defined — skipping")
else:
    anchor = 'SENT_ALERTS_FILE = "/root/csl-bot/ftl_sent_alerts.json"'
    if anchor not in code:
        print("ERROR: Cannot find SENT_ALERTS_FILE constant")
        exit(1)
    code = code.replace(
        anchor,
        anchor + '\nTRACKING_CACHE_FILE = "/root/csl-bot/ftl_tracking_cache.json"',
    )
    changes += 1
    print("[1] Added TRACKING_CACHE_FILE constant")

# ── 2) Add cache helper functions after mark_sent ────────────────────────
if "def load_tracking_cache" in code:
    print("[2] load_tracking_cache already defined — skipping")
else:
    # Insert after mark_sent function (before the comment about EFJ Pro alert)
    anchor = "# ── EFJ Pro alert"
    if anchor not in code:
        # Fallback: insert after mark_sent function
        anchor = "def mark_sent(sent: dict, key: str, status: str):"
        idx = code.index(anchor)
        # Find the end of mark_sent (next blank line followed by def or comment)
        block_end = re.search(r'\n\n(?=def |# ──)', code[idx:])
        if block_end:
            insert_pos = idx + block_end.start()
        else:
            print("ERROR: Cannot find end of mark_sent function")
            exit(1)
    else:
        insert_pos = code.index(anchor)

    cache_funcs = '''
# ── Tracking cache (for dashboard) ──────────────────────────────────────
def load_tracking_cache() -> dict:
    """Load the tracking cache from disk."""
    try:
        with open(TRACKING_CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_tracking_cache(cache: dict):
    """Atomically write tracking cache to disk."""
    tmp = TRACKING_CACHE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, TRACKING_CACHE_FILE)


def update_tracking_cache(efj: str, load_num: str, status, mp_load_id,
                          cant_make_it, stop_times: dict, url: str, cache: dict):
    """Update a single load entry in the tracking cache dict."""
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")
    cache[efj] = {
        "efj": efj,
        "load_num": load_num,
        "status": status,
        "mp_load_id": mp_load_id,
        "cant_make_it": cant_make_it,
        "stop_times": stop_times or {},
        "macropoint_url": url,
        "last_scraped": now,
    }


'''
    code = code[:insert_pos] + cache_funcs + code[insert_pos:]
    changes += 1
    print("[2] Added tracking cache helper functions")

# ── 3) Load cache at the start of each poll cycle ────────────────────────
if "tracking_cache = load_tracking_cache()" in code:
    print("[3] tracking_cache load already present — skipping")
else:
    anchor = "    sent = load_sent_alerts()"
    if anchor not in code:
        print("ERROR: Cannot find 'sent = load_sent_alerts()'")
        exit(1)
    code = code.replace(
        anchor,
        anchor + "\n    tracking_cache = load_tracking_cache()",
    )
    changes += 1
    print("[3] Added tracking_cache load at poll start")

# ── 4) Update cache after each row is scraped ────────────────────────────
if "update_tracking_cache(row[" in code:
    print("[4] update_tracking_cache call already present — skipping")
else:
    # Find the print statement that shows scrape results, then insert after it
    # The print is a multi-line f-string ending with mp_load_id
    anchor = '                    f"  |  mp_load_id={mp_load_id!r}"'
    if anchor not in code:
        # Try without the specific spacing
        m = re.search(r'mp_load_id=\{mp_load_id!r\}"\s*\n\s*\)', code)
        if m:
            insert_pos = m.end()
        else:
            print("ERROR: Cannot find mp_load_id print statement")
            exit(1)
    else:
        idx = code.index(anchor) + len(anchor)
        # Find the closing paren of the print
        next_paren = code.index(")", idx)
        insert_pos = next_paren + 1

    # Find the next newline
    next_nl = code.index("\n", insert_pos)

    cache_update = """
                update_tracking_cache(
                    row["efj"], row["load_num"], status,
                    mp_load_id, cant_make_it, stop_times,
                    row["url"], tracking_cache,
                )
"""
    code = code[:next_nl + 1] + cache_update + code[next_nl + 1:]
    changes += 1
    print("[4] Added update_tracking_cache call after each scrape")

# ── 5) Save cache before browser.close() ────────────────────────────────
if "save_tracking_cache(tracking_cache)" in code:
    print("[5] save_tracking_cache call already present — skipping")
else:
    anchor = "        browser.close()"
    if anchor not in code:
        print("ERROR: Cannot find browser.close()")
        exit(1)
    code = code.replace(
        anchor,
        "        save_tracking_cache(tracking_cache)\n" + anchor,
    )
    changes += 1
    print("[5] Added save_tracking_cache before browser.close()")

with open(FILE, "w") as f:
    f.write(code)

print(f"\n✅ ftl_monitor.py patched ({changes} changes)")
print("   Cache file: /root/csl-bot/ftl_tracking_cache.json")
print("   Restart: systemctl restart csl-ftl")
