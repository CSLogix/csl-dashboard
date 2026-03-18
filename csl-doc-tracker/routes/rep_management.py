"""
Rep management routes: account assignment + manual tasks.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

import database as db

log = logging.getLogger(__name__)
router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# REP-ACCOUNT ASSIGNMENTS
# ═══════════════════════════════════════════════════════════════

@router.get("/api/rep-accounts")
async def get_rep_accounts():
    """Return rep -> accounts mapping from DB."""
    with db.get_cursor() as cur:
        cur.execute("SELECT rep_name, accounts FROM rep_accounts ORDER BY rep_name")
        rows = cur.fetchall()
    result = {}
    for row in rows:
        accounts = row["accounts"] or []
        result[row["rep_name"]] = accounts
    return {"rep_accounts": result}


@router.post("/api/rep-accounts")
async def update_rep_accounts(request: Request):
    """Update account assignments for a rep."""
    body = await request.json()
    rep_name = body.get("rep_name", "").strip()
    accounts = body.get("accounts", [])
    if not rep_name:
        raise HTTPException(400, "Missing rep_name")
    if not isinstance(accounts, list):
        raise HTTPException(400, "accounts must be a list")

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO rep_accounts (rep_name, accounts, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (rep_name)
                DO UPDATE SET accounts = EXCLUDED.accounts, updated_at = NOW()
            """, (rep_name, accounts))

    log.info("Updated rep_accounts: %s -> %s", rep_name, accounts)
    return {"ok": True}


@router.post("/api/rep-accounts/bulk")
async def bulk_update_rep_accounts(request: Request):
    """Bulk update all rep-account assignments at once."""
    body = await request.json()
    assignments = body.get("assignments", {})
    if not isinstance(assignments, dict):
        raise HTTPException(400, "assignments must be an object")

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            for rep_name, accounts in assignments.items():
                if not isinstance(accounts, list):
                    continue
                cur.execute("""
                    INSERT INTO rep_accounts (rep_name, accounts, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (rep_name)
                    DO UPDATE SET accounts = EXCLUDED.accounts, updated_at = NOW()
                """, (rep_name.strip(), accounts))

    log.info("Bulk updated rep_accounts for %d reps", len(assignments))
    return {"ok": True}


@router.delete("/api/rep-accounts/{rep_name}")
async def delete_rep(rep_name: str):
    """Remove a rep from the assignments table."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("DELETE FROM rep_accounts WHERE rep_name = %s", (rep_name,))
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
# REP TASKS (Manual action items)
# ═══════════════════════════════════════════════════════════════

@router.get("/api/rep-tasks")
async def get_rep_tasks(rep: str = None):
    """Return open tasks, optionally filtered by rep."""
    with db.get_cursor() as cur:
        if rep:
            cur.execute("""
                SELECT id, rep, text, efj, auto_type, assigned_by, status, created_at
                FROM rep_tasks
                WHERE rep = %s AND status = 'open'
                ORDER BY created_at DESC
            """, (rep,))
        else:
            cur.execute("""
                SELECT id, rep, text, efj, auto_type, assigned_by, status, created_at
                FROM rep_tasks
                WHERE status = 'open'
                ORDER BY created_at DESC
            """)
        rows = cur.fetchall()

    tasks = []
    for r in rows:
        tasks.append({
            "id": r["id"],
            "rep": r["rep"],
            "text": r["text"],
            "efj": r["efj"],
            "auto_type": r["auto_type"],
            "assigned_by": r["assigned_by"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })
    return {"tasks": tasks}


@router.post("/api/rep-tasks")
async def create_task(request: Request):
    """Create a new manual task for a rep."""
    body = await request.json()
    rep = body.get("rep", "").strip()
    text = body.get("text", "").strip()
    efj = body.get("efj", "").strip() or None
    auto_type = body.get("auto_type") or None
    assigned_by = body.get("assigned_by", "").strip() or None

    if not rep or not text:
        raise HTTPException(400, "Missing rep or text")

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO rep_tasks (rep, text, efj, auto_type, assigned_by, status)
                VALUES (%s, %s, %s, %s, %s, 'open')
                RETURNING id
            """, (rep, text, efj, auto_type, assigned_by))
            task_id = cur.fetchone()["id"]

    return {"ok": True, "id": task_id}


@router.post("/api/rep-tasks/{task_id}/complete")
async def complete_task(task_id: int):
    """Mark a task as completed."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("""
                UPDATE rep_tasks SET status = 'completed', completed_at = NOW()
                WHERE id = %s
            """, (task_id,))
    return {"ok": True}


@router.delete("/api/rep-tasks/{task_id}")
async def delete_task(task_id: int):
    """Delete a task."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("DELETE FROM rep_tasks WHERE id = %s", (task_id,))
    return {"ok": True}


@router.post("/api/rep-tasks/auto-clear")
async def auto_clear_tasks(request: Request):
    """Auto-clear tasks based on conditions (e.g., driver assigned)."""
    body = await request.json()
    efj = body.get("efj", "").strip()
    clear_type = body.get("clear_type", "").strip()  # e.g. "driver_assigned", "delivered"

    if not efj or not clear_type:
        raise HTTPException(400, "Missing efj or clear_type")

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            if clear_type == "driver_assigned":
                cur.execute("""
                    UPDATE rep_tasks SET status = 'auto_cleared', completed_at = NOW()
                    WHERE efj = %s AND status = 'open'
                    AND (auto_type IN ('needs_driver', 'cover_load') OR text ILIKE '%%driver%%' OR text ILIKE '%%carrier%%')
                """, (efj,))
            elif clear_type == "delivered":
                cur.execute("""
                    UPDATE rep_tasks SET status = 'auto_cleared', completed_at = NOW()
                    WHERE efj = %s AND status = 'open'
                    AND auto_type IN ('close_out', 'cover_load', 'pro_load', 'needs_driver')
                """, (efj,))
            elif clear_type == "pro_assigned":
                cur.execute("""
                    UPDATE rep_tasks SET status = 'auto_cleared', completed_at = NOW()
                    WHERE efj = %s AND status = 'open' AND auto_type = 'pro_load'
                """, (efj,))
            else:
                cur.execute("""
                    UPDATE rep_tasks SET status = 'auto_cleared', completed_at = NOW()
                    WHERE efj = %s AND status = 'open' AND auto_type = %s
                """, (efj, clear_type))

    return {"ok": True}
