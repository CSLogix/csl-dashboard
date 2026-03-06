#!/usr/bin/env python3
"""
Patch: Inbox Command Center API
Adds unified inbox endpoint with thread-level grouping + sent-reply detection.

Endpoints:
  GET  /api/inbox              — Thread-grouped emails with reply detection
  POST /api/inbox/{id}/feedback — Classification feedback (correct/incorrect)
  GET  /api/inbox/reply-alerts  — Unreplied customer quote thread alerts

Also modifies GET /api/v2/shipments to include email_count + email_max_priority.

Run on server:
    python3 /tmp/patch_inbox_api.py
"""

import re, shutil, os, sys
from datetime import datetime

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

def backup(path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{path}.bak_{ts}"
    shutil.copy2(path, bak)
    print(f"Backup: {bak}")

INBOX_ENDPOINTS = '''

# ── Inbox Command Center Endpoints ──────────────────────────────────

@app.get("/api/inbox")
async def get_inbox(request: Request):
    """Unified inbox: thread-grouped emails with sent-reply detection."""
    from urllib.parse import parse_qs
    params = dict(request.query_params)
    days = int(params.get("days", "7"))
    tab = params.get("tab", "all")
    email_type_filter = params.get("type", "")
    priority_min = int(params.get("priority_min", "0"))
    rep_filter = params.get("rep", "")
    limit = min(int(params.get("limit", "200")), 500)

    with db.get_cursor() as cur:
        # Fetch all inbound emails (matched + unmatched) from the lookback window
        cur.execute("""
            SELECT
                e.id, e.gmail_thread_id, e.gmail_message_id, e.subject, e.sender,
                e.body_preview, e.has_attachments, e.attachment_names,
                e.sent_at, e.email_type, e.lane, e.priority, e.ai_summary,
                e.classification_feedback, e.corrected_type,
                e.efj, NULL as review_status, NULL as suggested_rep,
                'matched' as source
            FROM email_threads e
            WHERE e.sent_at >= NOW() - INTERVAL '%s days'
            UNION ALL
            SELECT
                u.id, u.gmail_thread_id, u.gmail_message_id, u.subject, u.sender,
                u.body_preview, u.has_attachments, u.attachment_names,
                u.sent_at, u.email_type, u.lane, u.priority, u.ai_summary,
                u.classification_feedback, u.corrected_type,
                NULL as efj, u.review_status, u.suggested_rep,
                'unmatched' as source
            FROM unmatched_inbox_emails u
            WHERE u.sent_at >= NOW() - INTERVAL '%s days'
              AND u.review_status = 'pending'
            ORDER BY sent_at DESC
        """ % (days, days))
        inbound_rows = cur.fetchall()

        # Fetch all sent messages from the lookback window
        cur.execute("""
            SELECT gmail_thread_id, gmail_message_id, recipient, subject, sent_at
            FROM sent_messages
            WHERE sent_at >= NOW() - INTERVAL '%s days'
            ORDER BY sent_at ASC
        """ % days)
        sent_rows = cur.fetchall()

    # Build sent lookup: thread_id -> list of sent timestamps
    sent_by_thread = {}
    sent_msgs_by_thread = {}
    for s in sent_rows:
        tid = s["gmail_thread_id"]
        if tid not in sent_by_thread:
            sent_by_thread[tid] = []
            sent_msgs_by_thread[tid] = []
        sent_by_thread[tid].append(s["sent_at"])
        sent_msgs_by_thread[tid].append({
            "id": None,
            "sender": "You",
            "subject": s["subject"],
            "sent_at": s["sent_at"].isoformat() if s["sent_at"] else None,
            "body_preview": None,
            "direction": "sent",
        })

    # Group inbound by thread_id
    threads_map = {}
    for row in inbound_rows:
        tid = row["gmail_thread_id"] or row["gmail_message_id"]  # fallback if no thread
        if tid not in threads_map:
            threads_map[tid] = {
                "thread_id": tid,
                "efj": row["efj"],
                "messages": [],
                "max_priority": 0,
                "email_type": None,
                "ai_summary": None,
                "lane": None,
                "has_attachments": False,
                "source": row["source"],
                "review_status": row["review_status"],
                "suggested_rep": row["suggested_rep"],
                "classification_feedback": row["classification_feedback"],
            }

        thread = threads_map[tid]
        thread["messages"].append({
            "id": row["id"],
            "sender": row["sender"],
            "subject": row["subject"],
            "sent_at": row["sent_at"].isoformat() if row["sent_at"] else None,
            "body_preview": row["body_preview"],
            "direction": "inbound",
            "has_attachments": row["has_attachments"],
            "attachment_names": row["attachment_names"],
            "email_type": row["email_type"],
            "priority": row["priority"],
            "ai_summary": row["ai_summary"],
        })

        # Track thread-level aggregates
        p = row["priority"] or 0
        if p > thread["max_priority"]:
            thread["max_priority"] = p
            thread["email_type"] = row["email_type"]
            thread["ai_summary"] = row["ai_summary"]
        if row["lane"]:
            thread["lane"] = row["lane"]
        if row["has_attachments"]:
            thread["has_attachments"] = True
        if row["efj"]:
            thread["efj"] = row["efj"]
        if row["source"] == "matched":
            thread["source"] = "matched"
        if row["suggested_rep"]:
            thread["suggested_rep"] = row["suggested_rep"]

    # Build final thread list with reply detection
    threads = []
    for tid, thread in threads_map.items():
        # Sort messages chronologically
        all_msgs = thread["messages"][:]
        # Add sent messages for this thread
        if tid in sent_msgs_by_thread:
            all_msgs.extend(sent_msgs_by_thread[tid])
        all_msgs.sort(key=lambda m: m["sent_at"] or "")

        # Determine latest message and reply status
        latest_msg = all_msgs[-1] if all_msgs else None
        latest_inbound = [m for m in thread["messages"]]
        latest_inbound.sort(key=lambda m: m["sent_at"] or "")
        latest_inbound_msg = latest_inbound[-1] if latest_inbound else None

        # has_csl_reply: any sent message AFTER the latest inbound
        has_csl_reply = False
        if latest_inbound_msg and tid in sent_by_thread:
            latest_inbound_time = latest_inbound_msg["sent_at"]
            for st in sent_by_thread[tid]:
                if st and latest_inbound_time and st.isoformat() > latest_inbound_time:
                    has_csl_reply = True
                    break

        # needs_reply: latest message is inbound + no CSL reply after it
        needs_reply = (
            latest_msg is not None
            and latest_msg.get("direction") == "inbound"
            and not has_csl_reply
        )

        thread_start = thread["messages"][0]["sent_at"] if thread["messages"] else None

        threads.append({
            "thread_id": tid,
            "efj": thread["efj"],
            "message_count": len(all_msgs),
            "latest_subject": latest_msg["subject"] if latest_msg else None,
            "latest_sender": latest_msg["sender"] if latest_msg else None,
            "latest_sent_at": latest_msg["sent_at"] if latest_msg else None,
            "thread_start": thread_start,
            "max_priority": thread["max_priority"],
            "email_type": thread["email_type"],
            "ai_summary": thread["ai_summary"],
            "lane": thread["lane"],
            "has_attachments": thread["has_attachments"],
            "has_csl_reply": has_csl_reply,
            "needs_reply": needs_reply,
            "suggested_rep": thread["suggested_rep"],
            "source": thread["source"],
            "review_status": thread["review_status"],
            "classification_feedback": thread["classification_feedback"],
            "messages": all_msgs,
        })

    # Sort by priority DESC, then latest_sent_at DESC
    threads.sort(key=lambda t: (-(t["max_priority"] or 0), t["latest_sent_at"] or ""), reverse=False)
    threads.sort(key=lambda t: -(t["max_priority"] or 0))

    # Apply tab filter
    if tab == "needs_reply":
        threads = [t for t in threads if t["needs_reply"]]
    elif tab == "unmatched":
        threads = [t for t in threads if t["source"] == "unmatched"]
    elif tab == "rates":
        threads = [t for t in threads if t["email_type"] in ("carrier_rate", "customer_rate")]

    # Apply additional filters
    if email_type_filter:
        types = set(email_type_filter.split(","))
        threads = [t for t in threads if t["email_type"] in types]
    if priority_min > 0:
        threads = [t for t in threads if (t["max_priority"] or 0) >= priority_min]
    if rep_filter:
        threads = [t for t in threads if t.get("suggested_rep") == rep_filter]

    # Stats
    all_threads = list(threads_map.values())
    stats = {
        "total_threads": len(threads_map),
        "needs_reply": sum(1 for t in threads if t["needs_reply"]),
        "unmatched": sum(1 for t in threads_map.values() if t["source"] == "unmatched"),
        "high_priority": sum(1 for t in threads_map.values() if t["max_priority"] >= 4),
    }

    return JSONResponse({
        "threads": threads[:limit],
        "stats": stats,
    })


@app.post("/api/inbox/{email_id}/feedback")
async def inbox_classification_feedback(email_id: int, request: Request):
    """Store classification feedback (correct/incorrect) for an email."""
    body = await request.json()
    feedback = body.get("feedback")  # "correct" or "incorrect"
    corrected_type = body.get("corrected_type")  # only if incorrect

    if feedback not in ("correct", "incorrect"):
        raise HTTPException(400, "feedback must be 'correct' or 'incorrect'")

    # Try email_threads first, then unmatched
    updated = False
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                """UPDATE email_threads
                   SET classification_feedback = %s, corrected_type = %s
                   WHERE id = %s""",
                (feedback, corrected_type if feedback == "incorrect" else None, email_id),
            )
            if cur.rowcount > 0:
                updated = True
            else:
                cur.execute(
                    """UPDATE unmatched_inbox_emails
                       SET classification_feedback = %s, corrected_type = %s
                       WHERE id = %s""",
                    (feedback, corrected_type if feedback == "incorrect" else None, email_id),
                )
                if cur.rowcount > 0:
                    updated = True

    if not updated:
        raise HTTPException(404, "Email not found")

    return JSONResponse({"status": "ok", "feedback": feedback})


@app.get("/api/inbox/reply-alerts")
async def get_inbox_reply_alerts():
    """Return unreplied customer quote emails (threads needing reply)."""
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT ca.id, ca.email_thread_id, ca.efj, ca.sender, ca.subject,
                   ca.alerted_at, ca.dismissed
            FROM customer_reply_alerts ca
            WHERE ca.dismissed = false
            ORDER BY ca.alerted_at DESC
            LIMIT 50
        """)
        rows = cur.fetchall()

    alerts = []
    for r in rows:
        alerts.append({
            "id": r["id"],
            "email_thread_id": r["email_thread_id"],
            "efj": r["efj"],
            "sender": r["sender"],
            "subject": r["subject"],
            "alerted_at": r["alerted_at"].isoformat() if r["alerted_at"] else None,
        })

    return JSONResponse({"alerts": alerts, "count": len(alerts)})

'''


def patch():
    if not os.path.exists(APP_PY):
        print(f"ERROR: {APP_PY} not found"); sys.exit(1)

    backup(APP_PY)
    code = open(APP_PY).read()
    changes = 0

    # ── 1. Add inbox endpoints ──
    if "/api/inbox" in code and "get_inbox" in code:
        print("= Inbox endpoints already exist")
    else:
        marker = '@app.get("/health")'
        if marker in code:
            code = code.replace(marker, INBOX_ENDPOINTS + "\n\n" + marker)
            print("+ Added inbox command center endpoints")
            changes += 1
        else:
            code += INBOX_ENDPOINTS
            print("+ Appended inbox endpoints to end of file")
            changes += 1

    # ── 2. Add email stats to /api/v2/shipments ──
    # Look for the v2 shipments query and add LEFT JOIN for email counts
    if "email_count" not in code:
        # Find the v2 shipments SELECT
        old_v2 = "SELECT * FROM shipments WHERE archived = false"
        if old_v2 in code:
            new_v2 = """SELECT s.*,
                COALESCE(ec.email_count, 0) as email_count,
                COALESCE(ec.email_max_priority, 0) as email_max_priority
            FROM shipments s
            LEFT JOIN (
                SELECT efj, COUNT(*) as email_count, COALESCE(MAX(priority), 0) as email_max_priority
                FROM email_threads
                GROUP BY efj
            ) ec ON s.efj = ec.efj
            WHERE s.archived = false"""
            code = code.replace(old_v2, new_v2)
            print("+ Added email stats JOIN to /api/v2/shipments")
            changes += 1
        else:
            print("WARNING: Could not find v2 shipments query — email stats not added")
    else:
        print("= email_count already in v2 shipments query")

    if changes > 0:
        open(APP_PY, "w").write(code)
        print(f"\n{changes} changes applied.")
        print("Restart: systemctl restart csl-dashboard")
    else:
        print("\nNo changes needed.")


if __name__ == "__main__":
    patch()
