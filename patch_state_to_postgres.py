#!/usr/bin/env python3
"""
patch_state_to_postgres.py -- Migrate JSON state files to Postgres tables.

Creates 3 new tables (idempotent) and imports existing data from:
  - /root/csl-bot/last_check.json        -> import_tracking_state
  - /root/csl-bot/export_state.json      -> export_tracking_state
  - /root/csl-bot/jsoncargo_cache.json   -> jsoncargo_cache

Safe to run multiple times (uses ON CONFLICT DO NOTHING).
JSON files are renamed to *.json.migrated after import (not deleted).
"""
import json
import os
import sys
import time

# Load DB env from csl-doc-tracker/.env
from dotenv import load_dotenv
dt_env = os.path.join(os.path.dirname(__file__), "csl-doc-tracker", ".env")
if os.path.exists(dt_env):
    load_dotenv(dt_env, override=False)

import psycopg2

LAST_CHECK_FILE = "/root/csl-bot/last_check.json"
EXPORT_STATE_FILE = "/root/csl-bot/export_state.json"
JSONCARGO_CACHE_FILE = "/root/csl-bot/jsoncargo_cache.json"


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "csl_doc_tracker"),
        user=os.environ.get("DB_USER", "csl_admin"),
        password=os.environ.get("DB_PASSWORD", ""),
        connect_timeout=10,
    )


def create_tables(conn):
    """Create the 3 tracking state tables (idempotent)."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS import_tracking_state (
                state_key   TEXT PRIMARY KEY,
                eta         TEXT DEFAULT '',
                lfd         TEXT DEFAULT '',
                return_date TEXT DEFAULT '',
                status      TEXT DEFAULT '',
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS export_tracking_state (
                state_key       TEXT PRIMARY KEY,
                erd             TEXT DEFAULT '',
                cutoff          TEXT DEFAULT '',
                cutoff_alerted  TEXT DEFAULT '',
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS jsoncargo_cache (
                cache_key  TEXT PRIMARY KEY,
                data       JSONB NOT NULL,
                cached_at  TIMESTAMPTZ DEFAULT NOW()
            );
        """)
    conn.commit()
    print("Tables created (or already exist).")


def migrate_import_state(conn):
    """Migrate last_check.json -> import_tracking_state."""
    if not os.path.exists(LAST_CHECK_FILE):
        print(f"  {LAST_CHECK_FILE} not found — skipping import state migration.")
        return 0

    with open(LAST_CHECK_FILE) as f:
        data = json.load(f)

    count = 0
    with conn.cursor() as cur:
        for key, val in data.items():
            cur.execute("""
                INSERT INTO import_tracking_state (state_key, eta, lfd, return_date, status, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (state_key) DO NOTHING
            """, (
                key,
                val.get("eta", ""),
                val.get("lfd", ""),
                val.get("return_date", ""),
                val.get("status", ""),
            ))
            count += 1
    conn.commit()

    migrated_path = LAST_CHECK_FILE + ".migrated"
    os.rename(LAST_CHECK_FILE, migrated_path)
    print(f"  Migrated {count} import state entries. File renamed to {migrated_path}")
    return count


def migrate_export_state(conn):
    """Migrate export_state.json -> export_tracking_state."""
    if not os.path.exists(EXPORT_STATE_FILE):
        print(f"  {EXPORT_STATE_FILE} not found — skipping export state migration.")
        return 0

    with open(EXPORT_STATE_FILE) as f:
        data = json.load(f)

    count = 0
    with conn.cursor() as cur:
        for key, val in data.items():
            cur.execute("""
                INSERT INTO export_tracking_state (state_key, erd, cutoff, cutoff_alerted, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (state_key) DO NOTHING
            """, (
                key,
                val.get("erd", ""),
                val.get("cutoff", ""),
                val.get("cutoff_alerted", ""),
            ))
            count += 1
    conn.commit()

    migrated_path = EXPORT_STATE_FILE + ".migrated"
    os.rename(EXPORT_STATE_FILE, migrated_path)
    print(f"  Migrated {count} export state entries. File renamed to {migrated_path}")
    return count


def migrate_jsoncargo_cache(conn):
    """Migrate jsoncargo_cache.json -> jsoncargo_cache table.
    Only imports entries newer than 48 hours."""
    if not os.path.exists(JSONCARGO_CACHE_FILE):
        print(f"  {JSONCARGO_CACHE_FILE} not found — skipping cache migration.")
        return 0

    with open(JSONCARGO_CACHE_FILE) as f:
        data = json.load(f)

    cutoff = time.time() - 48 * 3600
    count = 0
    with conn.cursor() as cur:
        for key, val in data.items():
            ts = val.get("ts", 0)
            if ts < cutoff:
                continue  # Skip expired entries
            cached_data = val.get("data")
            if cached_data is None:
                continue
            cur.execute("""
                INSERT INTO jsoncargo_cache (cache_key, data, cached_at)
                VALUES (%s, %s::jsonb, TO_TIMESTAMP(%s))
                ON CONFLICT (cache_key) DO NOTHING
            """, (key, json.dumps(cached_data), ts))
            count += 1
    conn.commit()

    migrated_path = JSONCARGO_CACHE_FILE + ".migrated"
    os.rename(JSONCARGO_CACHE_FILE, migrated_path)
    print(f"  Migrated {count} cache entries (skipped expired). File renamed to {migrated_path}")
    return count


def main():
    print("=== Migrate JSON state files to Postgres ===\n")

    try:
        conn = get_conn()
        conn.autocommit = False
    except Exception as exc:
        print(f"FATAL: Could not connect to Postgres: {exc}")
        sys.exit(1)

    try:
        create_tables(conn)
        conn.autocommit = True  # Each migration commits independently

        print("\n1. Import tracking state (last_check.json):")
        migrate_import_state(conn)

        print("\n2. Export tracking state (export_state.json):")
        migrate_export_state(conn)

        print("\n3. JsonCargo cache (jsoncargo_cache.json):")
        migrate_jsoncargo_cache(conn)

        # Verify
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM import_tracking_state")
            print(f"\n  import_tracking_state rows: {cur.fetchone()[0]}")
            cur.execute("SELECT count(*) FROM export_tracking_state")
            print(f"  export_tracking_state rows: {cur.fetchone()[0]}")
            cur.execute("SELECT count(*) FROM jsoncargo_cache")
            print(f"  jsoncargo_cache rows:       {cur.fetchone()[0]}")

        conn.close()
        print("\nMigration complete.")
    except Exception as exc:
        print(f"\nERROR during migration: {exc}")
        conn.close()
        sys.exit(1)


if __name__ == "__main__":
    main()
