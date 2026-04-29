import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_root_serves_legacy_index_when_flag_off(monkeypatch, client):
    monkeypatch.setenv("ENABLE_NEW_UX", "false")
    r = client.get("/")
    assert r.status_code == 200
    # Legacy index.html has the Convert page heading
    assert b"Convert Documents" in r.content or b"Document Conversion" in r.content


def test_root_serves_new_index_when_flag_on(monkeypatch, client):
    monkeypatch.setenv("ENABLE_NEW_UX", "true")
    r = client.get("/")
    assert r.status_code == 200
    # New index.html mounts mf-home div and loads search-home page module
    assert b'id="mf-home"' in r.content
    assert b"search-home.js" in r.content


def test_root_default_serves_legacy(monkeypatch, client):
    """No env var set → legacy UI is served (production-safe default)."""
    monkeypatch.delenv("ENABLE_NEW_UX", raising=False)
    r = client.get("/")
    assert r.status_code == 200
    assert b'id="mf-home"' not in r.content
