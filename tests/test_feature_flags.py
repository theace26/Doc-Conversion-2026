"""Tests for core.feature_flags — three-tier UX lookup."""
import os
import pytest

pytestmark = pytest.mark.asyncio


async def _make_get_user_prefs(prefs: dict):
    async def _get(db, user_sub):
        return prefs
    return _get


async def _make_get_preference(value):
    async def _get(key, default=None):
        return value
    return _get


async def test_user_pref_wins_over_env(monkeypatch):
    import core.feature_flags as ff
    import core.user_prefs as up
    import core.db.preferences as dbp

    monkeypatch.setenv("ENABLE_NEW_UX", "false")
    monkeypatch.setattr(up, "get_user_prefs", await _make_get_user_prefs(
        {"use_new_ux": True}
    ))
    result = await ff.is_new_ux_enabled_for("alice")
    assert result is True


async def test_user_pref_opt_out_wins_over_env(monkeypatch):
    import core.feature_flags as ff
    import core.user_prefs as up

    monkeypatch.setenv("ENABLE_NEW_UX", "true")
    monkeypatch.setattr(up, "get_user_prefs", await _make_get_user_prefs(
        {"use_new_ux": False}
    ))
    result = await ff.is_new_ux_enabled_for("alice")
    assert result is False


async def test_env_bypass_wins_over_system_pref(monkeypatch):
    import core.feature_flags as ff
    import core.user_prefs as up
    import core.db.preferences as dbp

    monkeypatch.setenv("ENABLE_NEW_UX", "true")
    monkeypatch.setattr(up, "get_user_prefs", await _make_get_user_prefs({}))
    monkeypatch.setattr(dbp, "get_preference", await _make_get_preference("false"))
    result = await ff.is_new_ux_enabled_for("alice")
    assert result is True


async def test_system_pref_used_when_no_env(monkeypatch):
    import core.feature_flags as ff
    import core.user_prefs as up
    import core.db.preferences as dbp

    monkeypatch.delenv("ENABLE_NEW_UX", raising=False)
    monkeypatch.setattr(up, "get_user_prefs", await _make_get_user_prefs({}))
    monkeypatch.setattr(dbp, "get_preference", await _make_get_preference("true"))
    result = await ff.is_new_ux_enabled_for("alice")
    assert result is True


async def test_default_is_false(monkeypatch):
    import core.feature_flags as ff
    import core.user_prefs as up
    import core.db.preferences as dbp

    monkeypatch.delenv("ENABLE_NEW_UX", raising=False)
    monkeypatch.setattr(up, "get_user_prefs", await _make_get_user_prefs({}))
    monkeypatch.setattr(dbp, "get_preference", await _make_get_preference(None))
    result = await ff.is_new_ux_enabled_for("alice")
    assert result is False
