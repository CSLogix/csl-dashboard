#!/usr/bin/env python3
"""
csl_pg_writer.py -- Lightweight Postgres writer for CSL bot monitors.

Provides fire-and-forget dual-write functions so bots can update the
shipments table alongside their normal Google Sheet writes.

All functions handle errors silently (log + return False).
Bots never crash from a PG failure.

Usage:
    from csl_pg_writer import pg_update_shipment, pg_archive_shipment
"""
import os
import logging
from date_normalizer import clean_date

log = logging.getLogger("pg_writer")

_conn = None
_env_loaded = False


def _load_db_env():
    """Load DB credentials from csl-doc-tracker/.env (separate from bot .env)."""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    try:
        from dotenv import load_dotenv
        # DB creds live in csl-doc-tracker/.env, not the bot-level .env
        dt_env = os.path.join(os.path.dirname(__file__), "csl-doc-tracker", ".env")
        if os.path.exists(dt_env):
            load_dotenv(dt_env, override=False)
    except Exception:
        pass


def _get_conn():
    """Lazy-init a psycopg2 connection. Returns None if PG unreachable."""
    global _conn
    _load_db_env()

    if _conn is not None:
        try:
            if not _conn.closed:
                # Ping to detect stale TCP connections
                _conn.cursor().execute("SELECT 1")
                return _conn
        except Exception:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None

    try:
        import psycopg2
        _conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
            dbname=os.environ.get("DB_NAME", "csl_doc_tracker"),
            user=os.environ.get("DB_USER", "csl_admin"),
            password=os.environ.get("DB_PASSWORD", ""),
            connect_timeout=5,
        )
        _conn.autocommit = True
        return _conn
    except Exception as exc:
        log.warning("Could not connect to Postgres: %s", exc)
        _conn = None
        return None


def pg_update_shipment(efj: str, **fields) -> bool:
    """
    Upsert a row in the shipments table.

    Accepts any combination of shipment fields (eta, pickup_date, status, etc.).
    If the EFJ doesn't exist, inserts a minimal row. If it exists, updates only
    the provided fields + updated_at.

    Returns True on success, False on any error (never raises).
    """
    if not efj or not efj.strip():
        return False

    efj = efj.strip()

    # Filter to valid shipments columns only
    VALID = {
        "move_type", "container", "bol", "vessel", "carrier",
        "origin", "destination", "eta", "lfd", "pickup_date",
        "delivery_date", "status", "notes", "driver", "bot_notes",
        "return_date", "account", "hub", "rep", "source",
        "container_url", "driver_phone", "customer_ref",
        "equipment_type",
    }
    updates = {k: v for k, v in fields.items() if k in VALID and v is not None}

    # Normalize date fields to MM-DD / MM-DD HH:MM at the gate
    DATE_FIELDS = {"eta", "lfd", "pickup_date", "delivery_date", "return_date"}
    for df in DATE_FIELDS:
        if df in updates and updates[df]:
            cleaned = clean_date(updates[df])
            if cleaned:
                updates[df] = cleaned

    if not updates:
        return True  # nothing to do

    conn = _get_conn()
    if conn is None:
        return False

    try:
        cur = conn.cursor()

        # Build dynamic UPSERT
        cols = list(updates.keys())
        placeholders = ["%s"] * len(cols)
        set_parts = [f"{c} = EXCLUDED.{c}" for c in cols]

        sql = (
            f"INSERT INTO shipments (efj, {', '.join(cols)}, updated_at) "
            f"VALUES (%s, {', '.join(placeholders)}, NOW()) "
            f"ON CONFLICT (efj) DO UPDATE SET "
            f"{', '.join(set_parts)}, updated_at = NOW()"
        )
        params = [efj] + list(updates.values())

        cur.execute(sql, params)

        # Auto-create tracking token on new shipment INSERT (not on update)
        # xmax=0 means the row was freshly inserted (no previous version)
        cur.execute(
            "SELECT xmax FROM shipments WHERE efj = %s",
            (efj,)
        )
        row = cur.fetchone()
        if row and row[0] == 0:
            cur.execute(
                "INSERT INTO public_tracking_tokens (efj) VALUES (%s) ON CONFLICT DO NOTHING",
                (efj,)
            )

        cur.close()
        return True
    except Exception as exc:
        log.warning("Update failed for %s: %s", efj, exc)
        # Reset connection on error
        global _conn
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None
        return False


def pg_archive_shipment(efj: str) -> bool:
    """
    Mark a shipment as archived in Postgres.
    Sets archived=True, archived_at=NOW(), updated_at=NOW().
    Returns True on success, False on error (never raises).
    """
    if not efj or not efj.strip():
        return False

    efj = efj.strip()
    conn = _get_conn()
    if conn is None:
        return False

    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE shipments SET archived = TRUE, archived_at = NOW(), "
            "updated_at = NOW() WHERE efj = %s",
            (efj,),
        )
        cur.close()
        return True
    except Exception as exc:
        log.warning("Archive failed for %s: %s", efj, exc)
        global _conn
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None
        return False
