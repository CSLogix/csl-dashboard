#!/usr/bin/env python3
"""
Fix csl_sheet_sync.py to skip completed/delivered/cancelled rows during import.
"""
import shutil, datetime, sys

TARGET = "/root/csl-bot/csl-doc-tracker/csl_sheet_sync.py"
BAK = TARGET + f".bak_terminal_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

shutil.copy2(TARGET, BAK)
print(f"Backup: {BAK}")

with open(TARGET, "r") as f:
    lines = f.readlines()

changes = 0

# 1. Add TERMINAL_STATUSES after SYNC_INTERVAL line
for i, line in enumerate(lines):
    if line.strip() == 'SYNC_INTERVAL = 600  # 10 minutes':
        lines.insert(i + 1, '\n')
        lines.insert(i + 2, '# Statuses that mean the load is done — skip importing these from sheets\n')
        lines.insert(i + 3, 'TERMINAL_STATUSES = {"completed", "ready to close", "delivered", "cancelled", "billed_closed"}\n')
        changes += 1
        print("[1/3] Added TERMINAL_STATUSES constant")
        break
else:
    print("[1/3] SKIP: Could not find SYNC_INTERVAL line")

# Re-read after insert
# 2. Add skip after "if not load_id: continue" in Tolead sync
for i, line in enumerate(lines):
    if 'if not load_id:' in line and i + 1 < len(lines) and 'continue' in lines[i + 1]:
        # Insert after the continue line
        indent = '                '
        lines.insert(i + 2, f'{indent}if status.lower() in TERMINAL_STATUSES:\n')
        lines.insert(i + 3, f'{indent}    continue\n')
        changes += 1
        print("[2/3] Added terminal status skip in Tolead sync")
        break
else:
    print("[2/3] SKIP: Could not find Tolead load_id check")

# 3. Add skip after "if not efj: continue" in Boviet sync
for i, line in enumerate(lines):
    if 'if not efj:' in line and i + 1 < len(lines) and 'continue' in lines[i + 1]:
        indent = '                '
        lines.insert(i + 2, f'{indent}if status.lower() in TERMINAL_STATUSES:\n')
        lines.insert(i + 3, f'{indent}    continue\n')
        changes += 1
        print("[3/3] Added terminal status skip in Boviet sync")
        break
else:
    print("[3/3] SKIP: Could not find Boviet efj check")

with open(TARGET, "w") as f:
    f.writelines(lines)

print(f"\nDone — {changes}/3 patches applied to {TARGET}")
if changes < 3:
    print("WARNING: Not all patches applied.")
    sys.exit(1)
