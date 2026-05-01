"""Tests for GET /api/me — identity + role + build info.

Uses the same auth pattern as test_auth.py: temporarily disable
DEV_BYPASS_AUTH and set UNIONCORE_JWT_SECRET to a known test secret.
The conftest default (DEV_BYPASS_AUTH=true) would bypass auth on every
request and make the 401 test impossible.
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


def _auth_headers(role: str, sub: str = "test-user", email: str = "test@local46.org") -> dict:
    return {"Authorization": f"Bearer {_create_jwt(role, sub=sub, email=email)}"}


@pytest.fixture
def real_auth_client():
    """TestClient with DEV_BYPASS_AUTH=false and JWT secret configured.

    Temporarily overrides the conftest default so auth is actually
    enforced during these tests.
    """
    orig_bypass = os.environ.get("DEV_BYPASS_AUTH")
    orig_secret = os.environ.get("UNIONCORE_JWT_SECRET")

    os.environ["DEV_BYPASS_AUTH"] = "false"
    os.environ["UNIONCORE_JWT_SECRET"] = TEST_JWT_SECRET

    import core.auth
    core.auth.DEV_BYPASS_AUTH = False

    from main import app
    client = TestClient(app, raise_server_exceptions=False)

    yield client

    # Restore env and module state to conftest defaults
    if orig_bypass is None:
        os.environ.pop("DEV_BYPASS_AUTH", None)
    else:
        os.environ["DEV_BYPASS_AUTH"] = orig_bypass
    if orig_secret is None:
        os.environ.pop("UNIONCORE_JWT_SECRET", None)
    else:
        os.environ["UNIONCORE_JWT_SECRET"] = orig_secret

    core.auth.DEV_BYPASS_AUTH = True


def test_me_returns_admin_identity(real_auth_client):
    headers = _auth_headers("admin", sub="xerxes@local46.org", email="xerxes@local46.org")
    r = real_auth_client.get("/api/me", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "xerxes@local46.org"
    assert body["role"] == "admin"
    assert body["scope"]  # non-empty string


def test_me_returns_search_user_as_member(real_auth_client):
    """search_user JWT role maps to 'member' in the 3-tier UI response."""
    headers = _auth_headers("search_user", sub="sarah@local46.org", email="sarah@local46.org")
    r = real_auth_client.get("/api/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["role"] == "member"


def test_me_unauthenticated_returns_401(real_auth_client):
    r = real_auth_client.get("/api/me")
    assert r.status_code == 401


def test_me_includes_build_info(real_auth_client):
    """Build info travels with /api/me so the avatar dropdown can render
    it without a separate endpoint or hardcoded HTML."""
    headers = _auth_headers("admin")
    r = real_auth_client.get("/api/me", headers=headers)
    body = r.json()
    assert "build" in body
    assert "version" in body["build"]
