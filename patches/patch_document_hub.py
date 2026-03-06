#!/usr/bin/env python3
"""
Patch: Add document hub + Macropoint screenshot API endpoints to app.py

Creates:
1. load_documents table in PostgreSQL
2. GET  /api/load/{efj}/documents          — list docs for a load
3. POST /api/load/{efj}/documents          — upload a document
4. DELETE /api/load/{efj}/documents/{id}   — delete a document
5. GET  /api/load/{efj}/documents/{id}/download — download a document
6. GET  /api/macropoint/{efj}/screenshot   — serve Macropoint screenshot PNG
"""

import subprocess, sys, os, shutil

APP = "/root/csl-bot/csl-doc-tracker/app.py"

# ── Step 1: Create directories ──────────────────────────────────────────────
print("[1/4] Creating upload directories...")
os.makedirs("/root/csl-bot/csl-doc-tracker/uploads", exist_ok=True)
os.makedirs("/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots", exist_ok=True)
print("   /root/csl-bot/csl-doc-tracker/uploads/")
print("   /root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/")

# ── Step 2: Create DB table ─────────────────────────────────────────────────
print("[2/4] Creating load_documents table...")

import psycopg2
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS load_documents (
    id SERIAL PRIMARY KEY,
    efj TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'other',
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    size_bytes INTEGER DEFAULT 0,
    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    uploaded_by TEXT DEFAULT 'dashboard'
);
CREATE INDEX IF NOT EXISTS idx_docs_efj ON load_documents(efj);
""")
conn.commit()
cur.close()
conn.close()
print("   Table created (or already exists).")

# ── Step 3: Read app.py ─────────────────────────────────────────────────────
print("[3/4] Reading app.py...")
with open(APP, "r") as f:
    code = f.read()

# Backup
shutil.copy(APP, APP + ".bak_docs")
print("   Backup saved to app.py.bak_docs")

# ── Step 4: Inject endpoints ────────────────────────────────────────────────
print("[4/4] Patching app.py with document hub endpoints...")

# Check if already patched
if "/api/load/{efj}/documents" in code:
    print("   Already patched! Skipping endpoint injection.")
else:
    # Ensure required imports are present
    imports_added = []

    if "import os" not in code:
        # Add 'import os' near the top after existing imports
        code = "import os\n" + code
        imports_added.append("import os")

    if "from fastapi import" in code:
        # Check if File, Form, UploadFile are already imported
        import_line_start = code.index("from fastapi import")
        import_line_end = code.index("\n", import_line_start)
        fastapi_import = code[import_line_start:import_line_end]

        missing = []
        for name in ["File", "Form", "UploadFile"]:
            if name not in fastapi_import:
                missing.append(name)

        if missing:
            # Append missing imports to the existing fastapi import line
            new_import = fastapi_import.rstrip() + ", " + ", ".join(missing)
            code = code[:import_line_start] + new_import + code[import_line_end:]
            imports_added.append(f"Added {', '.join(missing)} to fastapi import")
    else:
        # No fastapi import line found — add one
        code = "from fastapi import File, Form, UploadFile\n" + code
        imports_added.append("from fastapi import File, Form, UploadFile")

    if imports_added:
        for ia in imports_added:
            print(f"   {ia}")

    DOCUMENT_CODE = '''

# ===================================================================
# DOCUMENT HUB API
# ===================================================================

@app.get("/api/load/{efj}/documents")
async def get_load_documents(efj: str):
    """List all documents for a load."""
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT id, doc_type, original_name, size_bytes, uploaded_at "
            "FROM load_documents WHERE efj = %s ORDER BY uploaded_at DESC",
            (efj,)
        )
        rows = cur.fetchall()
    docs = [
        {
            "id": r["id"],
            "doc_type": r["doc_type"],
            "original_name": r["original_name"],
            "size_bytes": r["size_bytes"],
            "uploaded_at": r["uploaded_at"].isoformat() if r["uploaded_at"] else None,
        }
        for r in rows
    ]
    return JSONResponse({"documents": docs})


@app.post("/api/load/{efj}/documents")
async def upload_load_document(efj: str, file: UploadFile = File(...), doc_type: str = Form("other")):
    """Upload a document for a load."""
    import uuid
    upload_dir = f"/root/csl-bot/csl-doc-tracker/uploads/{efj}"
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_name)
    contents = await file.read()
    with open(file_path, "wb") as f:
        f.write(contents)
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO load_documents (efj, doc_type, filename, original_name, size_bytes) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (efj, doc_type, safe_name, file.filename, len(contents))
            )
            doc_id = cur.fetchone()["id"]
    return JSONResponse({"ok": True, "id": doc_id, "original_name": file.filename})


@app.delete("/api/load/{efj}/documents/{doc_id}")
async def delete_load_document(efj: str, doc_id: int):
    """Delete a document for a load."""
    with db.get_cursor() as cur:
        cur.execute("SELECT filename FROM load_documents WHERE id = %s AND efj = %s", (doc_id, efj))
        row = cur.fetchone()
    if row:
        file_path = f"/root/csl-bot/csl-doc-tracker/uploads/{efj}/{row['filename']}"
        if os.path.exists(file_path):
            os.remove(file_path)
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("DELETE FROM load_documents WHERE id = %s AND efj = %s", (doc_id, efj))
    return JSONResponse({"ok": True})


@app.get("/api/load/{efj}/documents/{doc_id}/download")
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
    return FileResponse(file_path, filename=row["original_name"])


# ===================================================================
# MACROPOINT SCREENSHOT API
# ===================================================================

@app.get("/api/macropoint/{efj}/screenshot")
async def get_macropoint_screenshot(efj: str):
    """Serve a cached Macropoint tracking screenshot."""
    screenshot_path = f"/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.png"
    if not os.path.exists(screenshot_path):
        return JSONResponse(status_code=404, content={"error": "no screenshot"})
    import json as _json
    meta_path = f"/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.json"
    headers = {"Cache-Control": "max-age=300"}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = _json.load(f)
        headers["X-Captured-At"] = meta.get("captured_at", "")
    return FileResponse(screenshot_path, media_type="image/png", headers=headers)

'''

    # Find injection point: before @app.get("/app") or before @app.get("/health") or append
    marker = '@app.get("/app")'
    health_marker = '@app.get("/health")'

    if marker in code:
        code = code.replace(marker, DOCUMENT_CODE + "\n" + marker)
        print("   Injected before /app route.")
    elif health_marker in code:
        code = code.replace(health_marker, DOCUMENT_CODE + "\n" + health_marker)
        print("   Injected before /health route.")
    else:
        code += DOCUMENT_CODE
        print("   Appended to end of file.")

    with open(APP, "w") as f:
        f.write(code)
    print("   Patched successfully.")

print()
print("Done! Endpoints added:")
print("  - GET    /api/load/{efj}/documents")
print("  - POST   /api/load/{efj}/documents")
print("  - DELETE  /api/load/{efj}/documents/{doc_id}")
print("  - GET    /api/load/{efj}/documents/{doc_id}/download")
print("  - GET    /api/macropoint/{efj}/screenshot")
print()
print("Restart with: systemctl restart csl-dashboard")
