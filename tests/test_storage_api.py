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
    succeed.
    """
    monkeypatch.setenv("SECRET_KEY", "test-secret-" + "x" * 32)
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "markflow_test.db"))
    # Skip long-running scheduler + prefetch jobs that would delay teardown
    monkeypatch.setenv("SKIP_FIRST_RUN_WIZARD", "1")

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


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
