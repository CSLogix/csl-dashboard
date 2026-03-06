#!/usr/bin/env python3
"""
Patch: Add team tasks API endpoints to app.py
- Creates team_tasks table in PostgreSQL
- Adds endpoints: GET /api/tasks, POST /api/tasks,
  PATCH /api/tasks/{id}, DELETE /api/tasks/{id}
"""

import subprocess, sys, textwrap

APP = "/root/csl-bot/csl-doc-tracker/app.py"

# ── Step 1: Create DB table ────────────────────────────────────────────────
print("[1/3] Creating team_tasks table...")

import psycopg2
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS team_tasks (
    id              SERIAL PRIMARY KEY,
    task_type       TEXT NOT NULL,
    assignee        TEXT NOT NULL,
    efj             TEXT,
    description     TEXT,
    completed       BOOLEAN DEFAULT FALSE,
    completed_at    TIMESTAMPTZ,
    completed_note  TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON team_tasks(assignee);
CREATE INDEX IF NOT EXISTS idx_tasks_completed ON team_tasks(completed);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON team_tasks(created_at DESC);
""")
conn.commit()
cur.close()
conn.close()
print("   Table created (or already exists).")

# ── Step 2: Add task endpoints to app.py ─────────────────────────────────
print("[2/3] Patching app.py with task endpoints...")

TASK_CODE = '''

# ═══════════════════════════════════════════════════════════════
# TEAM TASKS API
# ═══════════════════════════════════════════════════════════════

@app.get("/api/tasks")
def api_tasks_list(request: Request):
    """List team tasks. ?status=open|completed|all (default: open). ?assignee=Name"""
    status_filter = request.query_params.get("status", "open")
    assignee = request.query_params.get("assignee", None)

    with db.get_cursor() as cur:
        where = []
        params = []
        if status_filter == "open":
            where.append("completed = FALSE")
        elif status_filter == "completed":
            where.append("completed = TRUE")

        if assignee:
            where.append("assignee = %s")
            params.append(assignee)

        where_clause = "WHERE " + " AND ".join(where) if where else ""
        cur.execute(
            f"SELECT id, task_type, assignee, efj, description, "
            f"completed, completed_at::text, completed_note, created_at::text "
            f"FROM team_tasks {where_clause} "
            f"ORDER BY completed ASC, created_at DESC",
            params
        )
        rows = cur.fetchall()
    return JSONResponse({"tasks": [dict(r) for r in rows]})


@app.post("/api/tasks")
async def api_tasks_create(request: Request):
    """Create a new task."""
    body = await request.json()
    task_type = (body.get("task_type") or "").strip()
    assignee = (body.get("assignee") or "").strip()
    efj = (body.get("efj") or "").strip() or None
    description = (body.get("description") or "").strip() or None

    if not task_type or not assignee:
        return JSONResponse({"error": "task_type and assignee required"}, status_code=400)

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO team_tasks (task_type, assignee, efj, description) "
                "VALUES (%s, %s, %s, %s) RETURNING id, created_at::text",
                (task_type, assignee, efj, description)
            )
            row = cur.fetchone()
    return JSONResponse({"ok": True, "id": row["id"], "created_at": row["created_at"]})


@app.patch("/api/tasks/{task_id}")
async def api_tasks_update(task_id: int, request: Request):
    """Update or complete a task."""
    body = await request.json()

    sets = []
    params = []

    if "completed" in body:
        if body["completed"]:
            sets.append("completed = TRUE")
            sets.append("completed_at = NOW()")
            note = (body.get("completed_note") or "").strip() or None
            sets.append("completed_note = %s")
            params.append(note)
        else:
            sets.append("completed = FALSE")
            sets.append("completed_at = NULL")
            sets.append("completed_note = NULL")

    for field in ("task_type", "assignee", "description", "efj"):
        if field in body and "completed" not in body:
            val = body[field]
            if isinstance(val, str):
                val = val.strip() or None
            sets.append(f"{field} = %s")
            params.append(val)

    if not sets:
        return JSONResponse({"error": "No fields to update"}, status_code=400)

    params.append(task_id)
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                f"UPDATE team_tasks SET {', '.join(sets)} WHERE id = %s",
                params
            )
    return JSONResponse({"ok": True})


@app.delete("/api/tasks/{task_id}")
def api_tasks_delete(task_id: int):
    """Delete a task."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("DELETE FROM team_tasks WHERE id = %s", (task_id,))
    return JSONResponse({"ok": True})
'''

# Read current app.py
with open(APP, "r") as f:
    code = f.read()

# Check if already patched
if "/api/tasks" in code:
    print("   Already patched! Skipping.")
else:
    marker = '@app.get("/app")'
    if marker in code:
        code = code.replace(marker, TASK_CODE + "\n\n" + marker)
        with open(APP, "w") as f:
            f.write(code)
        print("   Patched successfully.")
    else:
        code += TASK_CODE
        with open(APP, "w") as f:
            f.write(code)
        print("   Appended to end of file.")

# ── Step 3: Verify auth bypass ───────────────────────────────────────────
print("[3/3] Checking auth bypass...")

with open(APP, "r") as f:
    code = f.read()

if 'path.startswith("/api/")' in code:
    print("   /api/ paths already bypassed in auth middleware. No change needed.")
else:
    print("   WARNING: May need to add /api/tasks to auth bypass manually.")

print("\n✅ Done! Restart with: systemctl restart csl-dashboard")
