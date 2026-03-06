#!/usr/bin/env python3
"""
Patch: Inbox Command Center — DB Migration
Creates sent_messages table + adds classification_feedback columns.

Run on server:
    python3 /tmp/patch_inbox_command_center_db.py
"""

import sys, psycopg2

print("[1/2] Connecting to database...")
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config

conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()

# ── Create sent_messages table ──
print("[1/2] Creating sent_messages table...")
cur.execute("""
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
cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_sent_messages_sent_at
    ON sent_messages (sent_at DESC)
""")
conn.commit()
print("   sent_messages table ready.")

# ── Add feedback columns to email tables ──
print("[2/2] Adding classification_feedback columns...")
for table in ("email_threads", "unmatched_inbox_emails"):
    for col, dtype in [("classification_feedback", "TEXT"), ("corrected_type", "TEXT")]:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
            conn.commit()
            print(f"   Added {col} to {table}")
        except Exception:
            conn.rollback()
            print(f"   {col} already exists in {table}")

cur.close()
conn.close()
print("\nDone! DB migration complete.")
