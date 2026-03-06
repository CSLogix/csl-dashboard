#!/usr/bin/env python3
"""Patch: Add batch tracking-summary and document-summary endpoints for table columns."""

APP_FILE = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP_FILE, "r") as f:
    code = f.read()

# ─── Find insertion point: before the team profiles section ───
marker = '# ═══════════════════════════════════════════════════════════════\n# TEAM PROFILE ENDPOINTS'
if marker not in code:
    marker = '@app.get("/api/team/profiles")'

if marker not in code:
    print("ERROR: Could not find insertion marker")
    exit(1)

insert_pos = code.index(marker)

ENDPOINTS = '''
# ═══════════════════════════════════════════════════════════════
# BATCH TABLE DATA ENDPOINTS (tracking + documents)
# ═══════════════════════════════════════════════════════════════

@app.get("/api/shipments/tracking-summary")
async def api_tracking_summary():
    """Return tracking status summary for all FTL loads (for table column)."""
    cache = _read_tracking_cache()
    result = {}
    for efj, entry in cache.items():
        stop_times = entry.get("stop_times") or {}
        behind = False
        for k in ("stop1_eta", "stop2_eta"):
            val = stop_times.get(k) or ""
            if "BEHIND" in val.upper():
                behind = True
        result[efj] = {
            "behindSchedule": behind,
            "cantMakeIt": bool(entry.get("cant_make_it")),
            "status": entry.get("status", ""),
            "lastScraped": entry.get("last_scraped", ""),
        }
    return {"tracking": result}


@app.get("/api/shipments/document-summary")
async def api_document_summary():
    """Return document type counts per load for table icons."""
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT efj, doc_type, COUNT(*) as cnt
            FROM load_documents
            GROUP BY efj, doc_type
            ORDER BY efj
        """)
        rows = cur.fetchall()
    result = {}
    for r in rows:
        efj_val = r["efj"] if isinstance(r, dict) else r[0]
        doc_type = r["doc_type"] if isinstance(r, dict) else r[1]
        cnt = r["cnt"] if isinstance(r, dict) else r[2]
        if efj_val not in result:
            result[efj_val] = {}
        result[efj_val][doc_type] = cnt
    return {"documents": result}


'''

if "/api/shipments/tracking-summary" not in code:
    code = code[:insert_pos] + ENDPOINTS + code[insert_pos:]
    with open(APP_FILE, "w") as f:
        f.write(code)
    print("✅ Batch table endpoints patched!")
    print("   GET /api/shipments/tracking-summary")
    print("   GET /api/shipments/document-summary")
else:
    print("⏭  Endpoints already exist, skipping.")

print("   Restart csl-dashboard to apply.")
