"""
cron_log_parser.py — Shared log parser for cron-based monitors.

Used by health_check.py and app.py /api/cron-status to parse
/tmp/csl_import.log and /tmp/export_monitor.log.
"""
import os
import re
from datetime import datetime, date
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Timestamp pattern: [2026-03-04 13:30 ET]
TS_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) ET\]")
ERROR_RE = re.compile(r"ERROR|Traceback|FATAL|Exception", re.IGNORECASE)

CRON_JOBS = [
    {
        "key": "dray_import",
        "name": "Dray Import Scanner",
        "log": "/tmp/csl_import.log",
        "success_marker": "Run complete",
        "cycle_marker": "Dray Import cycle",
        "rows_re": re.compile(r"Dray Import rows: (\d+)"),
        "schedule": "7:30 AM & 1:30 PM M-F",
    },
    {
        "key": "dray_export",
        "name": "Dray Export Scanner",
        "log": "/tmp/export_monitor.log",
        "success_marker": "Run complete",
        "cycle_marker": "Export poll cycle",
        "rows_re": re.compile(r"Found (\d+) export row"),
        "schedule": "7:30 AM & 1:30 PM M-F",
    },
]


def _tail(path, n=150):
    """Read last n lines of a file."""
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        return lines[-n:]
    except (FileNotFoundError, PermissionError):
        return []


def parse_cron_log(job):
    """
    Parse a cron job log and return structured status.

    Returns dict with:
      name, schedule, key, status, last_run, runs_today,
      items_tracked, errors, last_cycle_lines
    """
    lines = _tail(job["log"])
    today = date.today()
    now = datetime.now(ET)
    weekday = now.weekday()  # 0=Mon, 6=Sun

    # Find all cycle timestamps and success markers
    runs = []  # list of {"ts": datetime, "success": bool, "items": int, "errors": []}
    current_ts = None
    current_errors = []
    current_items = 0
    current_success = False

    for line in lines:
        # Check for cycle start timestamp
        ts_match = TS_RE.search(line)
        if ts_match and job["cycle_marker"] in line:
            # Save previous cycle if exists
            if current_ts is not None:
                runs.append({
                    "ts": current_ts,
                    "success": current_success,
                    "items": current_items,
                    "errors": current_errors,
                })
            try:
                current_ts = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M")
            except ValueError:
                current_ts = None
            current_errors = []
            current_items = 0
            current_success = False
            continue

        # Check for success marker
        if job["success_marker"] in line:
            current_success = True

        # Count items
        row_match = job["rows_re"].search(line)
        if row_match:
            current_items += int(row_match.group(1))

        # Track errors
        if ERROR_RE.search(line) and current_ts is not None:
            current_errors.append(line.strip()[:120])

    # Don't forget the last cycle
    if current_ts is not None:
        runs.append({
            "ts": current_ts,
            "success": current_success,
            "items": current_items,
            "errors": current_errors,
        })

    # Filter today's runs
    today_runs = [r for r in runs if r["ts"].date() == today]
    successful_today = [r for r in today_runs if r["success"]]
    last_run = runs[-1] if runs else None

    # Determine status
    is_weekday = weekday < 5
    if not is_weekday:
        status = "idle"  # Doesn't run on weekends
    elif not runs:
        status = "no_data"
    elif last_run and last_run["errors"] and not last_run["success"]:
        status = "failed"
    elif is_weekday and now.hour >= 9 and len(successful_today) == 0:
        status = "overdue"
    elif is_weekday and now.hour >= 15 and len(successful_today) < 2:
        status = "partial"  # AM ran, PM hasn't
    elif last_run and last_run["success"]:
        status = "success"
    else:
        status = "pending"

    # Collect recent errors across all runs
    all_errors = []
    for r in runs[-3:]:
        for e in r["errors"][-2:]:
            all_errors.append({"time": r["ts"].strftime("%H:%M"), "msg": e})

    return {
        "key": job["key"],
        "name": job["name"],
        "schedule": job["schedule"],
        "status": status,
        "last_run": last_run["ts"].strftime("%Y-%m-%d %H:%M") if last_run else None,
        "last_success": last_run["success"] if last_run else False,
        "runs_today": len(successful_today),
        "items_tracked": sum(r["items"] for r in today_runs) if today_runs else (last_run["items"] if last_run else 0),
        "errors": all_errors[-5:],
    }


def get_all_cron_status():
    """Parse all cron job logs and return dict keyed by job key."""
    result = {}
    for job in CRON_JOBS:
        result[job["key"]] = parse_cron_log(job)
    return result


if __name__ == "__main__":
    import json
    status = get_all_cron_status()
    print(json.dumps(status, indent=2))
