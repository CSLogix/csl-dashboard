#!/usr/bin/env python3
"""Fix: app.py — start_row patch broke indentation (for loop dropped out of try block)"""

TARGET = "/root/csl-bot/csl-doc-tracker/app.py"

with open(TARGET, "r") as f:
    src = f.read()

# The patch put hub_start at 16 spaces (correct) but for loop at 12 spaces (wrong)
# Also the continue swallowed def _cell

old = '''                hub_start = hub_cfg.get("start_row", 1)
            for ri, row in enumerate(hub_rows[1:], start=1):
                if ri + 1 < hub_start:  # ri is 1-indexed data row, hub_start is sheet row
                    continue
                    def _cell(idx, r=row):'''

new = '''                hub_start = hub_cfg.get("start_row", 1)
                for ri, row in enumerate(hub_rows[1:], start=1):
                    if ri + 1 < hub_start:
                        continue
                    def _cell(idx, r=row):'''

if old in src:
    src = src.replace(old, new)
    print("  + Fixed for loop indentation (back inside try block)")
else:
    print("  ! Could not find broken indentation block")

with open(TARGET, "w") as f:
    f.write(src)

print(f"\n  Patched: {TARGET}")
