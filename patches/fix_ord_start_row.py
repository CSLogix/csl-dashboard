#!/usr/bin/env python3
"""Fix: ORD sheet starts reading from row 773 onward (skip old history)."""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

old_line = '            for ri, row in enumerate(rows[1:], start=1):\n                def tol_cell(idx):'
new_line = '            for ri, row in enumerate(rows[772:], start=772):  # Start at row 773\n                def tol_cell(idx):'

assert old_line in code, "ERROR: Could not find Tolead ORD enumerate line"
code = code.replace(old_line, new_line, 1)
print("[1/1] ORD sheet now starts at row 773")

with open(APP, "w") as f:
    f.write(code)

print("Done! Restart: systemctl restart csl-dashboard")
