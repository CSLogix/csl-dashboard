"""
Patch: Normalize EFJ keys in document-summary API to bare numbers
so DocIndicators match regardless of how the EFJ was stored.

Run: python3 /tmp/patch_doc_summary_normalize.py
"""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

# ── 1. Normalize EFJ keys in document-summary response ──
old_summary = '''    result = {}
    for r in rows:
        efj_val = r["efj"] if isinstance(r, dict) else r[0]
        doc_type = r["doc_type"] if isinstance(r, dict) else r[1]
        cnt = r["cnt"] if isinstance(r, dict) else r[2]
        if efj_val not in result:
            result[efj_val] = {}
        result[efj_val][doc_type] = cnt
    return {"documents": result}'''

new_summary = '''    import re as _re
    result = {}
    for r in rows:
        efj_val = r["efj"] if isinstance(r, dict) else r[0]
        doc_type = r["doc_type"] if isinstance(r, dict) else r[1]
        cnt = r["cnt"] if isinstance(r, dict) else r[2]
        # Normalize key: strip "EFJ" prefix and whitespace -> bare number
        bare = _re.sub(r"^EFJ\s*", "", str(efj_val).strip(), flags=_re.IGNORECASE).strip()
        key = bare if bare else efj_val
        if key not in result:
            result[key] = {}
        # Merge counts (in case both "107230" and "EFJ107230" exist)
        result[key][doc_type] = result[key].get(doc_type, 0) + cnt
    return {"documents": result}'''

if old_summary in code:
    code = code.replace(old_summary, new_summary, 1)
    print("[OK] Normalized EFJ keys in document-summary API")
else:
    print("[WARN] Could not find document-summary result block")

with open(APP, "w") as f:
    f.write(code)

print("[DONE] Patch applied. Restart csl-dashboard.")
