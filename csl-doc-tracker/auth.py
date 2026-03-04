"""
Authentication module for CSL AI Dispatch.
- Session-based auth with signed cookies
- First-run password setup (you choose your own password)
- Brute force lockout after 5 failed attempts
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

log = logging.getLogger(__name__)

AUTH_FILE = Path(__file__).parent / ".auth.json"
SESSION_MAX_AGE = 86400 * 7  # 7 days
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 900  # 15 min lockout

# Secret key for signing cookies — generated once, persisted
_secret_key = None
_failed_attempts = {}  # ip -> {count, last_attempt}


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


def is_configured() -> bool:
    """Check if a password has been set."""
    return AUTH_FILE.exists()


def setup_password(username: str, password: str) -> bool:
    """Set up the initial username + password. Only works if not yet configured."""
    if is_configured():
        return False
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    data = {"username": username, "password_hash": hashed}
    AUTH_FILE.write_text(json.dumps(data))
    os.chmod(str(AUTH_FILE), 0o600)
    log.info("Auth configured for user: %s", username)
    return True


def change_password(current_password: str, new_password: str) -> bool:
    """Change password (requires current password)."""
    if not is_configured():
        return False
    data = json.loads(AUTH_FILE.read_text())
    if not bcrypt.checkpw(current_password.encode(), data["password_hash"].encode()):
        return False
    data["password_hash"] = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    AUTH_FILE.write_text(json.dumps(data))
    return True


def check_lockout(ip: str) -> tuple[bool, int]:
    """Check if an IP is locked out. Returns (is_locked, seconds_remaining)."""
    if ip not in _failed_attempts:
        return False, 0
    info = _failed_attempts[ip]
    if info["count"] >= MAX_FAILED_ATTEMPTS:
        elapsed = time.time() - info["last_attempt"]
        if elapsed < LOCKOUT_SECONDS:
            return True, int(LOCKOUT_SECONDS - elapsed)
        # Lockout expired, reset
        del _failed_attempts[ip]
    return False, 0


def record_failed_attempt(ip: str):
    if ip not in _failed_attempts:
        _failed_attempts[ip] = {"count": 0, "last_attempt": 0}
    _failed_attempts[ip]["count"] += 1
    _failed_attempts[ip]["last_attempt"] = time.time()


def clear_failed_attempts(ip: str):
    _failed_attempts.pop(ip, None)


def verify_login(username: str, password: str) -> bool:
    """Check username + password against stored credentials."""
    if not is_configured():
        return False
    data = json.loads(AUTH_FILE.read_text())
    if data["username"] != username:
        return False
    return bcrypt.checkpw(password.encode(), data["password_hash"].encode())


def create_session_token(username: str) -> str:
    """Create a signed session token."""
    payload = json.dumps({
        "user": username,
        "exp": int(time.time()) + SESSION_MAX_AGE,
        "nonce": secrets.token_hex(8),
    })
    sig = hmac.new(_get_secret_key().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def verify_session_token(token: str) -> str | None:
    """Verify a session token. Returns username if valid, None otherwise."""
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
        return data.get("user")
    except Exception:
        return None
