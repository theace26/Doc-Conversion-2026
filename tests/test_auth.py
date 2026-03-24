"""
Tests for Phase 10 — Auth layer, role guards, and API key management.

Tests JWT validation, role hierarchy, API key auth, dev bypass mode,
and route guard enforcement.
"""

import hashlib
import os
import time
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Test JWT secret — used only in tests
TEST_JWT_SECRET = "test-secret-do-not-use"
TEST_API_KEY_SALT = "test-salt-do-not-use"


def _create_jwt(role: str, sub: str = "test-user", email: str = "test@local46.org",
                expired: bool = False, secret: str = TEST_JWT_SECRET,
                omit_role: bool = False) -> str:
    """Generate a JWT for testing."""
    from jose import jwt

    now = int(time.time())
    payload = {
        "sub": sub,
        "email": email,
        "iat": now,
        "exp": now - 10 if expired else now + 3600,
    }
    if not omit_role:
        payload["role"] = role
    return jwt.encode(payload, secret, algorithm="HS256")


def _auth_headers(role: str, **kwargs) -> dict:
    """Return Authorization header with a valid JWT for the given role."""
    token = _create_jwt(role, **kwargs)
    return {"Authorization": f"Bearer {token}"}


def _hash_key(raw_key: str) -> str:
    return hashlib.blake2b(
        raw_key.encode() + TEST_API_KEY_SALT.encode(), digest_size=32
    ).hexdigest()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def auth_client():
    """
    Client with DEV_BYPASS_AUTH=false and JWT secret configured.
    This client enforces auth unlike the default test client.
    """
    # Save original env
    orig_bypass = os.environ.get("DEV_BYPASS_AUTH")
    orig_secret = os.environ.get("UNIONCORE_JWT_SECRET")
    orig_salt = os.environ.get("API_KEY_SALT")

    # Set auth env
    os.environ["DEV_BYPASS_AUTH"] = "false"
    os.environ["UNIONCORE_JWT_SECRET"] = TEST_JWT_SECRET
    os.environ["API_KEY_SALT"] = TEST_API_KEY_SALT

    # Reload the auth module to pick up new env
    import core.auth
    core.auth.DEV_BYPASS_AUTH = False

    from core.database import init_db
    from main import app

    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Restore
    core.auth.DEV_BYPASS_AUTH = True
    if orig_bypass is not None:
        os.environ["DEV_BYPASS_AUTH"] = orig_bypass
    else:
        os.environ["DEV_BYPASS_AUTH"] = "true"
    if orig_secret is not None:
        os.environ["UNIONCORE_JWT_SECRET"] = orig_secret
    else:
        os.environ.pop("UNIONCORE_JWT_SECRET", None)
    if orig_salt is not None:
        os.environ["API_KEY_SALT"] = orig_salt
    else:
        os.environ.pop("API_KEY_SALT", None)


# ── Core auth unit tests ─────────────────────────────────────────────────────

class TestUserRole:
    def test_role_hierarchy(self):
        from core.auth import UserRole, role_satisfies

        assert role_satisfies(UserRole.ADMIN, UserRole.SEARCH_USER)
        assert role_satisfies(UserRole.ADMIN, UserRole.ADMIN)
        assert role_satisfies(UserRole.MANAGER, UserRole.OPERATOR)
        assert role_satisfies(UserRole.OPERATOR, UserRole.SEARCH_USER)
        assert not role_satisfies(UserRole.SEARCH_USER, UserRole.OPERATOR)
        assert not role_satisfies(UserRole.OPERATOR, UserRole.MANAGER)
        assert not role_satisfies(UserRole.SEARCH_USER, UserRole.ADMIN)


class TestVerifyToken:
    @pytest.mark.asyncio
    async def test_valid_jwt(self):
        from core.auth import verify_token, UserRole

        token = _create_jwt("admin", sub="u1", email="admin@test.org")
        user = await verify_token(token, TEST_JWT_SECRET)
        assert user.sub == "u1"
        assert user.email == "admin@test.org"
        assert user.role == UserRole.ADMIN
        assert user.is_service_account is False

    @pytest.mark.asyncio
    async def test_expired_jwt(self):
        from fastapi import HTTPException
        from core.auth import verify_token

        token = _create_jwt("admin", expired=True)
        with pytest.raises(HTTPException) as exc_info:
            await verify_token(token, TEST_JWT_SECRET)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_bad_signature(self):
        from fastapi import HTTPException
        from core.auth import verify_token

        token = _create_jwt("admin", secret="wrong-secret")
        with pytest.raises(HTTPException) as exc_info:
            await verify_token(token, TEST_JWT_SECRET)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_role_claim(self):
        from fastapi import HTTPException
        from core.auth import verify_token

        token = _create_jwt("admin", omit_role=True)
        with pytest.raises(HTTPException) as exc_info:
            await verify_token(token, TEST_JWT_SECRET)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_unknown_role_value(self):
        from fastapi import HTTPException
        from core.auth import verify_token

        token = _create_jwt("superuser")
        with pytest.raises(HTTPException) as exc_info:
            await verify_token(token, TEST_JWT_SECRET)
        assert exc_info.value.status_code == 403


class TestVerifyApiKey:
    @pytest.mark.asyncio
    async def test_valid_api_key(self):
        from core.auth import verify_api_key, hash_api_key, UserRole
        from core.database import create_api_key, init_db

        os.environ["API_KEY_SALT"] = TEST_API_KEY_SALT
        await init_db()

        raw_key = "mf_test_key_valid_123"
        key_hash = hash_api_key(raw_key, TEST_API_KEY_SALT)
        key_id = uuid.uuid4().hex
        await create_api_key(key_id, "test-key", key_hash)

        user = await verify_api_key(raw_key)
        assert user.sub == key_id
        assert user.role == UserRole.SEARCH_USER
        assert user.is_service_account is True

    @pytest.mark.asyncio
    async def test_revoked_api_key(self):
        from fastapi import HTTPException
        from core.auth import verify_api_key, hash_api_key
        from core.database import create_api_key, revoke_api_key, init_db

        os.environ["API_KEY_SALT"] = TEST_API_KEY_SALT
        await init_db()

        raw_key = "mf_test_key_revoked_456"
        key_hash = hash_api_key(raw_key, TEST_API_KEY_SALT)
        key_id = uuid.uuid4().hex
        await create_api_key(key_id, "revoked-key", key_hash)
        await revoke_api_key(key_id)

        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(raw_key)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_api_key(self):
        from fastapi import HTTPException
        from core.auth import verify_api_key

        os.environ["API_KEY_SALT"] = TEST_API_KEY_SALT
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key("mf_nonexistent_key")
        assert exc_info.value.status_code == 401


# ── Route guard integration tests ────────────────────────────────────────────

class TestDevBypass:
    """When DEV_BYPASS_AUTH=true, all requests succeed as admin."""

    @pytest.mark.asyncio
    async def test_bypass_returns_admin(self, client):
        """Default test client has bypass enabled."""
        res = await client.get("/api/auth/me")
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "admin"
        assert data["sub"] == "dev"

    @pytest.mark.asyncio
    async def test_bypass_allows_admin_routes(self, client):
        """Admin routes accessible without credentials in bypass mode."""
        res = await client.get("/api/admin/system")
        assert res.status_code == 200


class TestAuthEnforcement:
    """With DEV_BYPASS_AUTH=false, auth is enforced."""

    @pytest.mark.asyncio
    async def test_no_header_returns_401(self, auth_client):
        res = await auth_client.get("/api/auth/me")
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_jwt_returns_user(self, auth_client):
        headers = _auth_headers("operator")
        res = await auth_client.get("/api/auth/me", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "operator"

    @pytest.mark.asyncio
    async def test_expired_jwt_returns_401(self, auth_client):
        token = _create_jwt("admin", expired=True)
        headers = {"Authorization": f"Bearer {token}"}
        res = await auth_client.get("/api/auth/me", headers=headers)
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_bad_signature_returns_401(self, auth_client):
        token = _create_jwt("admin", secret="wrong")
        headers = {"Authorization": f"Bearer {token}"}
        res = await auth_client.get("/api/auth/me", headers=headers)
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_role_returns_403(self, auth_client):
        token = _create_jwt("admin", omit_role=True)
        headers = {"Authorization": f"Bearer {token}"}
        res = await auth_client.get("/api/auth/me", headers=headers)
        assert res.status_code == 403

    @pytest.mark.asyncio
    async def test_unknown_role_returns_403(self, auth_client):
        token = _create_jwt("superadmin")
        headers = {"Authorization": f"Bearer {token}"}
        res = await auth_client.get("/api/auth/me", headers=headers)
        assert res.status_code == 403


class TestRoleGuards:
    """Test that routes enforce their minimum role."""

    @pytest.mark.asyncio
    async def test_search_user_can_search(self, auth_client):
        """search_user can access /api/search."""
        headers = _auth_headers("search_user")
        # Meilisearch may be down in tests; 503 is acceptable (not 401/403)
        res = await auth_client.get("/api/search?q=test", headers=headers)
        assert res.status_code in (200, 503)

    @pytest.mark.asyncio
    async def test_search_user_cannot_convert(self, auth_client):
        """search_user is blocked from operator-level routes."""
        headers = _auth_headers("search_user")
        res = await auth_client.post("/api/convert/preview", headers=headers)
        assert res.status_code == 403

    @pytest.mark.asyncio
    async def test_operator_can_access_history(self, auth_client):
        headers = _auth_headers("operator")
        res = await auth_client.get("/api/history", headers=headers)
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_operator_cannot_manage_bulk(self, auth_client):
        """operator is blocked from manager-level routes."""
        headers = _auth_headers("operator")
        res = await auth_client.get("/api/bulk/jobs", headers=headers)
        assert res.status_code == 403

    @pytest.mark.asyncio
    async def test_manager_can_manage_bulk(self, auth_client):
        headers = _auth_headers("manager")
        res = await auth_client.get("/api/bulk/jobs", headers=headers)
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_manager_cannot_access_admin(self, auth_client):
        """manager is blocked from admin-level routes."""
        headers = _auth_headers("manager")
        res = await auth_client.get("/api/admin/api-keys", headers=headers)
        assert res.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_access_everything(self, auth_client):
        headers = _auth_headers("admin")
        res = await auth_client.get("/api/admin/system", headers=headers)
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_role_hierarchy_admin_on_operator_route(self, auth_client):
        """admin satisfies operator-level requirement."""
        headers = _auth_headers("admin")
        res = await auth_client.get("/api/history", headers=headers)
        assert res.status_code == 200


class TestServiceAccountGuards:
    """Service accounts (API key) always get search_user role."""

    @pytest.mark.asyncio
    async def test_api_key_grants_search_access(self, auth_client):
        from core.auth import hash_api_key
        from core.database import create_api_key

        raw_key = "mf_svc_test_search_" + uuid.uuid4().hex[:8]
        key_hash = hash_api_key(raw_key, TEST_API_KEY_SALT)
        key_id = uuid.uuid4().hex
        await create_api_key(key_id, "svc-test", key_hash)

        headers = {"X-API-Key": raw_key}
        res = await auth_client.get("/api/auth/me", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "search_user"
        assert data["is_service_account"] is True

    @pytest.mark.asyncio
    async def test_api_key_blocked_on_manager_route(self, auth_client):
        from core.auth import hash_api_key
        from core.database import create_api_key

        raw_key = "mf_svc_test_bulk_" + uuid.uuid4().hex[:8]
        key_hash = hash_api_key(raw_key, TEST_API_KEY_SALT)
        key_id = uuid.uuid4().hex
        await create_api_key(key_id, "svc-test-bulk", key_hash)

        headers = {"X-API-Key": raw_key}
        res = await auth_client.get("/api/bulk/jobs", headers=headers)
        assert res.status_code == 403

    @pytest.mark.asyncio
    async def test_api_key_blocked_on_admin_route(self, auth_client):
        from core.auth import hash_api_key
        from core.database import create_api_key

        raw_key = "mf_svc_test_admin_" + uuid.uuid4().hex[:8]
        key_hash = hash_api_key(raw_key, TEST_API_KEY_SALT)
        key_id = uuid.uuid4().hex
        await create_api_key(key_id, "svc-test-admin", key_hash)

        headers = {"X-API-Key": raw_key}
        res = await auth_client.get("/api/admin/api-keys", headers=headers)
        assert res.status_code == 403


class TestPreferencesRoleSplit:
    """PUT on system preference keys requires manager role."""

    @pytest.mark.asyncio
    async def test_operator_can_read_preferences(self, auth_client):
        headers = _auth_headers("operator")
        res = await auth_client.get("/api/preferences", headers=headers)
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_operator_can_update_personal_pref(self, auth_client):
        headers = _auth_headers("operator")
        res = await auth_client.put(
            "/api/preferences/default_direction",
            json={"value": "to_md"},
            headers=headers,
        )
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_operator_blocked_on_system_pref(self, auth_client):
        headers = _auth_headers("operator")
        res = await auth_client.put(
            "/api/preferences/max_concurrent_conversions",
            json={"value": "5"},
            headers=headers,
        )
        assert res.status_code == 403

    @pytest.mark.asyncio
    async def test_manager_can_update_system_pref(self, auth_client):
        headers = _auth_headers("manager")
        res = await auth_client.put(
            "/api/preferences/max_concurrent_conversions",
            json={"value": "5"},
            headers=headers,
        )
        assert res.status_code == 200


class TestApiKeyManagement:
    """Admin API key CRUD via /api/admin/api-keys."""

    @pytest.mark.asyncio
    async def test_generate_and_list_key(self, auth_client):
        headers = _auth_headers("admin")

        # Generate
        res = await auth_client.post(
            "/api/admin/api-keys",
            json={"label": "test-gen"},
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["raw_key"].startswith("mf_")
        assert "warning" in data
        key_id = data["key_id"]

        # List
        res = await auth_client.get("/api/admin/api-keys", headers=headers)
        assert res.status_code == 200
        keys = res.json()
        assert any(k["key_id"] == key_id for k in keys)

    @pytest.mark.asyncio
    async def test_revoke_key(self, auth_client):
        headers = _auth_headers("admin")

        # Generate
        res = await auth_client.post(
            "/api/admin/api-keys",
            json={"label": "test-revoke"},
            headers=headers,
        )
        key_id = res.json()["key_id"]

        # Revoke
        res = await auth_client.delete(f"/api/admin/api-keys/{key_id}", headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "revoked"

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key(self, auth_client):
        headers = _auth_headers("admin")
        res = await auth_client.delete("/api/admin/api-keys/nonexistent", headers=headers)
        assert res.status_code == 404


class TestHealthNoAuth:
    """Health endpoint stays unauthenticated."""

    @pytest.mark.asyncio
    async def test_health_no_auth_needed(self, auth_client):
        """Health check works without any credentials."""
        res = await auth_client.get("/api/health")
        assert res.status_code == 200


class TestRootRedirect:
    """Root redirects to search page."""

    @pytest.mark.asyncio
    async def test_root_redirects_to_search(self, client):
        res = await client.get("/", follow_redirects=False)
        assert res.status_code == 307
        assert "/search.html" in res.headers.get("location", "")
