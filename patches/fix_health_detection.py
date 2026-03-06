"""
Patch: Fix _analyze_service_health crash detection.

Problem: The old code counts ANY log line containing 'error/traceback/failed/exception'
as a "crash". Normal operational errors (browser scraping failures, quota retries,
missing columns) push the count > 3, causing every service to show CRASH LOOP.

Fix: Count actual systemd service restarts as "crashes" and keep error-level log
lines separate. Health status based on real crashes, not noisy error lines.
"""
import re

NEW_FUNC = r'''
def _analyze_service_health(unit: str, name: str, poll_min: int) -> dict:
    """Analyze 24h of journalctl logs for a single service."""
    import subprocess as _sp

    # 1. Active state
    try:
        r = _sp.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
        active_state = r.stdout.strip()
    except Exception:
        active_state = "unknown"

    # 2. Pull 24h of journal logs
    try:
        r = _sp.run(
            ["journalctl", "-u", unit, "--since", "24 hours ago", "--no-pager", "-o", "short"],
            capture_output=True, text=True, timeout=30,
        )
        raw = r.stdout.strip()
        lines = raw.split(chr(10)) if raw else []
    except Exception:
        lines = []

    # 3. Count ACTUAL crashes = systemd restart events (not just any error line)
    crash_pattern = re.compile(
        r"(Failed with result|Main process exited, code=exited, status=1|"
        r"Scheduled restart job, restart counter|"
        r"systemd\[\d+\]: .+: Main process exited)",
        re.IGNORECASE,
    )
    crash_count = sum(1 for l in lines if crash_pattern.search(l))

    # 4. Operational errors (for display, not health determination)
    error_pattern = re.compile(r"error|traceback|failed|exception", re.IGNORECASE)
    error_lines = [l for l in lines if error_pattern.search(l) and not crash_pattern.search(l)]
    recent_errors = []
    for el in (error_lines[-5:] if error_lines else []):
        tm = re.match(r"\w+ \d+ (\d+:\d+:\d+)", el)
        time_str = tm.group(1) if tm else ""
        msg = el.split(":", 3)[-1].strip() if ":" in el else el
        recent_errors.append({"time": time_str, "level": "error", "msg": msg[:120]})

    # Also add crash lines to recent_errors
    crash_lines = [l for l in lines if crash_pattern.search(l)]
    for cl in (crash_lines[-3:] if crash_lines else []):
        tm = re.match(r"\w+ \d+ (\d+:\d+:\d+)", cl)
        time_str = tm.group(1) if tm else ""
        msg = cl.split(":", 3)[-1].strip() if ":" in cl else cl
        recent_errors.append({"time": time_str, "level": "crash", "msg": msg[:120]})
    recent_errors.sort(key=lambda e: e.get("time", ""), reverse=True)
    recent_errors = recent_errors[:8]

    # 5. Email count
    email_pattern = re.compile(r"Sent alert|SMTP|email sent", re.IGNORECASE)
    email_count = sum(1 for l in lines if email_pattern.search(l))

    # 6. Cycle count
    cycle_pattern = re.compile(
        r"\[Dray Import\]|\[Dray Export\]|\[FTL\]|\[Boviet\]|\[Tolead\]|Tab:|Checking |Starting cycle|--- Cycle"
    )
    cycle_count = sum(1 for l in lines if cycle_pattern.search(l))

    # 7. Loads tracked
    loads_pattern = re.compile(r"Tracking|Scraping|Container:|Row \d+:")
    loads_count = sum(1 for l in lines if loads_pattern.search(l))

    # 8. Last successful cycle timestamp
    last_cycle_ts = None
    cycle_end_pattern = re.compile(r"Run complete|poll complete|Done|Sleeping")
    for l in reversed(lines):
        if cycle_end_pattern.search(l):
            tm = re.match(r"(\w+ \d+ \d+:\d+:\d+)", l)
            if tm:
                try:
                    from datetime import datetime as _dt
                    last_cycle_ts = _dt.strptime(f"2026 {tm.group(1)}", "%Y %b %d %H:%M:%S").isoformat()
                except Exception:
                    pass
            break

    # 9. Health status — based on real crashes, not operational errors
    if active_state not in ("active", "activating"):
        health = "down"
    elif crash_count > 10:
        health = "crash_loop"
    elif crash_count > 3:
        health = "degraded"
    else:
        health = "healthy"

    # 10. Uptime
    uptime_str = ""
    try:
        r = _sp.run(
            ["systemctl", "show", unit, "--property=ActiveEnterTimestamp"],
            capture_output=True, text=True, timeout=5,
        )
        ts_line = r.stdout.strip()
        if "=" in ts_line:
            ts_val = ts_line.split("=", 1)[1].strip()
            if ts_val:
                from datetime import datetime as _dt
                try:
                    started = _dt.strptime(ts_val, "%a %Y-%m-%d %H:%M:%S %Z")
                    delta = _dt.now() - started
                    hours = int(delta.total_seconds() // 3600)
                    mins = int((delta.total_seconds() % 3600) // 60)
                    if hours >= 24:
                        uptime_str = f"{hours // 24}d {hours % 24}h"
                    elif hours > 0:
                        uptime_str = f"{hours}h {mins}m"
                    else:
                        uptime_str = f"{mins}m"
                except Exception:
                    pass
    except Exception:
        pass

    # 11. Last run / next run
    last_run = ""
    next_run = ""
    for l in reversed(lines):
        tm = re.match(r"(\w+ \d+ \d+:\d+:\d+)", l)
        if tm:
            try:
                from datetime import datetime as _dt
                ts = _dt.strptime(f"2026 {tm.group(1)}", "%Y %b %d %H:%M:%S")
                mins = int((_dt.now() - ts).total_seconds() / 60)
                last_run = "just now" if mins < 1 else (f"{mins}m ago" if mins < 60 else f"{mins // 60}h {mins % 60}m ago")
                if poll_min > 0:
                    nm = poll_min - mins
                    next_run = "overdue" if nm < 0 else (f"{nm} min" if nm < 60 else f"{nm // 60}h {nm % 60}m")
            except Exception:
                pass
            break

    return {
        "unit": unit,
        "name": name,
        "active_state": active_state,
        "health": health,
        "uptime": uptime_str,
        "poll_min": poll_min,
        "crashes_24h": crash_count,
        "emails_24h": email_count,
        "cycles_24h": cycle_count,
        "loads_24h": loads_count,
        "last_run": last_run or "unknown",
        "next_run": next_run,
        "last_successful_cycle": last_cycle_ts,
        "recent_errors": recent_errors,
    }
'''

# Also update the return in api_bot_health to include services as a dict keyed by unit
NEW_BOT_HEALTH = r'''
@app.get("/api/bot-health")
def api_bot_health():
    """Deep health check for all bot services - 24h window."""
    services = {}
    total_crashes = 0
    total_emails = 0
    total_cycles = 0
    healthy_count = 0

    for svc in BOT_SERVICES:
        info = _analyze_service_health(svc["unit"], svc["name"], svc["poll_min"])
        services[svc["unit"]] = info
        total_crashes += info["crashes_24h"]
        total_emails += info["emails_24h"]
        total_cycles += info["cycles_24h"]
        if info["health"] == "healthy":
            healthy_count += 1

    summary = {
        "total_crashes_24h": total_crashes,
        "total_emails_24h": total_emails,
        "total_cycles_24h": total_cycles,
        "services_healthy": healthy_count,
        "services_total": len(services),
    }

    return {"services": services, "summary": summary, "generated_at": __import__("datetime").datetime.now().isoformat()}
'''


def apply():
    import sys
    path = "/root/csl-bot/csl-doc-tracker/app.py"
    with open(path, "r") as f:
        content = f.read()

    # 1. Replace _analyze_service_health function
    old_start = "def _analyze_service_health(unit: str, name: str, poll_min: int) -> dict:"
    old_end = '        "recent_errors": recent_errors,\n    }'

    start_idx = content.find(old_start)
    end_idx = content.find(old_end, start_idx)
    if start_idx == -1 or end_idx == -1:
        print("ERROR: Could not find _analyze_service_health function boundaries")
        sys.exit(1)
    end_idx += len(old_end)

    content = content[:start_idx] + NEW_FUNC.strip() + "\n" + content[end_idx:]
    print(f"Replaced _analyze_service_health at char {start_idx}")

    # 2. Replace api_bot_health to return dict keyed by unit + generated_at
    old_bot_health_start = '@app.get("/api/bot-health")\ndef api_bot_health():'
    old_bot_health_end = '    return {"services": services, "summary": summary}'

    start_idx = content.find(old_bot_health_start)
    end_idx = content.find(old_bot_health_end, start_idx)
    if start_idx == -1 or end_idx == -1:
        print("WARNING: Could not find api_bot_health boundaries, skipping")
    else:
        end_idx += len(old_bot_health_end)
        content = content[:start_idx] + NEW_BOT_HEALTH.strip() + "\n" + content[end_idx:]
        print(f"Replaced api_bot_health at char {start_idx}")

    with open(path, "w") as f:
        f.write(content)
    print("Patch applied successfully.")


if __name__ == "__main__":
    apply()
