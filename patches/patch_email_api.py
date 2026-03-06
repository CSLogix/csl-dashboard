#!/usr/bin/env python3
"""
Patch app.py to add email history + unmatched email endpoints.

Adds:
  GET  /api/load/{efj}/emails          — email thread history for a load
  GET  /api/unmatched-emails            — list unmatched inbox emails
  POST /api/unmatched-emails/{id}/assign — assign unmatched email to a load
  POST /api/unmatched-emails/{id}/dismiss — dismiss unmatched email

Run on server:
    python3 /tmp/patch_email_api.py
"""

import re

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

ENDPOINTS_CODE = '''

# ── Email History & Unmatched Inbox Endpoints ──

@app.get("/api/load/{efj}/emails")
async def get_load_emails(efj: str):
    """Return indexed emails for a load, newest first."""
    with db.get_cursor() as cur:
        cur.execute(
            """SELECT id, gmail_message_id, gmail_thread_id, subject, sender,
                      recipients, body_preview, has_attachments, attachment_names,
                      sent_at, indexed_at
               FROM email_threads
               WHERE efj = %s
               ORDER BY sent_at DESC NULLS LAST""",
            (efj,)
        )
        rows = cur.fetchall()
    emails = [
        {
            "id": r["id"],
            "gmail_message_id": r["gmail_message_id"],
            "subject": r["subject"],
            "sender": r["sender"],
            "recipients": r["recipients"],
            "body_preview": r["body_preview"],
            "has_attachments": r["has_attachments"],
            "attachment_names": r["attachment_names"],
            "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
            "indexed_at": r["indexed_at"].isoformat() if r["indexed_at"] else None,
        }
        for r in rows
    ]
    return JSONResponse({"emails": emails, "count": len(emails)})


@app.get("/api/unmatched-emails")
async def get_unmatched_emails():
    """List unmatched inbox emails pending review."""
    with db.get_cursor() as cur:
        cur.execute(
            """SELECT id, gmail_message_id, subject, sender, recipients,
                      body_preview, has_attachments, attachment_names,
                      sent_at, indexed_at, review_status
               FROM unmatched_inbox_emails
               WHERE review_status = 'pending'
               ORDER BY sent_at DESC NULLS LAST
               LIMIT 100""",
        )
        rows = cur.fetchall()
    emails = [
        {
            "id": r["id"],
            "subject": r["subject"],
            "sender": r["sender"],
            "body_preview": r["body_preview"],
            "has_attachments": r["has_attachments"],
            "attachment_names": r["attachment_names"],
            "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
            "review_status": r["review_status"],
        }
        for r in rows
    ]
    return JSONResponse({"emails": emails, "count": len(emails)})


@app.post("/api/unmatched-emails/{email_id}/assign")
async def assign_unmatched_email(email_id: int, request: Request):
    """Assign an unmatched email to a load by EFJ#."""
    body = await request.json()
    efj = body.get("efj", "").strip().upper()
    if not efj:
        raise HTTPException(400, "efj is required")

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            # Get the unmatched email
            cur.execute(
                "SELECT * FROM unmatched_inbox_emails WHERE id = %s AND review_status = 'pending'",
                (email_id,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Email not found or already processed")

            # Move to email_threads
            cur.execute(
                """INSERT INTO email_threads
                   (efj, gmail_thread_id, gmail_message_id, subject, sender,
                    recipients, body_preview, has_attachments, attachment_names, sent_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (gmail_message_id) DO NOTHING""",
                (efj, row["gmail_thread_id"], row["gmail_message_id"],
                 row["subject"], row["sender"], row["recipients"],
                 row["body_preview"], row["has_attachments"],
                 row["attachment_names"], row["sent_at"]),
            )

            # Mark as assigned
            cur.execute(
                "UPDATE unmatched_inbox_emails SET review_status = 'assigned', assigned_efj = %s WHERE id = %s",
                (efj, email_id),
            )

    log.info("Unmatched email %d assigned to %s", email_id, efj)
    return JSONResponse({"status": "ok", "efj": efj})


@app.post("/api/unmatched-emails/{email_id}/dismiss")
async def dismiss_unmatched_email(email_id: int):
    """Dismiss an unmatched email (mark as not relevant)."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE unmatched_inbox_emails SET review_status = 'dismissed' WHERE id = %s",
                (email_id,),
            )
    return JSONResponse({"status": "ok"})
'''

def patch():
    with open(APP_PY, "r") as f:
        content = f.read()

    # Check if already patched
    if "/api/load/{efj}/emails" in content:
        print("Already patched — email endpoints exist")
        return

    # Find the health check endpoint (near the end) and insert before it
    marker = '@app.get("/health")'
    if marker not in content:
        # Fallback: append to end of file
        content += ENDPOINTS_CODE
    else:
        content = content.replace(marker, ENDPOINTS_CODE + "\n\n" + marker)

    with open(APP_PY, "w") as f:
        f.write(content)

    print(f"Patched {APP_PY}")
    print("Added endpoints:")
    print("  GET  /api/load/{efj}/emails")
    print("  GET  /api/unmatched-emails")
    print("  POST /api/unmatched-emails/{id}/assign")
    print("  POST /api/unmatched-emails/{id}/dismiss")


if __name__ == "__main__":
    patch()
