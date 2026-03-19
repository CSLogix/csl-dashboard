#!/usr/bin/env python3
"""
backup_state.py — Backs up all CSL Bot state files to a timestamped directory.

Keeps the last 7 days of backups, pruning older ones automatically.
Cron: once daily at 5:30 AM ET (before monitors start)

    30 5 * * * cd /root/csl-bot && python3 backup_state.py >> /tmp/csl_backup.log 2>&1
"""
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
BACKUP_DIR = Path("/root/csl-bot/backups")
KEEP_DAYS = 7

STATE_FILES = [
    "/root/csl-bot/last_check.json",
    "/root/csl-bot/export_state.json",
    "/root/csl-bot/ftl_sent_alerts.json",
    "/root/csl-bot/ftl_tracking_cache.json",
    "/root/csl-bot/ftl_email_alerts.json",
    "/root/csl-bot/boviet_sent_alerts.json",
    "/root/csl-bot/tolead_sent_alerts.json",
    "/root/csl-bot/unresponsive_state.json",
    "/root/csl-bot/mp_cookies.json",
]


def backup():
    now = datetime.now(ET)
    stamp = now.strftime("%Y-%m-%d_%H%M")
    dest = BACKUP_DIR / stamp
    dest.mkdir(parents=True, exist_ok=True)

    print(f"[{now.strftime('%Y-%m-%d %H:%M ET')}] Backing up state files -> {dest}")

    backed = 0
    for path in STATE_FILES:
        src = Path(path)
        if not src.exists():
            print(f"  SKIP {src.name} (not found)")
            continue

        # Validate JSON before backing up
        try:
            with open(src) as f:
                json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  WARN {src.name} — corrupt JSON, backing up anyway: {e}")

        shutil.copy2(str(src), str(dest / src.name))
        size = src.stat().st_size
        print(f"  OK   {src.name} ({size:,} bytes)")
        backed += 1

    print(f"  {backed}/{len(STATE_FILES)} files backed up.")
    return dest


def prune():
    """Remove backup directories older than KEEP_DAYS."""
    if not BACKUP_DIR.exists():
        return

    now = datetime.now(ET)
    removed = 0
    for entry in sorted(BACKUP_DIR.iterdir()):
        if not entry.is_dir():
            continue
        # Parse directory name to get backup date
        try:
            dir_date = datetime.strptime(entry.name[:10], "%Y-%m-%d")
            age_days = (now.replace(tzinfo=None) - dir_date).days
            if age_days > KEEP_DAYS:
                shutil.rmtree(entry)
                print(f"  PRUNED {entry.name} ({age_days} days old)")
                removed += 1
        except ValueError:
            continue

    if removed:
        print(f"  Pruned {removed} old backup(s).")


def main():
    backup()
    prune()
    print("  Backup complete.")


if __name__ == "__main__":
    main()
