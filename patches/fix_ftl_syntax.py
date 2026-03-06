#!/usr/bin/env python3
"""Fix broken newlines in ftl_monitor.py comments and regex."""

FILE = "/root/csl-bot/ftl_monitor.py"

with open(FILE) as f:
    lines = f.readlines()

# Lines 398-402 (1-indexed) are broken. Replace them with 2 proper lines.
# 0-indexed: 397, 398, 399, 400, 401

new_lines = lines[:397]  # Keep lines 1-397

# Fixed comment line (line 398 replacement)
new_lines.append('            # "Tracking Phone\\n(443) 555-1234" or "Phone\\n+14435551234"\n')

# Fixed regex line (lines 401-402 replacement)
new_lines.append('            r"(?:Tracking\\s+)?Phone[:\\s]*\\n?\\s*(\\+?1?[\\s.-]?\\(?\\d{3}\\)?[\\s.-]?\\d{3}[\\s.-]?\\d{4})",\n')

# Continue from line 403 (0-indexed 402)
new_lines.extend(lines[402:])

with open(FILE, "w") as f:
    f.writelines(new_lines)

# Verify
with open(FILE) as f:
    verify_lines = f.readlines()

print(f"Lines: {len(lines)} -> {len(verify_lines)}")
print(f"Line 398: {repr(verify_lines[397])[:120]}")
print(f"Line 399: {repr(verify_lines[398])[:120]}")
print(f"Line 400: {repr(verify_lines[399])[:120]}")

# Quick syntax check
import py_compile
try:
    py_compile.compile(FILE, doraise=True)
    print("\n✅ Syntax OK")
except py_compile.PyCompileError as e:
    print(f"\n❌ Syntax error: {e}")
