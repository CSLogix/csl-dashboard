#!/usr/bin/env python3
"""
Patch: Universalize skip-status filtering across all scripts.
- Make all status checks case-insensitive
- Fix TOLEAD_SKIP_STATUSES "CANCELLED" typo in app.py
- Ensure FTL, Boviet, and Tolead all consistently skip Delivered/Cancelled
"""

import os

fixes = []

# ═══════════════════════════════════════════════════════════════════════════
# 1. app.py — Fix TOLEAD_SKIP_STATUSES case + make hub loop case-insensitive
# ═══════════════════════════════════════════════════════════════════════════

APP = "/root/csl-bot/csl-doc-tracker/app.py"
with open(APP, "r") as f:
    src = f.read()

# Fix the CANCELLED typo
old_ts = 'TOLEAD_SKIP_STATUSES = {"Delivered", "Canceled", "CANCELLED"}'
new_ts = 'TOLEAD_SKIP_STATUSES = {"delivered", "canceled", "cancelled"}'

if old_ts in src:
    src = src.replace(old_ts, new_ts)
    fixes.append("app.py: Fixed TOLEAD_SKIP_STATUSES (lowercase, fixed CANCELLED)")
else:
    # Try current form
    if "CANCELLED" in src.split("TOLEAD_SKIP_STATUSES")[1][:60] if "TOLEAD_SKIP_STATUSES" in src else False:
        fixes.append("app.py: ! TOLEAD_SKIP_STATUSES has CANCELLED but pattern differs")
    else:
        fixes.append("app.py: ~ TOLEAD_SKIP_STATUSES already fixed or different")

# Make all Tolead hub status checks case-insensitive
# DFW block
old_dfw_skip = '''                    if hub_name == "DFW":
                        if not load_id:
                            continue
                        if status and status in TOLEAD_SKIP_STATUSES:'''
new_dfw_skip = '''                    if hub_name == "DFW":
                        if not load_id:
                            continue
                        if status and status.lower() in TOLEAD_SKIP_STATUSES:'''
if old_dfw_skip in src:
    src = src.replace(old_dfw_skip, new_dfw_skip)
    fixes.append("app.py: DFW status check now case-insensitive")

# ORD block
old_ord_skip = '''                    elif hub_name == "ORD":
                        if not load_id:
                            continue
                        if status and status in TOLEAD_SKIP_STATUSES:'''
new_ord_skip = '''                    elif hub_name == "ORD":
                        if not load_id:
                            continue
                        if status and status.lower() in TOLEAD_SKIP_STATUSES:'''
if old_ord_skip in src:
    src = src.replace(old_ord_skip, new_ord_skip)
    fixes.append("app.py: ORD status check now case-insensitive")

# LAX block
old_lax_skip = '''                    elif hub_name == "LAX":
                        if not load_id:
                            continue
                        if status and status in TOLEAD_SKIP_STATUSES:'''
new_lax_skip = '''                    elif hub_name == "LAX":
                        if not load_id:
                            continue
                        if status and status.lower() in TOLEAD_SKIP_STATUSES:'''
if old_lax_skip in src:
    src = src.replace(old_lax_skip, new_lax_skip)
    fixes.append("app.py: LAX status check now case-insensitive")

# JFK block
old_jfk_skip = '''                    elif hub_name == "JFK":
                        if not load_id:
                            continue
                        if status and status in TOLEAD_SKIP_STATUSES:'''
new_jfk_skip = '''                    elif hub_name == "JFK":
                        if not load_id:
                            continue
                        if status and status.lower() in TOLEAD_SKIP_STATUSES:'''
if old_jfk_skip in src:
    src = src.replace(old_jfk_skip, new_jfk_skip)
    fixes.append("app.py: JFK status check now case-insensitive")

# Also make Boviet check case-insensitive
old_bov_check = 'if not efj or status in BOVIET_DONE_STATUSES:'
new_bov_check = 'if not efj or status.lower() in {s.lower() for s in BOVIET_DONE_STATUSES}:'
if old_bov_check in src:
    # Better: just lowercase the set definition
    old_bov_set = 'BOVIET_DONE_STATUSES = {"Delivered", "Completed", "Canceled", "Cancelled", "Ready to Close"}'
    new_bov_set = 'BOVIET_DONE_STATUSES = {"delivered", "completed", "canceled", "cancelled", "ready to close"}'
    if old_bov_set in src:
        src = src.replace(old_bov_set, new_bov_set)
        src = src.replace(old_bov_check, 'if not efj or status.lower() in BOVIET_DONE_STATUSES:')
        fixes.append("app.py: BOVIET_DONE_STATUSES now lowercase + case-insensitive check")

with open(APP, "w") as f:
    f.write(src)


# ═══════════════════════════════════════════════════════════════════════════
# 2. daily_summary.py — Make all skip checks case-insensitive
# ═══════════════════════════════════════════════════════════════════════════

DS = "/root/csl-bot/daily_summary.py"
with open(DS, "r") as f:
    src2 = f.read()

# Lowercase the skip sets
for old_set, new_set, label in [
    ('FTL_SKIP_STATUSES = {"Delivered", "Completed", "Canceled", "Ready to Close"}',
     'FTL_SKIP_STATUSES = {"delivered", "completed", "canceled", "ready to close"}',
     "FTL_SKIP_STATUSES"),
    ('BOVIET_SKIP_STATUSES = {"Delivered", "Completed", "Canceled", "Cancelled", "Ready to Close"}',
     'BOVIET_SKIP_STATUSES = {"delivered", "completed", "canceled", "cancelled", "ready to close"}',
     "BOVIET_SKIP_STATUSES"),
    ('TOLEAD_SKIP_STATUSES = {"Delivered", "Canceled", "Cancelled"}',
     'TOLEAD_SKIP_STATUSES = {"delivered", "canceled", "cancelled"}',
     "TOLEAD_SKIP_STATUSES"),
]:
    if old_set in src2:
        src2 = src2.replace(old_set, new_set)
        fixes.append(f"daily_summary.py: {label} now lowercase")

# Make the status checks case-insensitive
old_ftl_check = 'if status in FTL_SKIP_STATUSES:'
new_ftl_check = 'if status.lower() in FTL_SKIP_STATUSES:'
if old_ftl_check in src2:
    src2 = src2.replace(old_ftl_check, new_ftl_check)
    fixes.append("daily_summary.py: FTL status check case-insensitive")

old_bov_ds_check = 'if status in BOVIET_SKIP_STATUSES:'
new_bov_ds_check = 'if status.lower() in BOVIET_SKIP_STATUSES:'
if old_bov_ds_check in src2:
    src2 = src2.replace(old_bov_ds_check, new_bov_ds_check)
    fixes.append("daily_summary.py: Boviet status check case-insensitive")

old_tol_ds_check = 'if status and status in TOLEAD_SKIP_STATUSES:'
new_tol_ds_check = 'if status and status.lower() in TOLEAD_SKIP_STATUSES:'
if old_tol_ds_check in src2:
    src2 = src2.replace(old_tol_ds_check, new_tol_ds_check)
    fixes.append("daily_summary.py: Tolead status check case-insensitive")

with open(DS, "w") as f:
    f.write(src2)


# ═══════════════════════════════════════════════════════════════════════════
# 3. boviet_monitor.py — Make status checks case-insensitive
# ═══════════════════════════════════════════════════════════════════════════

BOV = "/root/csl-bot/boviet_monitor.py"
with open(BOV, "r") as f:
    src3 = f.read()

old_bov_skip = 'SKIP_STATUSES = {"Delivered", "Completed", "Canceled", "Cancelled", "Ready to Close"}'
new_bov_skip = 'SKIP_STATUSES = {"delivered", "completed", "canceled", "cancelled", "ready to close"}'
if old_bov_skip in src3:
    src3 = src3.replace(old_bov_skip, new_bov_skip)
    fixes.append("boviet_monitor.py: SKIP_STATUSES now lowercase")

# Fix all exact-case status checks
old_bov_status_check = 'if status in SKIP_STATUSES:'
new_bov_status_check = 'if status.lower() in SKIP_STATUSES:'
count = src3.count(old_bov_status_check)
if count > 0:
    src3 = src3.replace(old_bov_status_check, new_bov_status_check)
    fixes.append(f"boviet_monitor.py: {count} status check(s) now case-insensitive")

with open(BOV, "w") as f:
    f.write(src3)


# ═══════════════════════════════════════════════════════════════════════════
# Print summary
# ═══════════════════════════════════════════════════════════════════════════

print()
for f in fixes:
    print(f"  + {f}")
print(f"\n  Patched: {APP}, {DS}, {BOV}")
print("  Done. Restart csl-dashboard, csl-boviet.")
