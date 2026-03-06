#!/usr/bin/env python3
"""
patch_atomic_state_writes.py
Adds atomic write pattern to state file saves in monitors that lack it.

Prevents state file corruption from crashes mid-write, which causes
dedup records to reset → duplicate email alerts.

Pattern: write to .tmp file, then os.replace() (atomic on Linux).
Also adds .bak backup before overwriting.

Applies to: csl_bot.py, export_monitor.py, tolead_monitor.py
Does NOT touch: boviet_monitor.py, ftl_monitor.py (already has atomic writes)

Run: python3 /tmp/patch_atomic_state_writes.py
"""
import os

TARGETS = {
    # ── csl_bot.py: save_last_check() ──
    "/root/csl-bot/csl_bot.py": {
        "old": '''\
def save_last_check(data):
    """Persist the current state dict to disk."""
    try:
        with open(LAST_CHECK_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        print(f"  WARNING: Could not save {LAST_CHECK_FILE}: {exc}")\
''',
        "new": '''\
def save_last_check(data):
    """Persist the current state dict to disk (atomic write)."""
    try:
        import shutil
        if os.path.exists(LAST_CHECK_FILE):
            shutil.copy2(LAST_CHECK_FILE, LAST_CHECK_FILE + ".bak")
        tmp = LAST_CHECK_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, LAST_CHECK_FILE)
    except Exception as exc:
        print(f"  WARNING: Could not save {LAST_CHECK_FILE}: {exc}")\
''',
        "label": "save_last_check() in csl_bot.py",
    },
    # ── export_monitor.py: save_state() ──
    "/root/csl-bot/export_monitor.py": {
        "old": '''\
def save_state(data):
    try:
        with open(STATE_FILE, "w") as f: json.dump(data, f, indent=2)
    except Exception as e: print(f"  WARNING: {e}")\
''',
        "new": '''\
def save_state(data):
    try:
        import shutil
        if os.path.exists(STATE_FILE):
            shutil.copy2(STATE_FILE, STATE_FILE + ".bak")
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception as e: print(f"  WARNING: {e}")\
''',
        "label": "save_state() in export_monitor.py",
    },
    # ── tolead_monitor.py: save_sent_alerts() ──
    "/root/csl-bot/tolead_monitor.py": {
        "old": '''\
def save_sent_alerts(data: dict):
    with open(SENT_ALERTS_FILE, "w") as f:
        json.dump(data, f, indent=2)\
''',
        "new": '''\
def save_sent_alerts(data: dict):
    import shutil
    if os.path.exists(SENT_ALERTS_FILE):
        shutil.copy2(SENT_ALERTS_FILE, SENT_ALERTS_FILE + ".bak")
    tmp = SENT_ALERTS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, SENT_ALERTS_FILE)\
''',
        "label": "save_sent_alerts() in tolead_monitor.py",
    },
}

total = 0
for filepath, spec in TARGETS.items():
    if not os.path.exists(filepath):
        print(f"[SKIP] {filepath} not found")
        continue
    with open(filepath) as f:
        code = f.read()
    if spec["old"] in code:
        code = code.replace(spec["old"], spec["new"], 1)
        with open(filepath, "w") as f:
            f.write(code)
        total += 1
        print(f"[OK] Patched {spec['label']}")
    elif "os.replace" in code and spec["label"].split("(")[0] in code:
        print(f"[SKIP] {spec['label']} — already has atomic writes")
    else:
        print(f"[WARN] Could not find exact match in {filepath} — check manually")

print(f"\n{'=' * 60}")
print(f"Applied {total} atomic write patches")
if total > 0:
    print("Restart affected services:")
    print("  systemctl restart csl-import csl-export csl-tolead")
