"""Tests for the per-user preferences module (core.user_prefs).

Distinct from tests/test_preferences.py which covers the system-level
preferences API. This module manages per-user JSON blobs in the
mf_user_prefs table (keyed by UnionCore sub claim).
"""
import pytest
import aiosqlite

from core.db.schema import _SCHEMA_SQL
from core.user_prefs import (
    DEFAULT_USER_PREFS,
    USER_PREF_KEYS,
    get_user_prefs,
    set_user_pref,
    set_user_prefs,
)


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db(tmp_path):
    """Init schema in a tmp DB and yield the path."""
    p = tmp_path / "test.db"
    async with aiosqlite.connect(p) as conn:
        await conn.executescript(_SCHEMA_SQL)
        await conn.commit()
    return p


async def test_defaults_returned_for_new_user(db):
    prefs = await get_user_prefs(db, "new@local46.org")
    assert prefs == DEFAULT_USER_PREFS


async def test_set_then_get(db):
    await set_user_pref(db, "alice@local46.org", "layout", "minimal")
    prefs = await get_user_prefs(db, "alice@local46.org")
    assert prefs["layout"] == "minimal"


async def test_unknown_key_rejected(db):
    with pytest.raises(ValueError, match="unknown preference"):
        await set_user_pref(db, "alice@local46.org", "not_a_real_key", "x")


async def test_layout_value_validated(db):
    with pytest.raises(ValueError, match="invalid value"):
        await set_user_pref(db, "alice@local46.org", "layout", "extreme")


async def test_partial_update_preserves_other_keys(db):
    await set_user_pref(db, "alice@local46.org", "layout", "recent")
    await set_user_pref(db, "alice@local46.org", "density", "list")
    prefs = await get_user_prefs(db, "alice@local46.org")
    assert prefs["layout"] == "recent"
    assert prefs["density"] == "list"


async def test_bulk_set_user_prefs(db):
    await set_user_prefs(db, "alice@local46.org", {
        "layout": "minimal",
        "density": "compact",
        "advanced_actions_inline": True,
    })
    prefs = await get_user_prefs(db, "alice@local46.org")
    assert prefs["layout"] == "minimal"
    assert prefs["density"] == "compact"
    assert prefs["advanced_actions_inline"] is True


async def test_recent_searches_capped_at_50(db):
    queries = [f"q{i}" for i in range(60)]
    await set_user_pref(db, "alice@local46.org", "recent_searches", queries)
    prefs = await get_user_prefs(db, "alice@local46.org")
    assert len(prefs["recent_searches"]) == 50
    assert prefs["recent_searches"][0] == "q10"
    assert prefs["recent_searches"][-1] == "q59"


async def test_items_per_page_bounds(db):
    with pytest.raises(ValueError):
        await set_user_pref(db, "alice@local46.org", "items_per_page_cards", 0)
    with pytest.raises(ValueError):
        await set_user_pref(db, "alice@local46.org", "items_per_page_cards", 99999)
