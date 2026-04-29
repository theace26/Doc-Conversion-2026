"""HTTP tests for /api/user-prefs (per-user prefs).

Auth notes:
- DEV_BYPASS_AUTH is a module-level constant in core.auth (read once at import).
- With --noconftest, we set the env var and patch core.auth.DEV_BYPASS_AUTH
  directly for tests that need auth enforced.
- All tests share a temp DB file so preferences persist within a test but
  each user_id ("dev" under bypass) is isolated from other users.
- test_unauthenticated_returns_401 patches core.auth.DEV_BYPASS_AUTH = False
  at the module level so get_current_user enforces auth. Because UNIONCORE_JWT_SECRET
  is unset, no valid JWT can be forged, so an unauthenticated request 401s.
"""
import os
import tempfile
from pathlib import Path

# Set env vars BEFORE any app import so module-level constants pick them up.
_TEST_DB = Path(tempfile.mktemp(suffix="_mf_user_prefs_test.db"))
os.environ["DB_PATH"] = str(_TEST_DB)
os.environ["DEV_BYPASS_AUTH"] = "true"

import pytest  # noqa: E402
import core.auth  # noqa: E402  — ensure the module is imported so we can patch it
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


# Ensure the mf_user_prefs table exists in the test DB before tests run.
import asyncio  # noqa: E402
import aiosqlite  # noqa: E402


def _init_db():
    async def _run():
        async with aiosqlite.connect(str(_TEST_DB)) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mf_user_prefs (
                    user_id    TEXT PRIMARY KEY,
                    value      TEXT NOT NULL DEFAULT '{}',
                    schema_ver INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            await conn.commit()

    asyncio.run(_run())


_init_db()


@pytest.fixture
def client():
    # Ensure bypass is on for normal tests
    core.auth.DEV_BYPASS_AUTH = True
    return TestClient(app)


def test_get_user_prefs_returns_complete_dict(client):
    """GET always returns a dict with all expected keys — exact values may vary if
    a previous test wrote different values."""
    from core.user_prefs import USER_PREF_KEYS
    r = client.get("/api/user-prefs")
    assert r.status_code == 200
    body = r.json()
    assert USER_PREF_KEYS == set(body.keys())


def test_put_user_prefs_persists(client):
    # Reset to defaults first with a distinct key we can track
    client.put("/api/user-prefs", json={"layout": "recent", "density": "compact"})
    r2 = client.get("/api/user-prefs")
    assert r2.json()["layout"] == "recent"
    assert r2.json()["density"] == "compact"


def test_put_invalid_value_returns_400(client):
    r = client.put("/api/user-prefs", json={"layout": "extreme"})
    assert r.status_code == 400
    assert "invalid" in r.json()["detail"].lower()


def test_put_unknown_key_returns_400(client):
    r = client.put("/api/user-prefs", json={"not_a_real_key": "x"})
    assert r.status_code == 400


def test_unauthenticated_returns_401(client):
    """Verify 401 is returned when auth bypass is off and no credentials provided.

    Patches core.auth.DEV_BYPASS_AUTH directly (it's a module-level constant;
    env var changes after import have no effect). Restores the original value
    after the test regardless of outcome.
    """
    original = core.auth.DEV_BYPASS_AUTH
    try:
        core.auth.DEV_BYPASS_AUTH = False
        r = client.get("/api/user-prefs")
        assert r.status_code == 401
    finally:
        core.auth.DEV_BYPASS_AUTH = original


def test_existing_preferences_route_unaffected():
    """Sanity check: /api/preferences is still registered (returns non-404).

    The route hits the DB pool which isn't initialized in this bare-host test
    environment, so we only assert the route exists (not 404), not that it
    returns 200. The preferences route is tested fully in the main test suite
    which initializes the pool via conftest.
    """
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/preferences")
    assert r.status_code != 404, "existing /api/preferences route must still be registered"
