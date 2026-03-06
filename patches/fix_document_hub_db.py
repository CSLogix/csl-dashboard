#!/usr/bin/env python3
"""Fix document hub endpoints to use db.get_cursor() / db.get_conn() pattern."""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

# Replace the entire DOCUMENT HUB API section
OLD_SECTION = '''# ===================================================================
# DOCUMENT HUB API
# ===================================================================

@app.get("/api/load/{efj}/documents")
async def get_load_documents(efj: str):
    """List all documents for a load."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, doc_type, original_name, size_bytes, uploaded_at "
        "FROM load_documents WHERE efj = %s ORDER BY uploaded_at DESC",
        (efj,)
    )
    docs = [
        {
            "id": r[0],
            "doc_type": r[1],
            "original_name": r[2],
            "size_bytes": r[3],
            "uploaded_at": r[4].isoformat() if r[4] else None,
        }
        for r in cur.fetchall()
    ]
    cur.close()
    conn.close()
    return {"documents": docs}


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
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO load_documents (efj, doc_type, filename, original_name, size_bytes) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (efj, doc_type, safe_name, file.filename, len(contents))
    )
    doc_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"ok": True, "id": doc_id, "original_name": file.filename}


@app.delete("/api/load/{efj}/documents/{doc_id}")
async def delete_load_document(efj: str, doc_id: int):
    """Delete a document for a load."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT filename FROM load_documents WHERE id = %s AND efj = %s", (doc_id, efj))
    row = cur.fetchone()
    if row:
        file_path = f"/root/csl-bot/csl-doc-tracker/uploads/{efj}/{row[0]}"
        if os.path.exists(file_path):
            os.remove(file_path)
        cur.execute("DELETE FROM load_documents WHERE id = %s AND efj = %s", (doc_id, efj))
        conn.commit()
    cur.close()
    conn.close()
    return {"ok": True}


@app.get("/api/load/{efj}/documents/{doc_id}/download")
async def download_load_document(efj: str, doc_id: int):
    """Download a specific document."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT filename, original_name FROM load_documents WHERE id = %s AND efj = %s",
        (doc_id, efj)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return JSONResponse(status_code=404, content={"error": "not found"})
    file_path = f"/root/csl-bot/csl-doc-tracker/uploads/{efj}/{row[0]}"
    if not os.path.exists(file_path):
        return JSONResponse(status_code=404, content={"error": "file missing"})
    return FileResponse(file_path, filename=row[1])'''

NEW_SECTION = '''# ===================================================================
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
    """Download a specific document."""
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

if OLD_SECTION in code:
    code = code.replace(OLD_SECTION, NEW_SECTION)
    with open(APP, "w") as f:
        f.write(code)
    print("Fixed document hub DB calls.")
else:
    print("ERROR: Could not find section to replace.")
    print("Trying line-by-line replacement...")
    # Fallback: replace get_db() calls
    code = code.replace("conn = get_db()\n    cur = conn.cursor()", "# using db helper")
    with open(APP, "w") as f:
        f.write(code)
    print("Fallback applied (check manually).")
