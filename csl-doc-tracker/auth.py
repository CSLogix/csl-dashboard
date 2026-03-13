"""
Multi-user authentication module for CSL AI Dispatch.
- PostgreSQL-backed user table (replaces .auth.json)
- Session tokens carry user_id, role, rep_name
- Admin + rep roles
- Brute-force lockout (IP-based)
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path

import bcrypt

import database as db

log = logging.getLogger(__name__)

SESSION_MAX_AGE = 86400 * 7  # 7 days
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 900  # 15 min

_secret_key = None
_failed_attempts = {}  # ip -> {count, last_attempt}


# ── Secret key (for signing session cookies) ─────────────────────────────
def _get_secret_key() -> str:
    global _secret_key
    if _secret_key:
        return _secret_key
    key_file = Path(__file__).parent / ".session_secret"
    if key_file.exists():
        _secret_key = key_file.read_text().strip()
    else:
        _secret_key = secrets.token_hex(32)
        key_file.write_text(_secret_key)
        os.chmod(str(key_file), 0o600)
    return _secret_key


# ── Table setup ──────────────────────────────────────────────────────────
def init_users_table():
    """Create users table if it doesn't exist."""
    with db.get_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          SERIAL PRIMARY KEY,
                username    VARCHAR(50)  UNIQUE NOT NULL,
                email       VARCHAR(100),
                password_hash VARCHAR(255) NOT NULL,
                role        VARCHAR(20)  DEFAULT 'rep',
                rep_name    VARCHAR(50),
                is_active   BOOLEAN      DEFAULT true,
                created_at  TIMESTAMPTZ  DEFAULT NOW(),
                last_login  TIMESTAMPTZ
            )
        """)
    log.info("users table ready")


def _migrate_from_auth_json():
    """One-time migration: import existing .auth.json admin into PG."""
    auth_file = Path(__file__).parent / ".auth.json"
    if not auth_file.exists():
        return
    try:
        data = json.loads(auth_file.read_text())
        username = data.get("username", "admin")
        pw_hash = data["password_hash"]
        with db.get_cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                return  # already migrated
            cur.execute(
                """INSERT INTO users (username, email, password_hash, role, rep_name)
                   VALUES (%s, %s, %s, 'admin', 'John F')""",
                (username, "John.Feltz@evansdelivery.com", pw_hash),
            )
        # Rename so we don't re-migrate
        auth_file.rename(auth_file.with_suffix(".json.migrated"))
        log.info("Migrated %s from .auth.json → PG users table", username)
    except Exception as e:
        log.error("auth.json migration failed: %s", e)


def seed_users():
    """Seed initial users if the table is empty (after migration)."""
    with db.get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM users")
        if cur.fetchone()["cnt"] > 1:
            return  # already seeded

    temp_hash = bcrypt.hashpw(b"evans2026", bcrypt.gensalt()).decode()
    users = [
        ("jsfel", "John.Feltz@evansdelivery.com", "admin", "John F"),
        ("radka", "Radka.White@evansdelivery.com", "rep", "Radka"),
        ("janice", "Janice.Cortes@evansdelivery.com", "rep", "Janice"),
        ("nancy", "Nancy.Feltz@evansdelivery.com", "admin", "Nancy"),
        ("allie", "Allie.Mancia@evansdelivery.com", "rep", "Allie"),
        ("john.nocon", "John.Nocon@evansdelivery.com", "rep", "John N"),
        ("climaco", "Climaco.Cortes@evansdelivery.com", "rep", "Climaco"),
    ]
    with db.get_cursor() as cur:
        for uname, email, role, rep in users:
            cur.execute("SELECT id FROM users WHERE username = %s", (uname,))
            if cur.fetchone():
                continue
            cur.execute(
                """INSERT INTO users (username, email, password_hash, role, rep_name)
                   VALUES (%s, %s, %s, %s, %s)""",
                (uname, email, temp_hash, role, rep),
            )
            log.info("Seeded user: %s (%s)", uname, role)


def init():
    """Call at startup — creates table, migrates, seeds."""
    init_users_table()
    _migrate_from_auth_json()
    seed_users()


# ── Brute-force lockout ──────────────────────────────────────────────────
def check_lockout(ip: str) -> tuple[bool, int]:
    if ip not in _failed_attempts:
        return False, 0
    info = _failed_attempts[ip]
    if info["count"] >= MAX_FAILED_ATTEMPTS:
        elapsed = time.time() - info["last_attempt"]
        if elapsed < LOCKOUT_SECONDS:
            return True, int(LOCKOUT_SECONDS - elapsed)
        del _failed_attempts[ip]
    return False, 0


def record_failed_attempt(ip: str):
    if ip not in _failed_attempts:
        _failed_attempts[ip] = {"count": 0, "last_attempt": 0}
    _failed_attempts[ip]["count"] += 1
    _failed_attempts[ip]["last_attempt"] = time.time()


def clear_failed_attempts(ip: str):
    _failed_attempts.pop(ip, None)


# ── Login / verify ───────────────────────────────────────────────────────
def verify_login(username: str, password: str) -> dict | None:
    """Verify credentials. Returns user dict on success, None on failure."""
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT id, username, email, password_hash, role, rep_name FROM users WHERE username = %s AND is_active = true",
            (username,),
        )
        row = cur.fetchone()
    if not row:
        return None
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return None
    # Update last_login
    with db.get_cursor() as cur:
        cur.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (row["id"],))
    return {
        "user_id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "rep_name": row["rep_name"],
    }


def is_configured() -> bool:
    """Check if any users exist in PG."""
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT 1 FROM users LIMIT 1")
            return cur.fetchone() is not None
    except Exception:
        return False


# ── Session tokens ───────────────────────────────────────────────────────
def create_session_token(user: dict) -> str:
    """Create a signed session token with user context."""
    payload = json.dumps({
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "rep_name": user["rep_name"],
        "exp": int(time.time()) + SESSION_MAX_AGE,
        "nonce": secrets.token_hex(8),
    })
    sig = hmac.new(_get_secret_key().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def verify_session_token(token: str) -> dict | None:
    """Verify token. Returns user dict {user_id, username, role, rep_name} or None."""
    if not token or "|" not in token:
        return None
    try:
        payload, sig = token.rsplit("|", 1)
        expected = hmac.new(_get_secret_key().encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(payload)
        if data.get("exp", 0) < time.time():
            return None
        return {
            "user_id": data.get("user_id"),
            "username": data.get("username", data.get("user")),
            "role": data.get("role", "admin"),
            "rep_name": data.get("rep_name"),
        }
    except Exception:
        return None


# ── User CRUD (for admin panel) ──────────────────────────────────────────
def get_user(user_id: int) -> dict | None:
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT id, username, email, role, rep_name, is_active, created_at, last_login FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT id, username, email, role, rep_name, is_active, created_at, last_login FROM users ORDER BY id"
        )
        return [dict(r) for r in cur.fetchall()]


def create_user(username: str, email: str, password: str, role: str = "rep", rep_name: str = None) -> dict:
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with db.get_cursor() as cur:
        cur.execute(
            """INSERT INTO users (username, email, password_hash, role, rep_name)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (username, email, pw_hash, role, rep_name),
        )
        uid = cur.fetchone()["id"]
    return get_user(uid)


def update_user(user_id: int, **fields) -> dict | None:
    allowed = {"email", "role", "rep_name", "is_active", "username"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_user(user_id)
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    vals = list(updates.values()) + [user_id]
    with db.get_cursor() as cur:
        cur.execute(f"UPDATE users SET {set_clause} WHERE id = %s", vals)
    return get_user(user_id)


def change_password(user_id: int, current_password: str, new_password: str) -> bool:
    with db.get_cursor() as cur:
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    if not row or not bcrypt.checkpw(current_password.encode(), row["password_hash"].encode()):
        return False
    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    with db.get_cursor() as cur:
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
    return True


def admin_reset_password(user_id: int, new_password: str) -> bool:
    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    with db.get_cursor() as cur:
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
    return True
