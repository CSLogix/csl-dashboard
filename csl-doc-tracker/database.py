"""
PostgreSQL database layer for CSL Document Tracker.
Provides a connection pool and all query/mutation functions.
"""

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import psycopg2
import psycopg2.pool
import psycopg2.extras

import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def init_pool(minconn: int = 2, maxconn: int = 10):
    """Create the global connection pool. Call once at startup."""
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn,
        maxconn,
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
    )
    log.info("Database connection pool initialized (min=%d, max=%d)", minconn, maxconn)


def close_pool():
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        log.info("Database connection pool closed")


@contextmanager
def get_conn():
    """Yield a connection from the pool, auto-commit on success, rollback on error."""
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


@contextmanager
def get_cursor(conn=None):
    """Yield a dict-cursor, optionally re-using an existing connection."""
    if conn is not None:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
        finally:
            cur.close()
    else:
        with get_conn() as c:
            cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                yield cur
            finally:
                cur.close()


# ---------------------------------------------------------------------------
# Loads
# ---------------------------------------------------------------------------

def upsert_load(
    load_number: str,
    customer_ref: str = None,
    customer_name: str = None,
    account: str = None,
) -> int:
    """Insert or update a load, returning its id."""
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO loads (load_number, customer_ref, customer_name, account)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (load_number) DO UPDATE SET
                    customer_ref  = COALESCE(EXCLUDED.customer_ref,  loads.customer_ref),
                    customer_name = COALESCE(EXCLUDED.customer_name, loads.customer_name),
                    account       = COALESCE(EXCLUDED.account,       loads.account),
                    updated_at    = NOW()
                RETURNING id
                """,
                (load_number, customer_ref, customer_name, account),
            )
            return cur.fetchone()["id"]


def get_load_by_number(load_number: str) -> Optional[dict]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM loads WHERE load_number = %s", (load_number,))
        return cur.fetchone()


def get_load_by_id(load_id: int) -> Optional[dict]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM loads WHERE id = %s", (load_id,))
        return cur.fetchone()


def get_all_loads(account_filter: str = None, status: str = "active") -> list:
    with get_cursor() as cur:
        if account_filter:
            cur.execute(
                "SELECT * FROM loads WHERE status = %s AND account = %s ORDER BY created_at DESC",
                (status, account_filter),
            )
        else:
            cur.execute(
                "SELECT * FROM loads WHERE status = %s ORDER BY created_at DESC",
                (status,),
            )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Load references
# ---------------------------------------------------------------------------

def upsert_reference(load_id: int, reference_type: str, reference_value: str):
    """Insert a reference, ignoring duplicates."""
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO load_references (load_id, reference_type, reference_value)
                VALUES (%s, %s, %s)
                ON CONFLICT (reference_type, reference_value) DO NOTHING
                """,
                (load_id, reference_type, reference_value),
            )


def find_load_id_by_reference(reference_value: str) -> Optional[int]:
    """Look up a load_id by any reference value (case-insensitive)."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT load_id FROM load_references WHERE UPPER(reference_value) = UPPER(%s) LIMIT 1",
            (reference_value,),
        )
        row = cur.fetchone()
        return row["load_id"] if row else None


def get_all_references() -> list:
    """Return all (reference_value, load_id) pairs for building in-memory lookup."""
    with get_cursor() as cur:
        cur.execute("SELECT reference_value, load_id FROM load_references")
        return cur.fetchall()


def get_references_for_load(load_id: int) -> list:
    with get_cursor() as cur:
        cur.execute(
            "SELECT reference_type, reference_value FROM load_references WHERE load_id = %s",
            (load_id,),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def insert_document(
    load_id: int,
    doc_type: str,
    file_path: str,
    file_name: str,
    email_subject: str = None,
    email_from: str = None,
    email_date: datetime = None,
    source_mailbox: str = None,
) -> int:
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO documents
                    (load_id, doc_type, file_path, file_name, email_subject,
                     email_from, email_date, source_mailbox)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (load_id, doc_type, file_path, file_name, email_subject,
                 email_from, email_date, source_mailbox),
            )
            doc_id = cur.fetchone()["id"]

            # Mark checklist item as received
            cur.execute(
                """
                UPDATE document_checklist
                SET received = TRUE, received_at = NOW()
                WHERE load_id = %s AND doc_type = %s AND received = FALSE
                """,
                (load_id, doc_type),
            )
            return doc_id


def get_documents_for_load(load_id: int) -> list:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM documents WHERE load_id = %s ORDER BY received_at DESC",
            (load_id,),
        )
        return cur.fetchall()


def get_latest_document(load_id: int, doc_type: str) -> Optional[dict]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM documents
            WHERE load_id = %s AND doc_type = %s
            ORDER BY received_at DESC LIMIT 1
            """,
            (load_id, doc_type),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Document checklist
# ---------------------------------------------------------------------------

def ensure_checklist(load_id: int):
    """Create BOL and POD checklist entries for a load if they don't exist."""
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            for doc_type in ("BOL", "POD"):
                cur.execute(
                    """
                    INSERT INTO document_checklist (load_id, doc_type)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (load_id, doc_type),
                )
            # The ON CONFLICT may not fire without a unique constraint,
            # so guard with a check.
            cur.execute(
                "SELECT COUNT(*) as cnt FROM document_checklist WHERE load_id = %s",
                (load_id,),
            )
            if cur.fetchone()["cnt"] == 0:
                for doc_type in ("BOL", "POD"):
                    cur.execute(
                        "INSERT INTO document_checklist (load_id, doc_type) VALUES (%s, %s)",
                        (load_id, doc_type),
                    )


def get_checklist(load_id: int) -> list:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM document_checklist WHERE load_id = %s ORDER BY doc_type",
            (load_id,),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Email log (deduplication)
# ---------------------------------------------------------------------------

def is_email_processed(message_id: str) -> bool:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM email_log WHERE message_id = %s AND processed = TRUE",
            (message_id,),
        )
        return cur.fetchone() is not None


def log_email(
    message_id: str,
    mailbox_origin: str = None,
    subject: str = None,
    sender: str = None,
    received_date: datetime = None,
    attachments_count: int = 0,
    processed: bool = False,
    matched_load_id: int = None,
):
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO email_log
                    (message_id, mailbox_origin, subject, sender, received_date,
                     attachments_count, processed, processed_at, matched_load_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO UPDATE SET
                    processed       = EXCLUDED.processed,
                    processed_at    = EXCLUDED.processed_at,
                    matched_load_id = COALESCE(EXCLUDED.matched_load_id, email_log.matched_load_id)
                """,
                (
                    message_id, mailbox_origin, subject, sender, received_date,
                    attachments_count, processed,
                    datetime.utcnow() if processed else None,
                    matched_load_id,
                ),
            )


def mark_email_processed(message_id: str, matched_load_id: int = None):
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """
                UPDATE email_log
                SET processed = TRUE, processed_at = NOW(), matched_load_id = COALESCE(%s, matched_load_id)
                WHERE message_id = %s
                """,
                (matched_load_id, message_id),
            )


# ---------------------------------------------------------------------------
# Unmatched emails
# ---------------------------------------------------------------------------

def insert_unmatched_email(
    message_id: str,
    subject: str = None,
    sender: str = None,
    received_date: datetime = None,
    attachment_names: str = None,
):
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO unmatched_emails
                    (message_id, subject, sender, received_date, attachment_names)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (message_id, subject, sender, received_date, attachment_names),
            )


def get_unmatched_emails(status: str = "pending") -> list:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM unmatched_emails WHERE review_status = %s ORDER BY received_date DESC",
            (status,),
        )
        return cur.fetchall()


def resolve_unmatched_email(unmatched_id: int, load_id: int):
    """Manually match an unmatched email to a load."""
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """
                UPDATE unmatched_emails
                SET review_status = 'matched', matched_load_id = %s, reviewed_at = NOW()
                WHERE id = %s
                """,
                (load_id, unmatched_id),
            )


def ignore_unmatched_email(unmatched_id: int):
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """
                UPDATE unmatched_emails
                SET review_status = 'ignored', reviewed_at = NOW()
                WHERE id = %s
                """,
                (unmatched_id,),
            )


# ---------------------------------------------------------------------------
# Dashboard aggregate queries
# ---------------------------------------------------------------------------

def get_dashboard_loads(account_filter: str = None) -> list:
    """
    Return loads with BOL/POD status for the dashboard.
    Each row includes: load info + bol_received, pod_received, bol_file_path, pod_file_path.
    """
    with get_cursor() as cur:
        query = """
            SELECT
                l.id,
                l.load_number,
                l.customer_ref,
                l.customer_name,
                l.account,
                l.status,
                l.created_at,
                -- BOL
                (SELECT d.file_path FROM documents d
                 WHERE d.load_id = l.id AND d.doc_type = 'BOL'
                 ORDER BY d.received_at DESC LIMIT 1) AS bol_file_path,
                (SELECT d.file_name FROM documents d
                 WHERE d.load_id = l.id AND d.doc_type = 'BOL'
                 ORDER BY d.received_at DESC LIMIT 1) AS bol_file_name,
                EXISTS(SELECT 1 FROM documents d
                       WHERE d.load_id = l.id AND d.doc_type = 'BOL') AS bol_received,
                -- POD
                (SELECT d.file_path FROM documents d
                 WHERE d.load_id = l.id AND d.doc_type = 'POD'
                 ORDER BY d.received_at DESC LIMIT 1) AS pod_file_path,
                (SELECT d.file_name FROM documents d
                 WHERE d.load_id = l.id AND d.doc_type = 'POD'
                 ORDER BY d.received_at DESC LIMIT 1) AS pod_file_name,
                EXISTS(SELECT 1 FROM documents d
                       WHERE d.load_id = l.id AND d.doc_type = 'POD') AS pod_received
            FROM loads l
            WHERE l.status = 'active'
        """
        params = []
        if account_filter:
            query += " AND l.account = %s"
            params.append(account_filter)
        query += " ORDER BY l.created_at DESC"
        cur.execute(query, params)
        return cur.fetchall()


def get_dashboard_stats(account_filter: str = None) -> dict:
    """Return aggregate stats for the dashboard header."""
    with get_cursor() as cur:
        where = "WHERE l.status = 'active'"
        params = []
        if account_filter:
            where += " AND l.account = %s"
            params.append(account_filter)

        cur.execute(f"SELECT COUNT(*) as total FROM loads l {where}", params)
        total = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT COUNT(*) as missing_bol FROM loads l {where}
            AND NOT EXISTS (
                SELECT 1 FROM documents d WHERE d.load_id = l.id AND d.doc_type = 'BOL'
            )
            """,
            params,
        )
        missing_bol = cur.fetchone()["missing_bol"]

        cur.execute(
            f"""
            SELECT COUNT(*) as missing_pod FROM loads l {where}
            AND NOT EXISTS (
                SELECT 1 FROM documents d WHERE d.load_id = l.id AND d.doc_type = 'POD'
            )
            """,
            params,
        )
        missing_pod = cur.fetchone()["missing_pod"]

        cur.execute(
            "SELECT COUNT(*) as cnt FROM unmatched_emails WHERE review_status = 'pending'"
        )
        unmatched = cur.fetchone()["cnt"]

        return {
            "total_loads": total,
            "missing_bol": missing_bol,
            "missing_pod": missing_pod,
            "unmatched_emails": unmatched,
        }


# ---------------------------------------------------------------------------
# Quotes (Rate IQ)
# ---------------------------------------------------------------------------

def create_quotes_table():
    """Create quotes table if not exists. Called at startup."""
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS quotes (
                    id SERIAL PRIMARY KEY,
                    quote_number VARCHAR(32) UNIQUE NOT NULL,
                    status VARCHAR(20) DEFAULT 'draft',
                    pod VARCHAR(256),
                    final_delivery VARCHAR(256),
                    final_zip VARCHAR(20),
                    round_trip_miles VARCHAR(32),
                    one_way_miles VARCHAR(32),
                    transit_time VARCHAR(64),
                    duration_hours FLOAT,
                    shipment_type VARCHAR(32) DEFAULT 'Dray',
                    carrier_name VARCHAR(256),
                    carrier_total FLOAT DEFAULT 0,
                    margin_pct FLOAT DEFAULT 15,
                    sell_subtotal FLOAT DEFAULT 0,
                    accessorial_total FLOAT DEFAULT 0,
                    estimated_total FLOAT DEFAULT 0,
                    customer_name VARCHAR(256),
                    customer_email VARCHAR(256),
                    linehaul_json JSONB,
                    accessorials_json JSONB,
                    terms_json JSONB,
                    route_json JSONB,
                    created_by VARCHAR(256) DEFAULT '',
                    valid_until DATE,
                    source_type VARCHAR(64) DEFAULT '',
                    source_filename VARCHAR(512) DEFAULT '',
                    outcome VARCHAR(50),
                    outcome_notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # Add columns if missing (existing DBs)
            for col, coltype, default in [
                ("created_by", "VARCHAR(256)", "''"),
                ("valid_until", "DATE", None),
                ("source_type", "VARCHAR(64)", "''"),
                ("source_filename", "VARCHAR(512)", "''"),
                ("outcome", "VARCHAR(50)", None),
                ("outcome_notes", "TEXT", None),
            ]:
                try:
                    default_clause = f" DEFAULT {default}" if default else ""
                    cur.execute(f"ALTER TABLE quotes ADD COLUMN {col} {coltype}{default_clause}")
                except Exception:
                    conn.rollback()
            # Backfill created_by on existing quotes that have empty/null value
            try:
                cur.execute("""
                    UPDATE quotes SET created_by = 'system'
                    WHERE created_by IS NULL OR created_by = ''
                """)
                if cur.rowcount > 0:
                    log.info("backfilled created_by='system' on %d existing quotes", cur.rowcount)
            except Exception:
                conn.rollback()
    log.info("quotes table ready")


def _next_quote_number() -> str:
    """Generate next quote number like CSL-Q-0001."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT quote_number FROM quotes ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row and row["quote_number"]:
            try:
                num = int(row["quote_number"].split("-")[-1]) + 1
            except (ValueError, IndexError):
                num = 1
        else:
            num = 1
        return f"CSL-Q-{num:04d}"


def insert_quote(data: dict) -> dict:
    """Insert a new quote, auto-generating quote_number. Returns the row."""
    qn = _next_quote_number()
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO quotes
                    (quote_number, created_by, status, pod, final_delivery, final_zip,
                     round_trip_miles, one_way_miles, transit_time, duration_hours,
                     shipment_type, carrier_name, carrier_total, margin_pct, margin_type,
                     sell_subtotal, accessorial_total, estimated_total,
                     customer_name, customer_email, valid_until,
                     linehaul_json, accessorials_json, terms_json, route_json,
                     source_type, source_filename)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
            """, (
                qn, data.get("created_by", "system"),
                data.get("status", "draft"),
                data.get("pod"), data.get("final_delivery"), data.get("final_zip"),
                data.get("round_trip_miles"), data.get("one_way_miles"),
                data.get("transit_time"), data.get("duration_hours"),
                data.get("shipment_type", "Dray"),
                data.get("carrier_name"), data.get("carrier_total", 0),
                data.get("margin_pct", 15), data.get("margin_type", "pct"),
                data.get("sell_subtotal", 0), data.get("accessorial_total", 0),
                data.get("estimated_total", 0),
                data.get("customer_name"), data.get("customer_email"),
                data.get("valid_until"),
                json.dumps(data.get("linehaul_items", [])),
                json.dumps(data.get("accessorials", [])),
                json.dumps(data.get("terms", [])),
                json.dumps(data.get("route", [])),
                data.get("source_type", "manual"),
                data.get("source_filename", ""),
            ))
            return dict(cur.fetchone())


def update_quote(quote_id: int, data: dict) -> dict:
    """Update an existing quote. Returns the updated row."""
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute("""
                UPDATE quotes SET
                    status = %s, pod = %s, final_delivery = %s, final_zip = %s,
                    round_trip_miles = %s, one_way_miles = %s,
                    transit_time = %s, duration_hours = %s,
                    shipment_type = %s, carrier_name = %s, carrier_total = %s,
                    margin_pct = %s, margin_type = %s, sell_subtotal = %s, accessorial_total = %s,
                    estimated_total = %s, customer_name = %s, customer_email = %s,
                    linehaul_json = %s, accessorials_json = %s,
                    terms_json = %s, route_json = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
            """, (
                data.get("status", "draft"),
                data.get("pod"), data.get("final_delivery"), data.get("final_zip"),
                data.get("round_trip_miles"), data.get("one_way_miles"),
                data.get("transit_time"), data.get("duration_hours"),
                data.get("shipment_type", "Dray"),
                data.get("carrier_name"), data.get("carrier_total", 0),
                data.get("margin_pct", 15), data.get("margin_type", "pct"),
                data.get("sell_subtotal", 0), data.get("accessorial_total", 0),
                data.get("estimated_total", 0),
                data.get("customer_name"), data.get("customer_email"),
                json.dumps(data.get("linehaul_items")),
                json.dumps(data.get("accessorials")),
                json.dumps(data.get("terms")),
                json.dumps(data.get("route")),
                quote_id,
            ))
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)


def get_quote(quote_id: int) -> Optional[dict]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM quotes WHERE id = %s", (quote_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_quotes(status: str = None, search: str = None, move_types: list = None, limit: int = 50, offset: int = 0) -> list:
    with get_cursor() as cur:
        where_clauses = []
        params = []
        if status:
            where_clauses.append("status = %s")
            params.append(status)
        if search:
            where_clauses.append(
                "(quote_number ILIKE %s OR customer_name ILIKE %s OR pod ILIKE %s OR final_delivery ILIKE %s)"
            )
            s = f"%{search}%"
            params.extend([s, s, s, s])
        if move_types:
            placeholders = ",".join(["%s"] * len(move_types))
            where_clauses.append(f"shipment_type IN ({placeholders})")
            params.extend(move_types)
        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        cur.execute(
            f"SELECT * FROM quotes {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# AI Knowledge Base
# ---------------------------------------------------------------------------

def kb_search(category: str = None, scope: str = None, query: str = None, limit: int = 50) -> list:
    """Search knowledge base entries with optional filters and text search."""
    with get_cursor() as cur:
        conditions = ["active = TRUE"]
        params = []
        if category:
            conditions.append("category = %s")
            params.append(category)
        if scope:
            conditions.append("(scope ILIKE %s OR scope IS NULL)")
            params.append(f"%{scope}%")
        if query:
            conditions.append("content ILIKE %s")
            params.append(f"%{query}%")
        where = " AND ".join(conditions)
        cur.execute(
            f"SELECT * FROM ai_knowledge_base WHERE {where} ORDER BY updated_at DESC LIMIT %s",
            params + [limit],
        )
        return [dict(r) for r in cur.fetchall()]


def kb_insert(category: str, content: str, scope: str = None, source: str = "admin_entry") -> dict:
    """Insert a new knowledge base entry. Returns the created row."""
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO ai_knowledge_base (category, scope, content, source)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (category, scope, content, source),
            )
            return dict(cur.fetchone())


def kb_update(entry_id: int, **fields) -> Optional[dict]:
    """Update a knowledge base entry. Accepts category, scope, content, active."""
    allowed = {"category", "scope", "content", "active"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return None
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    params = list(updates.values()) + [entry_id]
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                f"UPDATE ai_knowledge_base SET {set_clause}, updated_at = NOW() WHERE id = %s RETURNING *",
                params,
            )
            row = cur.fetchone()
            return dict(row) if row else None


def kb_delete(entry_id: int) -> bool:
    """Soft-delete a knowledge base entry (set active=False)."""
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                "UPDATE ai_knowledge_base SET active = FALSE, updated_at = NOW() WHERE id = %s",
                (entry_id,),
            )
            return cur.rowcount > 0


def kb_get_relevant(scopes: list, limit: int = 20) -> list:
    """Get active knowledge entries matching any of the given scopes, plus global entries."""
    if not scopes:
        scopes = []
    with get_cursor() as cur:
        # Build scope conditions: match any scope OR global (scope IS NULL)
        scope_conditions = ["scope IS NULL"]
        params = []
        for s in scopes:
            scope_conditions.append("scope ILIKE %s")
            params.append(f"%{s}%")
        scope_where = " OR ".join(scope_conditions)
        cur.execute(
            f"""
            SELECT id, category, scope, content
            FROM ai_knowledge_base
            WHERE active = TRUE AND ({scope_where})
            ORDER BY
                CASE WHEN scope IS NOT NULL THEN 0 ELSE 1 END,
                updated_at DESC
            LIMIT %s
            """,
            params + [limit],
        )
        return [dict(r) for r in cur.fetchall()]
