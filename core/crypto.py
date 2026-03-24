"""
Symmetric encryption for sensitive values (API keys) stored at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) via the `cryptography` library.
Encryption key is derived from the SECRET_KEY environment variable.
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        raise ValueError("SECRET_KEY env var required when storing API keys")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns a base64-encoded ciphertext."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Returns the original plaintext."""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise ValueError("Failed to decrypt value — SECRET_KEY may have changed")


def mask_api_key(key: str | None) -> str | None:
    """Mask an API key for display: show first 6 chars + '****'."""
    if not key:
        return None
    if len(key) <= 8:
        return key[:2] + "****"
    return key[:6] + "****"
