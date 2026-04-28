"""Tests for v0.34.1 Convert page write-guard fix.

Covers BUG-003 (output_dir form param now propagates to orchestrator)
and the resolver layer (BUG-004 silent path drift).

Author: v0.34.1 — closes BUG-001..009 in docs/bug-log.md.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import patch

import pytest


# ── Resolver tests ───────────────────────────────────────────────────────────


def test_get_output_root_prefers_storage_manager(monkeypatch):
    """Storage Manager wins over env vars."""
    from core import storage_manager
    from core.storage_paths import get_output_root

    monkeypatch.setenv("OUTPUT_DIR", "/env/output")
    monkeypatch.setenv("BULK_OUTPUT_PATH", "/env/bulk")
    storage_manager.set_output_path("/sm/configured")
    try:
        assert str(get_output_root()) == "/sm/configured"
    finally:
        storage_manager.set_output_path(None)


def test_get_output_root_falls_through_to_bulk_env(monkeypatch):
    """BULK_OUTPUT_PATH wins when Storage Manager is unset."""
    from core import storage_manager
    from core.storage_paths import get_output_root

    storage_manager.set_output_path(None)
    monkeypatch.setenv("BULK_OUTPUT_PATH", "/env/bulk")
    monkeypatch.setenv("OUTPUT_DIR", "/env/output")
    assert str(get_output_root()) == "/env/bulk"


def test_get_output_root_falls_through_to_output_dir(monkeypatch):
    """OUTPUT_DIR wins when SM and BULK are unset."""
    from core import storage_manager
    from core.storage_paths import get_output_root

    storage_manager.set_output_path(None)
    monkeypatch.delenv("BULK_OUTPUT_PATH", raising=False)
    monkeypatch.setenv("OUTPUT_DIR", "/env/output")
    assert str(get_output_root()) == "/env/output"


def test_get_output_root_legacy_fallback(monkeypatch):
    """Falls through to relative 'output' when nothing else is set."""
    from core import storage_manager
    from core.storage_paths import get_output_root

    storage_manager.set_output_path(None)
    monkeypatch.delenv("BULK_OUTPUT_PATH", raising=False)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    assert str(get_output_root()) == "output"


def test_resolve_or_raise_rejects_legacy_fallback(monkeypatch):
    """resolve_output_root_or_raise() refuses the legacy default."""
    from core import storage_manager
    from core.storage_paths import resolve_output_root_or_raise

    storage_manager.set_output_path(None)
    monkeypatch.delenv("BULK_OUTPUT_PATH", raising=False)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    with pytest.raises(RuntimeError, match="no Storage Manager output"):
        resolve_output_root_or_raise()


# ── /api/convert request-layer tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_convert_rejects_out_of_allowed_output_dir(client, monkeypatch):
    """Posting a non-allowed output_dir → HTTP 422 with structured error."""
    from core import storage_manager

    # Configure Storage Manager so the resolver has a valid default
    # (this isolates the test to BUG-003 — operator-supplied bad path)
    storage_manager.set_output_path("/mnt/output-repo")
    try:
        files = {"files": ("test.txt", io.BytesIO(b"hello"), "text/plain")}
        data = {"direction": "to_md", "output_dir": "/etc/passwd"}
        resp = await client.post("/api/convert", files=files, data=data)
        assert resp.status_code == 422
        body = resp.json()
        # FastAPI wraps the dict under "detail" — payload structured as
        # {"error": "output_dir_not_allowed", "message": ..., "requested": ...}
        detail = body["detail"]
        assert detail["error"] == "output_dir_not_allowed"
        assert "/etc/passwd" in detail["message"]
        assert detail["requested"] == "/etc/passwd"
    finally:
        storage_manager.set_output_path(None)


@pytest.mark.asyncio
async def test_convert_uses_storage_manager_default_when_unset(
    client, tmp_path, monkeypatch
):
    """Posting with no output_dir resolves via Storage Manager."""
    from core import storage_manager

    sm_target = tmp_path / "sm-output"
    sm_target.mkdir()
    storage_manager.set_output_path(str(sm_target))
    try:
        files = {"files": ("hello.txt", io.BytesIO(b"hi there"), "text/plain")}
        data = {"direction": "to_md"}  # no output_dir
        resp = await client.post("/api/convert", files=files, data=data)
        # Convert returns 200 with a batch_id even though processing is
        # async — we just need to confirm it didn't 422 on the resolver.
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "batch_id" in body
    finally:
        storage_manager.set_output_path(None)


@pytest.mark.asyncio
async def test_convert_rejects_when_no_output_configured(client, monkeypatch):
    """No Storage Manager + no env → HTTP 422 with no_output_configured."""
    from core import storage_manager

    storage_manager.set_output_path(None)
    monkeypatch.delenv("BULK_OUTPUT_PATH", raising=False)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)

    files = {"files": ("test.txt", io.BytesIO(b"hello"), "text/plain")}
    data = {"direction": "to_md"}  # no output_dir, nothing in env, no SM
    resp = await client.post("/api/convert", files=files, data=data)
    assert resp.status_code == 422
    body = resp.json()
    detail = body["detail"]
    assert detail["error"] == "no_output_configured"
    assert "Storage page" in detail["message"]
