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


async def test_default_list_values_not_shared(db):
    """get_user_prefs must return independent list copies, not references to
    DEFAULT_USER_PREFS. Mutating the returned dict must not corrupt defaults."""
    prefs_a = await get_user_prefs(db, "user_a@local46.org")
    prefs_b = await get_user_prefs(db, "user_b@local46.org")
    prefs_a["pinned_folders"].append("corrupted")
    # user_b should be unaffected; DEFAULT_USER_PREFS should be unaffected
    assert prefs_b["pinned_folders"] == []
    assert DEFAULT_USER_PREFS["pinned_folders"] == []


async def test_new_pref_defaults(db):
    prefs = await get_user_prefs(db, "new@local46.org")
    assert prefs["theme"] == "nebula"
    assert prefs["font"] == "system"
    assert prefs["text_scale"] == "default"
    assert prefs["use_new_ux"] is True


async def test_theme_enum_validated(db):
    with pytest.raises(ValueError, match="invalid value"):
        await set_user_pref(db, "alice@local46.org", "theme", "not-a-theme")


async def test_theme_valid_accepted(db):
    await set_user_pref(db, "alice@local46.org", "theme", "nebula")
    prefs = await get_user_prefs(db, "alice@local46.org")
    assert prefs["theme"] == "nebula"


async def test_font_enum_validated(db):
    with pytest.raises(ValueError, match="invalid value"):
        await set_user_pref(db, "alice@local46.org", "font", "comic-sans")


async def test_text_scale_enum_validated(db):
    with pytest.raises(ValueError, match="invalid value"):
        await set_user_pref(db, "alice@local46.org", "text_scale", "huge")


async def test_use_new_ux_bool_validated(db):
    with pytest.raises(ValueError, match="must be bool"):
        await set_user_pref(db, "alice@local46.org", "use_new_ux", "yes")


async def test_schema_ver_is_2(db):
    await set_user_pref(db, "alice@local46.org", "theme", "aurora")
    async with aiosqlite.connect(str(db)) as conn:
        async with conn.execute(
            "SELECT schema_ver FROM mf_user_prefs WHERE user_id = ?",
            ("alice@local46.org",)
        ) as cur:
            row = await cur.fetchone()
    assert row[0] == 2


async def test_existing_row_gets_new_defaults(db):
    """Rows written before v0.37.0 (SCHEMA_VER 1) must pick up new defaults on read."""
    import json
    old_blob = json.dumps({"layout": "minimal", "density": "cards"})
    async with aiosqlite.connect(str(db)) as conn:
        await conn.execute(
            "INSERT INTO mf_user_prefs (user_id, value, schema_ver) VALUES (?, ?, 1)",
            ("olduser@local46.org", old_blob)
        )
        await conn.commit()
    prefs = await get_user_prefs(db, "olduser@local46.org")
    assert prefs["theme"] == "nebula"
    assert prefs["use_new_ux"] is True
    assert prefs["layout"] == "minimal"   # old value preserved
