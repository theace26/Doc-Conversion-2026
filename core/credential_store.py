"""Fernet-encrypted credential store for SMB/NFS shares.

Threat model: attacker gains file-read access but not process environment.
Key derivation: PBKDF2(SECRET_KEY, salt, 100_000 iterations) via cryptography.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import threading
from pathlib import Path

import structlog
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

log = structlog.get_logger(__name__)

_DEFAULT_PATH = "/etc/markflow/credentials.enc"
# OWASP 2023+ recommendation for PBKDF2-HMAC-SHA256; if SECRET_KEY is ever a
# human passphrase, this is the only barrier against offline brute force.
_ITERATIONS = 600_000
_SALT_BYTES = 16


class CredentialStore:
    """Load/save encrypted credentials to disk. Thread-safe for intra-process access."""

    def __init__(self, secret_key: str, path: str = _DEFAULT_PATH) -> None:
        if not secret_key:
            raise ValueError("secret_key is required")
        self._secret = secret_key.encode("utf-8")
        self._path = path
        self._lock = threading.Lock()

    def _derive_key(self, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_ITERATIONS)
        return base64.urlsafe_b64encode(kdf.derive(self._secret))

    def _load(self) -> dict:
        if not os.path.isfile(self._path):
            return {"salt": base64.b64encode(secrets.token_bytes(_SALT_BYTES)).decode("ascii"), "shares": {}}
        try:
            raw = Path(self._path).read_bytes()
            header, _, payload = raw.partition(b"\n")
            salt_b64 = header.decode("ascii").strip()
            salt = base64.b64decode(salt_b64)
            f = Fernet(self._derive_key(salt))
            data = json.loads(f.decrypt(payload).decode("utf-8"))
            return {"salt": salt_b64, "shares": data.get("shares", {})}
        except (InvalidToken, json.JSONDecodeError, ValueError, OSError) as exc:
            log.warning("credential_store_load_failed", path=self._path, error_type=type(exc).__name__)
            return {"salt": base64.b64encode(secrets.token_bytes(_SALT_BYTES)).decode("ascii"), "shares": {}}

    def _save(self, blob: dict) -> None:
        salt = base64.b64decode(blob["salt"])
        f = Fernet(self._derive_key(salt))
        payload = f.encrypt(json.dumps({"shares": blob["shares"]}).encode("utf-8"))
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(blob["salt"].encode("ascii") + b"\n" + payload)
        os.replace(tmp, self._path)
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            # Windows / unsupported FS — best-effort
            pass

    def save_credentials(self, share_name: str, protocol: str, username: str, password: str) -> None:
        if not share_name or not protocol:
            raise ValueError("share_name and protocol are required")
        with self._lock:
            blob = self._load()
            blob["shares"][share_name] = {"protocol": protocol, "username": username, "password": password}
            self._save(blob)

    def get_credentials(self, share_name: str) -> tuple[str, str] | None:
        with self._lock:
            blob = self._load()
            entry = blob["shares"].get(share_name)
            if not entry:
                return None
            return entry.get("username", ""), entry.get("password", "")

    def delete_credentials(self, share_name: str) -> None:
        with self._lock:
            blob = self._load()
            blob["shares"].pop(share_name, None)
            self._save(blob)

    def list_shares(self) -> list[str]:
        with self._lock:
            blob = self._load()
            return sorted(blob["shares"].keys())
