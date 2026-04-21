"""Unit tests for the encrypted credential store."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.credential_store import CredentialStore


@pytest.fixture
def store(tmp_path: Path) -> CredentialStore:
    return CredentialStore(secret_key="test-secret-0123456789abcdef", path=str(tmp_path / "creds.enc"))


def test_save_then_get_round_trip(store: CredentialStore) -> None:
    store.save_credentials("nas-docs", "smb", "alice", "p@ssw0rd")
    creds = store.get_credentials("nas-docs")
    assert creds == ("alice", "p@ssw0rd")


def test_get_missing_returns_none(store: CredentialStore) -> None:
    assert store.get_credentials("never-saved") is None


def test_list_shares(store: CredentialStore) -> None:
    store.save_credentials("a", "smb", "u1", "p1")
    store.save_credentials("b", "nfs", "u2", "p2")
    assert set(store.list_shares()) == {"a", "b"}


def test_delete_credentials(store: CredentialStore) -> None:
    store.save_credentials("x", "smb", "u", "p")
    store.delete_credentials("x")
    assert store.get_credentials("x") is None
    assert "x" not in store.list_shares()


def test_file_is_encrypted_on_disk(store: CredentialStore, tmp_path: Path) -> None:
    store.save_credentials("share", "smb", "alice", "topsecretpass")
    raw = (tmp_path / "creds.enc").read_bytes()
    assert b"alice" not in raw
    assert b"topsecretpass" not in raw


def test_wrong_key_fails_to_decrypt(tmp_path: Path) -> None:
    path = str(tmp_path / "c.enc")
    s1 = CredentialStore(secret_key="key-one-0123456789abcdef", path=path)
    s1.save_credentials("share", "smb", "u", "p")
    s2 = CredentialStore(secret_key="key-two-0123456789abcdef", path=path)
    # Different key → load fails → behaves as empty
    assert s2.get_credentials("share") is None
    assert s2.list_shares() == []


def test_persists_across_instances(tmp_path: Path) -> None:
    path = str(tmp_path / "c.enc")
    s1 = CredentialStore(secret_key="same-key-0123456789abcdef", path=path)
    s1.save_credentials("persistent", "smb", "bob", "pw")
    s2 = CredentialStore(secret_key="same-key-0123456789abcdef", path=path)
    assert s2.get_credentials("persistent") == ("bob", "pw")
