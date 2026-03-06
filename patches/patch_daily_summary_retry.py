#!/usr/bin/env python3
"""
Patch: Add quota retry + inter-tab delays to daily_summary.py

- Adds _retry_on_quota() helper with exponential backoff (30s / 60s / 120s)
- Increases inter-tab sleep from 1s to 3s in scan_ftl, scan_boviet, scan_tolead
- Wraps sheet reads (get_all_values + get_hyperlinks) in retry helper
"""
import re

TARGET = "/root/csl-bot/daily_summary.py"

with open(TARGET, "r") as f:
    src = f.read()

# ── 1. Add _retry_on_quota helper after _load_credentials ──────────────────

retry_fn = '''

def _retry_on_quota(fn, label="", max_retries=3, base_delay=30):
    """Retry on 429 quota errors with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if '429' in str(e) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"    Quota exceeded{' (' + label + ')' if label else ''}, "
                      f"retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                import time
                time.sleep(delay)
            else:
                raise

'''

# Insert after _load_credentials function
anchor = "def _safe_get(row, idx):"
if "_retry_on_quota" not in src:
    src = src.replace(anchor, retry_fn + anchor)
    print("  + Added _retry_on_quota() helper")
else:
    print("  ~ _retry_on_quota() already exists, skipping")


# ── 2. Increase inter-tab sleep from 1s to 3s ──────────────────────────────

# scan_ftl, scan_boviet, scan_tolead all have time.sleep(1) before each tab read
old_sleep = "        time.sleep(1)"
new_sleep = "        time.sleep(3)  # avoid quota spikes"
count = src.count(old_sleep)
if count > 0:
    src = src.replace(old_sleep, new_sleep)
    print(f"  + Increased inter-tab sleep 1s -> 3s ({count} occurrences)")
else:
    print("  ~ No time.sleep(1) found to replace")


# ── 3. Wrap scan_ftl sheet reads in retry ──────────────────────────────────

# Original pattern in scan_ftl:
#     ws = gc.open_by_key(FTL_SHEET_ID).worksheet(tab_name)
#     rows = ws.get_all_values()
#     links = _get_hyperlinks(creds, FTL_SHEET_ID, tab_name, FTL_HYPERLINK_COL)

old_ftl_read = '''            ws = gc.open_by_key(FTL_SHEET_ID).worksheet(tab_name)
            rows = ws.get_all_values()
            links = _get_hyperlinks(creds, FTL_SHEET_ID, tab_name, FTL_HYPERLINK_COL)'''

new_ftl_read = '''            ws = _retry_on_quota(
                lambda: gc.open_by_key(FTL_SHEET_ID).worksheet(tab_name),
                label=f"FTL/{tab_name}")
            rows = _retry_on_quota(
                lambda: ws.get_all_values(),
                label=f"FTL/{tab_name} values")
            links = _retry_on_quota(
                lambda: _get_hyperlinks(creds, FTL_SHEET_ID, tab_name, FTL_HYPERLINK_COL),
                label=f"FTL/{tab_name} hyperlinks")'''

if old_ftl_read in src:
    src = src.replace(old_ftl_read, new_ftl_read)
    print("  + Wrapped scan_ftl sheet reads in _retry_on_quota()")
else:
    print("  ! Could not find FTL sheet read pattern — check manually")


# ── 4. Wrap scan_boviet sheet reads in retry ───────────────────────────────

old_boviet_read = '''            ws = gc.open_by_key(BOVIET_SHEET_ID).worksheet(tab_name)
            rows = ws.get_all_values()
            links = _get_hyperlinks(creds, BOVIET_SHEET_ID, tab_name, BOVIET_HYPERLINK_COL)'''

new_boviet_read = '''            ws = _retry_on_quota(
                lambda: gc.open_by_key(BOVIET_SHEET_ID).worksheet(tab_name),
                label=f"Boviet/{tab_name}")
            rows = _retry_on_quota(
                lambda: ws.get_all_values(),
                label=f"Boviet/{tab_name} values")
            links = _retry_on_quota(
                lambda: _get_hyperlinks(creds, BOVIET_SHEET_ID, tab_name, BOVIET_HYPERLINK_COL),
                label=f"Boviet/{tab_name} hyperlinks")'''

if old_boviet_read in src:
    src = src.replace(old_boviet_read, new_boviet_read)
    print("  + Wrapped scan_boviet sheet reads in _retry_on_quota()")
else:
    print("  ! Could not find Boviet sheet read pattern — check manually")


# ── 5. Wrap scan_tolead sheet reads in retry ───────────────────────────────

old_tolead_read = '''            ws = gc.open_by_key(sheet_id).worksheet(tab)
            rows = ws.get_all_values()
            links = _get_hyperlinks(creds, sheet_id, tab, col_efj)'''

new_tolead_read = '''            ws = _retry_on_quota(
                lambda sid=sheet_id, t=tab: gc.open_by_key(sid).worksheet(t),
                label=f"Tolead/{hub_name}")
            rows = _retry_on_quota(
                lambda: ws.get_all_values(),
                label=f"Tolead/{hub_name} values")
            links = _retry_on_quota(
                lambda sid=sheet_id, t=tab, c=col_efj: _get_hyperlinks(creds, sid, t, c),
                label=f"Tolead/{hub_name} hyperlinks")'''

if old_tolead_read in src:
    src = src.replace(old_tolead_read, new_tolead_read)
    print("  + Wrapped scan_tolead sheet reads in _retry_on_quota()")
else:
    print("  ! Could not find Tolead sheet read pattern — check manually")


# ── 6. Also wrap Account Rep tab read in retry ────────────────────────────

old_acct_read = '''        ws = gc.open_by_key(FTL_SHEET_ID).worksheet("Account Rep")
        rows = ws.get_all_values()'''

new_acct_read = '''        ws = _retry_on_quota(
            lambda: gc.open_by_key(FTL_SHEET_ID).worksheet("Account Rep"),
            label="Account Rep")
        rows = _retry_on_quota(
            lambda: ws.get_all_values(),
            label="Account Rep values")'''

if old_acct_read in src:
    src = src.replace(old_acct_read, new_acct_read)
    print("  + Wrapped Account Rep tab read in _retry_on_quota()")
else:
    print("  ~ Account Rep read pattern not found (may already be patched)")


# ── Write result ────────────────────────────────────────────────────────────
with open(TARGET, "w") as f:
    f.write(src)

print(f"\n  Patch applied to {TARGET}")
print("  Done.")
