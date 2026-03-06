#!/usr/bin/env python3
"""
Patch: Wire csl_email_classifier.py into csl_inbox_scanner.py
Requires: csl_email_classifier.py already in /root/csl-bot/

Changes:
  1. Import csl_email_classifier module
  2. Call ensure_classifier_tables() in ensure_tables()
  3. Update classify_doc_type() to handle rate docs via classifier
  4. Add email classification + rate extraction in process_message()
  5. Add check_unreplied_customer_emails() to run_loop()
  6. Update email_threads INSERT to include email_type + lane columns
"""
import shutil, os, sys
from datetime import datetime

SCANNER_PATH = "/root/csl-bot/csl_inbox_scanner.py"

def backup(path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{path}.bak_{ts}"
    shutil.copy2(path, bak)
    print(f"Backup: {bak}")

def patch():
    if not os.path.exists(SCANNER_PATH):
        print(f"ERROR: {SCANNER_PATH} not found"); sys.exit(1)
    if not os.path.exists("/root/csl-bot/csl_email_classifier.py"):
        print("ERROR: csl_email_classifier.py not found in /root/csl-bot/"); sys.exit(1)

    backup(SCANNER_PATH)
    code = open(SCANNER_PATH).read()
    changes = 0

    # ── 1. Add import ──
    if "import csl_email_classifier" not in code:
        anchor = "import psycopg2"
        if anchor in code:
            code = code.replace(anchor, "import csl_email_classifier as classifier\n" + anchor)
            print("+ Added classifier import")
            changes += 1
    else:
        print("= Classifier import already present")

    # ── 2. Call ensure_classifier_tables in ensure_tables ──
    if "classifier.ensure_classifier_tables" not in code:
        # Find conn.commit() inside ensure_tables
        old = "        conn.commit()\n\n\ndef get_conn"
        new = "        # Create/migrate classifier tables (rate_quotes, customer_reply_alerts)\n        classifier.ensure_classifier_tables(conn)\n        conn.commit()\n\n\ndef get_conn"
        if old in code:
            code = code.replace(old, new)
            print("+ Added ensure_classifier_tables() call")
            changes += 1
    else:
        print("= ensure_classifier_tables already wired")

    # ── 3. Remove old rate classifier from DOC_CLASSIFIERS ──
    old_rate = '    (re.compile(r"rate.?con|rate.?confirm", re.IGNORECASE), "rate"),\n'
    if old_rate in code:
        code = code.replace(old_rate, '')
        print("+ Removed old rate classifier from DOC_CLASSIFIERS")
        changes += 1

    # ── 4. Update classify_doc_type to handle rate docs ──
    old_classify = 'def classify_doc_type(filename, sender="", subject=""):'
    if old_classify in code:
        code = code.replace(old_classify, 'def classify_doc_type(filename, sender="", subject="", body=""):')

        # Add rate classification before the for loop
        old_for = "    for pattern, doc_type in DOC_CLASSIFIERS:"
        new_for = """    # Smart rate document classification
    rate_type = classifier.classify_rate_doc(filename, sender, subject, body)
    if rate_type:
        return rate_type

    for pattern, doc_type in DOC_CLASSIFIERS:"""
        if old_for in code:
            code = code.replace(old_for, new_for, 1)
            print("+ Updated classify_doc_type with smart rate classification")
            changes += 1
    else:
        print("= classify_doc_type already updated")

    # ── 5. Update classify_doc_type call in process_message ──
    old_call = 'doc_type = classify_doc_type(att["filename"], sender=sender, subject=subject)'
    new_call = 'doc_type = classify_doc_type(att["filename"], sender=sender, subject=subject, body=body_preview)'
    if old_call in code:
        code = code.replace(old_call, new_call)
        print("+ Updated classify_doc_type call with body param")
        changes += 1

    # ── 6. Add email classification before email_threads INSERT ──
    if "classifier.classify_email_type" not in code:
        old_insert = "        # Insert into email_threads\n        conn = get_conn()"
        new_insert = """        # Classify the email itself (carrier/customer quote, lane detection)
        email_type, lane = classifier.classify_email_type(sender, subject, body_preview)
        if email_type:
            log.info("  Email type: %s | Lane: %s", email_type, lane or "none")

        # Insert into email_threads
        email_thread_db_id = None
        conn = get_conn()"""
        if old_insert in code:
            code = code.replace(old_insert, new_insert)
            print("+ Added email classification before INSERT")
            changes += 1

        # Update INSERT SQL to include email_type + lane + RETURNING id
        old_sql = '''                   subject, sender, recipients, body_preview,
                        has_attachments, attachment_names, sent_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING'''
        new_sql = '''                   subject, sender, recipients, body_preview,
                        has_attachments, attachment_names, sent_at,
                        email_type, lane)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING
                       RETURNING id'''
        if old_sql in code:
            code = code.replace(old_sql, new_sql)
            print("+ Updated INSERT SQL with email_type, lane, RETURNING id")
            changes += 1

        # Update VALUES tuple
        old_vals = '''                     subject, sender, recipients, body_preview[:500],
                     has_attachments, ", ".join(attachment_names), sent_at),'''
        new_vals = '''                     subject, sender, recipients, body_preview[:500],
                     has_attachments, ", ".join(attachment_names), sent_at,
                     email_type, lane),'''
        if old_vals in code:
            code = code.replace(old_vals, new_vals, 1)
            print("+ Updated VALUES tuple")

        # Add fetchone for RETURNING id + use RealDictCursor
        old_cursor = "            with conn.cursor() as cur:\n                cur.execute(\n                    \"\"\"INSERT INTO email_threads"
        new_cursor = "            with conn.cursor(cursor_factory=RealDictCursor) as cur:\n                cur.execute(\n                    \"\"\"INSERT INTO email_threads"
        if old_cursor in code:
            code = code.replace(old_cursor, new_cursor, 1)

        # Add fetchone after the execute
        old_after = """                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error"""
        # Find the first occurrence (matched email section, not unmatched)
        idx = code.find(old_after)
        if idx >= 0 and "email_thread_db_id" in code:
            new_after = """                )
                row = cur.fetchone()
                if row:
                    email_thread_db_id = row["id"] if isinstance(row, dict) else row[0]
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error"""
            code = code[:idx] + new_after + code[idx+len(old_after):]
            print("+ Added RETURNING id handling")
            changes += 1
    else:
        print("= Email classification already integrated")

    # ── 7. Add rate extraction after matched email processing ──
    if "classifier.save_rate_quote" not in code:
        old_else = '''    else:
        log.info("UNMATCHED: %s [%s] from %s", msg_id[:12], subject[:60], sender[:40])'''
        new_else = '''        # Extract and save rate quote for carrier emails (Rate IQ)
        if email_type == "carrier_rate" and email_thread_db_id:
            rate_data = classifier.extract_rate_from_email(subject, body_preview, sender, lane, email_type)
            if rate_data:
                classifier.save_rate_quote(get_conn, put_conn, email_thread_db_id, efj, lane, rate_data, sent_at)

    else:
        # Classify the email even when unmatched
        email_type, lane = classifier.classify_email_type(sender, subject, body_preview)
        log.info("UNMATCHED: %s [%s] from %s | type=%s lane=%s",
                 msg_id[:12], subject[:60], sender[:40],
                 email_type or "unknown", lane or "none")'''
        if old_else in code:
            code = code.replace(old_else, new_else)
            print("+ Added rate extraction + unmatched classification")
            changes += 1

        # Update unmatched INSERT to include email_type + lane
        old_unmatched = '''                        attachment_names, sent_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING'''
        new_unmatched = '''                        attachment_names, sent_at, email_type, lane)
                       Values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (gmail_message_id) DO NOTHING'''
        if old_unmatched in code:
            code = code.replace(old_unmatched, new_unmatched)
            print("+ Updated unmatched INSERT with email_type + lane")

        # Update unmatched VALUES
        old_uvals = '''                     ", ".join(attachment_names), sent_at),'''
        new_uvals = '''                     ", ".join(attachment_names), sent_at,
                     email_type, lane),'''
        # Replace last occurrence only
        idx = code.rfind(old_uvals)
        if idx >= 0:
            code = code[:idx] + new_uvals + code[idx+len(old_uvals):]
            print("+ Updated unmatched VALUES")
    else:
        print("= Rate extraction already integrated")

    # ── 8. Add check_unreplied to run_loop ──
    if "check_unreplied" not in code:
        old_loop = "            scan_inbox(service)\n            failures = 0"
        new_loop = "            scan_inbox(service)\n            classifier.check_unreplied_customer_emails(get_conn, put_conn)\n            failures = 0"
        if old_loop in code:
            code = code.replace(old_loop, new_loop)
            print("+ Added check_unreplied_customer_emails to run_loop")
            changes += 1
    else:
        print("= check_unreplied already in run_loop")

    if changes > 0:
        open(SCANNER_PATH, "w").write(code)
        print(f"\n{changes} changes applied. Restart: systemctl restart csl-inbox")
    else:
        print("\nNo changes needed.")

if __name__ == "__main__":
    patch()
