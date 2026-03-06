#!/usr/bin/env python3
"""
Patch: Add task documents API + account column to team_tasks
- Adds 'account' column to team_tasks table
- Updates existing task endpoints to handle 'account' field
- Creates task_documents table
- Creates uploads/tasks/ directory
- Adds 4 document endpoints: list, upload, delete, download
"""

import sys, os

APP = "/root/csl-bot/csl-doc-tracker/app.py"

# ── Step 1: Database changes ─────────────────────────────────────────────
print("[1/4] Updating database...")

import psycopg2
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()

# Add account column to team_tasks (if not exists)
cur.execute("""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'team_tasks' AND column_name = 'account'
    ) THEN
        ALTER TABLE team_tasks ADD COLUMN account TEXT;
    END IF;
END $$;
""")

# Create task_documents table
cur.execute("""
CREATE TABLE IF NOT EXISTS task_documents (
    id            SERIAL PRIMARY KEY,
    task_id       INTEGER NOT NULL REFERENCES team_tasks(id) ON DELETE CASCADE,
    doc_type      TEXT NOT NULL DEFAULT 'other',
    filename      TEXT NOT NULL,
    original_name TEXT NOT NULL,
    size_bytes    INTEGER DEFAULT 0,
    uploaded_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_taskdocs_task ON task_documents(task_id);
""")

conn.commit()
cur.close()
conn.close()
print("   account column added + task_documents table created.")

# ── Step 2: Create uploads directory ─────────────────────────────────────
print("[2/4] Creating uploads/tasks/ directory...")
os.makedirs("/root/csl-bot/csl-doc-tracker/uploads/tasks", exist_ok=True)
print("   Directory ready.")

# ── Step 3: Update existing task endpoints for account field ────────────
print("[3/4] Updating existing task endpoints for account field...")

with open(APP, "r") as f:
    code = f.read()

# Update GET /api/tasks to include account in SELECT
old_select = (
    'f"SELECT id, task_type, assignee, efj, description, "'
    '\n            f"completed, completed_at::text, completed_note, created_at::text "'
)
new_select = (
    'f"SELECT id, task_type, assignee, efj, description, account, "'
    '\n            f"completed, completed_at::text, completed_note, created_at::text "'
)
if 'account,' not in code.split('FROM team_tasks')[0].split('SELECT')[-1] if 'FROM team_tasks' in code else '':
    code = code.replace(old_select, new_select)

# Update POST /api/tasks to accept account
old_post_extract = '''    efj = (body.get("efj") or "").strip() or None
    description = (body.get("description") or "").strip() or None

    if not task_type or not assignee:
        return JSONResponse({"error": "task_type and assignee required"}, status_code=400)

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO team_tasks (task_type, assignee, efj, description) "
                "VALUES (%s, %s, %s, %s) RETURNING id, created_at::text",
                (task_type, assignee, efj, description)
            )'''

new_post_extract = '''    efj = (body.get("efj") or "").strip() or None
    description = (body.get("description") or "").strip() or None
    account = (body.get("account") or "").strip() or None

    if not task_type or not assignee:
        return JSONResponse({"error": "task_type and assignee required"}, status_code=400)

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO team_tasks (task_type, assignee, efj, description, account) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id, created_at::text",
                (task_type, assignee, efj, description, account)
            )'''

code = code.replace(old_post_extract, new_post_extract)

# Update PATCH /api/tasks to handle account field
old_patch_fields = '''    for field in ("task_type", "assignee", "description", "efj"):'''
new_patch_fields = '''    for field in ("task_type", "assignee", "description", "efj", "account"):'''
code = code.replace(old_patch_fields, new_patch_fields)

with open(APP, "w") as f:
    f.write(code)
print("   Existing endpoints updated for account field.")

# ── Step 4: Add task document endpoints ──────────────────────────────────
print("[4/4] Adding task document endpoints...")

TASK_DOC_CODE = '''

# ═══════════════════════════════════════════════════════════════
# TASK DOCUMENTS API
# ═══════════════════════════════════════════════════════════════

@app.get("/api/tasks/{task_id}/documents")
async def get_task_documents(task_id: int):
    """List documents for a task."""
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT id, doc_type, original_name, size_bytes, uploaded_at::text "
            "FROM task_documents WHERE task_id = %s ORDER BY uploaded_at DESC",
            (task_id,)
        )
        rows = cur.fetchall()
    return JSONResponse({"documents": [dict(r) for r in rows]})


@app.post("/api/tasks/{task_id}/documents")
async def upload_task_document(task_id: int, file: UploadFile = File(...), doc_type: str = Form("other")):
    """Upload a document to a task."""
    import uuid as _uuid
    upload_dir = f"/root/csl-bot/csl-doc-tracker/uploads/tasks/{task_id}"
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{_uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_name)
    contents = await file.read()
    with open(file_path, "wb") as f:
        f.write(contents)
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO task_documents (task_id, doc_type, filename, original_name, size_bytes) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (task_id, doc_type, safe_name, file.filename, len(contents))
            )
            doc_id = cur.fetchone()["id"]
    return JSONResponse({"ok": True, "id": doc_id, "original_name": file.filename})


@app.delete("/api/tasks/{task_id}/documents/{doc_id}")
async def delete_task_document(task_id: int, doc_id: int):
    """Delete a task document."""
    with db.get_cursor() as cur:
        cur.execute("SELECT filename FROM task_documents WHERE id = %s AND task_id = %s", (doc_id, task_id))
        row = cur.fetchone()
    if row:
        file_path = f"/root/csl-bot/csl-doc-tracker/uploads/tasks/{task_id}/{row['filename']}"
        if os.path.exists(file_path):
            os.remove(file_path)
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("DELETE FROM task_documents WHERE id = %s AND task_id = %s", (doc_id, task_id))
    return JSONResponse({"ok": True})


@app.get("/api/tasks/{task_id}/documents/{doc_id}/download")
async def download_task_document(task_id: int, doc_id: int, request: Request):
    """Download or preview a task document."""
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT filename, original_name FROM task_documents WHERE id = %s AND task_id = %s",
            (doc_id, task_id)
        )
        row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "not found"})
    file_path = f"/root/csl-bot/csl-doc-tracker/uploads/tasks/{task_id}/{row['filename']}"
    if not os.path.exists(file_path):
        return JSONResponse(status_code=404, content={"error": "file missing"})
    inline = request.query_params.get("inline", "").lower() in ("true", "1")
    if inline:
        import mimetypes
        media_type = mimetypes.guess_type(row["original_name"])[0] or "application/octet-stream"
        return FileResponse(
            file_path,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{row["original_name"]}"'}
        )
    return FileResponse(file_path, filename=row["original_name"])
'''

with open(APP, "r") as f:
    code = f.read()

if "/api/tasks/{task_id}/documents" in code:
    print("   Task document endpoints already exist! Skipping.")
else:
    marker = '@app.get("/app")'
    if marker in code:
        code = code.replace(marker, TASK_DOC_CODE + "\n\n" + marker)
        with open(APP, "w") as f:
            f.write(code)
        print("   Task document endpoints injected.")
    else:
        code += TASK_DOC_CODE
        with open(APP, "w") as f:
            f.write(code)
        print("   Task document endpoints appended.")

print("\n✅ Done! Restart with: systemctl restart csl-dashboard")
