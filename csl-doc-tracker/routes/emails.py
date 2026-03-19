import logging
from datetime import datetime
from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import JSONResponse
import database as db
import config

log = logging.getLogger(__name__)
router = APIRouter()


# ── Customer Reply Alerts ─────────────────────────────────────────────────


@router.get("/api/customer-reply-alerts")
async def api_customer_reply_alerts():
    """Get active customer reply alerts (unreplied for 15+ min)."""
    with db.get_cursor() as cur:
        cur.execute("""
        SELECT cra.id, cra.email_thread_id, cra.efj, cra.sender,
               cra.subject, cra.alerted_at, cra.dismissed
        FROM customer_reply_alerts cra
        WHERE cra.dismissed = FALSE
        ORDER BY cra.alerted_at DESC
        LIMIT 50
        """)
        alerts = cur.fetchall()
    return [
        {
            "id": a["id"], "email_thread_id": a["email_thread_id"],
            "efj": a["efj"], "sender": a["sender"], "subject": a["subject"],
            "alerted_at": a["alerted_at"].isoformat() if a["alerted_at"] else None,
        }
        for a in alerts
    ]


@router.post("/api/customer-reply-alerts/{alert_id}/dismiss")
async def dismiss_customer_reply_alert(alert_id: int):
    """Dismiss a customer reply alert."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE customer_reply_alerts SET dismissed = TRUE WHERE id = %s RETURNING id",
                (alert_id,),
            )
            row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "alert not found"})
    return {"ok": True}


# ── Load Emails ───────────────────────────────────────────────────────────


@router.get("/api/load/{efj}/emails")
async def get_load_emails(efj: str):
    """Return indexed emails for a load, newest first."""
    with db.get_cursor() as cur:
        cur.execute(
        """SELECT id, gmail_message_id, gmail_thread_id, subject, sender,
                  recipients, body_preview, has_attachments, attachment_names,
                  sent_at, indexed_at, email_type, lane, priority, ai_summary
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
            "email_type": r.get("email_type"),
            "lane": r.get("lane"),
            "priority": r.get("priority"),
            "ai_summary": r.get("ai_summary"),
        }
        for r in rows
    ]
    return JSONResponse({"emails": emails, "count": len(emails)})


@router.get("/api/email/{email_id}/body")
async def get_email_body(email_id: int):
    """Fetch the full email body from Gmail for preview."""
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT gmail_message_id, subject, sender, recipients FROM email_threads WHERE id = %s",
            (email_id,),
        )
        row = cur.fetchone()
    if not row:
        # Try unmatched
        with db.get_cursor() as cur:
            cur.execute(
                "SELECT gmail_message_id, subject, sender, recipients FROM unmatched_inbox_emails WHERE id = %s",
                (email_id,),
            )
            row = cur.fetchone()
    if not row or not row["gmail_message_id"]:
        return JSONResponse({"body_html": None, "body_text": None, "error": "Email not found"}, status_code=404)

    try:
        import base64
        from gmail_monitor import _get_gmail_service
        service = _get_gmail_service()
        msg = service.users().messages().get(
            userId="me", id=row["gmail_message_id"], format="full"
        ).execute()

        body_html = None
        body_text = None

        def _extract_parts(payload):
            nonlocal body_html, body_text
            mime = payload.get("mimeType", "")
            if mime == "text/html" and not body_html:
                data = payload.get("body", {}).get("data", "")
                if data:
                    body_html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            elif mime == "text/plain" and not body_text:
                data = payload.get("body", {}).get("data", "")
                if data:
                    body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            for part in payload.get("parts", []):
                _extract_parts(part)

        _extract_parts(msg.get("payload", {}))

        return JSONResponse({
            "body_html": body_html,
            "body_text": body_text,
            "subject": row["subject"],
            "sender": row["sender"],
            "recipients": row["recipients"],
        })
    except Exception as e:
        log.error("Failed to fetch email body for id=%d: %s", email_id, e)
        return JSONResponse({"body_html": None, "body_text": None, "error": str(e)}, status_code=500)


@router.post("/api/load/{efj}/summary")
async def api_load_summary(efj: str, request: Request):
    """Generate an AI-powered operational summary for a load using Claude."""
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(422, "ANTHROPIC_API_KEY not configured")

    body = await request.json()
    shipment = body.get("shipment", {})
    emails = body.get("emails", [])
    documents = body.get("documents", [])
    driver = body.get("driver", {})
    tracking = body.get("tracking")
    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"Load: {shipment.get('efj', efj)}",
        f"Move Type: {shipment.get('moveType', 'Unknown')}",
        f"Account: {shipment.get('account', 'Unknown')}",
        f"Status: {shipment.get('rawStatus', shipment.get('status', 'Unknown'))}",
        f"Container/Load#: {shipment.get('container', 'N/A')}",
        f"Carrier: {shipment.get('carrier', 'N/A')}",
        f"Origin: {shipment.get('origin', 'N/A')} -> Destination: {shipment.get('destination', 'N/A')}",
        f"ETA: {shipment.get('eta', 'N/A')}",
        f"LFD/Cutoff: {shipment.get('lfd', 'N/A')}",
        f"Pickup: {shipment.get('pickupDate', 'N/A')}",
        f"Delivery: {shipment.get('deliveryDate', 'N/A')}",
        f"BOL: {shipment.get('bol', 'N/A')}",
        f"SSL/Vessel: {shipment.get('ssl', 'N/A')}",
        f"Return Port: {shipment.get('returnPort', 'N/A')}",
        f"Notes: {shipment.get('notes', 'None')}",
        f"Bot Alert: {shipment.get('botAlert', 'None')}",
        f"Rep: {shipment.get('rep', 'N/A')}",
    ]
    if shipment.get('hub'):
        lines.append(f"Hub: {shipment['hub']}")
    if shipment.get('project'):
        lines.append(f"Project: {shipment['project']}")

    if any(driver.get(k) for k in ("driverName", "driverPhone", "driverEmail", "trailerNumber")):
        lines.append("")
        lines.append("--- Driver/Carrier Contact ---")
        if driver.get("driverName"):
            lines.append(f"Driver: {driver['driverName']}")
        if driver.get("driverPhone"):
            lines.append(f"Phone: {driver['driverPhone']}")
        if driver.get("driverEmail"):
            lines.append(f"Email: {driver['driverEmail']}")
        if driver.get("carrierEmail"):
            lines.append(f"Carrier Email: {driver['carrierEmail']}")
        if driver.get("trailerNumber"):
            lines.append(f"Trailer: {driver['trailerNumber']}")

    if tracking:
        lines.append("")
        lines.append("--- Tracking Status ---")
        lines.append(f"Tracking Status: {tracking.get('trackingStatus', 'N/A')}")
        if tracking.get('eta'):
            lines.append(f"Tracking ETA: {tracking['eta']}")
        if tracking.get('behindSchedule'):
            lines.append("WARNING: Behind Schedule")
        if tracking.get('cantMakeIt'):
            lines.append(f"CRITICAL: {tracking['cantMakeIt']}")

    lines.append("")
    lines.append("--- Documents on File ---")
    if documents:
        doc_types = {}
        for d in documents:
            dt = d.get("doc_type", "other")
            doc_types.setdefault(dt, []).append(d.get("original_name", "unknown"))
        for dt, names in doc_types.items():
            lines.append(f"  {dt}: {len(names)} file(s) - {', '.join(names[:3])}")
    else:
        lines.append("  No documents uploaded")

    doc_type_set = {d.get("doc_type") for d in documents}
    missing_docs = []
    if "bol" not in doc_type_set:
        missing_docs.append("BOL")
    if "pod" not in doc_type_set:
        missing_docs.append("POD")
    if "customer_rate" not in doc_type_set:
        missing_docs.append("Customer Rate Con")
    if "carrier_rate" not in doc_type_set:
        missing_docs.append("Carrier Rate Con")
    if missing_docs:
        lines.append(f"  MISSING: {', '.join(missing_docs)}")

    lines.append("")
    lines.append("--- Recent Email Activity ---")
    if emails:
        lines.append(f"Total emails: {len(emails)}")
        for e in emails[:5]:
            sent = e.get('sent_at', '')[:10] if e.get('sent_at') else 'N/A'
            lines.append(f"  [{sent}] From: {e.get('sender', 'Unknown')}")
            lines.append(f"    Subject: {e.get('subject', 'No subject')}")
            if e.get('body_preview'):
                lines.append(f"    Preview: {e['body_preview'][:120]}")
    else:
        lines.append("  No emails indexed for this load")

    context_str = "\n".join(lines)

    system_prompt = (
        "You are a logistics operations assistant for Evans Delivery (EFJ Operations). "
        "You produce concise, actionable load summaries for dispatchers.\n\n"
        "Rules:\n"
        "- Output exactly 3-5 bullet points using the bullet character\n"
        "- Each bullet should be one sentence, max 20 words\n"
        "- First bullet: Current status and location context\n"
        "- Flag any issues: behind schedule, missing documents, approaching LFD, no driver, no tracking\n"
        "- Note document completeness (what is present vs missing)\n"
        "- Summarize recent email activity if any\n"
        "- If everything looks good, say so\n"
        "- Today is: " + today + "\n"
        "- Use plain text only, no markdown, no bold, no headers\n"
        "- Be direct and operational for experienced dispatchers"
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Generate an operational summary for this load:\n\n{context_str}"}],
        )
        summary_text = message.content[0].text.strip()
        return JSONResponse({"summary": summary_text})
    except Exception as e:
        log.error("AI summary generation failed for %s: %s", efj, e)
        raise HTTPException(500, f"Summary generation failed: {str(e)}")


# ── Unmatched Emails ──────────────────────────────────────────────────────


@router.get("/api/unmatched-emails")
async def get_unmatched_emails():
    """List unmatched inbox emails pending review."""
    with db.get_cursor() as cur:
        cur.execute(
        """SELECT id, gmail_message_id, subject, sender, recipients,
                  body_preview, has_attachments, attachment_names,
                  sent_at, indexed_at, review_status,
                  email_type, lane, priority, ai_summary, suggested_rep
           FROM unmatched_inbox_emails
           WHERE review_status = 'pending'
           ORDER BY COALESCE(priority, 0) DESC, sent_at DESC NULLS LAST
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
            "email_type": r.get("email_type"),
            "lane": r.get("lane"),
            "priority": r.get("priority"),
            "ai_summary": r.get("ai_summary"),
            "suggested_rep": r.get("suggested_rep"),
        }
        for r in rows
    ]
    return JSONResponse({"emails": emails, "count": len(emails)})


@router.post("/api/unmatched-emails/{email_id}/assign")
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


@router.post("/api/unmatched-emails/{email_id}/dismiss")
async def dismiss_unmatched_email(email_id: int):
    """Dismiss an unmatched email (mark as not relevant)."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE unmatched_inbox_emails SET review_status = 'dismissed' WHERE id = %s",
                (email_id,),
            )
    return JSONResponse({"status": "ok"})


# ── Inbox API ─────────────────────────────────────────────────────────────


@router.get("/api/inbox")
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
                'matched' as source,
                e.quote_status, e.quote_status_at, e.quote_status_rep
            FROM email_threads e
            WHERE e.sent_at >= NOW() - INTERVAL '%s days'
            UNION ALL
            SELECT
                u.id, u.gmail_thread_id, u.gmail_message_id, u.subject, u.sender,
                u.body_preview, u.has_attachments, u.attachment_names,
                u.sent_at, u.email_type, u.lane, u.priority, u.ai_summary,
                u.classification_feedback, u.corrected_type,
                NULL as efj, u.review_status, u.suggested_rep,
                'unmatched' as source,
                NULL as quote_status, NULL as quote_status_at, NULL as quote_status_rep
            FROM unmatched_inbox_emails u
            WHERE u.sent_at >= NOW() - INTERVAL '%s days'
              AND u.review_status = 'pending'
            ORDER BY sent_at DESC
        """ % (days, days))
        inbound_rows = cur.fetchall()

        # No sent_messages query needed — reply detection uses sender patterns in email_threads
        pass  # Sent messages are detected by sender domain in the thread messages below

    # CSL team domains for reply detection
    _CSL_DOMAINS = ('evansdelivery', 'commonsenselogistics')

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
                "quote_status": row.get("quote_status"),
                "quote_status_at": row["quote_status_at"].isoformat() if row.get("quote_status_at") else None,
                "quote_status_rep": row.get("quote_status_rep"),
            }

        thread = threads_map[tid]
        _sender_lower = (row["sender"] or "").lower()
        _is_csl = any(d in _sender_lower for d in _CSL_DOMAINS)
        thread["messages"].append({
            "id": row["id"],
            "sender": row["sender"],
            "subject": row["subject"],
            "sent_at": row["sent_at"].isoformat() if row["sent_at"] else None,
            "body_preview": row["body_preview"],
            "direction": "sent" if _is_csl else "inbound",
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
        # Sort messages chronologically (sent/inbound already tagged by direction)
        all_msgs = thread["messages"][:]
        all_msgs.sort(key=lambda m: m["sent_at"] or "")

        # Determine latest message and reply status
        latest_msg = all_msgs[-1] if all_msgs else None
        # Reply detection is done via external/CSL sender matching below

        # has_csl_reply: any CSL team message AFTER the latest external inbound
        external_msgs = [m for m in all_msgs if m.get("direction") == "inbound"]
        csl_msgs = [m for m in all_msgs if m.get("direction") == "sent"]
        latest_external = external_msgs[-1] if external_msgs else None
        has_csl_reply = False
        if latest_external and csl_msgs:
            latest_ext_time = latest_external.get("sent_at") or ""
            has_csl_reply = any(
                (m.get("sent_at") or "") > latest_ext_time
                for m in csl_msgs
            )

        # needs_reply: latest external message exists + no CSL reply after it
        needs_reply = (
            latest_external is not None
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
        threads = [t for t in threads if t["email_type"] in (
            "carrier_rate", "customer_rate", "carrier_rate_response",
            "carrier_rate_confirmation", "rate_outreach")]

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


@router.post("/api/inbox/{email_id}/feedback")
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


@router.patch("/api/inbox/{email_id}/quote-action")
async def patch_quote_action(email_id: int, request: Request):
    """Set quote_status on an inbox thread (quoted/won/lost/pass/clear).
    Also allows re-linking to a different EFJ."""
    data = await request.json()
    status = data.get("quote_status")   # quoted | won | lost | pass | None (clear)
    new_efj = data.get("efj")           # optional EFJ re-link
    rep = data.get("rep", "")

    valid = {None, "quoted", "won", "lost", "pass"}
    if status not in valid:
        return JSONResponse({"error": f"Invalid status '{status}'"}, status_code=422)

    with db.get_cursor() as cur:
        # Update email_threads
        if new_efj:
            cur.execute(
                """UPDATE email_threads
                   SET quote_status=%s, quote_status_at=NOW(), quote_status_rep=%s, efj=%s
                   WHERE id=%s""",
                (status, rep or None, new_efj.strip().upper(), email_id)
            )
        else:
            cur.execute(
                """UPDATE email_threads
                   SET quote_status=%s, quote_status_at=NOW(), quote_status_rep=%s
                   WHERE id=%s""",
                (status, rep or None, email_id)
            )
        if cur.rowcount == 0:
            # Try unmatched_inbox_emails (no quote_status col there, just log)
            pass
    # When marking "won", auto-accept linked rate_quote
    if status == "won":
        with db.get_cursor() as cur_rq:
            cur_rq.execute("""
                UPDATE rate_quotes SET status = 'accepted'
                WHERE email_thread_id = %s AND status = 'pending'
                RETURNING id, rate_amount, efj
            """, (email_id,))
            accepted = cur_rq.fetchone()
            if accepted:
                log.info("Quote-action won: auto-accepted rate_quote %d ($%s) for %s",
                         accepted["id"], accepted["rate_amount"], accepted.get("efj"))
                # Also reject competing quotes for same EFJ
                if accepted.get("efj"):
                    cur_rq.execute(
                        "UPDATE rate_quotes SET status = 'rejected' WHERE efj = %s AND id != %s AND status = 'pending'",
                        (accepted["efj"], accepted["id"]),
                    )
    return {"ok": True, "quote_status": status}


@router.get("/api/inbox/reply-alerts")
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


@router.get("/api/rate-response-alerts")
async def rate_response_alerts():
    """Return recent carrier_rate_response emails for live alert consumption."""
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT id, efj, email_type, gmail_thread_id, sender, subject, lane,
                   ai_summary, sent_at, suggested_rep
            FROM email_threads
            WHERE email_type IN ('carrier_rate_response', 'payment_escalation',
                                 'carrier_invoice', 'carrier_rate_confirmation')
              AND sent_at > NOW() - INTERVAL '24 hours'
            ORDER BY sent_at DESC
        """)
        rows = cur.fetchall()
    alerts = []
    for r in rows:
        alerts.append({
            "id": r["id"],
            "efj": r["efj"],
            "email_type": r["email_type"],
            "sender": r["sender"],
            "subject": r["subject"],
            "lane": r["lane"],
            "summary": r["ai_summary"],
            "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
            "rep": r["suggested_rep"],
        })
    return JSONResponse({"alerts": alerts})
