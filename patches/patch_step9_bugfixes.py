"""Step 9: Bug fixes - webhook port + tolead NoneType."""

# --- Fix 1: Tolead NoneType bug ---
TOLEAD_FILE = '/root/csl-bot/tolead_monitor.py'

with open(TOLEAD_FILE, 'r') as f:
    code = f.read()

# The bug: status comes back as None, then .lower() crashes
# Fix: add `or ""` guard
# Look for the pattern where status is used with .lower()
import re

# Find patterns like: status.lower() or status.strip().lower()
# and add safety guards
fixes = 0

# Pattern 1: direct .lower() on status variable
old = 'status = row[COL_STATUS]'
if old in code:
    code = code.replace(old, 'status = row[COL_STATUS] if len(row) > COL_STATUS and row[COL_STATUS] else ""')
    fixes += 1

# Pattern 2: any .lower() on status without guard
# The skip check: if status in SKIP_STATUSES or status.lower() in ...
old2 = 'if status in SKIP_STATUSES'
if old2 in code:
    code = code.replace(old2, 'if not status or status in SKIP_STATUSES')
    fixes += 1

with open(TOLEAD_FILE, 'w') as f:
    f.write(code)

print(f"Fix 1: tolead_monitor.py NoneType guard added ({fixes} fixes)")


# --- Fix 2: Webhook port conflict ---
WEBHOOK_FILE = '/root/csl-bot/webhook.py'

with open(WEBHOOK_FILE, 'r') as f:
    wcode = f.read()

# Change port 5000 to 5002
if 'port=5000' in wcode or 'port = 5000' in wcode:
    wcode = wcode.replace('port=5000', 'port=5002')
    wcode = wcode.replace('port = 5000', 'port = 5002')
    wcode = re.sub(r"port\s*=\s*5000", "port=5002", wcode)
    with open(WEBHOOK_FILE, 'w') as f:
        f.write(wcode)
    print("Fix 2: webhook.py port changed 5000 -> 5002")
elif '5000' in wcode:
    wcode = wcode.replace("'5000'", "'5002'").replace('"5000"', '"5002"')
    with open(WEBHOOK_FILE, 'w') as f:
        f.write(wcode)
    print("Fix 2: webhook.py port string changed 5000 -> 5002")
else:
    print("Fix 2: WARNING - could not find port 5000 in webhook.py")

print("Step 9: Bug fixes complete")
