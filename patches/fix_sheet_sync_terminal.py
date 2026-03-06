#!/usr/bin/env python3
"""
Fix csl_sheet_sync.py to skip completed/delivered/cancelled rows during import.
Prevents the sync from re-importing terminal loads that were archived in Postgres.
"""
import shutil, datetime, sys

TARGET = "/root/csl-bot/csl-doc-tracker/csl_sheet_sync.py"
BAK = TARGET + f".bak_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

shutil.copy2(TARGET, BAK)
print(f"Backup: {BAK}")

with open(TARGET, "r") as f:
    src = f.read()

# First, undo the broken sed edits
# Fix the mangled TERMINAL_STATUSES line
src = src.replace(
    '# Statuses that mean the load is done — skip importing these from sheets'
    'TERMINAL_STATUSES = {"completed", "ready to close", "delivered", "cancelled", "billed_closed"}',
    '',
    1
)
# Fix mangled Tolead filter
src = src.replace(
    'if status.lower() in TERMINAL_STATUSES:                    continue',
    '',
)

changes = 0

# 1. Add TERMINAL_STATUSES constant after SYNC_INTERVAL line
anchor1 = 'SYNC_INTERVAL = 600  # 10 minutes\n'
if anchor1 in src:
    src = src.replace(
        anchor1,
        'SYNC_INTERVAL = 600  # 10 minutes\n\n'
        '# Statuses that mean the load is done — skip importing these from sheets\n'
        'TERMINAL_STATUSES = {"completed", "ready to close", "delivered", "cancelled", "billed_closed"}\n',
        1
    )
    changes += 1
    print("[1/3] Added TERMINAL_STATUSES constant")
else:
    print("[1/3] SKIP: Could not find SYNC_INTERVAL anchor")

# 2. Add skip in Tolead sync — after "if not load_id: continue"
anchor2 = '                if not load_id:\n                    continue\n\n                key = efj or load_id'
if anchor2 in src:
    src = src.replace(
        anchor2,
        '                if not load_id:\n'
        '                    continue\n'
        '                if status.lower() in TERMINAL_STATUSES:\n'
        '                    continue\n\n'
        '                key = efj or load_id',
        1
    )
    changes += 1
    print("[2/3] Added terminal status skip in Tolead sync")
else:
    print("[2/3] SKIP: Could not find Tolead anchor")

# 3. Add skip in Boviet sync — after "if not efj: continue"
anchor3 = '                if not efj:\n                    continue\n\n                bov_pickup'
if anchor3 in src:
    src = src.replace(
        anchor3,
        '                if not efj:\n'
        '                    continue\n'
        '                if status.lower() in TERMINAL_STATUSES:\n'
        '                    continue\n\n'
        '                bov_pickup',
        1
    )
    changes += 1
    print("[3/3] Added terminal status skip in Boviet sync")
else:
    print("[3/3] SKIP: Could not find Boviet anchor")

with open(TARGET, "w") as f:
    f.write(src)

print(f"\nDone — {changes}/3 patches applied to {TARGET}")
if changes < 3:
    print("WARNING: Not all patches applied. Check anchors manually.")
    sys.exit(1)
