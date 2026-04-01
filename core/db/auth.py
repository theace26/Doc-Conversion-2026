"""
API key management helpers.
"""

from typing import Any

from core.db.connection import (
    db_fetch_all,
    db_fetch_one,
    get_db,
    now_iso,
)


async def create_api_key(key_id: str, label: str, key_hash: str) -> str:
    """Insert an API key record. Returns key_id."""
    now = now_iso()
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO api_keys (key_id, label, key_hash, is_active, created_at)
               VALUES (?,?,?,?,?)""",
            (key_id, label, key_hash, 1, now),
        )
        await conn.commit()
    return key_id


async def get_api_key_by_hash(key_hash: str) -> dict[str, Any] | None:
    """Look up an API key by its hash."""
    return await db_fetch_one(
        "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
    )


async def revoke_api_key(key_id: str) -> bool:
    """Soft-revoke an API key. Returns True if found."""
    async with get_db() as conn:
        async with conn.execute(
            "UPDATE api_keys SET is_active=0 WHERE key_id=?", (key_id,)
        ) as cur:
            updated = cur.rowcount
        await conn.commit()
    return updated > 0


async def list_api_keys() -> list[dict[str, Any]]:
    """Return all API keys (id, label, dates, active status -- never the hash)."""
    rows = await db_fetch_all(
        "SELECT key_id, label, is_active, created_at, last_used_at "
        "FROM api_keys ORDER BY created_at DESC"
    )
    return rows


async def touch_api_key(key_id: str) -> None:
    """Update last_used_at to now."""
    async with get_db() as conn:
        await conn.execute(
            "UPDATE api_keys SET last_used_at=? WHERE key_id=?",
            (now_iso(), key_id),
        )
        await conn.commit()
