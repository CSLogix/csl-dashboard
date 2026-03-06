#!/usr/bin/env python3
"""Fix: Add phone/dest to boviet_monitor.py to_process items."""

TARGET = "/root/csl-bot/boviet_monitor.py"

with open(TARGET, "r") as f:
    src = f.read()

old = '''                    to_process.append({
                        "sheet_row": i + 1,
                        "efj":       efj,
                        "load_id":   load_id,
                        "pickup":    pickup,
                        "delivery":  delivery,
                        "status":    status,
                        "mp_url":    mp_url,
                        "tab_name":  tab_name,
                    })'''

new = '''                    phone = _safe_get(row, cfg.get("phone_col", -1)) if cfg.get("phone_col") is not None else ""
                    dest_val = delivery  # Use delivery location as destination
                    to_process.append({
                        "sheet_row": i + 1,
                        "efj":       efj,
                        "load_id":   load_id,
                        "pickup":    pickup,
                        "delivery":  delivery,
                        "status":    status,
                        "mp_url":    mp_url,
                        "tab_name":  tab_name,
                        "phone":     phone,
                        "dest":      dest_val,
                    })'''

if old in src:
    src = src.replace(old, new)
    print("  + Added phone/dest to to_process items")
else:
    print("  ! Could not find to_process.append block")

with open(TARGET, "w") as f:
    f.write(src)

print(f"  Patched: {TARGET}")
