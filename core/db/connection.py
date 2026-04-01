"""
Database connection, path resolution, and generic query helpers.

All domain modules import from here. External code should import
from ``core.database`` (the backward-compatible re-export wrapper).
"""

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

log = structlog.get_logger(__name__)

# ── Path resolution ───────────────────────────────────────────────────────────
_DEFAULT_DB = os.getenv("DB_PATH", "markflow.db")
DB_PATH = Path(_DEFAULT_DB)


def get_db_path() -> str:
    """Return the database file path as a string."""
    return str(DB_PATH)


# ── Connection context manager ────────────────────────────────────────────────
@asynccontextmanager
async def get_db():
    """Async context manager yielding a configured aiosqlite connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=10000")
        await conn.execute("PRAGMA foreign_keys=ON")
        yield conn


# ── Retry helper ──────────────────────────────────────────────────────────────
async def db_write_with_retry(fn, retries=3, base_delay=0.5):
    """Retry a DB write on lock contention with exponential backoff.

    Usage: ``await db_write_with_retry(lambda: update_bulk_file(...))``
    """
    import asyncio
    from sqlite3 import OperationalError

    for attempt in range(retries):
        try:
            return await fn()
        except OperationalError as e:
            if "database is locked" in str(e) and attempt < retries - 1:
                delay = base_delay * (2 ** attempt)
                log.warning("db_write_retry",
                            attempt=attempt + 1,
                            delay=delay,
                            error=str(e))
                await asyncio.sleep(delay)
            else:
                raise


# ── Shared utilities ──────────────────────────────────────────────────────────
def _count_by_status(rows: list, known_statuses: dict[str, int]) -> dict[str, int]:
    """Build a status->count dict from GROUP BY rows, adding a total."""
    for row in rows:
        if row["status"] in known_statuses:
            known_statuses[row["status"]] = row["cnt"]
    known_statuses["total"] = sum(known_statuses.values())
    return known_statuses


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Generic query helpers ─────────────────────────────────────────────────────
async def db_fetch_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    """Execute a SELECT and return the first row as a dict (or None)."""
    async with get_db() as conn:
        async with conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def db_fetch_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Execute a SELECT and return all rows as a list of dicts."""
    async with get_db() as conn:
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def db_execute(sql: str, params: tuple = ()) -> int:
    """Execute an INSERT/UPDATE/DELETE. Returns lastrowid."""
    async with get_db() as conn:
        async with conn.execute(sql, params) as cursor:
            await conn.commit()
            return cursor.lastrowid
