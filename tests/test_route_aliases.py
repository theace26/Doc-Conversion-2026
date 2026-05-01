import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


def test_pipeline_redirects_to_activity(client):
    """Old /pipeline URL -> 301 to /activity."""
    r = client.get("/pipeline")
    assert r.status_code == 301
    assert r.headers["location"] == "/activity"


def test_pipeline_subpath_redirects(client):
    """Subpath preserved: /pipeline/foo -> /activity/foo."""
    r = client.get("/pipeline/jobs/123")
    assert r.status_code == 301
    assert r.headers["location"] == "/activity/jobs/123"


def test_activity_route_exists(client):
    """/activity route should not 404 (even if it 401s under auth)."""
    r = client.get("/activity")
    assert r.status_code != 404
