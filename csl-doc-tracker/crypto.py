"""
Symmetric encryption helpers using Fernet.
Shared by app.py (upload endpoint) and gmail_monitor.py (email attachments).
"""
import logging

import config
from cryptography.fernet import Fernet

log = logging.getLogger(__name__)
_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = config.ENCRYPTION_KEY
        if not key:
            raise RuntimeError("ENCRYPTION_KEY not set in .env")
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_data(data: bytes) -> bytes:
    """Encrypt raw bytes using Fernet symmetric encryption."""
    return _get_fernet().encrypt(data)


def decrypt_data(data: bytes) -> bytes:
    """Decrypt Fernet-encrypted bytes."""
    return _get_fernet().decrypt(data)
