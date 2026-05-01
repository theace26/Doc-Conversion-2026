"""Tests for GET /api/activity/summary — operator-gated activity aggregator.

Uses the same real-auth pattern as test_me_endpoint.py: temporarily disable
DEV_BYPASS_AUTH and set UNIONCORE_JWT_SECRET to a known test secret.
"""
import os
import time

import pytest
from fastapi.testclient import TestClient

TEST_JWT_SECRET = "test-secret-do-not-use"


def _create_jwt(role: str, sub: str = "test-user", email: str = "test@local46.org") -> str:
    from jose import jwt
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "email": email, "role": role, "iat": now, "exp": now + 3600},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def _auth_headers(role: str, **kwargs) -> dict:
    return {"Authorization": f"Bearer {_create_jwt(role, **kwargs)}"}


@pytest.fixture
def real_auth_client():
    """TestClient with DEV_BYPASS_AUTH=false and JWT secret configured."""
    orig_bypass = os.environ.get("DEV_BYPASS_AUTH")
    orig_secret = os.environ.get("UNIONCORE_JWT_SECRET")

    os.environ["DEV_BYPASS_AUTH"] = "false"
    os.environ["UNIONCORE_JWT_SECRET"] = TEST_JWT_SECRET

    import core.auth
    core.auth.DEV_BYPASS_AUTH = False

    from main import app
    client = TestClient(app, raise_server_exceptions=False)

    yield client

    if orig_bypass is None:
        os.environ.pop("DEV_BYPASS_AUTH", None)
    else:
        os.environ["DEV_BYPASS_AUTH"] = orig_bypass
    if orig_secret is None:
        os.environ.pop("UNIONCORE_JWT_SECRET", None)
    else:
        os.environ["UNIONCORE_JWT_SECRET"] = orig_secret

    core.auth.DEV_BYPASS_AUTH = True


def test_activity_summary_admin_can_read(real_auth_client):
    r = real_auth_client.get(
        "/api/activity/summary",
        headers=_auth_headers("admin"),
    )
    assert r.status_code == 200
    body = r.json()
    for key in ["pulse", "tiles", "throughput", "running_jobs", "queues", "recent_jobs"]:
        assert key in body, f"missing key: {key}"


def test_activity_summary_search_user_forbidden(real_auth_client):
    """search_user (member tier) should not be able to read the activity summary."""
    r = real_auth_client.get(
        "/api/activity/summary",
        headers=_auth_headers("search_user"),
    )
    assert r.status_code == 403


def test_activity_summary_unauthenticated_401(real_auth_client):
    r = real_auth_client.get("/api/activity/summary")
    assert r.status_code == 401
