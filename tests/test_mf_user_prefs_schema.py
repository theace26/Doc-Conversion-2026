"""Schema test: mf_user_prefs table exists with correct columns and PK constraint.

The table stores per-user preferences (portable across machines), keyed by
UnionCore `sub` claim. Distinct from the existing `user_preferences` table
which stores system-level singleton prefs (key/value, not per-user).

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §10
"""
import json

import pytest
import aiosqlite

from core.db.schema import _SCHEMA_SQL


pytestmark = pytest.mark.asyncio


async def _init_schema(db_path):
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(_SCHEMA_SQL)
        await conn.commit()


async def test_mf_user_prefs_table_created(tmp_path):
    db = tmp_path / "test.db"
    await _init_schema(db)
    async with aiosqlite.connect(db) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mf_user_prefs'"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None, "mf_user_prefs table not created"

        async with conn.execute("PRAGMA table_info(mf_user_prefs)") as cur:
            cols = {r[1] for r in await cur.fetchall()}
        assert {"user_id", "value", "schema_ver", "updated_at"}.issubset(cols)


async def test_mf_user_prefs_roundtrip(tmp_path):
    """Insert and read back a JSON-blob preference value."""
    db = tmp_path / "test.db"
    await _init_schema(db)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO mf_user_prefs (user_id, value, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            ("xerxes@local46.org", json.dumps({"layout": "minimal", "density": "cards"})),
        )
        await conn.commit()
        async with conn.execute(
            "SELECT value FROM mf_user_prefs WHERE user_id = ?",
            ("xerxes@local46.org",),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        prefs = json.loads(row[0])
        assert prefs["layout"] == "minimal"


async def test_mf_user_prefs_unique_per_user(tmp_path):
    """user_id is PRIMARY KEY -- duplicate INSERT raises IntegrityError."""
    db = tmp_path / "test.db"
    await _init_schema(db)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO mf_user_prefs (user_id, value, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            ("alice@local46.org", json.dumps({"layout": "minimal"})),
        )
        await conn.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO mf_user_prefs (user_id, value, updated_at) "
                "VALUES (?, ?, datetime('now'))",
                ("alice@local46.org", json.dumps({"layout": "maximal"})),
            )
            await conn.commit()


async def test_existing_user_preferences_table_untouched(tmp_path):
    """Sanity: the legacy system-level user_preferences table still exists with
    its (key, value, updated_at) shape -- we did not break the existing prefs."""
    db = tmp_path / "test.db"
    await _init_schema(db)
    async with aiosqlite.connect(db) as conn:
        async with conn.execute("PRAGMA table_info(user_preferences)") as cur:
            cols = {r[1] for r in await cur.fetchall()}
        assert {"key", "value", "updated_at"}.issubset(cols)
        assert "user_id" not in cols, "user_preferences table got contaminated with per-user shape"
