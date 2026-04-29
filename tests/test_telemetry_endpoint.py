import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_telemetry_post_accepts_event(client):
    r = client.post(
        "/api/telemetry",
        json={"event": "ui.layout_mode_selected", "props": {"mode": "minimal"}},
    )
    assert r.status_code == 204


def test_telemetry_post_rejects_missing_event(client):
    r = client.post("/api/telemetry", json={"props": {"mode": "minimal"}})
    assert r.status_code == 422


def test_telemetry_post_rejects_non_ui_event(client):
    """Defensive: only ui.* events accepted (prevent accidental log floods)."""
    r = client.post(
        "/api/telemetry",
        json={"event": "system.boot", "props": {}},
    )
    assert r.status_code == 400


def test_telemetry_post_no_auth_required(client):
    """Telemetry endpoint is unauthenticated — instrumentation must work
    even on the login page."""
    r = client.post(
        "/api/telemetry",
        json={"event": "ui.density_toggle", "props": {"to": "list"}},
    )
    assert r.status_code == 204
