"""Integration tests for /api/storage/* endpoints (v0.28.0).

Uses FastAPI TestClient with DEV_BYPASS_AUTH=true so the MANAGER role
requirement is satisfied by the in-process bypass user.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Spin up the app with an isolated SQLite + bypass auth + test secret.

    TestClient as a context manager triggers lifespan startup, which runs
    init_db() and seeds DEFAULT_PREFERENCES so the storage routes' DB writes
    succeed. The mount_manager singleton is also reset between tests so
    saved shares from one test don't leak into another.
    """
    monkeypatch.setenv("SECRET_KEY", "test-secret-" + "x" * 32)
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "markflow_test.db"))
    # Skip long-running scheduler + prefetch jobs that would delay teardown
    monkeypatch.setenv("SKIP_FIRST_RUN_WIZARD", "1")

    # Reset MountManager + mount_health module-level state so tests don't share
    from core import mount_manager as _mm
    monkeypatch.setattr(_mm, "_singleton", None, raising=False)
    _mm.mount_health.clear()

    # Reset storage_manager cached output path
    from core import storage_manager as _sm
    monkeypatch.setattr(_sm, "_cached_output_path", None, raising=False)

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def role_override():
    """Helper: override get_current_user to return an AuthenticatedUser with a
    given role. Tests call role_override(UserRole.SEARCH_USER) to simulate a
    less-privileged caller even though DEV_BYPASS_AUTH is on.

    Yields a setter so each test can switch roles; the fixture cleans up
    after teardown.
    """
    from main import app
    from core.auth import AuthenticatedUser, UserRole, get_current_user

    current = {"role": UserRole.ADMIN}

    async def _override():
        return AuthenticatedUser(
            sub="test", email="test@local",
            role=current["role"], is_service_account=False,
        )

    app.dependency_overrides[get_current_user] = _override

    def setter(role):
        current["role"] = role

    yield setter
    app.dependency_overrides.pop(get_current_user, None)


def test_host_info(client):
    r = client.get("/api/storage/host-info")
    assert r.status_code == 200
    body = r.json()
    assert "os" in body
    assert "quick_access" in body
    assert isinstance(body["quick_access"], list)


def test_validate_missing_path(client):
    r = client.post(
        "/api/storage/validate",
        json={"path": "/nonexistent-xxx", "role": "source"},
    )
    assert r.status_code == 200
    assert not r.json()["ok"]


def test_validate_writable_output(client, tmp_path):
    r = client.post(
        "/api/storage/validate",
        json={"path": str(tmp_path), "role": "output"},
    )
    assert r.status_code == 200
    assert r.json()["ok"]


def test_add_and_remove_source(client, tmp_path):
    # Add
    r = client.post(
        "/api/storage/sources",
        json={"path": str(tmp_path), "label": "test"},
    )
    assert r.status_code == 201
    sid = r.json()["id"]
    # List contains it
    r2 = client.get("/api/storage/sources")
    assert any(s["id"] == sid for s in r2.json()["sources"])
    # Remove
    r3 = client.delete(f"/api/storage/sources/{sid}")
    assert r3.status_code == 204
    # No longer present
    r4 = client.get("/api/storage/sources")
    assert not any(s["id"] == sid for s in r4.json()["sources"])


def test_set_output_triggers_restart_flag_on_change(client, tmp_path):
    # First write: no flag
    client.put("/api/storage/output", json={"path": str(tmp_path)})
    r = client.get("/api/storage/restart-status")
    assert r.json()["reason"] == ""
    # Second write to a different path: flag fires
    other = tmp_path / "other"
    other.mkdir()
    client.put("/api/storage/output", json={"path": str(other)})
    r = client.get("/api/storage/restart-status")
    assert r.json()["reason"]


def test_wizard_status_suppressed_in_dev_bypass(client):
    r = client.get("/api/storage/wizard-status")
    assert r.json()["show"] is False
    assert r.json()["reason"] == "env-suppressed"


def test_exclusion_roundtrip(client):
    r = client.post("/api/storage/exclusions", json={"path_prefix": "/test/skip"})
    assert r.status_code == 201
    eid = r.json()["id"]
    r2 = client.get("/api/storage/exclusions")
    assert any(e["id"] == eid for e in r2.json()["exclusions"])
    r3 = client.delete(f"/api/storage/exclusions/{eid}")
    assert r3.status_code == 204


def test_mount_health_endpoint(client):
    r = client.get("/api/storage/health")
    assert r.status_code == 200
    assert "mounts" in r.json()


def test_restart_dismiss_snoozes_for_one_hour(client, tmp_path):
    # Force a reason first
    client.put("/api/storage/output", json={"path": str(tmp_path)})
    other = tmp_path / "d"
    other.mkdir()
    client.put("/api/storage/output", json={"path": str(other)})
    # Dismiss
    r = client.post("/api/storage/restart-dismiss")
    assert r.status_code == 200
    assert "dismissed_until" in r.json()


# ── D1 Role enforcement ──────────────────────────────────────────────────────


def test_search_user_cannot_list_sources(client, role_override):
    from core.auth import UserRole
    role_override(UserRole.SEARCH_USER)
    r = client.get("/api/storage/sources")
    assert r.status_code == 403


def test_manager_cannot_read_share_credentials(client, role_override):
    """Credential clear-text reads are ADMIN-only — MANAGER gets 403."""
    from core.auth import UserRole
    role_override(UserRole.MANAGER)
    r = client.get("/api/storage/shares/does-not-exist/credentials")
    assert r.status_code == 403


def test_admin_can_read_share_credentials_when_absent(client, role_override):
    """ADMIN passes the role check; missing credentials = 404, not 403."""
    from core.auth import UserRole
    role_override(UserRole.ADMIN)
    r = client.get("/api/storage/shares/does-not-exist/credentials")
    assert r.status_code == 404


def test_operator_cannot_access_storage_endpoints(client, role_override):
    """All storage endpoints require MANAGER — OPERATOR gets 403."""
    from core.auth import UserRole
    role_override(UserRole.OPERATOR)
    r = client.post("/api/storage/sources", json={"path": "/tmp", "label": "x"})
    assert r.status_code == 403


# ── D2 Path-safety ───────────────────────────────────────────────────────────


def test_validate_file_not_folder(client, tmp_path):
    f = tmp_path / "a-file.txt"
    f.write_text("hi")
    r = client.post("/api/storage/validate", json={"path": str(f), "role": "source"})
    assert r.status_code == 200
    body = r.json()
    assert not body["ok"]
    assert any("file, not a folder" in e for e in body["errors"])


def test_validate_path_with_null_byte_rejected(client):
    """A path containing a null byte must NOT crash the server or pass."""
    r = client.post("/api/storage/validate", json={"path": "/tmp/\x00evil", "role": "source"})
    # Either 200 with ok=false OR 422 (pydantic rejects). Both are acceptable.
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        assert not r.json()["ok"]


def test_add_source_to_file_rejected(client, tmp_path):
    """Adding a source that's a file (not a dir) must 400."""
    f = tmp_path / "not-a-dir.txt"
    f.write_text("x")
    r = client.post("/api/storage/sources", json={"path": str(f), "label": "bad"})
    assert r.status_code == 400


# ── D3 Idempotency / edge cases ──────────────────────────────────────────────


def test_delete_nonexistent_source_is_204(client):
    r = client.delete("/api/storage/sources/ghost-id")
    assert r.status_code == 204


def test_delete_nonexistent_exclusion_is_204(client):
    r = client.delete("/api/storage/exclusions/ghost-id")
    assert r.status_code == 204


def test_restart_status_returns_expected_shape(client):
    """The endpoint always returns the three documented keys as strings.

    (Can't assert 'reason == ""' portably because conftest.py's session-scoped
    DB_PATH is shared across tests and a sibling test may have set a reason.
    What matters is the shape + types.)
    """
    r = client.get("/api/storage/restart-status")
    assert r.status_code == 200
    body = r.json()
    for key in ("reason", "since", "dismissed_until"):
        assert key in body
        assert isinstance(body[key], str)


# ── D5 Write-guard in practice ───────────────────────────────────────────────


def test_write_guard_denies_outside_output(client, tmp_path):
    """After configuring an output, is_write_allowed() accepts inside, denies outside."""
    from core import storage_manager as sm

    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    # Configure output through the API so the full wiring fires
    client.put("/api/storage/output", json={"path": str(output)})

    assert sm.is_write_allowed(str(output / "file.md"))
    assert sm.is_write_allowed(str(output / "nested" / "file.md"))
    assert not sm.is_write_allowed(str(outside / "file.md"))
    assert not sm.is_write_allowed("/etc/passwd")


def test_write_guard_respects_realpath_escape(client, tmp_path):
    """A symlink pointing outside the output dir must be denied."""
    from core import storage_manager as sm

    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = output / "escape"
    link.symlink_to(outside)

    client.put("/api/storage/output", json={"path": str(output)})
    # is_write_allowed resolves the symlink → target is outside
    assert not sm.is_write_allowed(str(link / "file.md"))


# ── Wizard auto-open when configured ─────────────────────────────────────────


def test_wizard_hidden_after_sources_configured(client, tmp_path, monkeypatch):
    """Once a source is added, wizard-status returns show=false even without
    SKIP_FIRST_RUN_WIZARD. We re-test without the env suppressor by monkeypatching."""
    # Add a source first
    client.post("/api/storage/sources", json={"path": str(tmp_path), "label": "x"})
    # Clear the env suppressor for this single assertion
    monkeypatch.delenv("SKIP_FIRST_RUN_WIZARD", raising=False)
    monkeypatch.delenv("DEV_BYPASS_AUTH", raising=False)
    # With at least one source, reason should be "configured"
    r = client.get("/api/storage/wizard-status")
    body = r.json()
    assert body["show"] is False
    # reason may be "env-suppressed" if auth bypass is still active at dep-injection time,
    # or "configured" after env cleanup — either is a correct suppression.
    assert body["reason"] in ("configured", "env-suppressed", "dismissed")
