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
from date_normalizer import clean_date
from csl_logging import get_logger

log = get_logger("pg_writer")

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
    Mark the shipment identified by `efj` as archived in the database.
    
    Parameters:
        efj (str): External shipment identifier; must be a non-empty string.
    
    Returns:
        True if the archive update was applied successfully, False otherwise.
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


# ─────────────────────────────────────────────
# Tracking state tables (replaces JSON files)
# ─────────────────────────────────────────────

def pg_ensure_tracking_tables() -> bool:
    """
    Ensure the tracking and JSON cache tables exist in the PostgreSQL database.
    
    Creates the import_tracking_state, export_tracking_state, and jsoncargo_cache tables if they are absent; safe to call repeatedly.
    
    Returns:
        bool: `True` if the tables exist or were created successfully, `False` otherwise.
    """
    conn = _get_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
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
        cur.close()
        return True
    except Exception as exc:
        log.warning("Could not create tracking tables: %s", exc)
        return False


# -- Import tracking state ---------------------------------------------------

def pg_load_all_import_state() -> dict:
    """
    Load all rows from import_tracking_state and return them keyed by state_key.
    
    Returns:
        dict: Mapping from state_key (str) to a dict with keys:
            - "eta" (str): estimated time of arrival, empty string if NULL.
            - "lfd" (str): last free day, empty string if NULL.
            - "return_date" (str): return date, empty string if NULL.
            - "status" (str): status, empty string if NULL.
    """
    conn = _get_conn()
    if conn is None:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT state_key, eta, lfd, return_date, status FROM import_tracking_state")
        rows = cur.fetchall()
        cur.close()
        return {
            r[0]: {"eta": r[1] or "", "lfd": r[2] or "",
                   "return_date": r[3] or "", "status": r[4] or ""}
            for r in rows
        }
    except Exception as exc:
        log.warning("pg_load_all_import_state failed: %s", exc)
        return {}


def pg_set_import_state(state_key: str, eta: str = "",
                        lfd: str = "", return_date: str = "",
                        status: str = "") -> bool:
    """
                        Insert or update the import_tracking_state row for the given state_key.
                        
                        Parameters:
                            state_key (str): Identifier for the import tracking entry to upsert.
                            eta (str): Estimated time of arrival as a date string (may be empty).
                            lfd (str): Last free day / other date string (may be empty).
                            return_date (str): Return date as a date string (may be empty).
                            status (str): Status text associated with the tracking entry (may be empty).
                        
                        Returns:
                            bool: `True` if the row was inserted or updated successfully, `False` on error or if the database connection is unavailable.
                        """
    conn = _get_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO import_tracking_state (state_key, eta, lfd, return_date, status, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (state_key) DO UPDATE SET
                eta = EXCLUDED.eta, lfd = EXCLUDED.lfd,
                return_date = EXCLUDED.return_date, status = EXCLUDED.status,
                updated_at = NOW()
        """, (state_key, eta, lfd, return_date, status))
        cur.close()
        return True
    except Exception as exc:
        log.warning("pg_set_import_state failed for %s: %s", state_key, exc)
        return False


# -- Export tracking state ----------------------------------------------------

def pg_load_all_export_state() -> dict:
    """
    Load all rows from export_tracking_state into a mapping keyed by state_key.
    
    Null database columns are converted to empty strings.
    
    Returns:
        dict: Mapping from `state_key` to a dict with keys `erd`, `cutoff`, and `cutoff_alerted` (each a string; empty string used when the DB value was NULL).
    """
    conn = _get_conn()
    if conn is None:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT state_key, erd, cutoff, cutoff_alerted FROM export_tracking_state")
        rows = cur.fetchall()
        cur.close()
        return {
            r[0]: {"erd": r[1] or "", "cutoff": r[2] or "",
                   "cutoff_alerted": r[3] or ""}
            for r in rows
        }
    except Exception as exc:
        log.warning("pg_load_all_export_state failed: %s", exc)
        return {}


def pg_set_export_state(state_key: str, erd: str = "",
                        cutoff: str = "", cutoff_alerted: str = "") -> bool:
    """
                        Upsert an export tracking state row keyed by `state_key`.
                        
                        Inserts a new row or updates the existing row's `erd`, `cutoff`, `cutoff_alerted`, and `updated_at` columns.
                        
                        Parameters:
                            state_key (str): Identifier for the export state row.
                            erd (str): Value to store in the `erd` column.
                            cutoff (str): Value to store in the `cutoff` column.
                            cutoff_alerted (str): Value to store in the `cutoff_alerted` column.
                        
                        Returns:
                            bool: `true` if the row was successfully inserted or updated, `false` otherwise.
                        """
    conn = _get_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO export_tracking_state (state_key, erd, cutoff, cutoff_alerted, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (state_key) DO UPDATE SET
                erd = EXCLUDED.erd, cutoff = EXCLUDED.cutoff,
                cutoff_alerted = EXCLUDED.cutoff_alerted,
                updated_at = NOW()
        """, (state_key, erd, cutoff, cutoff_alerted))
        cur.close()
        return True
    except Exception as exc:
        log.warning("pg_set_export_state failed for %s: %s", state_key, exc)
        return False


def pg_delete_export_state(state_key: str) -> bool:
    """
    Delete the export_tracking_state row identified by state_key.
    
    Parameters:
        state_key (str): The key of the export tracking state to remove.
    
    Returns:
        bool: `True` if the delete statement executed without error, `False` otherwise.
    """
    conn = _get_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM export_tracking_state WHERE state_key = %s",
                    (state_key,))
        cur.close()
        return True
    except Exception as exc:
        log.warning("pg_delete_export_state failed for %s: %s", state_key, exc)
        return False


# -- JsonCargo API cache ------------------------------------------------------

import json as _json
import random as _random

def pg_jc_cache_get(cache_key: str, ttl_seconds: int = 21600):
    """
    Retrieve a cached jsoncargo_cache entry when its cached_at timestamp is within the specified TTL.
    
    Parameters:
        cache_key (str): Key identifying the cached entry.
        ttl_seconds (int): Time-to-live in seconds; only entries newer than NOW() - ttl_seconds are returned. Defaults to 21600.
    
    Returns:
        The stored `data` column for the matching cache_key if present and within TTL, or `None` otherwise.
    """
    conn = _get_conn()
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT data FROM jsoncargo_cache
            WHERE cache_key = %s AND cached_at > NOW() - INTERVAL '%s seconds'
        """, (cache_key, ttl_seconds))
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    except Exception as exc:
        log.warning("pg_jc_cache_get failed for %s: %s", cache_key, exc)
        return None


def pg_jc_cache_set(cache_key: str, data) -> bool:
    """
    Store or refresh a JSON cache entry for the given cache_key in the jsoncargo_cache table.
    
    This upserts the provided data (serialized to JSONB) and updates its cached timestamp. Occasionally (approximately 10% of calls) the function will also prune entries older than 48 hours.
    
    Parameters:
        cache_key (str): Key identifying the cached entry.
        data: Arbitrary JSON-serializable value to store for the key.
    
    Returns:
        bool: `True` if the entry was written or updated successfully, `False` on failure or when no database connection is available.
    """
    conn = _get_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO jsoncargo_cache (cache_key, data, cached_at)
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT (cache_key) DO UPDATE SET
                data = EXCLUDED.data, cached_at = NOW()
        """, (cache_key, _json.dumps(data)))
        # Probabilistic prune (~10% of writes)
        if _random.random() < 0.1:
            cur.execute("DELETE FROM jsoncargo_cache WHERE cached_at < NOW() - INTERVAL '48 hours'")
        cur.close()
        return True
    except Exception as exc:
        log.warning("pg_jc_cache_set failed for %s: %s", cache_key, exc)
        return False
