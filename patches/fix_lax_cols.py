#!/usr/bin/env python3
"""Fix LAX column mapping: status is col 8 (Loads), not col 1 (POD Status checkbox).
Also add CANCELLED to skip statuses."""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

# Fix LAX status column: 1 -> 8
old_lax = '''TOLEAD_LAX_COLS = {
    "efj": 0, "load_id": 3, "status": 1, "origin": None,
    "destination": 6, "pickup_date": 4, "pickup_time": 5,
    "delivery": 7, "driver": 10,
}'''

new_lax = '''TOLEAD_LAX_COLS = {
    "efj": 0, "load_id": 3, "status": 8, "origin": None,
    "destination": 6, "pickup_date": 4, "pickup_time": 5,
    "delivery": 7, "driver": 10,
}'''

assert old_lax in code, "ERROR: Could not find LAX cols block"
code = code.replace(old_lax, new_lax)
print("[1/2] Fixed LAX status column: 1 -> 8")

# Add CANCELLED to skip statuses
old_skip = 'TOLEAD_SKIP_STATUSES = {"Delivered", "Canceled"}'
new_skip = 'TOLEAD_SKIP_STATUSES = {"Delivered", "Canceled", "CANCELLED"}'

assert old_skip in code, "ERROR: Could not find TOLEAD_SKIP_STATUSES"
code = code.replace(old_skip, new_skip)
print("[2/2] Added CANCELLED to skip statuses")

with open(APP, "w") as f:
    f.write(code)

print("\nDone! Restart: systemctl restart csl-dashboard")
