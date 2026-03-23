#!/usr/bin/env python3
"""
One-time cleanup: remove ghost EFJ loads from Postgres that no longer exist
in the Google Sheet. Run on the production server:

    cd /root/csl-bot && python3 cleanup_ghost_loads.py

Or dry-run first:

    cd /root/csl-bot && python3 cleanup_ghost_loads.py --dry-run
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "csl-doc-tracker"))

from dotenv import load_dotenv
load_dotenv()

import database as db

GHOST_EFJS = [
    "EFJ107204",
    "EFJ107205",
    "EFJ107206",
    "EFJ107207",
    "EFJ107208",
    "EFJ107209",
    "EFJ107210",
    "EFJ107211",
    "EFJ107212",
]

RELATED_TABLES = [
    "load_documents", "load_notes", "tracking_events",
    "driver_contacts", "rate_quotes", "email_threads",
    "email_drafts", "customer_reply_alerts",
]


def main():
    dry_run = "--dry-run" in sys.argv
    db.init_pool(minconn=1, maxconn=2)

    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                # Verify which ones exist
                cur.execute(
                    "SELECT efj, account, status FROM shipments WHERE efj = ANY(%s) ORDER BY efj",
                    (GHOST_EFJS,),
                )
                found = cur.fetchall()
                if not found:
                    print("None of the listed EFJs exist in Postgres. Nothing to do.")
                    return

                print(f"Found {len(found)} loads to delete:")
                for r in found:
                    print(f"  {r['efj']}  account={r['account']}  status={r['status']}")

                if dry_run:
                    print("\n--dry-run: no changes made.")
                    return

                # Delete related records with savepoint protection
                for table in RELATED_TABLES:
                    try:
                        cur.execute("SAVEPOINT _cleanup")
                        cur.execute(
                            f"DELETE FROM {table} WHERE efj = ANY(%s)",
                            (GHOST_EFJS,),
                        )
                        deleted = cur.rowcount
                        if deleted:
                            print(f"  Deleted {deleted} rows from {table}")
                    except Exception:
                        cur.execute("ROLLBACK TO SAVEPOINT _cleanup")

                # Delete the shipments
                cur.execute(
                    "DELETE FROM shipments WHERE efj = ANY(%s)", (GHOST_EFJS,)
                )
                print(f"\nDeleted {cur.rowcount} shipments from Postgres.")

    finally:
        db.close_pool()


if __name__ == "__main__":
    main()
