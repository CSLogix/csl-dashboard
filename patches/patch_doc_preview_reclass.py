#!/usr/bin/env python3
"""
Patch app.py to add document preview (inline serving) and doc type reclassification.

Changes:
  - Modifies GET /api/load/{efj}/documents/{doc_id}/download to accept ?inline=true
    (serves with Content-Disposition: inline + correct MIME type for browser preview)
  - Adds PATCH /api/load/{efj}/documents/{doc_id} for reclassifying doc_type

Run on server:
    python3 /tmp/patch_doc_preview_reclass.py
"""

import shutil

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

# --- Read current code ---
with open(APP_PY, "r") as f:
    code = f.read()

# --- Check if already patched ---
if "inline: bool" in code and "update_load_document" in code:
    print("Already patched. Nothing to do.")
    exit(0)

# --- Backup ---
shutil.copy2(APP_PY, APP_PY + ".bak_preview")
print(f"Backup saved to {APP_PY}.bak_preview")

# --- 1. Replace the download endpoint to support ?inline=true ---

OLD_DOWNLOAD = '''@app.get("/api/load/{efj}/documents/{doc_id}/download")
async def download_load_document(efj: str, doc_id: int):
    """Download a document file."""
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT filename, original_name FROM load_documents WHERE id = %s AND efj = %s",
            (doc_id, efj)
        )
        row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "not found"})
    file_path = f"/root/csl-bot/csl-doc-tracker/uploads/{efj}/{row['filename']}"
    if not os.path.exists(file_path):
        return JSONResponse(status_code=404, content={"error": "file missing"})
    return FileResponse(file_path, filename=row["original_name"])'''

NEW_DOWNLOAD = '''@app.get("/api/load/{efj}/documents/{doc_id}/download")
async def download_load_document(efj: str, doc_id: int, inline: bool = False):
    """Download or inline-preview a specific document."""
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT filename, original_name FROM load_documents WHERE id = %s AND efj = %s",
            (doc_id, efj)
        )
        row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "not found"})
    file_path = f"/root/csl-bot/csl-doc-tracker/uploads/{efj}/{row['filename']}"
    if not os.path.exists(file_path):
        return JSONResponse(status_code=404, content={"error": "file missing"})
    if inline:
        import mimetypes
        media_type = mimetypes.guess_type(row["original_name"])[0] or "application/octet-stream"
        return FileResponse(
            file_path,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{row["original_name"]}"'}
        )
    return FileResponse(file_path, filename=row["original_name"])


@app.patch("/api/load/{efj}/documents/{doc_id}")
async def update_load_document(efj: str, doc_id: int, request: Request):
    """Update document metadata (doc_type reclassification)."""
    body = await request.json()
    new_type = body.get("doc_type", "").strip()
    valid_types = [
        "customer_rate", "carrier_rate", "pod", "bol",
        "carrier_invoice", "screenshot", "email", "other",
    ]
    if new_type not in valid_types:
        return JSONResponse(status_code=400, content={"error": f"Invalid doc_type. Must be one of: {valid_types}"})
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE load_documents SET doc_type = %s WHERE id = %s AND efj = %s RETURNING id",
                (new_type, doc_id, efj)
            )
            row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return JSONResponse({"ok": True, "doc_type": new_type})'''

if OLD_DOWNLOAD in code:
    code = code.replace(OLD_DOWNLOAD, NEW_DOWNLOAD)
    print("Replaced download endpoint with inline-aware version + added PATCH endpoint.")
else:
    print("ERROR: Could not find download endpoint to replace.")
    print("Check if it was already modified or the code has changed.")
    exit(1)

# --- 2. Ensure Request is imported from fastapi ---
# The PATCH endpoint uses `request: Request` so we need the import.
if "from fastapi import" in code and "Request" not in code.split("from fastapi import")[1].split("\n")[0]:
    # Add Request to the existing fastapi import line
    code = code.replace("from fastapi import", "from fastapi import Request, ", 1)
    print("Added Request to FastAPI imports.")
elif "Request" in code:
    print("Request already imported.")
else:
    # Fallback: add a standalone import after the first fastapi import
    code = code.replace("from fastapi import", "from fastapi import Request, ", 1)
    print("Added Request import (fallback).")

# --- Write patched file ---
with open(APP_PY, "w") as f:
    f.write(code)

print("Patch applied successfully!")
print("Restart: systemctl restart csl-dashboard")
