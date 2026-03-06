#!/usr/bin/env python3
"""
Patch: AI Email Triage
- Adds priority, ai_summary, suggested_rep columns to email_threads + unmatched_inbox_emails
- Adds ai_classify_email() to csl_email_classifier.py (calls Claude Haiku)
- Modifies csl_inbox_scanner.py to call AI classifier for all incoming emails
- Updates app.py email endpoints to return classification data
"""

import sys, psycopg2

# ── Step 1: DB Migration ─────────────────────────────────────────────
print("[1/4] Adding AI classification columns...")
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()

for table in ("email_threads", "unmatched_inbox_emails"):
    for col, dtype in [("priority", "INTEGER"), ("ai_summary", "TEXT"), ("suggested_rep", "TEXT")]:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
            conn.commit()
            print(f"   Added {col} to {table}")
        except Exception:
            conn.rollback()
            print(f"   {col} already exists in {table}")

cur.close()
conn.close()
print("   Columns ready.")

# ── Step 2: Add AI classify function to classifier module ────────────
print("[2/4] Adding ai_classify_email() to csl_email_classifier.py...")
CLASSIFIER = "/root/csl-bot/csl_email_classifier.py"

with open(CLASSIFIER, "r") as f:
    classifier_code = f.read()

if "def ai_classify_email" in classifier_code:
    print("   Already has ai_classify_email — skipping.")
else:
    AI_FUNCTION = '''


# ── AI Email Classification (Claude Haiku) ──────────────────────────

def ai_classify_email(sender, subject, body_preview, attachment_names=""):
    """
    Use Claude Haiku to classify an email with type, priority, and summary.
    Returns dict with: type, priority (1-5), suggested_rep, summary.
    Falls back to empty dict on error.
    """
    import json, os

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        env_path = "/root/csl-bot/.env"
        if os.path.exists(env_path):
            with open(env_path) as ef:
                for line in ef:
                    if line.startswith("ANTHROPIC_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not api_key:
        return {}

    prompt = f"""Classify this logistics email for a freight broker (Evans Delivery / CSL).

FROM: {sender}
SUBJECT: {subject}
BODY: {body_preview[:800]}
ATTACHMENTS: {attachment_names or "none"}

Respond with ONLY valid JSON (no markdown, no extra text):
{{
  "type": "<one of: carrier_rate, customer_rate, pod, bol, appointment, detention, delivery_update, tracking_update, invoice, general>",
  "priority": <1-5>,
  "suggested_rep": "<rep name if identifiable from content, otherwise null>",
  "summary": "<one-line operational summary, max 80 chars>"
}}

Priority scale:
5 = CRITICAL: detention/demurrage charges, customs hold, delivery failure, cargo damage
4 = HIGH: rate quotes needing response, appointment changes, ETA changes, missing docs
3 = NORMAL: routine updates, standard confirmations, POD received
2 = LOW: informational, FYI, carrier newsletters
1 = NOISE: marketing, spam, auto-replies, out-of-office"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        result["priority"] = max(1, min(5, int(result.get("priority", 3))))
        result["type"] = result.get("type", "general")
        result["summary"] = (result.get("summary") or "")[:120]
        result["suggested_rep"] = result.get("suggested_rep") or None
        return result
    except Exception as e:
        logging.getLogger("csl_email_classifier").warning("AI classify failed: %s", e)
        return {}
'''
    classifier_code += AI_FUNCTION
    with open(CLASSIFIER, "w") as f:
        f.write(classifier_code)
    print("   Added ai_classify_email() function.")

# ── Step 3: Modify inbox scanner ─────────────────────────────────────
print("[3/4] Patching inbox scanner...")
SCANNER = "/root/csl-bot/csl_inbox_scanner.py"

with open(SCANNER, "r") as f:
    scanner_code = f.read()

# 3a: Patch matched email section — add AI classification + expand INSERT
OLD_MATCHED = """        # Classify the email itself (carrier/customer quote, lane detection)
        email_type, lane = classify_email_type(sender, subject, body_preview)
        if email_type:
            log.info("  Email type: %s | Lane: %s", email_type, lane or "none")

        # Insert into email_threads
        email_thread_db_id = None
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    \"\"\"INSERT INTO email_threads
                       (efj, gmail_thread_id, gmail_message_id, message_id,
                        subject, sender, recipients, body_preview,
                        has_attachments, attachment_names, sent_at,
                        email_type, lane)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING
                       RETURNING id\"\"\",
                    (efj, gmail_thread_id, msg_id, rfc_message_id,
                     subject, sender, recipients, body_preview[:500],
                     has_attachments, ", ".join(attachment_names), sent_at,
                     email_type, lane),
                )"""

NEW_MATCHED = """        # Classify the email itself (carrier/customer quote, lane detection)
        email_type, lane = classify_email_type(sender, subject, body_preview)
        if email_type:
            log.info("  Email type: %s | Lane: %s", email_type, lane or "none")

        # AI classification (enhanced type, priority, summary)
        ai_result = classifier.ai_classify_email(
            sender, subject, body_preview,
            ", ".join(attachment_names) if attachment_names else "")
        ai_priority = ai_result.get("priority")
        ai_summary_text = ai_result.get("summary")
        ai_suggested_rep = ai_result.get("suggested_rep")
        final_email_type = email_type or ai_result.get("type")
        if ai_priority:
            log.info("  AI: type=%s priority=%d summary=%s",
                     ai_result.get("type", "?"), ai_priority, ai_summary_text or "?")

        # Insert into email_threads
        email_thread_db_id = None
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    \"\"\"INSERT INTO email_threads
                       (efj, gmail_thread_id, gmail_message_id, message_id,
                        subject, sender, recipients, body_preview,
                        has_attachments, attachment_names, sent_at,
                        email_type, lane, priority, ai_summary, suggested_rep)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING
                       RETURNING id\"\"\",
                    (efj, gmail_thread_id, msg_id, rfc_message_id,
                     subject, sender, recipients, body_preview[:500],
                     has_attachments, ", ".join(attachment_names), sent_at,
                     final_email_type, lane, ai_priority, ai_summary_text, ai_suggested_rep),
                )"""

if OLD_MATCHED in scanner_code:
    scanner_code = scanner_code.replace(OLD_MATCHED, NEW_MATCHED)
    print("   Patched matched email classification + INSERT.")
else:
    print("   WARNING: Could not find matched email section — may need manual edit")

# 3b: Patch unmatched email section
OLD_UNMATCHED = """        # Classify the email even when unmatched to an EFJ
        email_type, lane = classify_email_type(sender, subject, body_preview)
        log.info("UNMATCHED: %s [%s] from %s | type=%s lane=%s",
                 msg_id[:12], subject[:60], sender[:40],
                 email_type or "unknown", lane or "none")

        # Store in unmatched table
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    \"\"\"INSERT INTO unmatched_inbox_emails
                       (gmail_message_id, gmail_thread_id, subject, sender,
                        recipients, body_preview, has_attachments,
                        attachment_names, sent_at, email_type, lane)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING\"\"\",
                    (msg_id, gmail_thread_id, subject, sender,
                     recipients, body_preview[:500], has_attachments,
                     ", ".join(attachment_names), sent_at,
                     email_type, lane),
                )"""

NEW_UNMATCHED = """        # Classify the email even when unmatched to an EFJ
        email_type, lane = classify_email_type(sender, subject, body_preview)
        log.info("UNMATCHED: %s [%s] from %s | type=%s lane=%s",
                 msg_id[:12], subject[:60], sender[:40],
                 email_type or "unknown", lane or "none")

        # AI classification (enhanced type, priority, summary)
        ai_result = classifier.ai_classify_email(
            sender, subject, body_preview,
            ", ".join(attachment_names) if attachment_names else "")
        ai_priority = ai_result.get("priority")
        ai_summary_text = ai_result.get("summary")
        ai_suggested_rep = ai_result.get("suggested_rep")
        final_email_type = email_type or ai_result.get("type")
        if ai_priority:
            log.info("  AI: type=%s priority=%d rep=%s",
                     ai_result.get("type", "?"), ai_priority, ai_suggested_rep or "?")

        # Store in unmatched table
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    \"\"\"INSERT INTO unmatched_inbox_emails
                       (gmail_message_id, gmail_thread_id, subject, sender,
                        recipients, body_preview, has_attachments,
                        attachment_names, sent_at, email_type, lane,
                        priority, ai_summary, suggested_rep)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING\"\"\",
                    (msg_id, gmail_thread_id, subject, sender,
                     recipients, body_preview[:500], has_attachments,
                     ", ".join(attachment_names), sent_at,
                     final_email_type, lane, ai_priority, ai_summary_text, ai_suggested_rep),
                )"""

if OLD_UNMATCHED in scanner_code:
    scanner_code = scanner_code.replace(OLD_UNMATCHED, NEW_UNMATCHED)
    print("   Patched unmatched email classification + INSERT.")
else:
    print("   WARNING: Could not find unmatched email section — may need manual edit")

with open(SCANNER, "w") as f:
    f.write(scanner_code)

# ── Step 4: Update app.py email endpoints ─────────────────────────────
print("[4/4] Patching app.py email endpoints...")
APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    app_code = f.read()

# 4a: /api/load/{efj}/emails — add classification fields to query + response
OLD_EMAIL_EP = """    with db.get_cursor() as cur:
        cur.execute(
            \"\"\"SELECT id, gmail_message_id, gmail_thread_id, subject, sender,
                      recipients, body_preview, has_attachments, attachment_names,
                      sent_at, indexed_at
               FROM email_threads
               WHERE efj = %s
               ORDER BY sent_at DESC NULLS LAST\"\"\",
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
    return JSONResponse({"emails": emails, "count": len(emails)})"""

NEW_EMAIL_EP = """    with db.get_cursor() as cur:
        cur.execute(
            \"\"\"SELECT id, gmail_message_id, gmail_thread_id, subject, sender,
                      recipients, body_preview, has_attachments, attachment_names,
                      sent_at, indexed_at, email_type, lane, priority, ai_summary
               FROM email_threads
               WHERE efj = %s
               ORDER BY sent_at DESC NULLS LAST\"\"\",
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
    return JSONResponse({"emails": emails, "count": len(emails)})"""

if OLD_EMAIL_EP in app_code:
    app_code = app_code.replace(OLD_EMAIL_EP, NEW_EMAIL_EP)
    print("   Fixed /api/load/{efj}/emails endpoint.")
else:
    print("   WARNING: Could not find email endpoint block")

# 4b: /api/unmatched-emails — add classification + priority sorting
OLD_UNMATCHED_EP = """    with db.get_cursor() as cur:
        cur.execute(
            \"\"\"SELECT id, gmail_message_id, subject, sender, recipients,
                      body_preview, has_attachments, attachment_names,
                      sent_at, indexed_at, review_status
               FROM unmatched_inbox_emails
               WHERE review_status = 'pending'
               ORDER BY sent_at DESC NULLS LAST
               LIMIT 100\"\"\",
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
    return JSONResponse({"emails": emails, "count": len(emails)})"""

NEW_UNMATCHED_EP = """    with db.get_cursor() as cur:
        cur.execute(
            \"\"\"SELECT id, gmail_message_id, subject, sender, recipients,
                      body_preview, has_attachments, attachment_names,
                      sent_at, indexed_at, review_status,
                      email_type, lane, priority, ai_summary, suggested_rep
               FROM unmatched_inbox_emails
               WHERE review_status = 'pending'
               ORDER BY COALESCE(priority, 0) DESC, sent_at DESC NULLS LAST
               LIMIT 100\"\"\",
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
    return JSONResponse({"emails": emails, "count": len(emails)})"""

if OLD_UNMATCHED_EP in app_code:
    app_code = app_code.replace(OLD_UNMATCHED_EP, NEW_UNMATCHED_EP)
    print("   Fixed /api/unmatched-emails endpoint.")
else:
    print("   WARNING: Could not find unmatched email endpoint block")

with open(APP, "w") as f:
    f.write(app_code)

print("\n   Done! AI Email Triage patch applied.")
print("   Restart: systemctl restart csl-inbox csl-dashboard")
