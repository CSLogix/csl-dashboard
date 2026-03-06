#!/usr/bin/env python3
"""
Patch: Add email_count + email_max_priority to /api/v2/shipments response.
Enriches shipments with email thread stats after the main query.

Run on server:
    python3 /tmp/patch_v2_email_stats.py
"""

import shutil, os, sys
from datetime import datetime

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

def backup(path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{path}.bak_{ts}"
    shutil.copy2(path, bak)
    print(f"Backup: {bak}")

def patch():
    backup(APP_PY)
    code = open(APP_PY).read()

    old = '''    for s in shipments:
        s["_invoiced"] = invoiced_map.get(s["efj"], False)

    return {"shipments": shipments, "total": len(shipments)}'''

    new = '''    for s in shipments:
        s["_invoiced"] = invoiced_map.get(s["efj"], False)

    # Enrich with email thread stats (count + max priority)
    try:
        with db.get_cursor() as cur:
            cur.execute("""
                SELECT efj, COUNT(*) as email_count, COALESCE(MAX(priority), 0) as email_max_priority
                FROM email_threads
                GROUP BY efj
            """)
            email_stats = {r["efj"]: r for r in cur.fetchall()}
        for s in shipments:
            es = email_stats.get(s["efj"])
            s["email_count"] = es["email_count"] if es else 0
            s["email_max_priority"] = es["email_max_priority"] if es else 0
    except Exception:
        for s in shipments:
            s["email_count"] = 0
            s["email_max_priority"] = 0

    return {"shipments": shipments, "total": len(shipments)}'''

    if old in code:
        code = code.replace(old, new)
        open(APP_PY, "w").write(code)
        print("+ Added email stats enrichment to /api/v2/shipments")
        print("Restart: systemctl restart csl-dashboard")
    else:
        print("WARNING: Could not find target block — may already be patched")


if __name__ == "__main__":
    patch()
