#!/usr/bin/env python3
"""
Patch: Sent Mail Scanner
Adds sent-mail tracking to csl_inbox_scanner.py.
After scanning inbound messages, queries Gmail API for sent messages
and stores them in sent_messages table for reply detection.

Run on server:
    python3 /tmp/patch_sent_mail_scanner.py
"""

import shutil, os, sys
from datetime import datetime

SCANNER_PATH = "/root/csl-bot/csl_inbox_scanner.py"

def backup(path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{path}.bak_{ts}"
    shutil.copy2(path, bak)
    print(f"Backup: {bak}")

SENT_SCANNER_FUNCTION = '''

# ── Sent Mail Scanner (for reply detection) ──────────────────────────

def scan_sent_messages(service):
    """Scan sent folder for outbound messages to track CSL replies."""
    log.info("Scanning sent messages for reply tracking...")

    try:
        # Get sent messages from last 24 hours
        import datetime as dt
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).strftime("%Y/%m/%d")
        result = service.users().messages().list(
            userId="me",
            q=f"in:sent after:{since}",
            maxResults=100,
        ).execute()
    except Exception as e:
        log.error("Gmail API sent list failed: %s", e)
        return 0

    messages = result.get("messages", [])
    if not messages:
        log.info("No recent sent messages")
        return 0

    stored = 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for msg_meta in messages:
                msg_id = msg_meta["id"]
                try:
                    # Check if already indexed
                    cur.execute(
                        "SELECT 1 FROM sent_messages WHERE gmail_message_id = %s",
                        (msg_id,)
                    )
                    if cur.fetchone():
                        continue

                    # Fetch message metadata (not full body — lightweight)
                    msg = service.users().messages().get(
                        userId="me", id=msg_id, format="metadata",
                        metadataHeaders=["To", "Subject", "Date"],
                    ).execute()

                    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                    thread_id = msg.get("threadId", "")
                    recipient = headers.get("To", "")
                    subject = headers.get("Subject", "")

                    # Parse date
                    sent_at = None
                    date_str = headers.get("Date", "")
                    if date_str:
                        try:
                            from email.utils import parsedate_to_datetime
                            sent_at = parsedate_to_datetime(date_str)
                        except Exception:
                            pass

                    cur.execute(
                        """INSERT INTO sent_messages
                           (gmail_message_id, gmail_thread_id, recipient, subject, sent_at)
                           VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT (gmail_message_id) DO NOTHING""",
                        (msg_id, thread_id, recipient[:500] if recipient else None,
                         subject[:500] if subject else None, sent_at),
                    )
                    stored += 1

                except Exception as e:
                    log.warning("Error indexing sent message %s: %s", msg_id[:12], e)

        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error("sent_messages batch insert failed: %s", e)
    finally:
        put_conn(conn)

    if stored:
        log.info("Indexed %d new sent messages", stored)
    return stored

'''

def patch():
    if not os.path.exists(SCANNER_PATH):
        print(f"ERROR: {SCANNER_PATH} not found"); sys.exit(1)

    backup(SCANNER_PATH)
    code = open(SCANNER_PATH).read()
    changes = 0

    # ── 1. Add scan_sent_messages function ──
    if "def scan_sent_messages" in code:
        print("= scan_sent_messages already exists")
    else:
        # Insert before scan_inbox function
        marker = "\ndef scan_inbox(service):"
        if marker in code:
            code = code.replace(marker, SENT_SCANNER_FUNCTION + marker)
            print("+ Added scan_sent_messages() function")
            changes += 1
        else:
            print("WARNING: Could not find scan_inbox marker")

    # ── 2. Add sent_messages table creation to ensure_tables ──
    if "sent_messages" not in code:
        old_ensure = "        conn.commit()"
        # Find first occurrence in ensure_tables context
        idx = code.find("def ensure_tables")
        if idx >= 0:
            commit_idx = code.find(old_ensure, idx)
            if commit_idx >= 0:
                sent_table_sql = '''        cur.execute("""
            CREATE TABLE IF NOT EXISTS sent_messages (
                id SERIAL PRIMARY KEY,
                gmail_message_id TEXT UNIQUE NOT NULL,
                gmail_thread_id TEXT NOT NULL,
                recipient TEXT,
                subject TEXT,
                sent_at TIMESTAMPTZ,
                indexed_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_sent_messages_thread_id
            ON sent_messages (gmail_thread_id)
        """)
        '''
                code = code[:commit_idx] + sent_table_sql + code[commit_idx:]
                print("+ Added sent_messages CREATE TABLE to ensure_tables()")
                changes += 1
    else:
        print("= sent_messages table creation already present")

    # ── 3. Call scan_sent_messages in run_loop ──
    if "scan_sent_messages" not in code.split("def run_loop")[1] if "def run_loop" in code else True:
        old_loop = "            scan_inbox(service)\n"
        # Find in run_loop context
        run_loop_idx = code.find("def run_loop")
        if run_loop_idx >= 0:
            loop_target = code.find(old_loop, run_loop_idx)
            if loop_target >= 0:
                new_loop = "            scan_inbox(service)\n            scan_sent_messages(service)\n"
                code = code[:loop_target] + new_loop + code[loop_target+len(old_loop):]
                print("+ Added scan_sent_messages() call to run_loop")
                changes += 1
    else:
        print("= scan_sent_messages already in run_loop")

    if changes > 0:
        open(SCANNER_PATH, "w").write(code)
        print(f"\n{changes} changes applied.")
        print("Restart: systemctl restart csl-inbox")
    else:
        print("\nNo changes needed.")


if __name__ == "__main__":
    patch()
