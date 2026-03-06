#!/usr/bin/env python3
"""
Patch: Add /api/bot-health endpoint with real health metrics.
Parses journalctl for crash counts, email counts, cycle completions,
loads tracked, errors, and classifies health per service.
"""
import re

APP = "/root/csl-bot/csl-doc-tracker/app.py"

# ── New code to insert after _get_bot_status_detailed (after line containing its closing results) ──

BOT_HEALTH_CODE = r'''

# ---------------------------------------------------------------------------
# Bot health metrics — deep journal parsing
# ---------------------------------------------------------------------------

BOT_SERVICE_PATTERNS = {
    "csl-import": {
        "cycle_complete": r"Run complete|poll cycle\.\.\.$|Sleeping \d+",
        "email_sent": r"Email sent",
        "loads_tracked": r"Dray Import rows: (\d+)",
        "error": r"ERROR:|Traceback|Exception",
        "is_server": False,
    },
    "csl-export": {
        "cycle_complete": r"Sleeping \d+|Export Monitor started",
        "email_sent": r"Email sent",
        "loads_tracked": r"(\d+) change\(s\) detected",
        "error": r"ERROR:|Traceback|Exception",
        "is_server": False,
    },
    "csl-ftl": {
        "cycle_complete": r"Sleeping \d+|save_sent_alerts|save_tracking_cache",
        "email_sent": r"Email sent",
        "loads_tracked": r"Found (\d+) FTL row",
        "error": r"ERROR:|Traceback|Exception",
        "is_server": False,
    },
    "csl-boviet": {
        "cycle_complete": r"Done .* tracked|Sleeping \d+",
        "email_sent": r"Email sent",
        "loads_tracked": r"tracked (\d+) load",
        "error": r"ERROR:|Traceback|Exception",
        "is_server": False,
    },
    "csl-tolead": {
        "cycle_complete": r"Done|Sleeping \d+",
        "email_sent": r"Email sent",
        "loads_tracked": r"To track: (\d+)",
        "error": r"ERROR:|Traceback|Exception",
        "is_server": False,
    },
    "csl-webhook": {
        "cycle_complete": None,
        "email_sent": None,
        "loads_tracked": None,
        "error": r"ERROR:|Traceback|Exception",
        "is_server": True,
    },
    "csl-upload": {
        "cycle_complete": None,
        "email_sent": None,
        "loads_tracked": None,
        "error": r"ERROR:|Traceback|Exception",
        "is_server": True,
    },
    "csl-inbox": {
        "cycle_complete": r"Sleeping|cycle complete|Processed",
        "email_sent": None,
        "loads_tracked": r"MATCHED|matched.*EFJ",
        "error": r"ERROR:|Traceback|Exception",
        "is_server": False,
    },
}

STATE_FILES = {
    "ftl_sent_alerts": "/root/csl-bot/ftl_sent_alerts.json",
    "last_check": "/root/csl-bot/last_check.json",
    "export_state": "/root/csl-bot/export_state.json",
    "ftl_tracking_cache": "/root/csl-bot/ftl_tracking_cache.json",
}

_bot_health_cache = {"data": None, "ts": 0}
BOT_HEALTH_CACHE_TTL = 180  # 3 minutes


def _classify_health(crashes_24h, cycles_24h, active_state, is_server):
    if active_state != "active":
        return "down"
    if is_server:
        return "healthy" if crashes_24h < 3 else "degraded"
    if crashes_24h > 10:
        return "crash_loop"
    if crashes_24h > 0 and cycles_24h == 0:
        return "crash_loop"
    if crashes_24h > 0:
        return "degraded"
    if cycles_24h == 0:
        return "idle"
    return "healthy"


def _parse_journal_metrics(unit):
    patterns = BOT_SERVICE_PATTERNS.get(unit, {})
    metrics = {
        "crashes": 0,
        "emails_sent": 0,
        "errors": 0,
        "cycles_completed": 0,
        "loads_tracked": 0,
    }
    last_cycle_ts = None
    recent_errors = []
    year = datetime.now().year

    try:
        r = subprocess.run(
            ["journalctl", "-u", unit, "--since", "24 hours ago", "--no-pager", "-o", "short"],
            capture_output=True, text=True, timeout=15,
        )
        lines = r.stdout.strip().split("\n") if r.stdout.strip() else []
    except Exception:
        return metrics, None, []

    for line in lines:
        if not line.strip():
            continue

        # Crash detection (systemd-level)
        if "Failed with result" in line:
            metrics["crashes"] += 1
            tm = re.match(r"\w+ \d+ (\d+:\d+:\d+)", line)
            if len(recent_errors) < 50:
                recent_errors.append({
                    "time": tm.group(1) if tm else "",
                    "msg": "Service crashed (exit-code failure)",
                    "level": "crash",
                })
            continue

        # Skip non-python lines for app metrics
        if "python3[" not in line and "python[" not in line:
            continue

        # Email sent
        if patterns.get("email_sent") and re.search(patterns["email_sent"], line):
            metrics["emails_sent"] += 1

        # Cycle completion
        if patterns.get("cycle_complete") and re.search(patterns["cycle_complete"], line):
            metrics["cycles_completed"] += 1
            tm = re.match(r"(\w+ \d+ \d+:\d+:\d+)", line)
            if tm:
                last_cycle_ts = tm.group(1)

        # Loads tracked
        if patterns.get("loads_tracked"):
            m = re.search(patterns["loads_tracked"], line)
            if m:
                for g in m.groups():
                    if g and g.isdigit():
                        metrics["loads_tracked"] += int(g)
                        break

        # App-level errors (but not the patterns we're counting above)
        if patterns.get("error") and re.search(patterns["error"], line):
            metrics["errors"] += 1
            tm = re.match(r"\w+ \d+ (\d+:\d+:\d+)", line)
            msg_part = line.split("]:", 1)[-1].strip()[:100] if "]:" in line else line[-100:]
            if len(recent_errors) < 50:
                recent_errors.append({
                    "time": tm.group(1) if tm else "",
                    "msg": msg_part,
                    "level": "error",
                })

    # Convert last_cycle_ts to ISO
    last_cycle_iso = None
    if last_cycle_ts:
        try:
            ts = datetime.strptime(f"{year} {last_cycle_ts}", "%Y %b %d %H:%M:%S")
            last_cycle_iso = ts.isoformat()
        except Exception:
            pass

    # Keep last 5 errors only
    return metrics, last_cycle_iso, recent_errors[-5:]


def _get_state_file_info():
    info = {}
    for name, path in STATE_FILES.items():
        try:
            stat = os.stat(path)
            with open(path) as f:
                data = json.load(f)
            info[name] = {
                "keys": len(data) if isinstance(data, dict) else len(data),
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        except Exception:
            info[name] = {"keys": 0, "size_bytes": 0, "modified": None}
    return info


def _compute_bot_health():
    all_services_data = {}
    total_emails = total_crashes = total_cycles = 0
    healthy_count = degraded_count = down_count = 0

    all_svc_list = list(BOT_SERVICES) + [{"unit": "csl-inbox", "name": "Inbox Scanner", "poll_min": 5}]

    for svc in all_svc_list:
        unit = svc["unit"]
        active_state = _get_service_status(unit)
        patterns = BOT_SERVICE_PATTERNS.get(unit, {})
        is_server = patterns.get("is_server", False)

        metrics, last_cycle_iso, recent_errors = _parse_journal_metrics(unit)

        health = _classify_health(metrics["crashes"], metrics["cycles_completed"], active_state, is_server)

        # Reuse existing last_run/next_run logic
        last_run = next_run = ""
        try:
            r = subprocess.run(
                ["journalctl", "-u", unit, "-n", "1", "--no-pager", "-o", "short"],
                capture_output=True, text=True, timeout=5,
            )
            line = r.stdout.strip().split("\n")[-1] if r.stdout.strip() else ""
            m = re.match(r"(\w+ \d+ \d+:\d+:\d+)", line)
            if m:
                ts = datetime.strptime(f"{datetime.now().year} {m.group(1)}", "%Y %b %d %H:%M:%S")
                mins = int((datetime.now() - ts).total_seconds() / 60)
                last_run = "just now" if mins < 1 else (f"{mins} min ago" if mins < 60 else f"{mins // 60} hr ago")
                if svc["poll_min"] > 0:
                    nm = svc["poll_min"] - mins
                    next_run = "overdue" if nm < 0 else (f"{nm} min" if nm < 60 else f"{nm // 60} hr {nm % 60} min")
        except Exception:
            pass

        total_emails += metrics["emails_sent"]
        total_crashes += metrics["crashes"]
        total_cycles += metrics["cycles_completed"]
        if health == "healthy":
            healthy_count += 1
        elif health in ("degraded", "crash_loop"):
            degraded_count += 1
        else:
            down_count += 1

        all_services_data[unit] = {
            "name": svc["name"],
            "unit": unit,
            "active_state": active_state,
            "health": health,
            "journal_24h": metrics,
            "last_successful_cycle": last_cycle_iso,
            "recent_errors": recent_errors,
            "last_run": last_run or "unknown",
            "next_run": next_run if svc["poll_min"] > 0 else "",
            "poll_min": svc["poll_min"],
        }

    return {
        "generated_at": datetime.now().isoformat(),
        "services": all_services_data,
        "state_files": _get_state_file_info(),
        "summary": {
            "total_emails_24h": total_emails,
            "total_crashes_24h": total_crashes,
            "total_cycles_24h": total_cycles,
            "services_healthy": healthy_count,
            "services_degraded": degraded_count,
            "services_down": down_count,
            "services_total": len(all_svc_list),
        },
    }


def _get_bot_health():
    now = _time.time()
    if _bot_health_cache["data"] and (now - _bot_health_cache["ts"]) < BOT_HEALTH_CACHE_TTL:
        return _bot_health_cache["data"]
    result = _compute_bot_health()
    _bot_health_cache["data"] = result
    _bot_health_cache["ts"] = now
    return result
'''

# ── Route to add ──
ROUTE_CODE = '''
@app.get("/api/bot-health")
def api_bot_health():
    return _get_bot_health()

'''

def patch():
    with open(APP) as f:
        src = f.read()

    if "/api/bot-health" in src:
        print("Already patched — /api/bot-health route exists.")
        return

    # Insert health functions after _get_bot_status_detailed block
    # Find the _get_recent_actions section marker
    marker = "# Recent bot actions from journal"
    idx = src.find(marker)
    if idx == -1:
        print("ERROR: Could not find marker '# Recent bot actions from journal'")
        return

    # Find the line start of this marker
    line_start = src.rfind("\n", 0, idx)
    src = src[:line_start] + "\n" + BOT_HEALTH_CODE + "\n\n" + src[line_start:]

    # Insert route after /api/bot-status
    route_marker = "def api_bot_status():\n    return _get_bot_status_detailed()\n"
    idx2 = src.find(route_marker)
    if idx2 == -1:
        print("ERROR: Could not find api_bot_status route")
        return

    insert_after = idx2 + len(route_marker)
    src = src[:insert_after] + "\n" + ROUTE_CODE + src[insert_after:]

    with open(APP, "w") as f:
        f.write(src)

    print("Patched app.py with /api/bot-health endpoint.")
    print("Restart: systemctl restart csl-dashboard")

if __name__ == "__main__":
    patch()
